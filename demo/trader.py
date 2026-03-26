"""
Paper trading engine.
Integrates with the live full_analysis scheduler loop.
Reuses backtest/rules.py directly — no logic duplication.
"""

import asyncio
import logging
import time
from typing import Optional

import config
from backtest.rules import TradeRule, check_entry, check_exit
from demo import store as demo_store
from engine.classifier import SignalOutput
from engine.fvg import FVG
from engine.orderblocks import OrderBlock

logger = logging.getLogger(__name__)

# Shared reference to live_state for mark-to-market pricing
_live_state: dict = {}


def set_live_state_ref(state: dict) -> None:
    global _live_state
    _live_state = state


class DemoTrader:
    def __init__(
        self,
        initial_capital: float = config.INITIAL_CAPITAL,
        leverage: float = config.DEFAULT_LEVERAGE,
        slippage: float = config.SLIPPAGE_PERCENT,
        fees: float = config.TAKER_FEE_PERCENT,
        mode: str = "aggressive",
    ):
        self._initial_capital = initial_capital
        self._equity: float = initial_capital
        self._open_positions: list[dict] = []
        self._leverage = leverage
        self._slippage = slippage
        self._fees = fees
        self._mode = mode
        # aggressive = trades on yellow+green (regime_is_green=False)
        # conservative = trades only on green (regime_is_green=True)
        self._rules = TradeRule(regime_is_green=(mode == "conservative"))
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        return self._mode

    def load_state(self) -> None:
        """Restore open positions and equity from DB on startup / restart."""
        self._open_positions = demo_store.fetch_open_positions(mode=self._mode)
        self._equity = demo_store.get_current_equity(mode=self._mode)
        logger.info(
            "Demo trader loaded: equity=$%.2f, open_positions=%d",
            self._equity,
            len(self._open_positions),
        )

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def open_positions(self) -> list[dict]:
        return list(self._open_positions)

    def mark_to_market(self, position: dict, current_price: float) -> float:
        """Unrealized leveraged P&L in USD for a position at current_price."""
        entry = position["entry_price"]
        size_usd = position["size_usd"]
        leverage = position.get("leverage", self._leverage)
        side = position["side"]

        if entry <= 0:
            return 0.0

        price_change_pct = (current_price - entry) / entry
        if side == "short":
            price_change_pct = -price_change_pct

        return size_usd * price_change_pct * leverage

    def _liquidation_price(self, entry_price: float, side: str, leverage: float) -> float:
        mm = config.MAINTENANCE_MARGIN_RATE
        if side == "long":
            return entry_price * (1 - (1 / leverage) + mm)
        else:
            return entry_price * (1 + (1 / leverage) - mm)

    async def on_signal(
        self,
        signal: SignalOutput,
        pair: str,
        timeframe: str,
        current_price: float,
        current_candle: dict,
        bullish_fvg: Optional[FVG],
        bearish_fvg: Optional[FVG],
        bullish_ob: Optional[OrderBlock],
        bearish_ob: Optional[OrderBlock],
        timestamp_ms: int,
    ) -> None:
        """
        Called once per (pair, timeframe) per full_analysis cycle.
        Processes exits for existing positions, then checks for new entry.
        """
        async with self._lock:
            # ─── Process exits for this pair+tf ───
            for pos in [p for p in self._open_positions
                        if p["pair"] == pair and p["timeframe"] == timeframe]:
                exit_result = check_exit(
                    position=pos,
                    current_candle=current_candle,
                    current_signal=signal,
                    rules=self._rules,
                )
                if not exit_result:
                    continue

                if exit_result["exit_reason"] == "tp1" and not pos.get("tp1_hit"):
                    # TP1 partial close: close 50%, move stop to breakeven, set TP2
                    self._handle_tp1_partial(pos, exit_result, timestamp_ms)
                else:
                    # Full close
                    self._close_position(pos, exit_result, timestamp_ms)

            # ─── Check for new entry ───
            open_count = len(self._open_positions)
            entry = check_entry(
                signal=signal,
                bullish_fvg=bullish_fvg,
                bearish_fvg=bearish_fvg,
                bullish_ob=bullish_ob,
                bearish_ob=bearish_ob,
                current_price=current_price,
                open_positions=open_count,
                rules=self._rules,
                current_ts=timestamp_ms,
                candle_low=current_candle.get("low"),
                candle_high=current_candle.get("high"),
            )

            if entry:
                self._open_position(entry, pair, timeframe, signal.confidence, timestamp_ms)

    def _open_position(
        self,
        entry: dict,
        pair: str,
        timeframe: str,
        confidence: int,
        timestamp_ms: int,
    ) -> None:
        """Size and persist a new paper position."""
        risk_usd = self._equity * self._rules.risk_percent_base * entry["size_multiplier"]
        if entry["risk_distance"] <= 0:
            return

        size_usd = risk_usd / (entry["risk_distance"] / entry["entry_price"])
        if size_usd <= 0 or size_usd > self._equity * 5:
            return

        # Apply entry slippage
        slip = entry["entry_price"] * self._slippage
        actual_entry = entry["entry_price"] + slip if entry["side"] == "long" else entry["entry_price"] - slip

        entry_fee = size_usd * self._fees
        self._equity -= entry_fee

        margin_usd = size_usd / self._leverage
        liq_price = self._liquidation_price(actual_entry, entry["side"], self._leverage)

        pos = {
            "pair": pair,
            "timeframe": timeframe,
            "side": entry["side"],
            "entry_price": actual_entry,
            "stop_loss": entry["stop_loss"],
            "tp1": entry["tp1"],
            "tp2_target": entry.get("tp2_target"),
            "size_usd": size_usd,
            "risk_distance": entry["risk_distance"],
            "size_multiplier": entry["size_multiplier"],
            "leverage": self._leverage,
            "margin_usd": margin_usd,
            "liquidation_price": liq_price,
            "entry_ts": timestamp_ms,
            "regime_at_entry": entry["regime_at_entry"],
            "risk_color_at_entry": entry.get("risk_color_at_entry", ""),
            "entry_zone_type": (entry.get("entry_zone") or {}).get("type"),
            "confidence_at_entry": confidence,
            "tp1_hit": 0,
            "partial_exit_pnl": 0.0,
            "mode": self._mode,
        }

        row_id = demo_store.insert_position(pos)
        pos["id"] = row_id
        self._open_positions.append(pos)

        logger.info(
            "DEMO ENTRY: %s %s %s @ %.4f | lev=%dx | SL=%.4f | conf=%d",
            pair, timeframe, entry["side"].upper(), actual_entry,
            int(self._leverage), entry["stop_loss"], confidence,
        )

    def _handle_tp1_partial(self, pos: dict, exit_result: dict, timestamp_ms: int) -> None:
        """Close 50% at TP1, move stop to breakeven, set TP2 at 3R."""
        partial_size = pos["size_usd"] * 0.5
        gross_pnl = exit_result["pnl_percent"] * partial_size * self._leverage
        fee = partial_size * self._fees
        net = gross_pnl - fee

        self._equity += net

        # Update in-memory position
        pos["tp1_hit"] = 1
        pos["stop_loss"] = pos["entry_price"]  # move to breakeven
        pos["size_usd"] = partial_size
        pos["partial_exit_pnl"] = net

        if pos["tp2_target"] is None:
            rd = pos["risk_distance"]
            if pos["side"] == "long":
                pos["tp2_target"] = pos["entry_price"] + rd * 3.0
            else:
                pos["tp2_target"] = pos["entry_price"] - rd * 3.0

        demo_store.update_position(pos["id"], {
            "tp1_hit": 1,
            "stop_loss": pos["stop_loss"],
            "size_usd": pos["size_usd"],
            "partial_exit_pnl": net,
            "tp2_target": pos["tp2_target"],
        })

        logger.info(
            "DEMO TP1: %s %s — partial close @ %.4f | net P&L=$%.2f",
            pos["pair"], pos["side"].upper(), exit_result["exit_price"], net,
        )

    def _close_position(self, pos: dict, exit_result: dict, timestamp_ms: int) -> None:
        """Full close — book trade record and update equity."""
        exit_price = exit_result["exit_price"]
        pnl_pct_raw = exit_result["pnl_percent"]  # unleveraged

        gross_pnl = pnl_pct_raw * pos["size_usd"] * self._leverage
        hold_hours = (timestamp_ms - pos["entry_ts"]) / 3_600_000
        funding_periods = int(hold_hours / 8)
        funding_cost = abs(pos["size_usd"]) * 0.0001 * funding_periods

        exit_fee = pos["size_usd"] * self._fees
        net_pnl = gross_pnl - exit_fee - funding_cost + pos.get("partial_exit_pnl", 0.0)

        self._equity += net_pnl

        pnl_leveraged_pct = pnl_pct_raw * self._leverage

        trade = {
            "position_id": pos["id"],
            "pair": pos["pair"],
            "timeframe": pos["timeframe"],
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "entry_ts": pos["entry_ts"],
            "exit_ts": timestamp_ms,
            "exit_reason": exit_result["exit_reason"],
            "pnl_usd": gross_pnl,
            "pnl_percent": pnl_pct_raw,
            "fee_usd": exit_fee + funding_cost,
            "net_pnl_usd": net_pnl,
            "size_usd": pos["size_usd"],
            "leverage": pos.get("leverage", self._leverage),
            "margin_usd": pos.get("margin_usd", pos["size_usd"] / self._leverage),
            "pnl_leveraged_pct": pnl_leveraged_pct,
            "regime_at_entry": pos["regime_at_entry"],
            "confidence_at_entry": pos.get("confidence_at_entry", 0),
            "entry_zone_type": pos.get("entry_zone_type"),
            "hold_hours": hold_hours,
            "mode": self._mode,
        }
        demo_store.insert_trade(trade)
        demo_store.close_position(pos["id"], timestamp_ms)
        self._open_positions = [p for p in self._open_positions if p["id"] != pos["id"]]

        logger.info(
            "DEMO EXIT: %s %s @ %.4f | reason=%s | net=$%.2f | equity=$%.2f",
            pos["pair"], pos["side"].upper(), exit_price,
            exit_result["exit_reason"], net_pnl, self._equity,
        )

    def record_equity_snapshot(self, timestamp_ms: int) -> None:
        """Called once per full_analysis cycle (not per pair). Records equity + open P&L."""
        open_pnl = 0.0
        for pos in self._open_positions:
            last_price = _live_state.get(pos["pair"], {}).get("last_price", pos["entry_price"])
            open_pnl += self.mark_to_market(pos, last_price)

        demo_store.upsert_equity_snapshot(
            ts=timestamp_ms,
            equity=self._equity,
            open_pnl=open_pnl,
            open_count=len(self._open_positions),
            mode=self._mode,
        )

    def get_positions_with_mtm(self, live_state: dict) -> list[dict]:
        """Return open positions enriched with current price + MTM P&L."""
        result = []
        for pos in self._open_positions:
            current_price = live_state.get(pos["pair"], {}).get("last_price", pos["entry_price"])
            mtm = self.mark_to_market(pos, current_price)
            entry = pos["entry_price"]
            leverage = pos.get("leverage", self._leverage)

            if entry > 0:
                price_change_pct = (current_price - entry) / entry
                if pos["side"] == "short":
                    price_change_pct = -price_change_pct
            else:
                price_change_pct = 0.0

            pct_leveraged = price_change_pct * leverage
            margin_usd = pos.get("margin_usd", pos["size_usd"] / leverage)

            # Risk to liquidation
            liq = pos.get("liquidation_price")
            risk_to_liq = 0.0
            if liq and entry > 0:
                risk_to_liq = abs(current_price - liq) / liq * 100

            # Current R:R
            sl = pos["stop_loss"]
            tp1 = pos["tp1"]
            risk_dist = abs(entry - sl)
            current_move = abs(current_price - entry)
            current_rr = current_move / risk_dist if risk_dist > 0 else 0.0
            tp1_rr = abs(tp1 - entry) / risk_dist if risk_dist > 0 else 0.0
            tp2 = pos.get("tp2_target")
            tp2_rr = abs(tp2 - entry) / risk_dist if tp2 and risk_dist > 0 else None

            hold_ms = int(time.time() * 1000) - pos["entry_ts"]
            hold_h = int(hold_ms / 3_600_000)
            hold_m = int((hold_ms % 3_600_000) / 60_000)

            result.append({
                **pos,
                "current_price": current_price,
                "unrealized_pnl": {
                    "usd": round(mtm, 2),
                    "pct_unleveraged": round(price_change_pct * 100, 3),
                    "pct_leveraged": round(pct_leveraged * 100, 3),
                    "roi_on_margin": round(pct_leveraged * 100, 3),
                },
                "risk_reward": {
                    "current_rr": round(current_rr, 2),
                    "target_rr_tp1": round(tp1_rr, 2),
                    "target_rr_tp2": round(tp2_rr, 2) if tp2_rr else None,
                },
                "liquidation_price": liq,
                "risk_to_liq_pct": round(risk_to_liq, 2),
                "hold_duration": f"{hold_h}h {hold_m}m",
            })
        return result

    def get_portfolio_summary(self, live_state: dict) -> dict:
        """Aggregate portfolio metrics across all open positions."""
        total_margin = sum(p.get("margin_usd", 0) for p in self._open_positions)
        total_notional = sum(p["size_usd"] for p in self._open_positions)
        total_open_pnl = sum(
            self.mark_to_market(p, live_state.get(p["pair"], {}).get("last_price", p["entry_price"]))
            for p in self._open_positions
        )
        effective_leverage = total_notional / self._equity if self._equity > 0 else 0.0
        margin_util_pct = total_margin / self._equity * 100 if self._equity > 0 else 0.0

        return {
            "total_margin_used": round(total_margin, 2),
            "total_unrealized_pnl_usd": round(total_open_pnl, 2),
            "total_notional_exposure": round(total_notional, 2),
            "effective_leverage": round(effective_leverage, 2),
            "margin_utilization_pct": round(margin_util_pct, 2),
            "available_margin": round(self._equity - total_margin, 2),
            "current_equity": round(self._equity, 2),
        }
