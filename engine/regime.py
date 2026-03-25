"""
4H macro regime classification.
Provides high-timeframe context that informs the classifier.
"""

import numpy as np
from typing import Optional

from engine import indicators
from engine.structure import detect_swing_points, detect_structure_breaks


def classify_macro_regime(
    candles_4h: list[dict],
    oi_history: list[float],
    funding_history: list[float],
    volume_history: list[float],
    lookback: int = 30,  # 30 candles = ~5 days on 4H
) -> str:
    """
    Determine macro regime from 4H data.

    Returns one of:
    - "accumulation": ranging/up, OI building, funding neutral/negative
    - "distribution": ranging/down, OI building, funding neutral/positive
    - "markup": strong uptrend with BOS, expanding volume, healthy pullbacks
    - "markdown": strong downtrend with BOS, expanding volume, weak bounces
    - "transition": CHoCH detected, conflicting signals
    """
    if len(candles_4h) < lookback:
        return "transition"

    recent = candles_4h[-lookback:]

    closes = np.array([c["close"] for c in recent])
    highs = np.array([c["high"] for c in recent])
    lows = np.array([c["low"] for c in recent])
    volumes = np.array([c["volume"] for c in recent])

    # Price trend: net change over period
    price_change = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0

    # Volume trend: is volume expanding or contracting?
    half = len(volumes) // 2
    vol_first_half = np.mean(volumes[:half]) if half > 0 else 1
    vol_second_half = np.mean(volumes[half:]) if half > 0 else 1
    vol_expanding = vol_second_half > vol_first_half * 1.1

    # OI trend
    oi_arr = np.array(oi_history[-lookback:]) if len(oi_history) >= lookback else np.array(oi_history)
    oi_building = False
    if len(oi_arr) >= 2:
        oi_change = (oi_arr[-1] - oi_arr[0]) / oi_arr[0] if oi_arr[0] > 0 else 0
        oi_building = oi_change > 0.03

    # Funding trend
    fund_arr = np.array(funding_history[-lookback:]) if len(funding_history) >= lookback else np.array(funding_history)
    mean_funding = float(np.mean(fund_arr)) if len(fund_arr) > 0 else 0.0
    funding_positive = mean_funding > 0.0001
    funding_negative = mean_funding < -0.0001

    # Structure analysis
    swings = detect_swing_points(recent, lookback=3)  # Tighter lookback for 4H
    breaks, current_trend = detect_structure_breaks(swings)

    # Check for recent CHoCH
    recent_choch = any(b.type.startswith("choch") for b in breaks[-5:]) if breaks else False

    # ─── Classification Logic ───
    if recent_choch:
        return "transition"

    if current_trend == "uptrend":
        if vol_expanding and not funding_positive:
            return "markup"
        elif price_change > 0.05:
            return "markup"
        else:
            return "accumulation"

    if current_trend == "downtrend":
        if vol_expanding and not funding_negative:
            return "markdown"
        elif price_change < -0.05:
            return "markdown"
        else:
            return "distribution"

    # Ranging
    if oi_building and funding_negative:
        return "accumulation"
    elif oi_building and funding_positive:
        return "distribution"

    return "transition"
