"""
Adapter: converts demo_trades dicts into TradeRecord dataclasses,
then delegates to backtest/metrics.py — no logic duplication.
"""

import dataclasses
from typing import Optional

from backtest.metrics import calculate_metrics
from backtest.simulator import TradeRecord
from demo import store as demo_store
import config


def _dict_to_trade_record(d: dict) -> TradeRecord:
    """Convert a demo_trades row dict to a TradeRecord for metrics calculation."""
    return TradeRecord(
        id=d["id"],
        side=d["side"],
        entry_price=d["entry_price"],
        exit_price=d["exit_price"],
        entry_ts=d["entry_ts"],
        exit_ts=d["exit_ts"],
        exit_reason=d["exit_reason"],
        pnl_usd=d["pnl_usd"],
        pnl_percent=d["pnl_percent"],
        fee_usd=d["fee_usd"],
        slippage_usd=0.0,
        net_pnl_usd=d["net_pnl_usd"],
        size_usd=d["size_usd"],
        regime_at_entry=d["regime_at_entry"],
        risk_color_at_entry=d.get("risk_color_at_entry", ""),
        entry_zone_type=d.get("entry_zone_type"),
        confidence_at_entry=d.get("confidence_at_entry", 0),
        hold_hours=d.get("hold_hours", 0.0),
        had_fvg_overlap=(d.get("entry_zone_type") == "fvg"),
    )


def compute_demo_metrics(current_equity: float) -> Optional[dict]:
    """
    Load all closed demo trades + equity curve from DB and return metrics dict.
    Returns None if no trades yet.
    """
    trades_raw = demo_store.fetch_all_closed_trades()
    if not trades_raw:
        return None

    equity_rows = demo_store.fetch_equity_curve(limit=10000)
    equity_curve = [(r["timestamp"], r["equity"]) for r in equity_rows]

    # Build drawdown curve from equity curve
    drawdown_curve = []
    peak = config.INITIAL_CAPITAL
    for ts, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        drawdown_curve.append((ts, dd))

    trades = [_dict_to_trade_record(t) for t in trades_raw]
    result = calculate_metrics(
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        initial_capital=config.INITIAL_CAPITAL,
    )

    d = dataclasses.asdict(result)
    # Override final_equity with current live equity (includes open positions)
    d["current_equity"] = current_equity
    d["initial_capital"] = config.INITIAL_CAPITAL
    return d
