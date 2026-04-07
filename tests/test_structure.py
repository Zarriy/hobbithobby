"""
Tests for engine/structure.py — swing points, BOS/CHoCH, equal levels, price zones.
"""

import pytest
from tests.conftest import make_candle, make_trending_candles, make_flat_candles
from engine.structure import (
    SwingPoint, StructureBreak,
    detect_swing_points, detect_structure_breaks, detect_equal_levels,
    get_premium_discount_zone, get_trend_state,
)


class TestDetectSwingPoints:
    def test_minimum_candles_required(self):
        """Need at least 2*lookback+1 candles (default lookback=5 → 11)."""
        candles = [make_candle(i * 3600000, 100, 101, 99, 100) for i in range(10)]
        swings = detect_swing_points(candles, lookback=5)
        assert len(swings) == 0  # Not enough for any swing

    def test_clear_swing_high(self):
        """Create a peak in the middle of a V-shape."""
        ts = 1_000_000_000_000
        tf = 3_600_000
        candles = []
        # 5 candles going up
        for i in range(5):
            p = 100 + i * 2
            candles.append(make_candle(ts + i * tf, p, p + 1, p - 1, p + 1))
        # Peak candle
        candles.append(make_candle(ts + 5 * tf, 110, 115, 109, 112))
        # 5 candles going down
        for i in range(5):
            p = 108 - i * 2
            candles.append(make_candle(ts + (6 + i) * tf, p, p + 1, p - 1, p - 1))

        swings = detect_swing_points(candles, lookback=5)
        highs = [s for s in swings if s.type == "swing_high"]
        assert len(highs) == 1
        assert highs[0].price == 115

    def test_clear_swing_low(self):
        """Create a trough: descend then ascend."""
        ts = 1_000_000_000_000
        tf = 3_600_000
        candles = []
        for i in range(5):
            p = 110 - i * 2
            candles.append(make_candle(ts + i * tf, p, p + 1, p - 1, p - 1))
        # Trough
        candles.append(make_candle(ts + 5 * tf, 100, 101, 95, 98))
        for i in range(5):
            p = 102 + i * 2
            candles.append(make_candle(ts + (6 + i) * tf, p, p + 1, p - 1, p + 1))

        swings = detect_swing_points(candles, lookback=5)
        lows = [s for s in swings if s.type == "swing_low"]
        assert len(lows) == 1
        assert lows[0].price == 95

    def test_sorted_by_timestamp(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=0.5, volatility=2)
        swings = detect_swing_points(candles, lookback=3)
        timestamps = [s.timestamp for s in swings]
        assert timestamps == sorted(timestamps)


class TestDetectStructureBreaks:
    def test_bos_bullish_continuation(self):
        """Higher highs in uptrend → BOS bullish."""
        swings = [
            SwingPoint(1000, 100, "swing_high"),
            SwingPoint(2000, 95, "swing_low"),
            SwingPoint(3000, 105, "swing_high"),  # higher high → BOS
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="uptrend")
        assert any(b.type == "bos_bullish" for b in breaks)
        assert trend == "uptrend"

    def test_bos_bearish_continuation(self):
        """Lower lows in downtrend → BOS bearish."""
        swings = [
            SwingPoint(1000, 100, "swing_low"),
            SwingPoint(2000, 110, "swing_high"),
            SwingPoint(3000, 95, "swing_low"),  # lower low → BOS
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="downtrend")
        assert any(b.type == "bos_bearish" for b in breaks)
        assert trend == "downtrend"

    def test_choch_bullish_reversal(self):
        """Higher high in downtrend → CHoCH bullish."""
        swings = [
            SwingPoint(1000, 100, "swing_high"),
            SwingPoint(2000, 90, "swing_low"),
            SwingPoint(3000, 105, "swing_high"),  # higher high in downtrend
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="downtrend")
        assert any(b.type == "choch_bullish" for b in breaks)
        assert trend == "transition"

    def test_choch_bearish_reversal(self):
        """Lower low in uptrend → CHoCH bearish."""
        swings = [
            SwingPoint(1000, 100, "swing_low"),
            SwingPoint(2000, 110, "swing_high"),
            SwingPoint(3000, 95, "swing_low"),  # lower low in uptrend
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="uptrend")
        assert any(b.type == "choch_bearish" for b in breaks)
        assert trend == "transition"

    def test_no_breaks_equal_levels(self):
        """Equal highs should not trigger breaks."""
        swings = [
            SwingPoint(1000, 100, "swing_high"),
            SwingPoint(2000, 95, "swing_low"),
            SwingPoint(3000, 100, "swing_high"),  # equal high
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="uptrend")
        assert len(breaks) == 0

    def test_empty_swings(self):
        breaks, trend = detect_structure_breaks([], current_trend="ranging")
        assert breaks == []
        assert trend == "ranging"

    def test_ranging_to_uptrend(self):
        """Higher high in ranging → BOS bullish to uptrend."""
        swings = [
            SwingPoint(1000, 100, "swing_high"),
            SwingPoint(3000, 105, "swing_high"),
        ]
        breaks, trend = detect_structure_breaks(swings, current_trend="ranging")
        assert trend == "uptrend"


class TestDetectEqualLevels:
    def test_equal_highs(self):
        swings = [
            SwingPoint(1000, 100.0, "swing_high"),
            SwingPoint(2000, 100.05, "swing_high"),  # within 0.1% of 100
            SwingPoint(3000, 95.0, "swing_low"),
        ]
        result = detect_equal_levels(swings, tolerance=0.001)
        assert len(result["equal_highs"]) == 1
        assert result["equal_highs"][0] == pytest.approx(100.025)

    def test_equal_lows(self):
        swings = [
            SwingPoint(1000, 50.0, "swing_low"),
            SwingPoint(2000, 50.04, "swing_low"),
            SwingPoint(3000, 60.0, "swing_high"),
        ]
        result = detect_equal_levels(swings, tolerance=0.001)
        assert len(result["equal_lows"]) == 1

    def test_no_equals_too_far_apart(self):
        swings = [
            SwingPoint(1000, 100.0, "swing_high"),
            SwingPoint(2000, 105.0, "swing_high"),  # 5% apart
        ]
        result = detect_equal_levels(swings, tolerance=0.001)
        assert len(result["equal_highs"]) == 0

    def test_empty_swings(self):
        result = detect_equal_levels([])
        assert result == {"equal_highs": [], "equal_lows": []}

    def test_single_swing_no_cluster(self):
        swings = [SwingPoint(1000, 100.0, "swing_high")]
        result = detect_equal_levels(swings)
        assert result["equal_highs"] == []


class TestGetPremiumDiscountZone:
    def test_premium(self):
        swings = [
            SwingPoint(1000, 110, "swing_high"),
            SwingPoint(2000, 90, "swing_low"),
        ]
        # midpoint = 100, band = 5
        assert get_premium_discount_zone(swings, 106.0) == "premium"

    def test_discount(self):
        swings = [
            SwingPoint(1000, 110, "swing_high"),
            SwingPoint(2000, 90, "swing_low"),
        ]
        assert get_premium_discount_zone(swings, 94.0) == "discount"

    def test_equilibrium(self):
        swings = [
            SwingPoint(1000, 110, "swing_high"),
            SwingPoint(2000, 90, "swing_low"),
        ]
        assert get_premium_discount_zone(swings, 100.0) == "equilibrium"

    def test_no_swings(self):
        assert get_premium_discount_zone([], 100.0) == "equilibrium"

    def test_only_highs(self):
        swings = [SwingPoint(1000, 110, "swing_high")]
        assert get_premium_discount_zone(swings, 100.0) == "equilibrium"

    def test_uses_most_recent(self):
        """Should use the most recent swing high/low by timestamp."""
        swings = [
            SwingPoint(1000, 120, "swing_high"),
            SwingPoint(3000, 110, "swing_high"),  # more recent
            SwingPoint(2000, 80, "swing_low"),
            SwingPoint(4000, 90, "swing_low"),    # more recent
        ]
        # midpoint = (110+90)/2 = 100, band = 5
        assert get_premium_discount_zone(swings, 106.0) == "premium"


class TestGetTrendState:
    def test_uptrend_from_candles(self):
        candles = make_trending_candles(start_price=100, n=50, direction="up", step=1, volatility=0.3)
        trend, breaks = get_trend_state(candles)
        assert trend in ("uptrend", "ranging", "transition")

    def test_insufficient_candles(self):
        candles = [make_candle(i * 3600000, 100, 101, 99, 100) for i in range(5)]
        trend, breaks = get_trend_state(candles)
        assert trend == "ranging"
        assert breaks == []
