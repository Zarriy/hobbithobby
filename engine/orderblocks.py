"""
Order Block detection with FVG overlap scoring.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

import config
from engine.fvg import FVG


@dataclass
class OrderBlock:
    timestamp: int
    pair: str
    timeframe: str
    type: str          # "bullish" or "bearish"
    upper_bound: float
    lower_bound: float
    fvg_overlap: bool  # True if this OB zone overlaps with an FVG
    status: str        # "active" or "mitigated"
    mitigated_at: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "type": self.type,
            "upper_bound": self.upper_bound,
            "lower_bound": self.lower_bound,
            "fvg_overlap": self.fvg_overlap,
            "status": self.status,
            "mitigated_at": self.mitigated_at,
        }


def _is_bullish_candle(c: dict) -> bool:
    return c["close"] >= c["open"]


def _is_bearish_candle(c: dict) -> bool:
    return c["close"] < c["open"]


def _candle_range(c: dict) -> float:
    return c["high"] - c["low"]


def _zones_overlap(upper1: float, lower1: float, upper2: float, lower2: float) -> bool:
    """Check if two price zones overlap."""
    return lower1 < upper2 and lower2 < upper1


def detect_order_blocks(
    candles: list[dict],
    fvgs: list[FVG],
    impulse_min_candles: int = config.OB_IMPULSE_MIN_CANDLES,
    impulse_min_atr_multiple: float = config.OB_IMPULSE_MIN_RANGE_ATR,
    atr_values: Optional[np.ndarray] = None,
) -> list[OrderBlock]:
    """
    1. Detect impulsive moves: `impulse_min_candles` or more consecutive same-direction
       candles covering >= impulse_min_atr_multiple * ATR.
    2. The last OPPOSING candle before the impulse is the Order Block.
       - Bullish OB: last bearish candle before a bullish impulse
       - Bearish OB: last bullish candle before a bearish impulse
    3. Check FVG overlap.
    """
    n = len(candles)
    if n < impulse_min_candles + 1:
        return []

    pair = candles[0].get("pair", "")
    timeframe = candles[0].get("timeframe", "")
    obs: list[OrderBlock] = []

    # Compute ATR if not provided
    if atr_values is None:
        from engine.indicators import atr as compute_atr
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        closes = np.array([c["close"] for c in candles])
        atr_values = compute_atr(highs, lows, closes, period=14)

    # Active unfilled FVGs for overlap check
    active_fvgs = [f for f in fvgs if f.status != "filled"]

    i = impulse_min_candles
    while i < n:
        # Check for bullish impulse ending at candle i
        window = candles[i - impulse_min_candles + 1 : i + 1]
        if all(_is_bullish_candle(c) for c in window):
            total_range = sum(_candle_range(c) for c in window)
            atr_ref = atr_values[i]
            if not np.isnan(atr_ref) and total_range >= impulse_min_atr_multiple * atr_ref:
                # Find last bearish candle before window
                ob_idx = None
                for j in range(i - impulse_min_candles, -1, -1):
                    if _is_bearish_candle(candles[j]):
                        ob_idx = j
                        break
                if ob_idx is not None:
                    ob_candle = candles[ob_idx]
                    upper = ob_candle["high"]
                    lower = ob_candle["low"]
                    overlap = any(
                        _zones_overlap(upper, lower, f.upper_bound, f.lower_bound)
                        for f in active_fvgs
                        if f.type == "bullish"
                    )
                    obs.append(OrderBlock(
                        timestamp=ob_candle["timestamp"],
                        pair=pair,
                        timeframe=timeframe,
                        type="bullish",
                        upper_bound=upper,
                        lower_bound=lower,
                        fvg_overlap=overlap,
                        status="active",
                    ))

        # Check for bearish impulse ending at candle i
        window = candles[i - impulse_min_candles + 1 : i + 1]
        if all(_is_bearish_candle(c) for c in window):
            total_range = sum(_candle_range(c) for c in window)
            atr_ref = atr_values[i]
            if not np.isnan(atr_ref) and total_range >= impulse_min_atr_multiple * atr_ref:
                # Find last bullish candle before window
                ob_idx = None
                for j in range(i - impulse_min_candles, -1, -1):
                    if _is_bullish_candle(candles[j]):
                        ob_idx = j
                        break
                if ob_idx is not None:
                    ob_candle = candles[ob_idx]
                    upper = ob_candle["high"]
                    lower = ob_candle["low"]
                    overlap = any(
                        _zones_overlap(upper, lower, f.upper_bound, f.lower_bound)
                        for f in active_fvgs
                        if f.type == "bearish"
                    )
                    obs.append(OrderBlock(
                        timestamp=ob_candle["timestamp"],
                        pair=pair,
                        timeframe=timeframe,
                        type="bearish",
                        upper_bound=upper,
                        lower_bound=lower,
                        fvg_overlap=overlap,
                        status="active",
                    ))

        i += 1

    # Deduplicate by timestamp+type+upper_bound
    seen = set()
    unique_obs = []
    for ob in obs:
        key = (ob.timestamp, ob.type, ob.upper_bound)
        if key not in seen:
            seen.add(key)
            unique_obs.append(ob)

    return unique_obs


def update_ob_status(obs: list[OrderBlock], current_candle: dict) -> list[OrderBlock]:
    """
    Mitigate an Order Block if price closed through it.
    - Bullish OB: mitigated when candle close < ob.lower_bound
    - Bearish OB: mitigated when candle close > ob.upper_bound
    """
    ts = current_candle["timestamp"]
    close = current_candle["close"]

    for ob in obs:
        if ob.status == "mitigated":
            continue
        if ob.type == "bullish" and close < ob.lower_bound:
            ob.status = "mitigated"
            ob.mitigated_at = ts
        elif ob.type == "bearish" and close > ob.upper_bound:
            ob.status = "mitigated"
            ob.mitigated_at = ts

    return obs


def get_nearest_ob(
    obs: list[OrderBlock],
    current_price: float,
    direction: str,  # "bullish" or "bearish"
) -> Optional[OrderBlock]:
    """
    Nearest active OB in the given direction.
    Bullish OB: upper_bound below current price (support below).
    Bearish OB: lower_bound above current price (resistance above).
    """
    candidates = [ob for ob in obs if ob.type == direction and ob.status == "active"]

    if direction == "bullish":
        below = [ob for ob in candidates if ob.upper_bound < current_price]
        if not below:
            return None
        return max(below, key=lambda ob: ob.upper_bound)

    elif direction == "bearish":
        above = [ob for ob in candidates if ob.lower_bound > current_price]
        if not above:
            return None
        return min(above, key=lambda ob: ob.lower_bound)

    return None


def ob_to_store_dict(ob: OrderBlock) -> dict:
    return {
        "pair": ob.pair,
        "timeframe": ob.timeframe,
        "detected_at": ob.timestamp,
        "type": ob.type,
        "upper_bound": ob.upper_bound,
        "lower_bound": ob.lower_bound,
        "fvg_overlap": int(ob.fvg_overlap),
        "status": ob.status,
        "mitigated_at": ob.mitigated_at,
    }
