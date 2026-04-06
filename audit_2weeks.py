"""
2-week signal audit.

Loads existing 12-month CSV data + signal caches, slices the last 14 days,
then runs a candle-by-candle simulation with full gate-level tracing for every
entry attempt. Writes everything to SIGNAL_AUDIT_2W.md.

Run from the crypto-signal-engine directory:
    python audit_2weeks.py
    python audit_2weeks.py --days 14 --timeframe 1h
"""

import argparse
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── path fix so engine imports work when run directly ─────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import config
from backtest.data_loader import _csv_path, _read_csv
from backtest.rules import TradeRule, check_exit
from engine.classifier import SignalOutput
from engine.fvg import detect_fvgs, get_nearest_fvg
from engine.orderblocks import detect_order_blocks, get_nearest_ob

PAIRS = config.PAIRS
DATA_DIR = Path(__file__).parent / "data" / "historical"
OUT_FILE = Path(__file__).parent / "SIGNAL_AUDIT_2W.md"

MS_PER_DAY = 86_400_000


def _ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v * 100:.2f}%"


def _load_cache(pair: str, timeframe: str) -> Optional[list]:
    # Try 12m first, then 1m
    for months in (12, 1):
        p = DATA_DIR / f"signal_cache_{pair}_{timeframe}_{months}m.pkl"
        if p.exists():
            with open(p, "rb") as f:
                return pickle.load(f)
    return None


# ── verbose entry gate tracer ─────────────────────────────────────────────────

def trace_entry(
    signal: SignalOutput,
    bullish_fvg, bearish_fvg, bullish_ob, bearish_ob,
    current_price: float,
    open_positions: int,
    rules: TradeRule,
    candle_low: float,
    candle_high: float,
    current_ts: int,
) -> tuple[Optional[dict], list[str]]:
    """
    Same logic as check_entry() but returns a step-by-step gate trace.
    Returns (entry_dict_or_None, list_of_trace_lines).
    """
    gates = []

    # Gate 1: max concurrent
    if open_positions >= rules.max_concurrent:
        gates.append(f"SKIP  max_positions ({open_positions}/{rules.max_concurrent})")
        return None, gates
    gates.append(f"PASS  positions ({open_positions}/{rules.max_concurrent})")

    # Gate 2: confidence
    if signal.confidence < rules.confidence_above:
        gates.append(f"SKIP  confidence {signal.confidence} < {rules.confidence_above}")
        return None, gates
    gates.append(f"PASS  confidence {signal.confidence} >= {rules.confidence_above}")

    # Gate 3: risk color
    if rules.regime_is_green and signal.risk_color != "green":
        gates.append(f"SKIP  risk_color={signal.risk_color} (need green)")
        return None, gates
    gates.append(f"PASS  risk_color={signal.risk_color}")

    # Gate 4: action bias
    if signal.action_bias == "long_bias":
        side = "long"
    elif signal.action_bias == "short_bias":
        side = "short"
    else:
        gates.append(f"SKIP  action_bias={signal.action_bias} (stay_flat/reduce)")
        return None, gates
    gates.append(f"PASS  action_bias={signal.action_bias} → {side}")

    # Gate 5: trend confirmation
    if rules.trend_confirmed:
        if side == "long" and signal.trend_state not in ("uptrend", "transition", "ranging"):
            gates.append(f"SKIP  trend_state={signal.trend_state} (need up/ranging/transition for long)")
            return None, gates
        if side == "short" and signal.trend_state not in ("downtrend", "transition", "ranging"):
            gates.append(f"SKIP  trend_state={signal.trend_state} (need down/ranging/transition for short)")
            return None, gates
    gates.append(f"PASS  trend_state={signal.trend_state}")

    # Gate 6: price zone
    if rules.price_in_zone:
        if side == "long" and signal.price_zone not in ("discount", "equilibrium"):
            gates.append(f"SKIP  price_zone={signal.price_zone} (need discount/equil for long)")
            return None, gates
        if side == "short" and signal.price_zone not in ("premium", "equilibrium"):
            gates.append(f"SKIP  price_zone={signal.price_zone} (need premium/equil for short)")
            return None, gates
    gates.append(f"PASS  price_zone={signal.price_zone}")

    # Gate 7: level touch
    entry_zone = None
    entry_price = current_price
    sl_price = None

    if side == "long":
        level = bullish_fvg or bullish_ob
        if rules.level_touched and level is None:
            gates.append("SKIP  no bullish FVG/OB in range")
            return None, gates
        if level is not None:
            probe = candle_low
            zone_type = "fvg" if bullish_fvg else "ob"
            if probe <= level.upper_bound * 1.005:
                if probe <= level.upper_bound:
                    entry_price = level.upper_bound
                else:
                    entry_price = (level.upper_bound + level.lower_bound) / 2.0
                sl_price = level.lower_bound * 0.999
                entry_zone = {
                    "type": zone_type,
                    "upper": level.upper_bound,
                    "lower": level.lower_bound,
                    "has_fvg_overlap": getattr(level, "fvg_overlap", False),
                }
                gates.append(
                    f"PASS  {zone_type.upper()} touched: "
                    f"zone={level.lower_bound:.4f}–{level.upper_bound:.4f}, "
                    f"candle_low={candle_low:.4f}"
                )
            else:
                gates.append(
                    f"SKIP  {zone_type.upper()} not touched: "
                    f"candle_low={candle_low:.4f}, zone_top={level.upper_bound:.4f} "
                    f"(gap={(candle_low - level.upper_bound) / level.upper_bound * 100:.2f}%)"
                )
                return None, gates
        else:
            gates.append("SKIP  no bullish FVG/OB detected")
            return None, gates
    else:
        level = bearish_fvg or bearish_ob
        if rules.level_touched and level is None:
            gates.append("SKIP  no bearish FVG/OB in range")
            return None, gates
        if level is not None:
            probe = candle_high
            zone_type = "fvg" if bearish_fvg else "ob"
            if probe >= level.lower_bound * 0.995:
                if probe >= level.lower_bound:
                    entry_price = level.lower_bound
                else:
                    entry_price = (level.upper_bound + level.lower_bound) / 2.0
                sl_price = level.upper_bound * 1.001
                entry_zone = {
                    "type": zone_type,
                    "upper": level.upper_bound,
                    "lower": level.lower_bound,
                    "has_fvg_overlap": getattr(level, "fvg_overlap", False),
                }
                gates.append(
                    f"PASS  {zone_type.upper()} touched: "
                    f"zone={level.lower_bound:.4f}–{level.upper_bound:.4f}, "
                    f"candle_high={candle_high:.4f}"
                )
            else:
                gates.append(
                    f"SKIP  {zone_type.upper()} not touched: "
                    f"candle_high={candle_high:.4f}, zone_bot={level.lower_bound:.4f} "
                    f"(gap={(level.lower_bound - candle_high) / level.lower_bound * 100:.2f}%)"
                )
                return None, gates
        else:
            gates.append("SKIP  no bearish FVG/OB detected")
            return None, gates

    risk_distance = abs(entry_price - sl_price)
    if risk_distance < entry_price * 0.0001:
        gates.append(f"SKIP  risk_distance too small ({risk_distance:.6f})")
        return None, gates

    if side == "long":
        tp1 = entry_price + risk_distance * rules.take_profit_1_rr
    else:
        tp1 = entry_price - risk_distance * rules.take_profit_1_rr

    from backtest.rules import _get_size_multiplier
    size_mult = _get_size_multiplier(signal.confidence, rules)

    entry_dict = {
        "side": side,
        "entry_price": entry_price,
        "stop_loss": sl_price,
        "tp1": tp1,
        "tp2_target": None,
        "size_multiplier": size_mult,
        "risk_distance": risk_distance,
        "entry_zone": entry_zone,
        "entry_ts": current_ts,
        "regime_at_entry": signal.regime_state,
        "risk_color_at_entry": signal.risk_color,
        "reason": f"{signal.regime_state} | conf={signal.confidence} | zone={entry_zone['type']}",
        "confidence_at_entry": signal.confidence,
    }
    return entry_dict, gates


# ── position tracking ─────────────────────────────────────────────────────────

class Position:
    _next_id = 1

    def __init__(self, entry: dict, equity: float, rules: TradeRule):
        self.id = Position._next_id
        Position._next_id += 1
        self.side = entry["side"]
        self.entry_price = entry["entry_price"]
        self.stop_loss = entry["stop_loss"]
        self.tp1 = entry["tp1"]
        self.tp2_target = entry.get("tp2_target")
        self.risk_distance = entry["risk_distance"]
        self.entry_zone = entry.get("entry_zone")
        self.entry_ts = entry["entry_ts"]
        self.regime_at_entry = entry["regime_at_entry"]
        self.risk_color_at_entry = entry["risk_color_at_entry"]
        self.confidence_at_entry = entry.get("confidence_at_entry", 0)

        # Position sizing (same as simulator)
        slip = self.entry_price * config.SLIPPAGE_PERCENT
        self.actual_entry = self.entry_price + slip if self.side == "long" else self.entry_price - slip
        actual_risk = abs(self.actual_entry - self.stop_loss)
        risk_usd = equity * rules.risk_percent_base * entry["size_multiplier"]
        self.size_usd = risk_usd / (actual_risk / self.actual_entry) if actual_risk > 0 else 0
        self.contracts = self.size_usd / self.actual_entry if self.actual_entry > 0 else 0

        self.tp1_hit = False
        self.partial_pnl = 0.0


# ── main audit loop ───────────────────────────────────────────────────────────

def run_audit(pair: str, timeframe: str, days: int, mode: str) -> list[str]:
    """Run audit for one pair/timeframe/mode. Returns markdown lines."""
    rules = TradeRule(
        regime_is_green=(mode == "conservative"),
        confidence_above=config.CONFIDENCE_THRESHOLD_TRADE,
    )

    # Load CSV data
    csv_file = _csv_path(pair, timeframe)
    if not csv_file.exists():
        return [f"> **No CSV data found for {pair} {timeframe}**\n"]
    candles = _read_csv(csv_file)
    if not candles:
        return [f"> **Empty CSV for {pair} {timeframe}**\n"]

    # Load signal cache
    signal_cache = _load_cache(pair, timeframe)
    if signal_cache is None:
        return [f"> **No signal cache found for {pair} {timeframe}. Run the 12m backtest first.**\n"]

    # Align cache length to candles (cache may be built from a different slice)
    n = len(candles)
    if len(signal_cache) != n:
        # Trim or pad to match
        if len(signal_cache) > n:
            signal_cache = signal_cache[-n:]
        else:
            signal_cache = [None] * (n - len(signal_cache)) + signal_cache

    # Slice last N days
    cutoff_ms = candles[-1]["timestamp"] - days * MS_PER_DAY
    start_idx = next((i for i, c in enumerate(candles) if c["timestamp"] >= cutoff_ms), 0)
    # Ensure we have at least 200 candles of look-back context for FVG/OB detection
    context_start = max(0, start_idx - 200)

    audit_candles = candles[start_idx:]
    period_start = _ts(audit_candles[0]["timestamp"])
    period_end = _ts(audit_candles[-1]["timestamp"])

    lines: list[str] = []
    lines.append(f"### {pair} · {timeframe} · {mode.upper()}\n")
    lines.append(f"Period: **{period_start}** → **{period_end}** ({len(audit_candles)} candles)\n")

    open_positions: list[Position] = []
    closed_trades: list[dict] = []
    equity = config.INITIAL_CAPITAL
    signals_checked = 0
    entries_attempted = 0
    entries_taken = 0
    skipped_below_conf = 0

    for local_i, candle in enumerate(audit_candles):
        global_i = start_idx + local_i
        ts = candle["timestamp"]
        signal: Optional[SignalOutput] = signal_cache[global_i] if global_i < len(signal_cache) else None

        # ── Exit checks ──
        for pos in list(open_positions):
            if signal is None:
                continue
            exit_result = check_exit(
                position={
                    "side": pos.side,
                    "entry_price": pos.actual_entry,
                    "stop_loss": pos.stop_loss,
                    "tp1": pos.tp1,
                    "tp2_target": pos.tp2_target,
                    "entry_ts": pos.entry_ts,
                    "tp1_hit": pos.tp1_hit,
                },
                current_candle=candle,
                current_signal=signal,
                rules=rules,
            )

            if exit_result:
                reason = exit_result["exit_reason"]

                if reason == "tp1" and not pos.tp1_hit:
                    # Partial close at TP1
                    pos.tp1_hit = True
                    partial_gross = exit_result["pnl_percent"] * pos.size_usd * 0.5
                    partial_fee = abs(pos.contracts * 0.5 * exit_result["exit_price"]) * config.TAKER_FEE_PERCENT
                    pos.partial_pnl = partial_gross - partial_fee
                    equity += pos.partial_pnl
                    pos.contracts *= 0.5
                    pos.size_usd *= 0.5
                    if pos.tp2_target is None:
                        if pos.side == "long":
                            pos.tp2_target = pos.actual_entry + pos.risk_distance * 3.0
                        else:
                            pos.tp2_target = pos.actual_entry - pos.risk_distance * 3.0
                    pos.stop_loss = pos.actual_entry  # move SL to breakeven

                    lines.append(
                        f"  - `{_ts(ts)}` 🟡 **TP1 PARTIAL** #{pos.id} {pos.side.upper()} "
                        f"exit @ {exit_result['exit_price']:.4f} | "
                        f"partial P&L {_pct(exit_result['pnl_percent'])} | "
                        f"SL moved to breakeven, TP2 set @ {pos.tp2_target:.4f}\n"
                    )
                    continue

                # Full close
                gross = exit_result["pnl_percent"] * pos.size_usd
                hold_h = (ts - pos.entry_ts) / 3_600_000
                fee = abs(pos.contracts * exit_result["exit_price"]) * config.TAKER_FEE_PERCENT
                slip = abs(pos.contracts * exit_result["exit_price"]) * config.SLIPPAGE_PERCENT
                net = gross - fee - slip + pos.partial_pnl
                equity += net

                win = "WIN" if net > 0 else "LOSS"
                icon = "🟢" if net > 0 else "🔴"
                lines.append(
                    f"  - `{_ts(ts)}` {icon} **{reason.upper()} {win}** #{pos.id} {pos.side.upper()} "
                    f"exit @ {exit_result['exit_price']:.4f} | "
                    f"gross {_pct(exit_result['pnl_percent'])} | "
                    f"net ${net:+.2f} | hold {hold_h:.1f}h | "
                    f"equity → ${equity:,.2f}\n"
                )
                closed_trades.append({
                    "id": pos.id,
                    "side": pos.side,
                    "entry_price": pos.actual_entry,
                    "exit_price": exit_result["exit_price"],
                    "exit_reason": reason,
                    "net_pnl": net,
                    "pnl_pct": exit_result["pnl_percent"],
                    "hold_h": hold_h,
                    "regime": pos.regime_at_entry,
                    "confidence": pos.confidence_at_entry,
                    "zone": pos.entry_zone.get("type") if pos.entry_zone else "none",
                    "entry_ts": pos.entry_ts,
                    "exit_ts": ts,
                })
                open_positions.remove(pos)

        # ── Entry check ──
        if signal is None:
            continue

        signals_checked += 1

        # Skip logging entirely if well below threshold AND no positions open
        if signal.confidence < 60 and not open_positions:
            skipped_below_conf += 1
            continue

        # Detect FVG/OB for this candle (no future leak: use candles up to global_i)
        context = candles[context_start: global_i + 1]
        fvgs = detect_fvgs(context[-100:])
        obs = detect_order_blocks(context[-100:], fvgs)
        current_price = candle["close"]
        bullish_fvg = get_nearest_fvg(fvgs, current_price, "bullish")
        bearish_fvg = get_nearest_fvg(fvgs, current_price, "bearish")
        bullish_ob = get_nearest_ob(obs, current_price, "bullish")
        bearish_ob = get_nearest_ob(obs, current_price, "bearish")

        entries_attempted += 1

        entry, gates = trace_entry(
            signal=signal,
            bullish_fvg=bullish_fvg,
            bearish_fvg=bearish_fvg,
            bullish_ob=bullish_ob,
            bearish_ob=bearish_ob,
            current_price=current_price,
            open_positions=len(open_positions),
            rules=rules,
            candle_low=candle["low"],
            candle_high=candle["high"],
            current_ts=ts,
        )

        # Determine final gate result line for summary
        final_gate = gates[-1]
        passed = entry is not None

        # Format signal summary line
        conf_icon = "🟢" if signal.confidence >= 80 else ("🟡" if signal.confidence >= 70 else "⚪")
        risk_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(signal.risk_color, "⚫")

        signal_line = (
            f"- `{_ts(ts)}` {conf_icon}{risk_icon} "
            f"**{signal.regime_state}** conf={signal.confidence} "
            f"bias={signal.action_bias} trend={signal.trend_state} zone={signal.price_zone} "
            f"price={current_price:.4f}"
        )

        if passed:
            entries_taken += 1
            pos = Position(entry, equity, rules)
            entry_fee = pos.size_usd * config.TAKER_FEE_PERCENT
            equity -= entry_fee
            open_positions.append(pos)

            lines.append(signal_line + "\n")
            lines.append(f"  - Gates: {' → '.join(gates)}\n")
            lines.append(
                f"  - ✅ **TRADE ENTERED #{pos.id}** {pos.side.upper()} "
                f"entry={pos.actual_entry:.4f} SL={pos.stop_loss:.4f} TP1={pos.tp1:.4f} "
                f"size=${pos.size_usd:,.0f} ({entry['size_multiplier']}× mult) "
                f"zone={entry['entry_zone']['type'].upper() if entry.get('entry_zone') else 'n/a'} "
                f"equity → ${equity:,.2f}\n"
            )
        else:
            # Only log failed entries near threshold — don't flood the doc
            if signal.confidence >= 65:
                lines.append(signal_line + "\n")
                lines.append(f"  - Gates: {' → '.join(gates)}\n")

    # ── Section summary ──
    wins = sum(1 for t in closed_trades if t["net_pnl"] > 0)
    total = len(closed_trades)
    win_rate = wins / total if total else 0
    net_total = sum(t["net_pnl"] for t in closed_trades)

    lines.append("\n")
    lines.append(f"**Summary** — {signals_checked} signals checked "
                 f"({skipped_below_conf} below conf<60 skipped) | "
                 f"{entries_attempted} above threshold | "
                 f"{entries_taken} trades entered | "
                 f"{total} closed\n")
    if total:
        lines.append(
            f"Win rate: **{win_rate * 100:.1f}%** ({wins}/{total}) | "
            f"Net P&L: **${net_total:+,.2f}** | "
            f"Final equity: **${equity:,.2f}**\n"
        )
        lines.append("\n#### Closed Trade Log\n\n")
        lines.append("| # | Side | Entry | Exit | Reason | P&L% | Net $ | Hold | Regime | Conf | Zone |\n")
        lines.append("|---|------|-------|------|--------|------|-------|------|--------|------|------|\n")
        for t in closed_trades:
            lines.append(
                f"| {t['id']} | {t['side']} | {t['entry_price']:.4f} | {t['exit_price']:.4f} "
                f"| {t['exit_reason']} | {_pct(t['pnl_pct'])} | ${t['net_pnl']:+.2f} "
                f"| {t['hold_h']:.1f}h | {t['regime']} | {t['confidence']} | {t['zone']} |\n"
            )
    else:
        lines.append("No trades closed in this window.\n")

    lines.append("\n---\n\n")
    return lines


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="Look-back window in days")
    parser.add_argument("--timeframe", default="1h", choices=["1h", "4h"])
    parser.add_argument("--pair", default=None, help="Single pair (default: all)")
    parser.add_argument("--mode", default="both", choices=["aggressive", "conservative", "both"])
    args = parser.parse_args()

    pairs = [args.pair] if args.pair else PAIRS
    modes = ["aggressive", "conservative"] if args.mode == "both" else [args.mode]
    timeframes = ["1h", "4h"] if args.timeframe == "both" else [args.timeframe]

    run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_lines: list[str] = []

    all_lines.append(f"# Signal Audit — Last {args.days} Days\n\n")
    all_lines.append(f"Generated: **{run_date}**  \n")
    all_lines.append(f"Pairs: {', '.join(pairs)}  \n")
    all_lines.append(f"Timeframe: {args.timeframe}  \n")
    all_lines.append(f"Modes: {args.mode}  \n")
    all_lines.append(f"Confidence threshold: {config.CONFIDENCE_THRESHOLD_TRADE}  \n")
    all_lines.append(f"Capital: ${config.INITIAL_CAPITAL:,}  \n")
    all_lines.append(f"Max hold: {config.MAX_HOLD_HOURS}h  \n")
    all_lines.append(f"Leverage: {config.DEFAULT_LEVERAGE}×  \n\n")
    all_lines.append("---\n\n")

    all_lines.append("## Legend\n\n")
    all_lines.append("- 🟢 = green signal / win trade  \n")
    all_lines.append("- 🟡 = yellow signal / TP1 partial  \n")
    all_lines.append("- 🔴 = red signal / loss trade  \n")
    all_lines.append("- ⚪ = below threshold (conf < 70)  \n")
    all_lines.append("- `PASS` = gate condition met  \n")
    all_lines.append("- `SKIP` = gate failed, trade not taken  \n\n")
    all_lines.append("---\n\n")

    for mode in modes:
        all_lines.append(f"## Mode: {mode.upper()}\n\n")
        for pair in pairs:
            print(f"  Running {pair} {args.timeframe} {mode}...", flush=True)
            section = run_audit(pair, args.timeframe, args.days, mode)
            all_lines.extend(section)

    OUT_FILE.write_text("".join(all_lines), encoding="utf-8")
    print(f"\nAudit written to {OUT_FILE}")


if __name__ == "__main__":
    main()
