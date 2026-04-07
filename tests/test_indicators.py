"""
Tests for engine/indicators.py — all numpy-based technical indicators.
Covers edge cases: zero division, NaN warmup, single elements, constant data.
"""

import numpy as np
import pytest

from engine.indicators import (
    rolling_mean, rolling_std, rolling_zscore, rate_of_change,
    true_range, atr, vwap, vwap_deviation, ema, highest, lowest,
)


class TestRollingMean:
    def test_basic(self):
        vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = rolling_mean(vals, 3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_lookback_equals_length(self):
        vals = np.array([10.0, 20.0, 30.0])
        result = rolling_mean(vals, 3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == pytest.approx(20.0)

    def test_single_element(self):
        vals = np.array([5.0])
        result = rolling_mean(vals, 1)
        assert result[0] == pytest.approx(5.0)

    def test_constant_values(self):
        vals = np.full(10, 42.0)
        result = rolling_mean(vals, 5)
        for i in range(4, 10):
            assert result[i] == pytest.approx(42.0)

    def test_lookback_larger_than_data(self):
        vals = np.array([1.0, 2.0])
        result = rolling_mean(vals, 5)
        assert all(np.isnan(result))


class TestRollingStd:
    def test_basic(self):
        vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = rolling_std(vals, 3)
        assert np.isnan(result[0])
        assert result[2] == pytest.approx(1.0)  # std([1,2,3], ddof=1)

    def test_constant_values_zero_std(self):
        vals = np.full(5, 10.0)
        result = rolling_std(vals, 3)
        assert result[2] == pytest.approx(0.0)
        assert result[4] == pytest.approx(0.0)


class TestRollingZscore:
    def test_zero_std_returns_zero(self):
        """When all values in window are identical, z-score should be 0."""
        vals = np.full(10, 50.0)
        result = rolling_zscore(vals, 5)
        for i in range(4, 10):
            assert result[i] == pytest.approx(0.0)

    def test_positive_zscore(self):
        vals = np.array([1.0, 1.0, 1.0, 1.0, 5.0])
        result = rolling_zscore(vals, 5)
        assert result[4] > 1.0  # 5 is well above mean of window

    def test_negative_zscore(self):
        vals = np.array([5.0, 5.0, 5.0, 5.0, 1.0])
        result = rolling_zscore(vals, 5)
        assert result[4] < -1.0

    def test_warmup_nans(self):
        vals = np.array([1.0, 2.0, 3.0])
        result = rolling_zscore(vals, 3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert not np.isnan(result[2])


class TestRateOfChange:
    def test_basic(self):
        vals = np.array([100.0, 110.0, 105.0])
        result = rate_of_change(vals, 1)
        assert np.isnan(result[0])
        assert result[1] == pytest.approx(0.1)
        assert result[2] == pytest.approx(-0.0454545, abs=1e-4)

    def test_zero_prev_value(self):
        vals = np.array([0.0, 10.0])
        result = rate_of_change(vals, 1)
        assert result[1] == pytest.approx(0.0)  # Division by zero guard

    def test_negative_values(self):
        vals = np.array([-10.0, -5.0])
        result = rate_of_change(vals, 1)
        assert result[1] == pytest.approx(0.5)  # (-5 - -10) / abs(-10) = 0.5

    def test_period_larger_than_data(self):
        vals = np.array([1.0, 2.0])
        result = rate_of_change(vals, 5)
        assert all(np.isnan(result))


class TestTrueRange:
    def test_basic(self):
        highs = np.array([105.0, 110.0])
        lows = np.array([95.0, 100.0])
        closes = np.array([100.0, 108.0])
        tr = true_range(highs, lows, closes)
        assert tr[0] == pytest.approx(10.0)  # high - low
        assert tr[1] == pytest.approx(10.0)  # max(10, |110-100|, |100-100|)

    def test_gap_up(self):
        """Gap up: high - prev_close > high - low."""
        highs = np.array([50.0, 60.0])
        lows = np.array([45.0, 55.0])
        closes = np.array([48.0, 58.0])
        tr = true_range(highs, lows, closes)
        # candle 1: hl=5, hpc=|60-48|=12, lpc=|55-48|=7 → TR=12
        assert tr[1] == pytest.approx(12.0)

    def test_gap_down(self):
        """Gap down: |low - prev_close| > high - low."""
        highs = np.array([50.0, 45.0])
        lows = np.array([45.0, 38.0])
        closes = np.array([48.0, 40.0])
        tr = true_range(highs, lows, closes)
        # candle 1: hl=7, hpc=|45-48|=3, lpc=|38-48|=10 → TR=10
        assert tr[1] == pytest.approx(10.0)


class TestATR:
    def test_basic_14_period(self):
        np.random.seed(42)
        n = 30
        closes = np.cumsum(np.random.normal(0, 1, n)) + 100
        highs = closes + np.random.uniform(0.5, 1.5, n)
        lows = closes - np.random.uniform(0.5, 1.5, n)

        result = atr(highs, lows, closes, period=14)
        assert all(np.isnan(result[:13]))
        assert not np.isnan(result[13])
        assert result[13] > 0
        # Wilder's smoothing should produce decreasing influence of old data
        assert not np.isnan(result[29])

    def test_insufficient_data(self):
        highs = np.array([101.0, 102.0])
        lows = np.array([99.0, 98.0])
        closes = np.array([100.0, 101.0])
        result = atr(highs, lows, closes, period=14)
        assert all(np.isnan(result))


class TestVWAP:
    def test_basic(self):
        highs = np.array([105.0, 110.0, 115.0])
        lows = np.array([95.0, 100.0, 105.0])
        closes = np.array([100.0, 108.0, 112.0])
        volumes = np.array([1000.0, 2000.0, 1500.0])

        result = vwap(highs, lows, closes, volumes)
        assert len(result) == 3
        # First candle: typical = (105+95+100)/3 = 100
        assert result[0] == pytest.approx(100.0)
        assert not np.isnan(result[2])

    def test_zero_volume(self):
        highs = np.array([105.0])
        lows = np.array([95.0])
        closes = np.array([100.0])
        volumes = np.array([0.0])

        result = vwap(highs, lows, closes, volumes)
        assert np.isnan(result[0])

    def test_cumulative_property(self):
        """VWAP should weight higher-volume candles more."""
        highs = np.array([102.0, 112.0])
        lows = np.array([98.0, 108.0])
        closes = np.array([100.0, 110.0])
        volumes = np.array([100.0, 10000.0])  # candle 2 has way more volume

        result = vwap(highs, lows, closes, volumes)
        # VWAP should be pulled toward candle 2's typical price (110)
        assert result[1] > 105.0


class TestVWAPDeviation:
    def test_warmup_nans(self):
        closes = np.full(10, 100.0)
        vwap_vals = np.full(10, 100.0)
        result = vwap_deviation(closes, vwap_vals, period=50)
        # Not enough data for period=50 std calculation
        assert all(np.isnan(result))

    def test_zero_std_returns_nan(self):
        """When close == vwap consistently, std is 0 → NaN."""
        closes = np.full(60, 100.0)
        vwap_vals = np.full(60, 100.0)
        result = vwap_deviation(closes, vwap_vals, period=50)
        # std of zeros is 0 → guarded, stays NaN
        assert np.isnan(result[55])


class TestEMA:
    def test_seed_is_sma(self):
        vals = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        result = ema(vals, period=3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        # Seed = SMA of [2,4,6] = 4.0
        assert result[2] == pytest.approx(4.0)

    def test_ema_responds_to_recent(self):
        vals = np.array([10.0, 10.0, 10.0, 20.0, 20.0])
        result = ema(vals, period=3)
        # After seeing 20s, EMA should move toward 20
        assert result[4] > result[3] > result[2]


class TestHighestLowest:
    def test_highest(self):
        vals = np.array([5.0, 3.0, 8.0, 1.0, 6.0])
        result = highest(vals, 3)
        assert np.isnan(result[0])
        assert result[2] == pytest.approx(8.0)  # max(5,3,8)
        assert result[3] == pytest.approx(8.0)  # max(3,8,1)
        assert result[4] == pytest.approx(8.0)  # max(8,1,6)

    def test_lowest(self):
        vals = np.array([5.0, 3.0, 8.0, 1.0, 6.0])
        result = lowest(vals, 3)
        assert result[2] == pytest.approx(3.0)
        assert result[3] == pytest.approx(1.0)
        assert result[4] == pytest.approx(1.0)
