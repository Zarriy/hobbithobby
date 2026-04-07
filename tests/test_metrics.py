"""
Tests for backtest/metrics.py — performance metrics calculation.
"""

import pytest
from backtest.metrics import (
    calculate_metrics, BacktestResult,
    _max_drawdown_duration_hours, _consecutive_stats,
    _compute_ratios, _compute_monthly_returns,
)
from backtest.simulator import TradeRecord


def _make_trade(pnl: float, regime: str = "accumulation", zone: str = "fvg",
                overlap: bool = False, entry_ts: int = 1000, exit_ts: int = 5000,
                id_: int = 1) -> TradeRecord:
    return TradeRecord(
        id=id_, side="long", entry_price=100, exit_price=100 + pnl,
        entry_ts=entry_ts, exit_ts=exit_ts,
        exit_reason="tp1" if pnl > 0 else "stop_loss",
        pnl_usd=pnl * 10, pnl_percent=pnl / 100,
        fee_usd=0.5, slippage_usd=0.1, net_pnl_usd=pnl * 10 - 0.6,
        size_usd=1000, regime_at_entry=regime, risk_color_at_entry="green",
        entry_zone_type=zone, hold_hours=1.0, had_fvg_overlap=overlap,
    )


class TestCalculateMetrics:
    def test_no_trades(self):
        result = calculate_metrics([], [], [], initial_capital=10000)
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.final_equity == 10000

    def test_all_winning_trades(self):
        trades = [_make_trade(5, id_=i) for i in range(10)]
        equity_curve = [(1000 + i * 1000, 10000 + i * 50) for i in range(10)]
        dd_curve = [(ts, 0.0) for ts, _ in equity_curve]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        assert result.win_rate == 1.0
        assert result.profit_factor == float("inf")
        assert result.max_consecutive_wins == 10
        assert result.max_consecutive_losses == 0

    def test_all_losing_trades(self):
        trades = [_make_trade(-5, id_=i) for i in range(10)]
        equity_curve = [(1000 + i * 1000, 10000 - i * 50) for i in range(10)]
        dd_curve = [(ts, i * 0.005) for i, (ts, _) in enumerate(equity_curve)]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        assert result.win_rate == 0.0
        assert result.profit_factor == 0.0
        assert result.max_consecutive_losses == 10

    def test_mixed_trades(self):
        trades = [
            _make_trade(5, id_=1), _make_trade(3, id_=2), _make_trade(-2, id_=3),
            _make_trade(4, id_=4), _make_trade(-1, id_=5),
        ]
        equity_curve = [(i * 1000, 10000 + i * 20) for i in range(5)]
        dd_curve = [(ts, 0.0) for ts, _ in equity_curve]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        assert result.total_trades == 5
        assert 0 < result.win_rate < 1.0
        assert result.profit_factor > 0

    def test_regime_breakdown(self):
        trades = [
            _make_trade(5, regime="accumulation", id_=1),
            _make_trade(-2, regime="accumulation", id_=2),
            _make_trade(3, regime="distribution", id_=3),
        ]
        equity_curve = [(i * 1000, 10000) for i in range(3)]
        dd_curve = [(ts, 0.0) for ts, _ in equity_curve]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        assert result.trades_in_accumulation == 2
        assert result.trades_in_distribution == 1
        assert result.win_rate_accumulation == 0.5

    def test_level_breakdown(self):
        trades = [
            _make_trade(5, zone="fvg", overlap=False, id_=1),
            _make_trade(3, zone="ob", overlap=False, id_=2),
            _make_trade(4, zone="fvg", overlap=True, id_=3),
        ]
        equity_curve = [(i * 1000, 10000) for i in range(3)]
        dd_curve = [(ts, 0.0) for ts, _ in equity_curve]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        assert result.trades_at_fvg_only == 1
        assert result.trades_at_ob_only == 1
        assert result.trades_at_fvg_ob_overlap == 1

    def test_expectancy(self):
        trades = [_make_trade(10, id_=1), _make_trade(-5, id_=2)]
        equity_curve = [(0, 10000), (1000, 10050)]
        dd_curve = [(0, 0.0), (1000, 0.0)]
        result = calculate_metrics(trades, equity_curve, dd_curve)
        # expectancy = wr * avg_win - (1-wr) * avg_loss
        assert result.expectancy_per_trade > 0


class TestMaxDrawdownDuration:
    def test_no_drawdown(self):
        curve = [(1000, 0.0), (2000, 0.0), (3000, 0.0)]
        assert _max_drawdown_duration_hours(curve) == 0.0

    def test_single_drawdown_period(self):
        # Drawdown starts at ts=3_600_000 (first dd>0), recovered at ts=10_800_000
        # Duration = (10_800_000 - 3_600_000) / 3_600_000 = 2.0h
        curve = [
            (0, 0.0),
            (3_600_000, 0.01),   # drawdown starts
            (7_200_000, 0.02),
            (10_800_000, 0.0),   # recovered
        ]
        assert _max_drawdown_duration_hours(curve) == pytest.approx(2.0)

    def test_ongoing_drawdown_at_end(self):
        # Drawdown starts at ts=3_600_000, still going at ts=7_200_000
        # Duration = (7_200_000 - 3_600_000) / 3_600_000 = 1.0h
        curve = [
            (0, 0.0),
            (3_600_000, 0.01),
            (7_200_000, 0.02),
        ]
        assert _max_drawdown_duration_hours(curve) == pytest.approx(1.0)

    def test_empty_curve(self):
        assert _max_drawdown_duration_hours([]) == 0.0


class TestConsecutiveStats:
    def test_all_wins(self):
        trades = [_make_trade(5, id_=i) for i in range(5)]
        wins, losses = _consecutive_stats(trades)
        assert wins == 5
        assert losses == 0

    def test_alternating(self):
        trades = [_make_trade(5 if i % 2 == 0 else -5, id_=i) for i in range(6)]
        wins, losses = _consecutive_stats(trades)
        assert wins == 1
        assert losses == 1

    def test_empty(self):
        wins, losses = _consecutive_stats([])
        assert wins == 0
        assert losses == 0


class TestComputeRatios:
    def test_single_point(self):
        sharpe, sortino = _compute_ratios([(0, 10000)])
        assert sharpe == 0.0
        assert sortino == 0.0

    def test_constant_equity(self):
        curve = [(i * 3_600_000, 10000) for i in range(100)]
        sharpe, sortino = _compute_ratios(curve)
        # All returns are 0 → std is effectively 0
        assert sharpe == 0.0

    def test_positive_returns(self):
        curve = [(i * 3_600_000, 10000 + i * 10) for i in range(100)]
        sharpe, sortino = _compute_ratios(curve)
        assert sharpe > 0
        assert sortino > 0


class TestComputeMonthlyReturns:
    def test_empty(self):
        assert _compute_monthly_returns([]) == {}

    def test_single_month(self):
        # All timestamps in January 2024
        curve = [
            (1704067200000, 10000),  # Jan 1
            (1704153600000, 10100),  # Jan 2
            (1706659200000, 10500),  # Jan 31 (approx)
        ]
        result = _compute_monthly_returns(curve)
        assert "2024-01" in result
        assert result["2024-01"] > 0
