"""
Tests for engine/liquidity.py — sweep detection, session levels, next session.
"""

import pytest
from tests.conftest import make_candle
from engine.structure import SwingPoint
from engine.liquidity import detect_liquidity_sweeps, get_session_levels, get_next_session_open


class TestDetectLiquiditySweeps:
    def test_bull_sweep_wick_below_swing_low(self):
        """Wick below swing low + close back above = bull_sweep."""
        swing_low = SwingPoint(timestamp=1_000_000_000_000, price=100.0, type="swing_low")
        candles = [
            make_candle(1_000_000_000_000, 105, 106, 104, 105),
            make_candle(1_000_003_600_000, 103, 104, 102, 103),
            make_candle(1_000_007_200_000, 101, 102, 99.8, 101),  # wick below 100, close above
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_low], max_exceed_percent=0.003)
        bull = [s for s in sweeps if s["type"] == "bull_sweep"]
        assert len(bull) >= 1
        assert bull[0]["level"] == 100.0

    def test_bear_sweep_wick_above_swing_high(self):
        """Wick above swing high + close back below = bear_sweep."""
        swing_high = SwingPoint(timestamp=1_000_000_000_000, price=110.0, type="swing_high")
        candles = [
            make_candle(1_000_000_000_000, 105, 106, 104, 105),
            make_candle(1_000_003_600_000, 108, 109, 107, 108),
            make_candle(1_000_007_200_000, 109, 110.2, 108, 109),  # wick above 110, close below
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_high], max_exceed_percent=0.003)
        bear = [s for s in sweeps if s["type"] == "bear_sweep"]
        assert len(bear) >= 1

    def test_no_sweep_wick_too_far(self):
        """Wick exceeds by more than max_exceed_percent → no sweep."""
        swing_low = SwingPoint(timestamp=1_000_000_000_000, price=100.0, type="swing_low")
        candles = [
            make_candle(1_000_003_600_000, 101, 102, 96, 101),  # wick at 96, 4% below
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_low], max_exceed_percent=0.003)
        assert len(sweeps) == 0

    def test_no_sweep_no_close_back(self):
        """Wick below level but close doesn't come back above within reversal window."""
        swing_low = SwingPoint(timestamp=1_000_000_000_000, price=100.0, type="swing_low")
        candles = [
            make_candle(1_000_003_600_000, 101, 102, 99.8, 99.5),  # closes below
            make_candle(1_000_007_200_000, 99.5, 99.8, 99, 99.2),
            make_candle(1_000_010_800_000, 99.2, 99.5, 98, 98.5),
            make_candle(1_000_014_400_000, 98.5, 99, 97, 98),
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_low], max_exceed_percent=0.003, max_reversal_candles=3)
        assert len(sweeps) == 0

    def test_deduplication(self):
        """Same sweep should not appear multiple times."""
        swing_low = SwingPoint(timestamp=1_000_000_000_000, price=100.0, type="swing_low")
        candles = [
            make_candle(1_000_003_600_000, 101, 102, 99.8, 101),
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_low])
        timestamps_types = [(s["timestamp"], s["type"], s["level"]) for s in sweeps]
        assert len(timestamps_types) == len(set(timestamps_types))

    def test_future_swing_ignored(self):
        """Swing point at or after candle timestamp should be ignored."""
        swing_low = SwingPoint(timestamp=1_000_007_200_000, price=100.0, type="swing_low")
        candles = [
            make_candle(1_000_003_600_000, 101, 102, 99.8, 101),
        ]
        sweeps = detect_liquidity_sweeps(candles, [swing_low])
        assert len(sweeps) == 0


class TestGetSessionLevels:
    def test_asian_session(self):
        """Candles during 00-08 UTC should be captured."""
        # Timestamp for 2024-01-15 03:00 UTC = approx 1705284000000
        ts_3am = 1705284000000
        tf = 3_600_000
        candles = [
            make_candle(ts_3am, 100, 105, 98, 103),
            make_candle(ts_3am + tf, 103, 106, 101, 104),
            make_candle(ts_3am + 2 * tf, 104, 108, 102, 107),
        ]
        levels = get_session_levels(candles)
        assert "asian" in levels
        assert levels["asian"]["high"] == 108
        assert levels["asian"]["low"] == 98

    def test_empty_candles(self):
        levels = get_session_levels([])
        assert levels == {}

    def test_no_candles_in_session(self):
        """If no candles fall in a session window, that session is absent."""
        # Timestamp for 2024-01-15 10:00 UTC (London session only)
        ts_10am = 1705309200000
        candles = [make_candle(ts_10am, 100, 105, 98, 103)]
        levels = get_session_levels(candles)
        assert "asian" not in levels
        assert "london" in levels

    def test_custom_sessions(self):
        ts = 1705309200000  # 10:00 UTC
        candles = [make_candle(ts, 100, 105, 98, 103)]
        levels = get_session_levels(candles, session_definitions={"custom": (9, 11)})
        assert "custom" in levels


class TestGetNextSessionOpen:
    def test_before_asian(self):
        """At 23:30 → next is Asian at 00:00 (30 min)."""
        # 23:30 UTC
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 15, 23, 30, tzinfo=timezone.utc)
        ts = int(dt.timestamp() * 1000)
        result = get_next_session_open(ts)
        assert result["session"] == "Asian"
        assert result["minutes_until"] == 30

    def test_before_london(self):
        """At 05:00 → next is London at 08:00 (180 min)."""
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 15, 5, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp() * 1000)
        result = get_next_session_open(ts)
        assert result["session"] == "London"
        assert result["minutes_until"] == 180

    def test_before_ny(self):
        """At 10:00 → next is New York at 13:00 (180 min)."""
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp() * 1000)
        result = get_next_session_open(ts)
        assert result["session"] == "New York"
        assert result["minutes_until"] == 180

    def test_after_all_sessions(self):
        """At 22:00 → next is Asian tomorrow."""
        from datetime import datetime, timezone
        dt = datetime(2024, 1, 15, 22, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp() * 1000)
        result = get_next_session_open(ts)
        assert result["session"] == "Asian"
        assert result["minutes_until"] == 120  # 22:00 to midnight
