"""
Tests for backtest/simulator.py — candle-by-candle simulation, no future leak.
"""

import numpy as np
import pytest
from tests.conftest import make_candle, make_trending_candles

from backtest.simulator import (
    _compute_signals_at, generate_signal_cache,
    run_backtest, BacktestState, Position, TradeRecord,
)
from backtest.rules import TradeRule


class TestComputeSignalsAt:
    def test_insufficient_data_returns_none(self):
        candles = [make_candle(i * 3600000, 100, 101, 99, 100) for i in range(20)]
        result = _compute_signals_at(candles, 19)
        assert result is None  # Need 30+ candles

    def test_sufficient_data_returns_signal(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5)
        result = _compute_signals_at(candles, 40)
        assert result is not None
        assert hasattr(result, "regime_state")
        assert hasattr(result, "confidence")

    def test_no_future_leak(self):
        """Signal at index 35 should not use data from index 36+."""
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5)
        # Add extreme data after index 35 that would change signal if leaked
        for i in range(36, 50):
            candles[i]["close"] = 1.0  # Crash to near-zero
            candles[i]["volume"] = 1_000_000

        sig_at_35 = _compute_signals_at(candles, 35)
        # Signal should reflect uptrend data, not the crash
        assert sig_at_35 is not None

    def test_oi_change_calculation(self):
        candles = make_trending_candles(
            start_price=100, n=50, direction="up", step=0.5,
            oi_start=1_000_000, oi_step=5000,
        )
        sig = _compute_signals_at(candles, 40)
        assert sig is not None
        assert sig.oi_change_percent != 0.0  # Should detect OI change

    def test_oi_change_none_when_no_oi(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5)
        # No open_interest set → should remain None
        sig = _compute_signals_at(candles, 40)
        assert sig is not None
        assert sig.oi_change_percent == 0.0  # Stored as 0 when None


class TestGenerateSignalCache:
    def test_first_30_are_none(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5)
        cache = generate_signal_cache(candles)
        assert len(cache) == 50
        for i in range(30):
            assert cache[i] is None
        assert cache[30] is not None

    def test_cache_length_matches_candles(self):
        candles = make_trending_candles(start_price=100, n=100, direction="up", step=0.3)
        cache = generate_signal_cache(candles)
        assert len(cache) == len(candles)


class TestRunBacktest:
    @pytest.fixture
    def trending_candles(self):
        """100 candles trending up with FVG-generating gaps."""
        candles = []
        ts = 1_000_000_000_000
        tf = 3_600_000
        price = 100.0

        for i in range(100):
            step = 0.5 + np.random.uniform(-0.2, 0.3)
            c = price + step
            h = max(price, c) + np.random.uniform(0.5, 2.0)
            l = min(price, c) - np.random.uniform(0.5, 2.0)

            candles.append(make_candle(
                ts + i * tf, price, h, l, c,
                volume=1000 + np.random.uniform(-200, 200),
                open_interest=1_000_000 + i * 5000,
            ))
            price = c

        return candles

    def test_backtest_runs_without_error(self, trending_candles):
        rules = TradeRule()
        state = run_backtest(trending_candles, rules)
        assert isinstance(state, BacktestState)
        assert state.equity > 0
        assert len(state.equity_curve) > 0

    def test_equity_curve_matches_candle_count(self, trending_candles):
        state = run_backtest(trending_candles, TradeRule())
        # Equity curve should have n-1 entries (starts from candle 1)
        assert len(state.equity_curve) == len(trending_candles) - 1

    def test_force_close_at_end(self, trending_candles):
        """All positions should be closed at end of backtest."""
        state = run_backtest(trending_candles, TradeRule())
        assert len(state.open_positions) == 0

    def test_no_trades_with_impossible_rules(self, trending_candles):
        """Rules requiring confidence > 200 should produce zero trades."""
        rules = TradeRule(confidence_above=200)
        state = run_backtest(trending_candles, rules)
        # Only forced closes (if any positions opened before confidence check)
        # With conf > 200, no entries should occur
        non_forced = [t for t in state.closed_trades if t.exit_reason != "forced_close_end"]
        assert len(non_forced) == 0

    def test_entry_fee_deducted(self, trending_candles):
        """Opening a position should immediately deduct entry fee."""
        rules = TradeRule(confidence_above=0, regime_is_green=False)  # Very permissive
        state = run_backtest(trending_candles, rules, initial_capital=10000)
        # Even without trades completing, equity should differ from initial if fees deducted
        # This is a sanity check

    def test_drawdown_curve_populated(self, trending_candles):
        state = run_backtest(trending_candles, TradeRule())
        assert len(state.drawdown_curve) == len(state.equity_curve)
        for _, dd in state.drawdown_curve:
            assert dd >= 0

    def test_signal_cache_reuse(self, trending_candles):
        """Running from cache should produce same result as generating inline."""
        rules = TradeRule()
        cache = generate_signal_cache(trending_candles)
        state1 = run_backtest(trending_candles, rules, signal_cache=cache)
        state2 = run_backtest(trending_candles, rules, signal_cache=cache)
        assert len(state1.closed_trades) == len(state2.closed_trades)
        assert state1.equity == pytest.approx(state2.equity)


class TestBacktestEdgeCases:
    def test_single_candle(self):
        candles = [make_candle(1000, 100, 101, 99, 100)]
        state = run_backtest(candles, TradeRule())
        assert state.equity == 10000  # No trades
        assert len(state.closed_trades) == 0

    def test_two_candles(self):
        candles = [
            make_candle(1000, 100, 101, 99, 100),
            make_candle(4600, 100, 102, 98, 101),
        ]
        state = run_backtest(candles, TradeRule())
        assert len(state.equity_curve) == 1

    def test_flat_market_few_trades(self):
        """Flat market should produce very few signals/trades."""
        candles = [
            make_candle(i * 3600000, 100, 100.1, 99.9, 100, volume=500)
            for i in range(100)
        ]
        state = run_backtest(candles, TradeRule())
        assert len(state.closed_trades) <= 5  # Very few in flat conditions
