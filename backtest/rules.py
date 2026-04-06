"""
Mechanical trade rules for backtesting.
No discretion. If conditions are not met, no trade is taken.
"""

from dataclasses import dataclass
from typing import Optional

import config
from engine.classifier import SignalOutput
from engine.fvg import FVG
from engine.orderblocks import OrderBlock


@dataclass
class TradeRule:
    # Entry conditions
    regime_is_green: bool = True
    confidence_above: int = config.CONFIDENCE_THRESHOLD_TRADE
    trend_confirmed: bool = True
    price_in_zone: bool = True
    level_touched: bool = True

    # Entry
    entry_at: str = "zone_midpoint"

    # Exit
    stop_loss: str = "below_zone"       # "below_zone" for longs, "above_zone" for shorts
    take_profit_1_rr: float = 1.5        # 1.5R — close 50%
    take_profit_2: str = "next_opposing_level"
    regime_exit: bool = True             # Exit if regime → RED
    max_hold_hours: int = config.MAX_HOLD_HOURS

    # Sizing
    risk_percent_base: float = config.RISK_PER_TRADE_PERCENT
    confidence_70_80_multiplier: float = 0.5
    confidence_80_90_multiplier: float = 1.0
    confidence_90_plus_multiplier: float = 1.5
    max_concurrent: int = config.MAX_CONCURRENT_POSITIONS


def _get_size_multiplier(confidence: int, rules: TradeRule) -> float:
    if confidence >= 90:
        return rules.confidence_90_plus_multiplier
    elif confidence >= 80:
        return rules.confidence_80_90_multiplier
    elif confidence >= 70:
        return rules.confidence_70_80_multiplier
    return 0.0


def check_entry(
    signal: SignalOutput,
    bullish_fvg: Optional[FVG],
    bearish_fvg: Optional[FVG],
    bullish_ob: Optional[OrderBlock],
    bearish_ob: Optional[OrderBlock],
    current_price: float,
    open_positions: int,
    rules: TradeRule,
    current_ts: int = 0,
    candle_low: Optional[float] = None,
    candle_high: Optional[float] = None,
) -> Optional[dict]:
    """
    Returns a trade entry dict if ALL conditions are met, None otherwise.
    {side, entry_price, stop_loss, tp1, tp2_target, size_multiplier, reason, entry_zone}
    """
    # Max concurrent positions
    if open_positions >= rules.max_concurrent:
        return None

    # Confidence gate
    if signal.confidence < rules.confidence_above:
        return None

    # Risk color gate
    if rules.regime_is_green and signal.risk_color != "green":
        return None

    # Determine trade direction from signal bias
    if signal.action_bias == "long_bias":
        side = "long"
    elif signal.action_bias == "short_bias":
        side = "short"
    else:
        return None  # stay_flat or reduce_exposure

    # Trend confirmation
    if rules.trend_confirmed:
        if side == "long" and signal.trend_state not in ("uptrend", "transition", "ranging"):
            return None
        if side == "short" and signal.trend_state not in ("downtrend", "transition", "ranging"):
            return None

    # Price zone check
    if rules.price_in_zone:
        if side == "long" and signal.price_zone not in ("discount", "equilibrium"):
            return None
        if side == "short" and signal.price_zone not in ("premium", "equilibrium"):
            return None

    # Level touch — must have an active FVG or OB near price
    entry_zone = None
    entry_price = current_price  # default

    if side == "long":
        # Look for a bullish FVG or OB that price has touched/entered
        level = bullish_fvg or bullish_ob
        if rules.level_touched and level is None:
            return None
        if level is not None:
            # Use candle low (wick) if available — price wicking into zone counts as touch
            probe_price = candle_low if candle_low is not None else current_price
            if probe_price <= level.upper_bound * 1.01:  # within 1.0% of zone top
                # Enter at zone upper_bound if wick touched it, else close
                if probe_price <= level.upper_bound:
                    entry_price = level.upper_bound  # wick entered zone — limit at top
                elif rules.entry_at == "zone_midpoint":
                    entry_price = (level.upper_bound + level.lower_bound) / 2.0
                else:
                    entry_price = level.upper_bound
                entry_zone = {
                    "type": "fvg" if isinstance(level, FVG) else "ob",
                    "upper": level.upper_bound,
                    "lower": level.lower_bound,
                    "has_fvg_overlap": getattr(level, "fvg_overlap", False),
                }
                sl_price = level.lower_bound * 0.999  # Just below zone
            else:
                return None  # Not touching zone
        else:
            return None

    else:  # short
        level = bearish_fvg or bearish_ob
        if rules.level_touched and level is None:
            return None
        if level is not None:
            probe_price = candle_high if candle_high is not None else current_price
            if probe_price >= level.lower_bound * 0.99:  # within 1.0% of zone bottom
                if probe_price >= level.lower_bound:
                    entry_price = level.lower_bound  # wick entered zone — limit at bottom
                elif rules.entry_at == "zone_midpoint":
                    entry_price = (level.upper_bound + level.lower_bound) / 2.0
                else:
                    entry_price = level.lower_bound
                entry_zone = {
                    "type": "fvg" if isinstance(level, FVG) else "ob",
                    "upper": level.upper_bound,
                    "lower": level.lower_bound,
                    "has_fvg_overlap": getattr(level, "fvg_overlap", False),
                }
                sl_price = level.upper_bound * 1.001  # Just above zone
            else:
                return None
        else:
            return None

    # Risk distance
    risk_distance = abs(entry_price - sl_price)
    if risk_distance < entry_price * 0.0001:  # Minimum 0.01% risk
        return None

    # TP1 at 1.5R
    if side == "long":
        tp1_price = entry_price + risk_distance * rules.take_profit_1_rr
    else:
        tp1_price = entry_price - risk_distance * rules.take_profit_1_rr

    size_multiplier = _get_size_multiplier(signal.confidence, rules)

    return {
        "side": side,
        "entry_price": entry_price,
        "stop_loss": sl_price,
        "tp1": tp1_price,
        "tp2_target": None,  # Set dynamically in simulator
        "size_multiplier": size_multiplier,
        "risk_distance": risk_distance,
        "reason": f"{signal.regime_state} | conf={signal.confidence} | zone={entry_zone['type'] if entry_zone else 'none'}",
        "entry_zone": entry_zone,
        "entry_ts": current_ts,
        "regime_at_entry": signal.regime_state,
        "risk_color_at_entry": signal.risk_color,
    }


def check_exit(
    position: dict,
    current_candle: dict,
    current_signal: SignalOutput,
    rules: TradeRule,
) -> Optional[dict]:
    """
    Returns exit dict if any exit condition is met, None otherwise.
    {exit_price, exit_reason, pnl_percent}

    CRITICAL: If both SL and TP could trigger in same candle, SL wins (conservative).
    """
    side = position["side"]
    entry_price = position["entry_price"]
    sl = position["stop_loss"]
    tp1 = position["tp1"]
    tp2 = position.get("tp2_target")
    entry_ts = position.get("entry_ts", 0)
    candle_ts = current_candle["timestamp"]

    high = current_candle["high"]
    low = current_candle["low"]
    close = current_candle["close"]

    # Time-based exit
    hours_held = (candle_ts - entry_ts) / 3_600_000
    if hours_held >= rules.max_hold_hours:
        return _make_exit(close, "time_exit", entry_price, side)

    # Regime exit
    if rules.regime_exit and current_signal.risk_color == "red":
        return _make_exit(close, "regime_red_exit", entry_price, side)

    if side == "long":
        # Check SL first (conservative)
        if low <= sl:
            return _make_exit(sl, "stop_loss", entry_price, side)
        # Check TP2
        if tp2 and high >= tp2:
            return _make_exit(tp2, "tp2", entry_price, side)
        # Check TP1 (partial — handled by simulator, here we exit full remaining)
        if not position.get("tp1_hit") and high >= tp1:
            return _make_exit(tp1, "tp1", entry_price, side)

    else:  # short
        # Check SL first
        if high >= sl:
            return _make_exit(sl, "stop_loss", entry_price, side)
        # Check TP2
        if tp2 and low <= tp2:
            return _make_exit(tp2, "tp2", entry_price, side)
        # Check TP1
        if not position.get("tp1_hit") and low <= tp1:
            return _make_exit(tp1, "tp1", entry_price, side)

    return None


def _make_exit(exit_price: float, reason: str, entry_price: float, side: str) -> dict:
    if side == "long":
        pnl_pct = (exit_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - exit_price) / entry_price
    return {
        "exit_price": exit_price,
        "exit_reason": reason,
        "pnl_percent": pnl_pct,
    }
