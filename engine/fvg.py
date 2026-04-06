"""
Fair Value Gap (FVG) detection and fill-status tracking.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class FVG:
    timestamp: int
    pair: str
    timeframe: str
    type: str          # "bullish" or "bearish"
    upper_bound: float
    lower_bound: float
    status: str        # "unfilled", "partial", "filled"
    gap_size_percent: float
    filled_at: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "type": self.type,
            "upper_bound": self.upper_bound,
            "lower_bound": self.lower_bound,
            "status": self.status,
            "gap_size_percent": self.gap_size_percent,
            "filled_at": self.filled_at,
        }


def detect_fvgs(
    candles: list[dict],
    min_gap_percent: float = config.FVG_MIN_GAP_PERCENT,
) -> list[FVG]:
    """
    Scan candle list for Fair Value Gaps.

    Bullish FVG: candle[i-2].high < candle[i].low
      - Gap zone = (candle[i-2].high, candle[i].low)

    Bearish FVG: candle[i-2].low > candle[i].high
      - Gap zone = (candle[i].high, candle[i-2].low)

    Filter: gap_size / mid_price > min_gap_percent
    """
    fvgs: list[FVG] = []
    n = len(candles)
    if n < 3:
        return fvgs

    pair = candles[0].get("pair", "")
    timeframe = candles[0].get("timeframe", "")

    for i in range(2, n):
        c0 = candles[i - 2]
        c2 = candles[i]

        # Bullish FVG
        if c0["high"] < c2["low"]:
            upper = c2["low"]
            lower = c0["high"]
            mid = (upper + lower) / 2.0
            gap_pct = (upper - lower) / mid if mid > 0 else 0
            if gap_pct >= min_gap_percent:
                fvgs.append(FVG(
                    timestamp=c2["timestamp"],
                    pair=pair,
                    timeframe=timeframe,
                    type="bullish",
                    upper_bound=upper,
                    lower_bound=lower,
                    status="unfilled",
                    gap_size_percent=gap_pct,
                ))

        # Bearish FVG
        if c0["low"] > c2["high"]:
            upper = c0["low"]
            lower = c2["high"]
            mid = (upper + lower) / 2.0
            gap_pct = (upper - lower) / mid if mid > 0 else 0
            if gap_pct >= min_gap_percent:
                fvgs.append(FVG(
                    timestamp=c2["timestamp"],
                    pair=pair,
                    timeframe=timeframe,
                    type="bearish",
                    upper_bound=upper,
                    lower_bound=lower,
                    status="unfilled",
                    gap_size_percent=gap_pct,
                ))

    return fvgs


def update_fvg_status(fvgs: list[FVG], current_candle: dict) -> list[FVG]:
    """
    Update fill status of each unfilled/partial FVG given the current candle.

    - Filled: close passed through the entire gap zone
    - Partial: wick touched the gap but close didn't fully pass through
    """
    candle_low = current_candle["low"]
    candle_high = current_candle["high"]
    candle_close = current_candle["close"]
    ts = current_candle["timestamp"]

    for fvg in fvgs:
        if fvg.status == "filled":
            continue

        if fvg.type == "bullish":
            # Bullish FVG below current price — check if price retraced into it
            if candle_low <= fvg.upper_bound:
                if candle_close < fvg.lower_bound:
                    # Closed fully through — filled
                    fvg.status = "filled"
                    fvg.filled_at = ts
                else:
                    # Wick entered the zone but close didn't breach the bottom
                    fvg.status = "partial"

        elif fvg.type == "bearish":
            # Bearish FVG above current price — check if price retraced into it
            if candle_high >= fvg.lower_bound:
                if candle_close > fvg.upper_bound:
                    # Closed fully through — filled
                    fvg.status = "filled"
                    fvg.filled_at = ts
                else:
                    # Wick entered the zone but close didn't breach the top
                    fvg.status = "partial"

    return fvgs


def get_nearest_fvg(
    fvgs: list[FVG],
    current_price: float,
    direction: str,  # "bullish" or "bearish"
) -> Optional[FVG]:
    """
    Return nearest unfilled/partial FVG in the specified direction.

    For bullish: nearest bullish FVG with upper_bound BELOW current price.
    For bearish: nearest bearish FVG with lower_bound ABOVE current price.
    """
    candidates = [f for f in fvgs if f.type == direction and f.status != "filled"]

    if direction == "bullish":
        below = [f for f in candidates if f.upper_bound < current_price]
        if not below:
            return None
        return max(below, key=lambda f: f.upper_bound)

    elif direction == "bearish":
        above = [f for f in candidates if f.lower_bound > current_price]
        if not above:
            return None
        return min(above, key=lambda f: f.lower_bound)

    return None


def fvg_to_store_dict(fvg: FVG) -> dict:
    """Convert FVG to the format expected by store.upsert_fvg."""
    return {
        "pair": fvg.pair,
        "timeframe": fvg.timeframe,
        "detected_at": fvg.timestamp,
        "type": fvg.type,
        "upper_bound": fvg.upper_bound,
        "lower_bound": fvg.lower_bound,
        "status": fvg.status,
        "filled_at": fvg.filled_at,
    }
