"""
Telegram alert delivery with deduplication.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

import config
from engine.classifier import SignalOutput
from engine.fvg import FVG
from engine.orderblocks import OrderBlock
from engine.liquidity import get_next_session_open

logger = logging.getLogger(__name__)

# ─── State Tracking ───
_last_alert_state: dict[str, dict] = {}  # key: f"{pair}_{timeframe}"

COLOR_EMOJI = {
    "green": "🟢",
    "yellow": "🟡",
    "red": "🔴",
}

REGIME_LABEL = {
    "accumulation": "ACCUMULATION",
    "distribution": "DISTRIBUTION",
    "short_squeeze": "SHORT SQUEEZE RISK",
    "long_liquidation": "LONG LIQUIDATION",
    "coiled_spring": "COILED SPRING",
    "deleveraging": "DELEVERAGING",
    "markup": "MARKUP (BULLISH)",
    "markdown": "MARKDOWN (BEARISH)",
    "transition": "TRANSITION",
}


def _format_price(price: float) -> str:
    if price >= 10000:
        return f"${price:,.0f}"
    elif price >= 100:
        return f"${price:,.2f}"
    else:
        return f"${price:.4f}"


def _format_fvg(fvg: Optional[FVG]) -> str:
    if fvg is None:
        return "None"
    return f"{_format_price(fvg.lower_bound)}-{_format_price(fvg.upper_bound)} ({fvg.status})"


def _format_ob(ob: Optional[OrderBlock]) -> str:
    if ob is None:
        return "None"
    overlap = " (FVG overlap ✓)" if ob.fvg_overlap else ""
    return f"{_format_price(ob.lower_bound)}-{_format_price(ob.upper_bound)}{overlap}"


def _calc_trade_levels(
    signal: SignalOutput,
    current_price: float,
    bullish_fvg: Optional[FVG],
    bearish_fvg: Optional[FVG],
    bullish_ob: Optional[OrderBlock],
    bearish_ob: Optional[OrderBlock],
) -> Optional[dict]:
    """Calculate entry, SL, TP1, TP2 from nearest zone if action bias is clear."""
    bias = signal.action_bias
    if bias == "long_bias":
        zone = bullish_fvg or bullish_ob
        if zone is None:
            return None
        entry = zone.upper_bound
        sl = zone.lower_bound * 0.999
        risk = abs(entry - sl)
        if risk <= 0:
            return None
        return {
            "side": "LONG",
            "entry": entry,
            "sl": sl,
            "tp1": entry + risk * 1.5,
            "tp2": entry + risk * 3.0,
            "rr": "1.5R / 3R",
        }
    elif bias == "short_bias":
        zone = bearish_fvg or bearish_ob
        if zone is None:
            return None
        entry = zone.lower_bound
        sl = zone.upper_bound * 1.001
        risk = abs(sl - entry)
        if risk <= 0:
            return None
        return {
            "side": "SHORT",
            "entry": entry,
            "sl": sl,
            "tp1": entry - risk * 1.5,
            "tp2": entry - risk * 3.0,
            "rr": "1.5R / 3R",
        }
    return None


def build_signal_alert(
    signal: SignalOutput,
    current_price: float,
    bullish_fvg: Optional[FVG] = None,
    bearish_fvg: Optional[FVG] = None,
    bullish_ob: Optional[OrderBlock] = None,
    bearish_ob: Optional[OrderBlock] = None,
    equal_highs: Optional[list[float]] = None,
    equal_lows: Optional[list[float]] = None,
    poc: Optional[float] = None,
    macro_regime: Optional[str] = None,
) -> str:
    emoji = COLOR_EMOJI.get(signal.risk_color, "⚪")
    pair_display = signal.pair.replace("USDT", "-USDT")
    regime_label = REGIME_LABEL.get(signal.regime_state, signal.regime_state.upper())

    # Session info
    session_info = get_next_session_open(signal.timestamp or int(time.time() * 1000))
    session_str = f"{session_info['session']} open in {session_info['minutes_until']}min" if session_info else "N/A"

    # Zone percentage from midpoint
    zone_pct = ""
    if signal.price_zone == "premium":
        zone_pct = "(above midpoint)"
    elif signal.price_zone == "discount":
        zone_pct = "(below midpoint)"

    lines = [
        f"{emoji} {pair_display} | {regime_label}",
        f"Trend: {signal.trend_state.title()} | HTF: {macro_regime.title() if macro_regime else 'N/A'}",
        f"Price: {_format_price(current_price)} | Zone: {signal.price_zone.title()} {zone_pct}",
        "",
        f"Regime: OI {signal.oi_change_percent:+.1%} | Vol {signal.volume_zscore:.1f}σ | Funding {signal.funding_rate:+.4%}",
        f"Taker: {signal.taker_ratio:.0%} buy | Confidence: {signal.confidence}/100",
        "",
        "Nearest levels:",
    ]

    if bullish_fvg:
        lines.append(f"  → Bullish FVG: {_format_fvg(bullish_fvg)}")
    if bullish_ob:
        lines.append(f"  → Bullish OB: {_format_ob(bullish_ob)}")
    if bearish_fvg:
        lines.append(f"  → Bearish FVG: {_format_fvg(bearish_fvg)}")
    if bearish_ob:
        lines.append(f"  → Bearish OB: {_format_ob(bearish_ob)}")
    if equal_highs:
        for lvl in equal_highs[:2]:
            lines.append(f"  → Equal highs: {_format_price(lvl)} (liquidity above)")
    if equal_lows:
        for lvl in equal_lows[:2]:
            lines.append(f"  → Equal lows: {_format_price(lvl)} (liquidity below)")
    if poc:
        lines.append(f"  → POC: {_format_price(poc)}")

    # Trade levels (only when actionable)
    trade = _calc_trade_levels(signal, current_price, bullish_fvg, bearish_fvg, bullish_ob, bearish_ob)
    if trade:
        lines.extend([
            "",
            f"📍 {trade['side']} Setup ({trade['rr']})",
            f"  Entry:  {_format_price(trade['entry'])}",
            f"  SL:     {_format_price(trade['sl'])}",
            f"  TP1:    {_format_price(trade['tp1'])}  (+50% close)",
            f"  TP2:    {_format_price(trade['tp2'])}  (remainder)",
        ])

    lines.extend([
        "",
        f"Session: {session_str}",
        f"Volatility: {'Low' if signal.atr_zscore < -0.5 else 'High' if signal.atr_zscore > 1.0 else 'Normal'} (ATR z-score: {signal.atr_zscore:.1f})",
        f"Risk posture: {signal.action_bias.replace('_', ' ').upper()}",
    ])

    if signal.data_age_seconds > config.STALE_DATA_THRESHOLD_SECONDS:
        lines.append("\n⚠️ STALE DATA — last update more than 15min ago")

    return "\n".join(lines)


def build_sweep_alert(sweep: dict, pair: str) -> str:
    emoji = "🔻" if sweep["type"] == "bear_sweep" else "🔺"
    sweep_type = "Bear sweep" if sweep["type"] == "bear_sweep" else "Bull sweep"
    return (
        f"{emoji} LIQUIDITY SWEEP — {pair}\n"
        f"Type: {sweep_type}\n"
        f"Level swept: {_format_price(sweep['level'])}\n"
        f"⚠️ Watch for reversal confirmation"
    )


def build_choch_alert(break_event: dict, pair: str, timeframe: str) -> str:
    direction = "BULLISH" if "bullish" in break_event.get("type", "") else "BEARISH"
    emoji = "↗️" if direction == "BULLISH" else "↘️"
    return (
        f"{emoji} CHoCH DETECTED — {pair} {timeframe.upper()}\n"
        f"Direction: {direction} Change of Character\n"
        f"Level broken: {_format_price(break_event.get('broken_level', 0))}\n"
        f"Trend shift: {break_event.get('trend_before', '?')} → {break_event.get('trend_after', '?')}\n"
        f"⚠️ Potential trend reversal — wait for confirmation"
    )


def build_fast_pulse_alert(pair: str, price_change_pct: float, current_price: float) -> str:
    return (
        f"🚨 FAST MOVE ALERT — {pair}\n"
        f"Price: {_format_price(current_price)}\n"
        f"Change (60s): {price_change_pct:+.2%}\n"
        f"⚠️ Potential cascade — check levels immediately"
    )


def build_stale_data_alert(pair: str, timeframe: str, age_minutes: float) -> str:
    return (
        f"⚠️ STALE DATA — {pair} {timeframe.upper()}\n"
        f"Last update: {age_minutes:.0f} minutes ago\n"
        f"Signals may be unreliable until data resumes."
    )


def should_alert(pair: str, timeframe: str, signal: SignalOutput) -> bool:
    """Deduplication: only alert on state changes."""
    key = f"{pair}_{timeframe}"
    prev = _last_alert_state.get(key)
    if prev is None:
        return True

    state_changed = (
        prev.get("regime_state") != signal.regime_state
        or prev.get("risk_color") != signal.risk_color
    )
    confidence_threshold_crossed = (
        (prev.get("confidence", 0) < config.CONFIDENCE_THRESHOLD_TRADE <= signal.confidence)
        or (signal.confidence < config.CONFIDENCE_THRESHOLD_TRADE <= prev.get("confidence", 0))
    )
    return state_changed or confidence_threshold_crossed


def record_alert_state(pair: str, timeframe: str, signal: SignalOutput) -> None:
    key = f"{pair}_{timeframe}"
    _last_alert_state[key] = {
        "regime_state": signal.regime_state,
        "risk_color": signal.risk_color,
        "confidence": signal.confidence,
        "timestamp": signal.timestamp,
    }


async def send_message(text: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured. Message not sent:\n%s", text)
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


async def send_signal_alert(
    signal: SignalOutput,
    current_price: float,
    bullish_fvg: Optional[FVG] = None,
    bearish_fvg: Optional[FVG] = None,
    bullish_ob: Optional[OrderBlock] = None,
    bearish_ob: Optional[OrderBlock] = None,
    equal_highs: Optional[list[float]] = None,
    equal_lows: Optional[list[float]] = None,
    poc: Optional[float] = None,
    macro_regime: Optional[str] = None,
    force: bool = False,
) -> bool:
    """Send signal alert with deduplication unless forced."""
    if not force and not should_alert(signal.pair, signal.timeframe, signal):
        return False

    text = build_signal_alert(
        signal=signal,
        current_price=current_price,
        bullish_fvg=bullish_fvg,
        bearish_fvg=bearish_fvg,
        bullish_ob=bullish_ob,
        bearish_ob=bearish_ob,
        equal_highs=equal_highs,
        equal_lows=equal_lows,
        poc=poc,
        macro_regime=macro_regime,
    )
    success = await send_message(text)
    if success:
        record_alert_state(signal.pair, signal.timeframe, signal)
    return success
