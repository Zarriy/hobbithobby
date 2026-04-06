"""
Signal matrix — regime state + risk color + confidence score.
The core of the system.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class SignalOutput:
    regime_state: str   # accumulation, distribution, short_squeeze, long_liquidation, coiled_spring, deleveraging
    risk_color: str     # green, yellow, red
    confidence: int     # 0-100
    trend_state: str    # uptrend, downtrend, ranging, transition
    price_zone: str     # premium, discount, equilibrium
    action_bias: str    # long_bias, short_bias, stay_flat, reduce_exposure
    pair: str = ""
    timeframe: str = ""
    timestamp: int = 0
    volume_zscore: float = 0.0
    oi_change_percent: float = 0.0
    funding_rate: float = 0.0
    taker_ratio: float = 0.5
    atr: float = 0.0
    atr_zscore: float = 0.0
    vwap_deviation: float = 0.0
    data_age_seconds: float = 0.0


def classify(
    price_change: float,
    oi_change: Optional[float],
    volume_zscore: float,
    funding_rate: float,
    taker_ratio: float,
    long_short_ratio: float,
    trend_state: str,
    vwap_deviation: float,
    atr_zscore: float,
    pair: str = "",
    timeframe: str = "",
    timestamp: int = 0,
    price_zone: str = "equilibrium",
    current_price: float = 0.0,
    atr: float = 0.0,
    data_age_seconds: float = 0.0,
) -> SignalOutput:
    """
    Core signal matrix. Maps market conditions to regime + risk posture.

    oi_change: None means no OI data available (volume-only fallback used).
               A numeric value (even small) means OI data is present.
    """
    # ─── Regime State Classification ───
    high_volume = volume_zscore > 1.5
    extreme_positive_funding = funding_rate > config.FUNDING_RATE_EXTREME_POSITIVE
    extreme_negative_funding = funding_rate < config.FUNDING_RATE_EXTREME_NEGATIVE
    # Use 0.0 as safe default for OI comparisons when data is unavailable
    _oi = oi_change if oi_change is not None else 0.0
    oi_building = _oi > config.OI_CHANGE_NOTABLE
    oi_unwinding = _oi < -config.OI_CHANGE_NOTABLE
    oi_spike = _oi > 0.05
    price_up = price_change > 0.002   # >0.2% move
    price_down = price_change < -0.002
    price_flat = not price_up and not price_down

    # Determine regime
    regime_state: str
    risk_color: str
    action_bias: str

    if price_up and oi_building and high_volume and not extreme_positive_funding:
        # Classic accumulation: new money entering on upside
        regime_state = "accumulation"
        risk_color = "green"
        action_bias = "long_bias"

    elif price_up and oi_building and high_volume and extreme_positive_funding:
        # Price up + OI up + crowded longs = unsustainable squeeze
        # Fade the move — rally likely to exhaust, short at reduced size
        regime_state = "short_squeeze"
        risk_color = "yellow"
        action_bias = "short_bias"

    elif price_up and oi_unwinding and high_volume:
        # Price up but OI falling = short covering rally, not real accumulation
        # Fade — covering rally exhausts once shorts are cleared
        regime_state = "short_squeeze"
        risk_color = "yellow"
        action_bias = "short_bias"

    elif price_down and oi_building and high_volume and not extreme_negative_funding:
        # Distribution: new short money entering on downside
        regime_state = "distribution"
        risk_color = "green"  # Good for shorts
        action_bias = "short_bias"

    elif price_down and oi_building and high_volume and extreme_negative_funding:
        # Price down + OI up + crowded shorts = long liquidation risk
        # Fade the cascade — buy the dip at reduced size once liquidations exhaust
        regime_state = "long_liquidation"
        risk_color = "yellow"
        action_bias = "long_bias"

    elif price_down and oi_unwinding and high_volume:
        # Price down + OI falling = long liquidation cascade
        regime_state = "long_liquidation"
        risk_color = "red"
        action_bias = "reduce_exposure"

    elif price_flat and oi_spike and not high_volume:
        # OI building without price movement = coiled spring
        regime_state = "coiled_spring"
        risk_color = "yellow"
        action_bias = "stay_flat"

    elif oi_unwinding and high_volume:
        # Mass deleveraging
        regime_state = "deleveraging"
        risk_color = "red"
        action_bias = "reduce_exposure"

    elif _oi < -0.05:
        # Fast OI drain (≥5%) — deleveraging even without a volume spike
        regime_state = "deleveraging"
        risk_color = "red"
        action_bias = "reduce_exposure"

    elif oi_change is None and volume_zscore > 2.0 and price_up:
        # No OI data available — use strong volume + price as proxy for accumulation
        regime_state = "accumulation"
        risk_color = "green"
        action_bias = "long_bias"

    elif oi_change is None and volume_zscore > 2.0 and price_down:
        # No OI data available — use strong volume + price as proxy for distribution
        regime_state = "distribution"
        risk_color = "green"
        action_bias = "short_bias"

    else:
        # Default: insufficient signal strength
        regime_state = "accumulation" if price_change >= 0 else "distribution"
        risk_color = "yellow"
        action_bias = "stay_flat"

    # ─── Confidence Scoring ───
    base_confidence = 50

    # Volume confirmation (+20 max)
    if volume_zscore > 2.0:
        base_confidence += 20
    elif volume_zscore > 1.5:
        base_confidence += 15
    elif volume_zscore > 1.0:
        base_confidence += 10

    # OI magnitude (+15 max) — only when OI data is actually available
    if oi_change is not None:
        if abs(oi_change) > 0.05:
            base_confidence += 15
        elif abs(oi_change) > 0.03:
            base_confidence += 10
        elif abs(oi_change) > 0.02:
            base_confidence += 5

    # Funding extreme (+10 max)
    if abs(funding_rate) > 0.0005:
        base_confidence += 10
    elif abs(funding_rate) > 0.0003:
        base_confidence += 7

    # Taker ratio alignment (+10 max)
    is_bullish_regime = regime_state in ("accumulation",)
    is_bearish_regime = regime_state in ("distribution", "long_liquidation")
    taker_aligns = (is_bullish_regime and taker_ratio > 0.55) or (
        is_bearish_regime and taker_ratio < 0.45
    )
    if taker_aligns:
        base_confidence += 10

    # Trend alignment (+10 max)
    trend_confirms = (
        (action_bias == "long_bias" and trend_state == "uptrend")
        or (action_bias == "short_bias" and trend_state == "downtrend")
    )
    if trend_confirms:
        base_confidence += 10

    # VWAP mean reversion bonus (+5 max)
    vwap_mean_reverting = (
        abs(vwap_deviation) > config.VWAP_DEVIATION_THRESHOLD
        and (
            (action_bias == "long_bias" and vwap_deviation < -config.VWAP_DEVIATION_THRESHOLD)
            or (action_bias == "short_bias" and vwap_deviation > config.VWAP_DEVIATION_THRESHOLD)
        )
    )
    if vwap_mean_reverting:
        base_confidence += 5

    # Low volatility penalty (-10 if mixed signals in low-vol)
    signals_mixed = not taker_aligns and not trend_confirms
    if atr_zscore < -1.0 and signals_mixed:
        base_confidence -= 10

    # Regime risk penalty — dangerous regimes still trade but at reduced size
    if regime_state == "short_squeeze":
        base_confidence -= 15
    elif regime_state == "long_liquidation" and risk_color == "yellow":
        base_confidence -= 10

    # Stale data handling
    if data_age_seconds > config.STALE_DATA_THRESHOLD_SECONDS:
        risk_color = "yellow"
        base_confidence -= 20

    confidence = max(0, min(100, base_confidence))

    return SignalOutput(
        regime_state=regime_state,
        risk_color=risk_color,
        confidence=confidence,
        trend_state=trend_state,
        price_zone=price_zone,
        action_bias=action_bias,
        pair=pair,
        timeframe=timeframe,
        timestamp=timestamp,
        volume_zscore=volume_zscore,
        oi_change_percent=oi_change if oi_change is not None else 0.0,
        funding_rate=funding_rate,
        taker_ratio=taker_ratio,
        atr=atr,
        atr_zscore=atr_zscore,
        vwap_deviation=vwap_deviation,
        data_age_seconds=data_age_seconds,
    )


def signal_state_changed(prev: Optional[SignalOutput], curr: SignalOutput) -> bool:
    """Returns True if the signal state has changed meaningfully."""
    if prev is None:
        return True
    return (
        prev.regime_state != curr.regime_state
        or prev.risk_color != curr.risk_color
        or prev.confidence < config.CONFIDENCE_THRESHOLD_TRADE <= curr.confidence
        or curr.confidence < config.CONFIDENCE_THRESHOLD_TRADE <= prev.confidence
    )
