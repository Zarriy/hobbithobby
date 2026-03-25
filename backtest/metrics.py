"""
Performance statistics from trade history and equity curve.
"""

import math
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


@dataclass
class BacktestResult:
    total_return_percent: float
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown_percent: float
    max_drawdown_duration_hours: float
    sharpe_ratio: float
    sortino_ratio: float
    expectancy_per_trade: float
    avg_trade_duration_hours: float
    max_consecutive_losses: int
    max_consecutive_wins: int

    # Regime breakdown
    trades_in_accumulation: int = 0
    win_rate_accumulation: float = 0.0
    trades_in_distribution: int = 0
    win_rate_distribution: float = 0.0

    # Level-type breakdown
    trades_at_fvg_only: int = 0
    win_rate_fvg_only: float = 0.0
    trades_at_ob_only: int = 0
    win_rate_ob_only: float = 0.0
    trades_at_fvg_ob_overlap: int = 0
    win_rate_fvg_ob_overlap: float = 0.0

    # Equity & drawdown curves
    equity_curve: list = field(default_factory=list)
    drawdown_curve: list = field(default_factory=list)
    trade_log: list = field(default_factory=list)
    monthly_returns: dict = field(default_factory=dict)

    # Summary
    initial_capital: float = 10000.0
    final_equity: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_fees: float = 0.0
    avg_monthly_return: float = 0.0


def calculate_metrics(
    trades: list,  # list of TradeRecord
    equity_curve: list,  # [(timestamp_ms, equity)]
    drawdown_curve: list,  # [(timestamp_ms, drawdown_fraction)]
    initial_capital: float = 10000.0,
) -> BacktestResult:
    if not trades:
        return BacktestResult(
            total_return_percent=0.0,
            total_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown_percent=0.0,
            max_drawdown_duration_hours=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            expectancy_per_trade=0.0,
            avg_trade_duration_hours=0.0,
            max_consecutive_losses=0,
            max_consecutive_wins=0,
            initial_capital=initial_capital,
            final_equity=initial_capital,
        )

    n = len(trades)
    wins = [t for t in trades if t.net_pnl_usd > 0]
    losses = [t for t in trades if t.net_pnl_usd <= 0]

    win_rate = len(wins) / n if n > 0 else 0.0
    gross_profit = sum(t.net_pnl_usd for t in wins)
    gross_loss = abs(sum(t.net_pnl_usd for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    avg_hold = sum(t.hold_hours for t in trades) / n if n > 0 else 0.0
    total_fees = sum(t.fee_usd for t in trades)

    # Max drawdown
    max_dd = max((d for _, d in drawdown_curve), default=0.0)

    # Max drawdown duration (hours in drawdown)
    max_dd_duration = _max_drawdown_duration_hours(drawdown_curve)

    # Consecutive wins/losses
    max_consec_wins, max_consec_losses = _consecutive_stats(trades)

    # Final equity
    final_equity = equity_curve[-1][1] if equity_curve else initial_capital
    total_return = (final_equity - initial_capital) / initial_capital

    # Sharpe / Sortino (annualized, daily returns)
    sharpe, sortino = _compute_ratios(equity_curve)

    # Monthly returns
    monthly = _compute_monthly_returns(equity_curve)
    avg_monthly = sum(monthly.values()) / len(monthly) if monthly else 0.0

    # Regime breakdown
    regime_stats = _regime_breakdown(trades)
    level_stats = _level_breakdown(trades)

    return BacktestResult(
        total_return_percent=total_return,
        total_trades=n,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_percent=max_dd,
        max_drawdown_duration_hours=max_dd_duration,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        expectancy_per_trade=expectancy,
        avg_trade_duration_hours=avg_hold,
        max_consecutive_losses=max_consec_losses,
        max_consecutive_wins=max_consec_wins,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trade_log=[_trade_to_dict(t) for t in trades],
        monthly_returns=monthly,
        initial_capital=initial_capital,
        final_equity=final_equity,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        total_fees=total_fees,
        avg_monthly_return=avg_monthly,
        **regime_stats,
        **level_stats,
    )


def _trade_to_dict(t) -> dict:
    return {
        "id": t.id,
        "side": t.side,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "entry_ts": t.entry_ts,
        "exit_ts": t.exit_ts,
        "exit_reason": t.exit_reason,
        "pnl_usd": t.pnl_usd,
        "net_pnl_usd": t.net_pnl_usd,
        "pnl_percent": t.pnl_percent,
        "fee_usd": t.fee_usd,
        "slippage_usd": t.slippage_usd,
        "regime_at_entry": t.regime_at_entry,
        "risk_color_at_entry": t.risk_color_at_entry,
        "entry_zone_type": t.entry_zone_type,
        "hold_hours": t.hold_hours,
        "had_fvg_overlap": t.had_fvg_overlap,
    }


def _max_drawdown_duration_hours(drawdown_curve: list) -> float:
    """Longest consecutive period in drawdown (dd > 0)."""
    if not drawdown_curve:
        return 0.0
    max_dur = 0.0
    start_ts = None
    for ts, dd in drawdown_curve:
        if dd > 0:
            if start_ts is None:
                start_ts = ts
        else:
            if start_ts is not None:
                dur = (ts - start_ts) / 3_600_000
                max_dur = max(max_dur, dur)
                start_ts = None
    # Handle ongoing drawdown at end
    if start_ts is not None and drawdown_curve:
        dur = (drawdown_curve[-1][0] - start_ts) / 3_600_000
        max_dur = max(max_dur, dur)
    return max_dur


def _consecutive_stats(trades: list) -> tuple[int, int]:
    max_wins = 0
    max_losses = 0
    cur_wins = 0
    cur_losses = 0
    for t in trades:
        if t.net_pnl_usd > 0:
            cur_wins += 1
            cur_losses = 0
        else:
            cur_losses += 1
            cur_wins = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return max_wins, max_losses


def _compute_ratios(equity_curve: list) -> tuple[float, float]:
    """Monthly Sharpe and Sortino from equity curve (hourly candles assumed)."""
    if len(equity_curve) < 2:
        return 0.0, 0.0

    equities = [e for _, e in equity_curve]
    returns = [(equities[i] - equities[i-1]) / equities[i-1] for i in range(1, len(equities))]

    if not returns:
        return 0.0, 0.0

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(variance) if variance > 0 else 1e-10

    # Scale to monthly: assuming 1h candles → 730 periods/month (24h × 30.44 days)
    periods_per_month = 730
    sharpe = (mean_r / std_r) * math.sqrt(periods_per_month)

    downside = [r for r in returns if r < 0]
    if not downside:
        sortino = sharpe  # No downside
    else:
        down_var = sum(r ** 2 for r in downside) / len(downside)
        down_std = math.sqrt(down_var) if down_var > 0 else 1e-10
        sortino = (mean_r / down_std) * math.sqrt(periods_per_month)

    return sharpe, sortino


def _compute_monthly_returns(equity_curve: list) -> dict:
    """Return {YYYY-MM: return_percent} from equity curve."""
    if not equity_curve:
        return {}

    from datetime import datetime, timezone
    monthly: dict[str, list] = defaultdict(list)

    for ts, equity in equity_curve:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        key = f"{dt.year:04d}-{dt.month:02d}"
        monthly[key].append(equity)

    result = {}
    prev_start = None
    for key in sorted(monthly.keys()):
        vals = monthly[key]
        if prev_start is None:
            prev_start = vals[0]
        start_val = vals[0]
        end_val = vals[-1]
        if start_val > 0:
            result[key] = (end_val - start_val) / start_val
        prev_start = end_val

    return result


def _regime_breakdown(trades: list) -> dict:
    accum = [t for t in trades if t.regime_at_entry == "accumulation"]
    dist = [t for t in trades if t.regime_at_entry == "distribution"]

    def wr(tl):
        if not tl:
            return 0.0
        return len([t for t in tl if t.net_pnl_usd > 0]) / len(tl)

    return {
        "trades_in_accumulation": len(accum),
        "win_rate_accumulation": wr(accum),
        "trades_in_distribution": len(dist),
        "win_rate_distribution": wr(dist),
    }


def _level_breakdown(trades: list) -> dict:
    fvg_only = [t for t in trades if t.entry_zone_type == "fvg" and not t.had_fvg_overlap]
    ob_only = [t for t in trades if t.entry_zone_type == "ob" and not t.had_fvg_overlap]
    overlap = [t for t in trades if t.had_fvg_overlap]

    def wr(tl):
        if not tl:
            return 0.0
        return len([t for t in tl if t.net_pnl_usd > 0]) / len(tl)

    return {
        "trades_at_fvg_only": len(fvg_only),
        "win_rate_fvg_only": wr(fvg_only),
        "trades_at_ob_only": len(ob_only),
        "win_rate_ob_only": wr(ob_only),
        "trades_at_fvg_ob_overlap": len(overlap),
        "win_rate_fvg_ob_overlap": wr(overlap),
    }
