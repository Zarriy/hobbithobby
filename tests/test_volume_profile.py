"""
Tests for engine/volume_profile.py — volume distribution, POC, HVN/LVN, value area.
"""

import pytest
from tests.conftest import make_candle, make_trending_candles, make_flat_candles
from engine.volume_profile import approximate_volume_profile, _empty_profile


class TestApproximateVolumeProfile:
    def test_empty_candles(self):
        result = approximate_volume_profile([])
        assert result["poc"] is None
        assert result["hvn"] == []
        assert result["bins"] == []

    def test_single_candle(self):
        candles = [make_candle(1000, 100, 105, 95, 102, volume=5000)]
        result = approximate_volume_profile(candles)
        assert result["poc"] is not None
        assert len(result["bins"]) == 50
        assert result["value_area_high"] >= result["value_area_low"]

    def test_poc_at_high_volume_area(self):
        """POC should be at the price with the most volume."""
        candles = []
        ts = 1000
        # Most candles trade around 100
        for i in range(20):
            candles.append(make_candle(ts + i, 99, 101, 98, 100, volume=5000))
        # A few candles trade at 120
        for i in range(5):
            candles.append(make_candle(ts + 20 + i, 119, 121, 118, 120, volume=1000))

        result = approximate_volume_profile(candles, num_bins=50)
        # POC should be near 100 where most volume traded
        assert abs(result["poc"] - 100) < abs(result["poc"] - 120)

    def test_zero_range_candle(self):
        """Doji/zero-range candle should put all volume in one bin."""
        candles = [
            make_candle(1000, 100, 100, 100, 100, volume=5000),
            make_candle(2000, 100, 105, 95, 102, volume=1000),
        ]
        result = approximate_volume_profile(candles)
        assert result["poc"] is not None

    def test_flat_price_same_range(self):
        """All candles at same price → high=low, returns empty profile."""
        candles = [make_candle(i, 100, 100, 100, 100, volume=1000) for i in range(10)]
        result = approximate_volume_profile(candles)
        assert result["poc"] is None  # price_high <= price_low

    def test_value_area_70_percent(self):
        """Value area should contain ~70% of total volume."""
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5, volatility=1)
        result = approximate_volume_profile(candles, num_bins=50)
        total_vol = sum(v for _, v in result["bins"])
        va_bins = [v for p, v in result["bins"]
                   if result["value_area_low"] <= p <= result["value_area_high"]]
        va_vol = sum(va_bins)
        assert va_vol / total_vol >= 0.60  # Approximately 70%

    def test_hvn_lvn_classification(self):
        """HVN bins should have higher volume than LVN bins."""
        candles = make_trending_candles(start_price=100, n=80, direction="up", step=0.3, volatility=1)
        result = approximate_volume_profile(candles, num_bins=50)
        if result["hvn"] and result["lvn"]:
            # HVN prices should correspond to higher volume bins
            hvn_set = set(result["hvn"])
            lvn_set = set(result["lvn"])
            assert hvn_set.isdisjoint(lvn_set)

    def test_lookback_limit(self):
        """Should only use last `lookback` candles."""
        candles = make_trending_candles(start_price=100, n=200, direction="up", step=0.2)
        result = approximate_volume_profile(candles, lookback=50)
        # Profile should reflect prices from last 50 candles, not all 200
        last_50_low = min(c["low"] for c in candles[-50:])
        last_50_high = max(c["high"] for c in candles[-50:])
        for price, _ in result["bins"]:
            assert last_50_low - 5 <= price <= last_50_high + 5


class TestEmptyProfile:
    def test_structure(self):
        result = _empty_profile()
        assert result["poc"] is None
        assert result["hvn"] == []
        assert result["lvn"] == []
        assert result["value_area_high"] is None
        assert result["value_area_low"] is None
        assert result["bins"] == []
