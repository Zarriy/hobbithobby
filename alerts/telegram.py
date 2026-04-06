"""
Telegram alert delivery.
- Immediate alerts ONLY when a trade is actually taken by the demo trader.
- Daily 9 AM summary with per-coin analysis.
"""

import logging
import time
from typing import Optional

import httpx

import config
from engine.classifier import SignalOutput

logger = logging.getLogger(__name__)

COLOR_EMOJI = {
    "green": "\u2705",
    "yellow": "\u26a0\ufe0f",
    "red": "\ud83d\udd34",
}

BIAS_ARROW = {
    "long_bias": "\u2b06\ufe0f LONG",
    "short_bias": "\u2b07\ufe0f SHORT",
    "stay_flat": "\u23f8\ufe0f FLAT",
    "reduce_exposure": "\ud83d\udea8 REDUCE",
}


def _format_price(price: float) -> str:
    if price >= 10000:
        return f"${price:,.0f}"
    elif price >= 100:
        return f"${price:,.2f}"
    else:
        return f"${price:.4f}"


# ─────────────────────────────────────────────
# Trade Entry Alert (sent immediately)
# ─────────────────────────────────────────────

def build_trade_entry_alert(
    pair: str,
    timeframe: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    tp1: float,
    confidence: int,
    regime: str,
    risk_color: str,
    mode: str,
    leverage: float,
    size_usd: float,
    tp2: Optional[float] = None,
) -> str:
    emoji = "\u2b06\ufe0f" if side == "long" else "\u2b07\ufe0f"
    color = COLOR_EMOJI.get(risk_color, "\u26aa")
    pair_display = pair.replace("USDT", "/USDT")

    risk_dist = abs(entry_price - stop_loss)
    risk_pct = (risk_dist / entry_price) * 100 if entry_price > 0 else 0

    lines = [
        f"{emoji} <b>NEW TRADE \u2014 {side.upper()}</b>",
        f"",
        f"<b>{pair_display}</b> | {timeframe} | {mode.upper()}",
        f"",
        f"Entry:  <code>{_format_price(entry_price)}</code>",
        f"SL:     <code>{_format_price(stop_loss)}</code>  ({risk_pct:.2f}% risk)",
        f"TP1:    <code>{_format_price(tp1)}</code>  (1.5R \u2014 close 50%)",
    ]
    if tp2:
        lines.append(
            f"TP2:    <code>{_format_price(tp2)}</code>  (3R \u2014 remainder)"
        )

    lines.extend([
        f"",
        f"{color} {regime.replace('_', ' ').title()} | Conf: <b>{confidence}/100</b>",
        f"Leverage: {int(leverage)}x | Size: {_format_price(size_usd)}",
    ])

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Trade Exit Alert (sent immediately)
# ─────────────────────────────────────────────

def build_trade_exit_alert(
    pair: str,
    side: str,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    net_pnl_usd: float,
    pnl_pct: float,
    hold_hours: float,
    mode: str,
    equity: float,
) -> str:
    pnl_emoji = "\u2705" if net_pnl_usd >= 0 else "\u274c"
    pair_display = pair.replace("USDT", "/USDT")

    reason_labels = {
        "tp1": "TP1 Hit (partial close)",
        "tp2": "TP2 Hit (full close)",
        "stop_loss": "Stop Loss",
        "regime_red_exit": "Regime turned RED",
        "time_exit": "Max hold time (48h)",
    }
    reason_label = reason_labels.get(exit_reason, exit_reason)

    lines = [
        f"{pnl_emoji} <b>TRADE CLOSED \u2014 {side.upper()}</b>",
        f"",
        f"<b>{pair_display}</b> | {mode.upper()}",
        f"",
        f"Entry:  <code>{_format_price(entry_price)}</code>",
        f"Exit:   <code>{_format_price(exit_price)}</code>",
        f"Reason: {reason_label}",
        f"",
        f"P&L: <b>{'+' if net_pnl_usd >= 0 else ''}{_format_price(net_pnl_usd)}</b> ({pnl_pct:+.2%})",
        f"Hold: {hold_hours:.1f}h | Equity: {_format_price(equity)}",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Daily 9 AM Summary
# ─────────────────────────────────────────────

def build_daily_summary(
    pair_data: list[dict],
    demo_aggressive_equity: float,
    demo_conservative_equity: float,
    aggressive_open: int,
    conservative_open: int,
) -> str:
    """
    pair_data: list of dicts with keys:
        pair, price, regime, risk_color, confidence, trend, action_bias,
        oi_change, vol_zscore, funding_rate, macro_regime
    """
    lines = [
        f"\ud83d\udcca <b>DAILY BRIEFING \u2014 {time.strftime('%b %d, %Y')}</b>",
        f"",
    ]

    for d in pair_data:
        pair_display = d["pair"].replace("USDT", "/USDT")
        color = COLOR_EMOJI.get(d["risk_color"], "\u26aa")
        bias = BIAS_ARROW.get(d["action_bias"], d["action_bias"])
        macro = d.get("macro_regime", "N/A")
        if macro:
            macro = macro.replace("_", " ").title()

        lines.extend([
            f"<b>{pair_display}</b> \u2014 {_format_price(d['price'])}",
            f"  {color} {d['regime'].replace('_', ' ').title()} | {bias}",
            f"  Trend: {d['trend'].title()} | Conf: {d['confidence']}/100",
            f"  OI: {d['oi_change']:+.1%} | Vol: {d['vol_zscore']:.1f}\u03c3 | Fund: {d['funding_rate']:+.4%}",
            f"  HTF: {macro}",
            f"",
        ])

    lines.extend([
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        f"\ud83d\udcb0 <b>Paper Trading</b>",
        f"  Aggressive: {_format_price(demo_aggressive_equity)} ({aggressive_open} open)",
        f"  Conservative: {_format_price(demo_conservative_equity)} ({conservative_open} open)",
    ])

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Send message
# ─────────────────────────────────────────────

async def send_message(text: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping message")
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
