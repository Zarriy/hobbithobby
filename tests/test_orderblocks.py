"""
Tests for engine/orderblocks.py — Order Block detection, mitigation, FVG overlap.
"""

import numpy as np
import pytest
from tests.conftest import make_candle
from engine.fvg import FVG
from engine.orderblocks import (
    OrderBlock, detect_order_blocks, update_ob_status, get_nearest_ob,
    _is_bullish_candle, _is_bearish_candle, _candle_range, _zones_overlap,
)


class TestHelpers:
    def test_bullish_candle(self):
        assert _is_bullish_candle({"open": 100, "close": 105}) is True
        assert _is_bullish_candle({"open": 100, "close": 100}) is True  # equal = bullish
        assert _is_bullish_candle({"open": 105, "close": 100}) is False

    def test_bearish_candle(self):
        assert _is_bearish_candle({"open": 105, "close": 100}) is True
        assert _is_bearish_candle({"open": 100, "close": 100}) is False  # equal = not bearish

    def test_candle_range(self):
        assert _candle_range({"high": 110, "low": 100}) == 10

    def test_zones_overlap_true(self):
        assert _zones_overlap(110, 100, 105, 95) is True

    def test_zones_overlap_false(self):
        assert _zones_overlap(100, 90, 110, 105) is False

    def test_zones_overlap_touching(self):
        assert _zones_overlap(100, 90, 100, 95) is True  # boundaries touch

    def test_zones_no_overlap_same_boundary(self):
        # lower1=90, upper2=90 → 90 < 90 is False → no overlap
        assert _zones_overlap(100, 90, 90, 80) is False


class TestDetectOrderBlocks:
    def _make_bullish_impulse(self, start_ts, start_price, atr_val=5.0):
        """Create candles with a bearish OB followed by 3+ bullish impulse candles."""
        candles = []
        ts = start_ts
        tf = 3_600_000
        price = start_price

        # Pad with some neutral candles first (need ATR warmup)
        for i in range(15):
            candles.append(make_candle(
                ts, price, price + 2, price - 2, price + 0.5,
                volume=1000,
            ))
            ts += tf
            price += 0.5

        # One bearish candle (will become the OB)
        candles.append(make_candle(ts, price, price + 1, price - 3, price - 2, volume=1000))
        price -= 2
        ts += tf

        # 3 bullish impulse candles covering > 2x ATR
        for _ in range(3):
            candles.append(make_candle(ts, price, price + atr_val, price - 0.5, price + atr_val - 1, volume=2000))
            price += atr_val - 1
            ts += tf

        return candles

    def test_detects_bullish_ob(self):
        candles = self._make_bullish_impulse(1_000_000_000_000, 100)
        obs = detect_order_blocks(candles, fvgs=[])
        bullish = [ob for ob in obs if ob.type == "bullish"]
        assert len(bullish) >= 1
        assert bullish[0].status == "active"

    def test_detects_bearish_ob(self):
        """Build bearish impulse: bullish OB candle then 3 bearish candles."""
        ts = 1_000_000_000_000
        tf = 3_600_000
        price = 100.0
        candles = []

        # ATR warmup
        for i in range(15):
            candles.append(make_candle(ts, price, price + 2, price - 2, price - 0.5, volume=1000))
            ts += tf
            price -= 0.5

        # One bullish candle (will become OB)
        candles.append(make_candle(ts, price, price + 3, price - 1, price + 2, volume=1000))
        price += 2
        ts += tf

        # 3 bearish impulse candles
        atr_val = 5.0
        for _ in range(3):
            candles.append(make_candle(ts, price, price + 0.5, price - atr_val, price - atr_val + 1, volume=2000))
            price -= atr_val - 1
            ts += tf

        obs = detect_order_blocks(candles, fvgs=[])
        bearish = [ob for ob in obs if ob.type == "bearish"]
        assert len(bearish) >= 1

    def test_insufficient_candles(self):
        candles = [make_candle(1000 + i * 3600000, 100, 101, 99, 100) for i in range(3)]
        obs = detect_order_blocks(candles, fvgs=[])
        assert obs == []

    def test_fvg_overlap_detection(self):
        candles = self._make_bullish_impulse(1_000_000_000_000, 100)
        # Create an FVG that overlaps with where the OB would be
        ob_candle = candles[15]  # the bearish candle
        fvg = FVG(
            timestamp=ob_candle["timestamp"], pair="BTCUSDT", timeframe="1h",
            type="bullish", upper_bound=ob_candle["high"] + 1,
            lower_bound=ob_candle["low"] - 1, status="unfilled", gap_size_percent=0.05,
        )
        obs = detect_order_blocks(candles, fvgs=[fvg])
        bullish = [ob for ob in obs if ob.type == "bullish"]
        if bullish:
            assert bullish[0].fvg_overlap is True

    def test_deduplication(self):
        """Same OB should not appear twice."""
        candles = self._make_bullish_impulse(1_000_000_000_000, 100)
        obs = detect_order_blocks(candles, fvgs=[])
        timestamps = [(ob.timestamp, ob.type, ob.upper_bound) for ob in obs]
        assert len(timestamps) == len(set(timestamps))


class TestUpdateOBStatus:
    def test_bullish_ob_mitigated(self):
        ob = OrderBlock(
            timestamp=1000, pair="BTC", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            fvg_overlap=False, status="active",
        )
        candle = make_candle(2000, 101, 102, 98, 99)  # close < lower_bound
        update_ob_status([ob], candle)
        assert ob.status == "mitigated"
        assert ob.mitigated_at == 2000

    def test_bearish_ob_mitigated(self):
        ob = OrderBlock(
            timestamp=1000, pair="BTC", timeframe="1h",
            type="bearish", upper_bound=110, lower_bound=105,
            fvg_overlap=False, status="active",
        )
        candle = make_candle(2000, 109, 112, 108, 111)  # close > upper_bound
        update_ob_status([ob], candle)
        assert ob.status == "mitigated"

    def test_already_mitigated_unchanged(self):
        ob = OrderBlock(
            timestamp=1000, pair="BTC", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            fvg_overlap=False, status="mitigated", mitigated_at=1500,
        )
        candle = make_candle(2000, 101, 102, 98, 99)
        update_ob_status([ob], candle)
        assert ob.mitigated_at == 1500

    def test_active_not_breached(self):
        ob = OrderBlock(
            timestamp=1000, pair="BTC", timeframe="1h",
            type="bullish", upper_bound=105, lower_bound=100,
            fvg_overlap=False, status="active",
        )
        candle = make_candle(2000, 106, 108, 103, 107)  # close > lower_bound
        update_ob_status([ob], candle)
        assert ob.status == "active"


class TestGetNearestOB:
    def test_nearest_bullish_below(self):
        obs = [
            OrderBlock(1000, "BTC", "1h", "bullish", 90, 85, False, "active"),
            OrderBlock(2000, "BTC", "1h", "bullish", 95, 90, False, "active"),
        ]
        result = get_nearest_ob(obs, 100.0, "bullish")
        assert result.upper_bound == 95

    def test_nearest_bearish_above(self):
        obs = [
            OrderBlock(1000, "BTC", "1h", "bearish", 115, 110, False, "active"),
            OrderBlock(2000, "BTC", "1h", "bearish", 108, 105, False, "active"),
        ]
        result = get_nearest_ob(obs, 100.0, "bearish")
        assert result.lower_bound == 105

    def test_mitigated_excluded(self):
        obs = [
            OrderBlock(1000, "BTC", "1h", "bullish", 95, 90, False, "mitigated"),
        ]
        assert get_nearest_ob(obs, 100.0, "bullish") is None

    def test_empty_list(self):
        assert get_nearest_ob([], 100.0, "bullish") is None
