"""
Liquidity sweep detection and session level marking.
"""

from datetime import datetime, timezone
from typing import Optional

from engine.structure import SwingPoint


def detect_liquidity_sweeps(
    candles: list[dict],
    swing_points: list[SwingPoint],
    max_exceed_percent: float = 0.003,
    max_reversal_candles: int = 3,
) -> list[dict]:
    """
    A liquidity sweep occurs when:
    1. Price exceeds a swing high/low by <= max_exceed_percent
    2. Price closes back inside the prior range within max_reversal_candles candles

    Returns list of:
    {
        timestamp, type: "bull_sweep"/"bear_sweep",
        level: float, reversal_candle: int (index), sweep_candle: int (index)
    }
    """
    sweeps = []
    swing_highs = [s for s in swing_points if s.type == "swing_high"]
    swing_lows = [s for s in swing_points if s.type == "swing_low"]

    n = len(candles)
    for i, candle in enumerate(candles):
        # Check bear sweep: price wicks below a swing low but closes back above
        for sl in swing_lows:
            if sl.timestamp >= candle["timestamp"]:
                continue
            level = sl.price
            max_below = level * (1 - max_exceed_percent)

            if candle["low"] < level and candle["low"] >= max_below:
                # Look for close-back within reversal window
                for j in range(i, min(i + max_reversal_candles + 1, n)):
                    if candles[j]["close"] > level:
                        sweeps.append({
                            "timestamp": candle["timestamp"],
                            "type": "bull_sweep",  # swept lows = bullish reversal potential
                            "level": level,
                            "sweep_candle_idx": i,
                            "reversal_candle_idx": j,
                        })
                        break

        # Check bull sweep: price wicks above a swing high but closes back below
        for sh in swing_highs:
            if sh.timestamp >= candle["timestamp"]:
                continue
            level = sh.price
            max_above = level * (1 + max_exceed_percent)

            if candle["high"] > level and candle["high"] <= max_above:
                # Look for close-back within reversal window
                for j in range(i, min(i + max_reversal_candles + 1, n)):
                    if candles[j]["close"] < level:
                        sweeps.append({
                            "timestamp": candle["timestamp"],
                            "type": "bear_sweep",  # swept highs = bearish reversal potential
                            "level": level,
                            "sweep_candle_idx": i,
                            "reversal_candle_idx": j,
                        })
                        break

    # Deduplicate by (timestamp, type, level)
    seen = set()
    unique = []
    for s in sweeps:
        key = (s["timestamp"], s["type"], s["level"])
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique


def get_session_levels(
    candles: list[dict],
    session_definitions: Optional[dict] = None,
) -> dict:
    """
    Calculate high and low for each trading session using UTC hours.

    Default sessions:
      Asian: 00:00-08:00 UTC
      London: 08:00-16:00 UTC
      New York: 13:00-21:00 UTC

    Returns:
    {
        session_name: {high: float, low: float, open: float, close: float, timestamp: int}
    }
    """
    if session_definitions is None:
        session_definitions = {
            "asian": (0, 8),
            "london": (8, 16),
            "new_york": (13, 21),
        }

    results = {}
    for session_name, (start_hour, end_hour) in session_definitions.items():
        session_candles = []
        for c in candles:
            dt = datetime.fromtimestamp(c["timestamp"] / 1000, tz=timezone.utc)
            hour = dt.hour
            if start_hour <= hour < end_hour:
                session_candles.append(c)

        if session_candles:
            results[session_name] = {
                "high": max(c["high"] for c in session_candles),
                "low": min(c["low"] for c in session_candles),
                "open": session_candles[0]["open"],
                "close": session_candles[-1]["close"],
                "timestamp": session_candles[0]["timestamp"],
            }

    return results


def get_next_session_open(current_ts_ms: int) -> Optional[dict]:
    """
    Return the name and time until the next major session open (UTC).
    Used in alert formatting.
    """
    dt = datetime.fromtimestamp(current_ts_ms / 1000, tz=timezone.utc)
    current_minutes = dt.hour * 60 + dt.minute

    sessions = [
        ("Asian", 0 * 60),
        ("London", 8 * 60),
        ("New York", 13 * 60),
    ]

    for name, open_min in sessions:
        if current_minutes < open_min:
            minutes_until = open_min - current_minutes
            return {"session": name, "minutes_until": minutes_until}

    # All sessions passed today — next is Asian tomorrow
    minutes_until = (24 * 60) - current_minutes
    return {"session": "Asian", "minutes_until": minutes_until}
