"""
Demo test: run simulation on last 2 days of CACHED data for all pairs.
Uses existing CSVs + signal cache pickles — no downloads required.

Usage:
    python demo_2day_test.py
    python demo_2day_test.py --days 3
    python demo_2day_test.py --aggressive   # yellow + green signals (conf >= 70)
    python demo_2day_test.py --conservative # green only (conf >= 70)
"""

import argparse
import csv
import logging
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from backtest.rules import TradeRule
from backtest.simulator import run_backtest_from_cache

logging.basicConfig(level=logging.WARNING)

DATA_DIR = Path(__file__).parent / "data" / "historical"
PAIRS = config.PAIRS       # ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TAOUSDT"]
TIMEFRAME = "1h"           # only 1h CSVs exist in cache
CANDLES_PER_DAY = 24       # 1h → 24 candles per day


def _load_csv(pair: str) -> list[dict]:
    path = DATA_DIR / f"{pair}_{TIMEFRAME}.csv"
    if not path.exists():
        return []
    candles = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            c = {}
            for k, v in row.items():
                if k in ("pair", "timeframe"):
                    c[k] = v
                elif v == "" or v is None:
                    c[k] = None
                else:
                    try:
                        c[k] = int(v) if k == "timestamp" else float(v)
                    except ValueError:
                        c[k] = None
            candles.append(c)
    return sorted(candles, key=lambda c: c["timestamp"])


def _load_cache(pair: str, months_tag: str) -> list | None:
    path = DATA_DIR / f"signal_cache_{pair}_{TIMEFRAME}_{months_tag}m.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def _fmt_ts(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def run_pair(pair: str, days: int, regime_is_green: bool) -> dict | None:
    window = days * CANDLES_PER_DAY  # candles to simulate

    candles = _load_csv(pair)
    if not candles:
        print(f"  ✗ {pair}: no CSV found")
        return None

    # Try 12m cache first, fall back to 1m
    cache = _load_cache(pair, "12") or _load_cache(pair, "1")
    if cache is None:
        print(f"  ✗ {pair}: no signal cache found — run backtest.runner first")
        return None

    if len(candles) != len(cache):
        # Cache may be from a different CSV length — regenerate is the right fix,
        # but here we align by taking the tail that matches
        min_len = min(len(candles), len(cache))
        candles = candles[-min_len:]
        cache = cache[-min_len:]

    if len(candles) < window:
        print(f"  ✗ {pair}: only {len(candles)} candles, need {window}")
        return None

    # Slice last N candles (signal at each index was computed using full prior history)
    candles_2d = candles[-window:]
    cache_2d = cache[-window:]

    rules = TradeRule(
        regime_is_green=regime_is_green,
        confidence_above=config.CONFIDENCE_THRESHOLD_TRADE,
        max_hold_hours=config.MAX_HOLD_HOURS,
    )

    state = run_backtest_from_cache(
        candles_2d, cache_2d, rules,
        initial_capital=config.INITIAL_CAPITAL,
        slippage=config.SLIPPAGE_PERCENT,
        fees=config.TAKER_FEE_PERCENT,
    )

    trades = state.closed_trades
    wins = sum(1 for t in trades if t.net_pnl_usd > 0)
    longs = sum(1 for t in trades if t.side == "long")
    shorts = sum(1 for t in trades if t.side == "short")
    net_pnl = sum(t.net_pnl_usd for t in trades)

    return {
        "pair": pair,
        "period": f"{_fmt_ts(candles_2d[0]['timestamp'])} → {_fmt_ts(candles_2d[-1]['timestamp'])} UTC",
        "total": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "longs": longs,
        "shorts": shorts,
        "win_rate": wins / len(trades) if trades else 0.0,
        "net_pnl": net_pnl,
        "final_equity": state.equity,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--aggressive", action="store_true",
                        help="Yellow + green signals (no OI key needed)")
    parser.add_argument("--conservative", action="store_true",
                        help="Green signals only (requires OI data)")
    args = parser.parse_args()

    # Default: aggressive (matches live engine without CoinGlass key)
    regime_is_green = args.conservative and not args.aggressive
    mode_label = "conservative (green only)" if regime_is_green else "aggressive (yellow+green)"

    print(f"\n{'='*68}")
    print(f"  {args.days}-DAY DEMO BACKTEST — {TIMEFRAME} — All pairs")
    print(f"  Mode: {mode_label}")
    print(f"  Confidence threshold: {config.CONFIDENCE_THRESHOLD_TRADE}")
    print(f"  Max hold: {config.MAX_HOLD_HOURS}h | Leverage: {config.DEFAULT_LEVERAGE}x")
    print(f"  Capital: ${config.INITIAL_CAPITAL:,.0f}")
    print(f"{'='*68}\n")

    results = []
    for pair in PAIRS:
        result = run_pair(pair, args.days, regime_is_green)
        if result:
            results.append(result)
            wr = f"{result['win_rate']*100:.0f}%" if result["total"] else "—"
            pnl_str = f"+${result['net_pnl']:,.2f}" if result["net_pnl"] >= 0 else f"-${abs(result['net_pnl']):,.2f}"
            print(f"  {pair}")
            print(f"    Period : {result['period']}")
            print(f"    Trades : {result['total']}  (L:{result['longs']} S:{result['shorts']})  W:{result['wins']} / L:{result['losses']}  WR {wr}")
            print(f"    Net P&L: {pnl_str}  |  Equity: ${result['final_equity']:,.2f}")
            print()

    if not results:
        print("No results — check data files in data/historical/")
        sys.exit(1)

    total_trades = sum(r["total"] for r in results)
    total_wins = sum(r["wins"] for r in results)
    total_pnl = sum(r["net_pnl"] for r in results)
    overall_wr = total_wins / total_trades if total_trades else 0.0

    print(f"{'='*68}")
    print(f"  TOTALS ACROSS ALL PAIRS")
    print(f"{'='*68}")
    print(f"  {'Pair':<12} {'Trades':>7} {'Wins':>5} {'Losses':>7} {'WR':>5}  Net P&L")
    print(f"  {'-'*55}")
    for r in results:
        wr = f"{r['win_rate']*100:.0f}%" if r["total"] else "—"
        pnl_str = f"+${r['net_pnl']:,.2f}" if r["net_pnl"] >= 0 else f"-${abs(r['net_pnl']):,.2f}"
        print(f"  {r['pair']:<12} {r['total']:>7} {r['wins']:>5} {r['losses']:>7} {wr:>5}  {pnl_str}")
    print(f"  {'-'*55}")
    wr_str = f"{overall_wr*100:.0f}%" if total_trades else "—"
    pnl_str = f"+${total_pnl:,.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):,.2f}"
    print(f"  {'TOTAL':<12} {total_trades:>7} {total_wins:>5} {total_trades-total_wins:>7} {wr_str:>5}  {pnl_str}")
    print(f"{'='*68}\n")


if __name__ == "__main__":
    main()
