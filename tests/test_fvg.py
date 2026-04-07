"""
Tests for engine/fvg.py — Fair Value Gap detection, fill tracking, nearest lookup.
"""

import pytest
from tests.conftest import make_candle
from engine.fvg import FVG, detect_fvgs, update_fvg_status, get_nearest_fvg, fvg_to_store_dict


class TestDetectFVGs:
    def test_bullish_fvg(self, fvg_candles):
        fvgs = detect_fvgs(fvg_candles)
        bullish = [f for f in fvgs if f.type == "bullish"]
        assert len(bullish) == 1
        assert bullish[0].lower_bound == 102  # candle0.high
        assert bullish[0].upper_bound == 104  # candle2.low
        assert bullish[0].status == "unfilled"

    def test_bearish_fvg(self, bearish_fvg_candles):
        fvgs = detect_fvgs(bearish_fvg_candles)
        bearish = [f for f in fvgs if f.type == "bearish"]
        assert len(bearish) == 1
        assert bearish[0].upper_bound == 106  # candle0.low
        assert bearish[0].lower_bound == 104  # candle2.high

    def test_no_fvg_when_overlapping(self):
        """When candle[0].high >= candle[2].low, no bullish FVG."""
        ts = 1_000_000_000_000
        candles = [
            make_candle(ts, 100, 105, 99, 104),
            make_candle(ts + 3600000, 104, 106, 103, 105),
            make_candle(ts + 7200000, 105, 107, 104, 106),  # low=104 < candle0.high=105
        ]
        fvgs = detect_fvgs(candles)
        assert len([f for f in fvgs if f.type == "bullish"]) == 0

    def test_fewer_than_3_candles(self):
        ts = 1_000_000_000_000
        candles = [make_candle(ts, 100, 101, 99, 100)]
        assert detect_fvgs(candles) == []
        assert detect_fvgs([]) == []

    def test_min_gap_percent_filter(self):
        """Tiny gap should be filtered out."""
        ts = 1_000_000_000_000
        candles = [
            make_candle(ts, 100, 100.01, 99.99, 100),
            make_candle(ts + 3600000, 100, 100.02, 99.98, 100.01),
            make_candle(ts + 7200000, 100.01, 100.03, 100.015, 100.02),
            # gap = 100.015 - 100.01 = 0.005, mid ≈ 100.01, pct ≈ 0.00005 < 0.001
        ]
        fvgs = detect_fvgs(candles, min_gap_percent=0.001)
        assert len(fvgs) == 0

    def test_multiple_fvgs_in_series(self):
        """Multiple gaps in a trending series."""
        ts = 1_000_000_000_000
        candles = [
            make_candle(ts, 100, 102, 99, 101),
            make_candle(ts + 3600000, 101, 110, 100, 109),
            make_candle(ts + 7200000, 109, 115, 104, 114),  # gap: 102 to 104
            make_candle(ts + 10800000, 114, 120, 113, 119),
            make_candle(ts + 14400000, 119, 130, 118, 129),  # gap: 115 to 118
        ]
        fvgs = detect_fvgs(candles)
        bullish = [f for f in fvgs if f.type == "bullish"]
        assert len(bullish) >= 1

    def test_pair_and_timeframe_from_candles(self, fvg_candles):
        fvgs = detect_fvgs(fvg_candles)
        assert fvgs[0].pair == "BTCUSDT"
        assert fvgs[0].timeframe == "1h"


class TestUpdateFVGStatus:
    def test_bullish_fvg_filled(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            status="unfilled", gap_size_percent=0.05,
        )
        candle = make_candle(2000, 103, 106, 98, 99)  # close < lower_bound
        update_fvg_status([fvg], candle)
        assert fvg.status == "filled"
        assert fvg.filled_at == 2000

    def test_bullish_fvg_partial(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            status="unfilled", gap_size_percent=0.05,
        )
        candle = make_candle(2000, 106, 107, 104, 103)  # low touches zone but close > lower
        update_fvg_status([fvg], candle)
        assert fvg.status == "partial"

    def test_bullish_fvg_untouched(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            status="unfilled", gap_size_percent=0.05,
        )
        candle = make_candle(2000, 110, 112, 108, 111)  # completely above zone
        update_fvg_status([fvg], candle)
        assert fvg.status == "unfilled"

    def test_bearish_fvg_filled(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bearish", upper_bound=110, lower_bound=105,
            status="unfilled", gap_size_percent=0.05,
        )
        candle = make_candle(2000, 108, 112, 107, 111)  # close > upper_bound
        update_fvg_status([fvg], candle)
        assert fvg.status == "filled"

    def test_bearish_fvg_partial(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bearish", upper_bound=110, lower_bound=105,
            status="unfilled", gap_size_percent=0.05,
        )
        candle = make_candle(2000, 103, 106, 102, 104)  # high enters zone but close < upper
        update_fvg_status([fvg], candle)
        assert fvg.status == "partial"

    def test_already_filled_stays_filled(self):
        fvg = FVG(
            timestamp=1000, pair="BTCUSDT", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            status="filled", gap_size_percent=0.05, filled_at=1500,
        )
        candle = make_candle(2000, 106, 107, 95, 96)
        update_fvg_status([fvg], candle)
        assert fvg.status == "filled"
        assert fvg.filled_at == 1500  # Unchanged


class TestGetNearestFVG:
    def test_nearest_bullish_below_price(self):
        fvgs = [
            FVG(1000, "BTC", "1h", "bullish", 95, 90, "unfilled", 0.05),
            FVG(2000, "BTC", "1h", "bullish", 98, 93, "unfilled", 0.05),
        ]
        result = get_nearest_fvg(fvgs, 100.0, "bullish")
        assert result is not None
        assert result.upper_bound == 98  # Closest below

    def test_nearest_bearish_above_price(self):
        fvgs = [
            FVG(1000, "BTC", "1h", "bearish", 115, 110, "unfilled", 0.05),
            FVG(2000, "BTC", "1h", "bearish", 108, 105, "unfilled", 0.05),
        ]
        result = get_nearest_fvg(fvgs, 100.0, "bearish")
        assert result is not None
        assert result.lower_bound == 105  # Closest above

    def test_no_fvg_in_direction(self):
        fvgs = [
            FVG(1000, "BTC", "1h", "bearish", 95, 90, "unfilled", 0.05),
        ]
        result = get_nearest_fvg(fvgs, 100.0, "bullish")
        assert result is None

    def test_filled_fvgs_excluded(self):
        fvgs = [
            FVG(1000, "BTC", "1h", "bullish", 98, 93, "filled", 0.05),
        ]
        result = get_nearest_fvg(fvgs, 100.0, "bullish")
        assert result is None

    def test_partial_fvgs_included(self):
        fvgs = [
            FVG(1000, "BTC", "1h", "bullish", 98, 93, "partial", 0.05),
        ]
        result = get_nearest_fvg(fvgs, 100.0, "bullish")
        assert result is not None

    def test_empty_list(self):
        assert get_nearest_fvg([], 100.0, "bullish") is None


class TestFVGToStoreDict:
    def test_conversion(self):
        fvg = FVG(1000, "BTCUSDT", "1h", "bullish", 105, 100, "unfilled", 0.05)
        d = fvg_to_store_dict(fvg)
        assert d["pair"] == "BTCUSDT"
        assert d["detected_at"] == 1000
        assert d["type"] == "bullish"
        assert d["upper_bound"] == 105
        assert d["status"] == "unfilled"
        assert d["filled_at"] is None
