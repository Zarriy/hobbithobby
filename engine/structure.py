"""
Market structure: swing points, BOS/CHoCH detection, equal levels, premium/discount zones.
"""

from dataclasses import dataclass, field
from typing import Optional

import config


@dataclass
class SwingPoint:
    timestamp: int
    price: float
    type: str  # "swing_high" or "swing_low"


@dataclass
class StructureBreak:
    timestamp: int
    type: str  # "bos_bullish", "bos_bearish", "choch_bullish", "choch_bearish"
    broken_level: float
    trend_before: str
    trend_after: str


def detect_swing_points(
    candles: list[dict],
    lookback: int = config.SWING_LOOKBACK,
) -> list[SwingPoint]:
    """
    Swing high: candle whose high is strictly higher than `lookback` candles on each side.
    Swing low: candle whose low is strictly lower than `lookback` candles on each side.
    Requires at least 2*lookback+1 candles.
    """
    n = len(candles)
    result: list[SwingPoint] = []

    for i in range(lookback, n - lookback):
        c = candles[i]
        left = candles[i - lookback : i]
        right = candles[i + 1 : i + lookback + 1]

        # Swing high
        if all(c["high"] > x["high"] for x in left) and all(
            c["high"] > x["high"] for x in right
        ):
            result.append(SwingPoint(timestamp=c["timestamp"], price=c["high"], type="swing_high"))

        # Swing low
        if all(c["low"] < x["low"] for x in left) and all(
            c["low"] < x["low"] for x in right
        ):
            result.append(SwingPoint(timestamp=c["timestamp"], price=c["low"], type="swing_low"))

    # Sort by timestamp
    result.sort(key=lambda s: s.timestamp)
    return result


def detect_structure_breaks(
    swing_points: list[SwingPoint],
    current_trend: str = "ranging",
) -> tuple[list[StructureBreak], str]:
    """
    Scan swing points in order to identify BOS and CHoCH events.

    BOS (Break of Structure) — trend continuation:
      - Uptrend: price breaks above prior swing_high
      - Downtrend: price breaks below prior swing_low

    CHoCH (Change of Character) — reversal signal:
      - Uptrend: price breaks below prior swing_low
      - Downtrend: price breaks above prior swing_high

    Returns (list_of_breaks, final_trend_state)
    """
    breaks: list[StructureBreak] = []
    trend = current_trend

    highs = [s for s in swing_points if s.type == "swing_high"]
    lows = [s for s in swing_points if s.type == "swing_low"]

    # Rebuild structure sequentially
    last_swing_high: Optional[SwingPoint] = None
    last_swing_low: Optional[SwingPoint] = None

    for sp in swing_points:
        if sp.type == "swing_high":
            if last_swing_high is not None:
                if trend in ("uptrend", "ranging"):
                    if sp.price > last_swing_high.price:
                        # Higher high — BOS bullish (continuation)
                        breaks.append(StructureBreak(
                            timestamp=sp.timestamp,
                            type="bos_bullish",
                            broken_level=last_swing_high.price,
                            trend_before=trend,
                            trend_after="uptrend",
                        ))
                        trend = "uptrend"
                    # Equal high or lower high doesn't confirm anything by itself
                elif trend == "downtrend":
                    if sp.price > last_swing_high.price:
                        # Higher high in downtrend = CHoCH bullish (reversal signal)
                        breaks.append(StructureBreak(
                            timestamp=sp.timestamp,
                            type="choch_bullish",
                            broken_level=last_swing_high.price,
                            trend_before=trend,
                            trend_after="transition",
                        ))
                        trend = "transition"
            last_swing_high = sp

        elif sp.type == "swing_low":
            if last_swing_low is not None:
                if trend in ("downtrend", "ranging"):
                    if sp.price < last_swing_low.price:
                        # Lower low — BOS bearish (continuation)
                        breaks.append(StructureBreak(
                            timestamp=sp.timestamp,
                            type="bos_bearish",
                            broken_level=last_swing_low.price,
                            trend_before=trend,
                            trend_after="downtrend",
                        ))
                        trend = "downtrend"
                elif trend == "uptrend":
                    if sp.price < last_swing_low.price:
                        # Lower low in uptrend = CHoCH bearish (reversal signal)
                        breaks.append(StructureBreak(
                            timestamp=sp.timestamp,
                            type="choch_bearish",
                            broken_level=last_swing_low.price,
                            trend_before=trend,
                            trend_after="transition",
                        ))
                        trend = "transition"
            last_swing_low = sp

    return breaks, trend


def detect_equal_levels(
    swing_points: list[SwingPoint],
    tolerance: float = config.EQUAL_LEVEL_TOLERANCE,
) -> dict:
    """
    Find swing highs within `tolerance` (as fraction of price) of each other = equal highs.
    Find swing lows within `tolerance` of each other = equal lows.
    Returns {"equal_highs": [prices], "equal_lows": [prices]}
    """
    highs = sorted(
        [s.price for s in swing_points if s.type == "swing_high"]
    )
    lows = sorted(
        [s.price for s in swing_points if s.type == "swing_low"]
    )

    def find_clusters(prices: list[float]) -> list[float]:
        clusters = []
        used = set()
        for i, p in enumerate(prices):
            if i in used:
                continue
            group = [p]
            for j in range(i + 1, len(prices)):
                if j not in used and abs(prices[j] - p) / max(p, 1e-10) <= tolerance:
                    group.append(prices[j])
                    used.add(j)
            if len(group) >= 2:
                clusters.append(sum(group) / len(group))
            used.add(i)
        return clusters

    return {
        "equal_highs": find_clusters(highs),
        "equal_lows": find_clusters(lows),
    }


def get_premium_discount_zone(
    swing_points: list[SwingPoint],
    current_price: float,
    equilibrium_band: float = 0.05,
) -> str:
    """
    Use most recent swing high + swing low to define the range.
    Above midpoint = premium, below = discount, within equilibrium_band = equilibrium.
    """
    recent_highs = [s for s in swing_points if s.type == "swing_high"]
    recent_lows = [s for s in swing_points if s.type == "swing_low"]

    if not recent_highs or not recent_lows:
        return "equilibrium"

    latest_high = max(recent_highs, key=lambda s: s.timestamp).price
    latest_low = max(recent_lows, key=lambda s: s.timestamp).price

    midpoint = (latest_high + latest_low) / 2.0
    band = midpoint * equilibrium_band

    if current_price > midpoint + band:
        return "premium"
    elif current_price < midpoint - band:
        return "discount"
    else:
        return "equilibrium"


def get_trend_state(candles: list[dict]) -> tuple[str, list[StructureBreak]]:
    """
    Convenience: detect swing points then structure breaks, return current trend + breaks.
    """
    swings = detect_swing_points(candles)
    breaks, trend = detect_structure_breaks(swings)
    return trend, breaks
