"""
Entry point — FastAPI app + dual-loop scheduler.
Run with: python main.py
"""

import asyncio
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from alerts import telegram
from api import routes
from core import backfill, fetcher, store
from demo.store import initialize_demo_db
from demo.trader import DemoTrader, set_live_state_ref
from engine import classifier, indicators, regime
from engine.fvg import detect_fvgs, get_nearest_fvg, update_fvg_status, fvg_to_store_dict
from engine.liquidity import detect_liquidity_sweeps
from engine.levels import estimate_liquidation_levels
from engine.orderblocks import detect_order_blocks, get_nearest_ob, update_ob_status, ob_to_store_dict
from engine.structure import detect_swing_points, detect_structure_breaks, detect_equal_levels, get_premium_discount_zone
from engine.volume_profile import approximate_volume_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App Lifecycle ───

@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler, demo_trader_aggressive, demo_trader_conservative

    logger.info("Starting Crypto Signal Engine...")

    # 1. Initialize DB (existing tables + demo tables)
    store.initialize_db()
    initialize_demo_db()
    logger.info("Database ready.")

    # Warn about missing API keys so operators know what's degraded
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram alerts will be disabled")
    if not config.COINGLASS_API_KEY:
        logger.warning(
            "COINGLASS_API_KEY not set — OI data unavailable; "
            "conservative trader will rarely generate green signals"
        )

    # 2. Initialize demo traders (aggressive = yellow+green, conservative = green only)
    demo_trader_aggressive = DemoTrader(mode="aggressive")
    demo_trader_aggressive.load_state()
    demo_trader_conservative = DemoTrader(mode="conservative")
    demo_trader_conservative.load_state()
    set_live_state_ref(live_state)
    routes.set_demo_traders(demo_trader_aggressive, demo_trader_conservative)
    logger.info(
        "Demo traders ready. Aggressive=$%.2f | Conservative=$%.2f",
        demo_trader_aggressive.equity, demo_trader_conservative.equity,
    )

    # 3. Backfill (blocking — need data before signals)
    logger.info("Running backfill (this may take a minute)...")
    await backfill.backfill_all_live()
    logger.info("Backfill complete.")

    # 4. Run initial analysis
    logger.info("Running initial analysis...")
    await full_analysis()
    await regime_task()

    # 5. Start scheduler
    # misfire_grace_time=None means never skip a trigger just because the event loop was busy.
    # coalesce=True means if multiple runs were missed, run just once (not N times).
    scheduler = AsyncIOScheduler(job_defaults={"misfire_grace_time": None, "coalesce": True})
    scheduler.add_job(fast_pulse, "interval", seconds=config.FAST_PULSE_INTERVAL_SECONDS, id="fast_pulse")
    scheduler.add_job(full_analysis, "interval", seconds=config.FULL_ANALYSIS_INTERVAL_SECONDS, id="full_analysis")
    scheduler.add_job(hourly_task, "interval", seconds=config.HOURLY_TASK_INTERVAL_SECONDS, id="hourly")
    scheduler.add_job(regime_task, "interval", seconds=config.HTF_REGIME_INTERVAL_SECONDS, id="regime")
    scheduler.add_job(daily_summary, "cron", hour=9, minute=0, id="daily_summary")
    scheduler.start()

    routes.set_scheduler_status({
        "running": True,
        "jobs": ["fast_pulse", "full_analysis", "hourly", "regime", "daily_summary"],
        "started_at": int(time.time()),
    })
    logger.info("Scheduler started. System ready.")
    logger.info("API docs: http://localhost:8001/docs")

    yield  # app is running

    # Shutdown
    logger.info("Shutting down...")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=True)
    await fetcher.close_client()
    await fetcher.close_cg_client()
    logger.info("Shutdown complete.")


# ─── FastAPI App ───
app = FastAPI(title="Crypto Signal Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "https://hobbithobby.quest",
        "https://www.hobbithobby.quest",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(routes.router)

# ─── Live State ───
# Shared mutable dict — one entry per pair
live_state: dict[str, dict] = {}
scheduler: Optional[AsyncIOScheduler] = None
demo_trader_aggressive: Optional[DemoTrader] = None
demo_trader_conservative: Optional[DemoTrader] = None

# ─── Previous price for fast pulse comparison ───
_prev_prices: dict[str, float] = {}

# ─── Track in-flight backfills to prevent duplicates competing for rate budget ───
_backfill_running: dict[str, bool] = {}


# ════════════════════════════════════════
# FAST PULSE — runs every 60 seconds
# ════════════════════════════════════════

async def fast_pulse() -> None:
    """Fetch latest price + taker ratio. Fire alert on sudden large moves — runs concurrently."""
    async def _pulse(pair: str) -> None:
        try:
            price_data = await fetcher.fetch_latest_price(pair)
            if not price_data:
                return

            current_price = price_data["price"]
            prev_price = _prev_prices.get(pair)

            if prev_price and prev_price > 0:
                change = (current_price - prev_price) / prev_price
                if abs(change) >= 0.03:
                    logger.warning("Fast pulse: %s moved %.2f%% in 60s", pair, change * 100)
                    await telegram.send_message(
                        f"\ud83d\udea8 <b>FAST MOVE</b> \u2014 {pair}\n"
                        f"Price: ${current_price:,.2f}\n"
                        f"Change (60s): {change:+.2%}"
                    )

            _prev_prices[pair] = current_price
            if pair not in live_state:
                live_state[pair] = {}
            live_state[pair]["last_price"] = current_price
            live_state[pair]["last_fast_pulse"] = time.time()

        except Exception as e:
            logger.error("Fast pulse error for %s: %s", pair, e)

    await asyncio.gather(*[_pulse(pair) for pair in config.PAIRS])


# ════════════════════════════════════════
# FULL ANALYSIS — runs every 300 seconds
# ════════════════════════════════════════

async def full_analysis() -> None:
    """Complete signal generation pipeline for all pairs — runs concurrently."""
    cycle_start = time.monotonic()

    async def _safe(pair: str, tf: str) -> None:
        try:
            await _run_full_analysis(pair, tf)
        except Exception as e:
            logger.error("Full analysis error for %s %s: %s", pair, tf, e, exc_info=True)

    await asyncio.gather(*[
        _safe(pair, tf)
        for pair in config.PAIRS
        for tf in config.TIMEFRAMES
    ])

    # One equity snapshot per full_analysis cycle (not per pair)
    ts_ms = int(time.time() * 1000)
    for _trader in (demo_trader_aggressive, demo_trader_conservative):
        if _trader is not None:
            _trader.record_equity_snapshot(ts_ms)

    elapsed = time.monotonic() - cycle_start
    logger.info("Full analysis cycle completed in %.1fs", elapsed)
    if elapsed > config.FULL_ANALYSIS_INTERVAL_SECONDS * 0.8:
        logger.warning(
            "Analysis cycle (%.1fs) approaching interval (%ds) — risk of skipped runs",
            elapsed, config.FULL_ANALYSIS_INTERVAL_SECONDS,
        )


async def _run_full_analysis(pair: str, timeframe: str) -> None:
    now_ms = int(time.time() * 1000)

    # Fetch latest candle with enriched data
    snapshot = await fetcher.fetch_full_candle_snapshot(pair, timeframe)
    if snapshot is None:
        logger.warning("No snapshot for %s %s", pair, timeframe)
        return

    # Write to DB
    store.upsert_candles([snapshot])

    # Check for and fill any gaps (fire-and-forget, but limit to 1 concurrent backfill)
    gaps = store.detect_and_log_gaps(pair, timeframe)
    if gaps and not _backfill_running.get(f"{pair}_{timeframe}"):
        logger.info("Gaps detected for %s %s — triggering backfill", pair, timeframe)
        _backfill_running[f"{pair}_{timeframe}"] = True

        async def _guarded_backfill(p: str, tf: str) -> None:
            try:
                await backfill.backfill_pair(p, tf, config.LIVE_BACKFILL_DAYS)
            finally:
                _backfill_running.pop(f"{p}_{tf}", None)

        asyncio.create_task(_guarded_backfill(pair, timeframe))

    # Load rolling window of candles for calculations
    candles = store.fetch_candles(pair, timeframe, limit=200)
    if len(candles) < 30:
        logger.warning("Insufficient candles for %s %s (%d)", pair, timeframe, len(candles))
        return

    # Check data freshness
    latest_ts = candles[-1]["timestamp"]
    data_age_s = (now_ms - latest_ts) / 1000.0

    # ─── Compute Indicators ───
    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    atr_vals = indicators.atr(highs, lows, closes, period=14)
    vwap_vals = indicators.vwap(highs, lows, closes, volumes)
    vol_zscore_arr = indicators.rolling_zscore(volumes, config.VOLUME_ZSCORE_LOOKBACK)
    atr_zscore_arr = indicators.rolling_zscore(atr_vals, config.ATR_ZSCORE_LOOKBACK)
    vwap_dev_arr = indicators.vwap_deviation(closes, vwap_vals, period=50)

    current_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
    current_vol_zscore = float(vol_zscore_arr[-1]) if not np.isnan(vol_zscore_arr[-1]) else 0.0
    current_atr_zscore = float(atr_zscore_arr[-1]) if not np.isnan(atr_zscore_arr[-1]) else 0.0
    current_vwap_dev = float(vwap_dev_arr[-1]) if not np.isnan(vwap_dev_arr[-1]) else 0.0

    current_price = float(closes[-1])
    prev_close = float(closes[-2]) if len(closes) >= 2 else current_price
    price_change = (current_price - prev_close) / prev_close if prev_close > 0 else 0.0

    # OI change — None means no OI data available (triggers volume-only fallback in classifier)
    oi_values = [c.get("open_interest") for c in candles if c.get("open_interest") is not None]
    oi_change: Optional[float] = None
    lb = config.OI_CHANGE_LOOKBACK
    if len(oi_values) > lb and oi_values[-1 - lb] > 0:
        oi_change = (oi_values[-1] - oi_values[-1 - lb]) / oi_values[-1 - lb]
    elif len(oi_values) >= 2 and oi_values[-2] > 0:
        oi_change = (oi_values[-1] - oi_values[-2]) / oi_values[-2]

    # Latest funding / ratios
    funding_rate = snapshot.get("funding_rate") or 0.0
    taker_ratio = snapshot.get("taker_buy_sell_ratio") or 0.5
    long_short_ratio = snapshot.get("long_short_ratio") or 1.0

    # ─── Market Structure ───
    swings = detect_swing_points(candles, lookback=config.SWING_LOOKBACK)
    breaks, trend_state = detect_structure_breaks(swings)
    equal_levels = detect_equal_levels(swings, config.EQUAL_LEVEL_TOLERANCE)
    price_zone = get_premium_discount_zone(swings, current_price)

    # ─── FVGs ───
    fvgs = detect_fvgs(candles, min_gap_percent=config.FVG_MIN_GAP_PERCENT)
    # Update fill status
    for fvg in fvgs:
        fvg_list = [fvg]
        update_fvg_status(fvg_list, candles[-1])

    # Persist new FVGs
    for fvg in fvgs[-20:]:  # Keep the most recent
        store.upsert_fvg(fvg_to_store_dict(fvg))

    nearest_bullish_fvg = get_nearest_fvg(fvgs, current_price, "bullish")
    nearest_bearish_fvg = get_nearest_fvg(fvgs, current_price, "bearish")

    # ─── Order Blocks ───
    obs = detect_order_blocks(candles, fvgs, atr_values=atr_vals)
    for ob in obs:
        ob_list = [ob]
        update_ob_status(ob_list, candles[-1])

    for ob in obs[-20:]:
        store.upsert_order_block(ob_to_store_dict(ob))

    nearest_bullish_ob = get_nearest_ob(obs, current_price, "bullish")
    nearest_bearish_ob = get_nearest_ob(obs, current_price, "bearish")

    # ─── Volume Profile ───
    vp = approximate_volume_profile(candles, num_bins=50, lookback=100)
    poc = vp.get("poc")

    # ─── Classify Signal ───
    signal = classifier.classify(
        price_change=price_change,
        oi_change=oi_change,
        volume_zscore=current_vol_zscore,
        funding_rate=funding_rate,
        taker_ratio=taker_ratio,
        long_short_ratio=long_short_ratio,
        trend_state=trend_state,
        vwap_deviation=current_vwap_dev,
        atr_zscore=current_atr_zscore,
        pair=pair,
        timeframe=timeframe,
        timestamp=now_ms,
        price_zone=price_zone,
        current_price=current_price,
        atr=current_atr,
        data_age_seconds=data_age_s,
    )

    # ─── Persist Signal ───
    # Build reasoning summary for metadata
    oi_pct = (oi_change * 100) if oi_change is not None else 0.0
    oi_note = "OI data unavailable — volume fallback used" if oi_change is None else None
    reasoning = {
        "regime_factors": [
            {"factor": "volume_zscore", "value": round(current_vol_zscore, 3),
             "threshold": 1.5, "direction": "above" if current_vol_zscore >= 1.5 else "below",
             "impact": "bullish" if current_vol_zscore >= 2.0 else "neutral"},
            {"factor": "oi_change_pct", "value": round(oi_pct, 3),
             "threshold": 1.5, "direction": "above" if oi_pct >= 1.5 else "below",
             "impact": "bullish" if oi_pct >= 1.5 else "neutral",
             "note": oi_note},
            {"factor": "funding_rate", "value": funding_rate,
             "threshold": config.FUNDING_RATE_EXTREME_POSITIVE,
             "direction": "above" if abs(funding_rate) >= config.FUNDING_RATE_EXTREME_POSITIVE else "below",
             "impact": "extreme" if abs(funding_rate) >= config.FUNDING_RATE_EXTREME_POSITIVE else "neutral"},
            {"factor": "taker_ratio", "value": taker_ratio,
             "threshold": 0.55, "direction": "above" if taker_ratio >= 0.55 else "below",
             "impact": "bullish" if taker_ratio >= 0.55 else "neutral"},
        ],
        "confidence_breakdown": {
            "base_score": 50,
            "volume_bonus": 20 if current_vol_zscore >= 2.0 else 0,
            "oi_bonus": 15 if oi_change is not None and abs(oi_change) >= 0.05 else 0,
            "funding_bonus": 10 if abs(funding_rate) >= config.FUNDING_RATE_EXTREME_POSITIVE else 0,
            "taker_bonus": 10 if taker_ratio >= 0.55 else 0,
            "final": signal.confidence,
        },
        "entry_conditions": {
            "in_fvg": nearest_bullish_fvg is not None or nearest_bearish_fvg is not None,
            "in_ob": nearest_bullish_ob is not None or nearest_bearish_ob is not None,
            "price_zone": price_zone,
            "trend_state": trend_state,
            "action_bias": signal.action_bias,
        },
        "summary": (
            f"{signal.regime_state} regime | conf={signal.confidence} | "
            f"vol_z={round(current_vol_zscore, 2)} | "
            + ("OI data unavailable — volume fallback" if oi_change is None else f"oi_chg={round(oi_pct, 2)}%")
        ),
    }

    signal_row = {
        "pair": pair,
        "timeframe": timeframe,
        "timestamp": now_ms,
        "regime_state": signal.regime_state,
        "risk_color": signal.risk_color,
        "confidence": signal.confidence,
        "trend_state": trend_state,
        "price_zone": price_zone,
        "nearest_bullish_fvg": json.dumps(nearest_bullish_fvg.to_dict()) if nearest_bullish_fvg else None,
        "nearest_bearish_fvg": json.dumps(nearest_bearish_fvg.to_dict()) if nearest_bearish_fvg else None,
        "nearest_bullish_ob": json.dumps(nearest_bullish_ob.to_dict()) if nearest_bullish_ob else None,
        "nearest_bearish_ob": json.dumps(nearest_bearish_ob.to_dict()) if nearest_bearish_ob else None,
        "equal_highs": json.dumps(equal_levels.get("equal_highs", [])),
        "equal_lows": json.dumps(equal_levels.get("equal_lows", [])),
        "volume_zscore": current_vol_zscore,
        "oi_change_percent": oi_change if oi_change is not None else 0.0,
        "funding_rate": funding_rate,
        "taker_ratio": taker_ratio,
        "atr": current_atr,
        "vwap_deviation": current_vwap_dev,
        "metadata": json.dumps({
            "poc": poc,
            "macro_regime": live_state.get(pair, {}).get("macro_regime"),
            "action_bias": signal.action_bias,
            "reasoning": reasoning,
        }),
    }
    store.upsert_signal(signal_row)

    # ─── Demo Trading (both modes) ───
    for _trader in (demo_trader_aggressive, demo_trader_conservative):
        if _trader is not None:
            await _trader.on_signal(
                signal=signal,
                pair=pair,
                timeframe=timeframe,
                current_price=current_price,
                current_candle=candles[-1],
                bullish_fvg=nearest_bullish_fvg,
                bearish_fvg=nearest_bearish_fvg,
                bullish_ob=nearest_bullish_ob,
                bearish_ob=nearest_bearish_ob,
                timestamp_ms=now_ms,
            )

    # ─── Liquidity Sweeps (log only — no Telegram spam) ───
    sweeps = detect_liquidity_sweeps(candles[-50:], swings[-20:])
    new_sweeps = [s for s in sweeps if s["timestamp"] >= now_ms - 600_000]
    for sweep in new_sweeps:
        logger.info("Liquidity sweep: %s %s @ %s", pair, sweep["type"], sweep["level"])

    # ─── CHoCH (log only — included in daily summary) ───
    recent_choch = [b for b in breaks if b.type.startswith("choch") and b.timestamp >= now_ms - 600_000]
    for choch in recent_choch:
        logger.info("CHoCH: %s %s %s → %s", pair, timeframe, choch.trend_before, choch.trend_after)

    # ─── Update Live State ───
    if pair not in live_state:
        live_state[pair] = {}
    live_state[pair].update({
        "last_update_ts": now_ms,
        "last_price": current_price,
        "last_signal": signal_row,
    })
    routes.set_live_state(live_state)

    # NOTE: Telegram trade alerts are now sent from demo/trader.py on actual entry/exit.
    # No per-signal alerts here — reduces noise.

    logger.info(
        "%s %s | %s | %s | conf=%d | price=%s",
        pair, timeframe, signal.regime_state, signal.risk_color, signal.confidence,
        _format_price(current_price),
    )


def _format_price(price: float) -> str:
    return f"${price:,.2f}" if price >= 100 else f"${price:.4f}"


# ════════════════════════════════════════
# HOURLY — liquidation level recalc
# ════════════════════════════════════════

async def hourly_task() -> None:
    """Recalculate liquidation levels and update FVG/OB statuses — runs concurrently."""
    async def _hourly(pair: str) -> None:
        try:
            candles = store.fetch_candles(pair, "1h", limit=50)
            if not candles:
                return

            current_price = candles[-1]["close"]
            oi_vals = [c.get("open_interest") for c in candles if c.get("open_interest")]

            if len(oi_vals) >= 2:
                oi_changes = [
                    {"price": candles[-(len(oi_vals) - i)]["close"],
                     "oi_change_percent": (oi_vals[i] - oi_vals[i-1]) / oi_vals[i-1] if oi_vals[i-1] > 0 else 0}
                    for i in range(1, len(oi_vals))
                ]
                liq_levels = estimate_liquidation_levels(
                    current_price=current_price,
                    open_interest=oi_vals[-1],
                    recent_oi_changes=oi_changes,
                )
                if pair not in live_state:
                    live_state[pair] = {}
                live_state[pair]["liq_levels"] = liq_levels

            logger.info("Hourly task complete for %s", pair)
        except Exception as e:
            logger.error("Hourly task error for %s: %s", pair, e)

    await asyncio.gather(*[_hourly(pair) for pair in config.PAIRS])


# ════════════════════════════════════════
# 4H REGIME — macro context
# ════════════════════════════════════════

async def regime_task() -> None:
    """Run macro regime analysis on 4H data — runs concurrently."""
    async def _regime(pair: str) -> None:
        try:
            candles_4h = store.fetch_candles(pair, "4h", limit=60)
            if len(candles_4h) < 10:
                return

            oi_hist = [c.get("open_interest") or 0.0 for c in candles_4h]
            funding_hist = [c.get("funding_rate") or 0.0 for c in candles_4h]
            vol_hist = [c.get("volume") or 0.0 for c in candles_4h]

            macro = regime.classify_macro_regime(
                candles_4h=candles_4h,
                oi_history=oi_hist,
                funding_history=funding_hist,
                volume_history=vol_hist,
            )

            if pair not in live_state:
                live_state[pair] = {}
            prev_macro = live_state[pair].get("macro_regime")
            live_state[pair]["macro_regime"] = macro
            live_state[pair]["last_regime_update"] = int(time.time() * 1000)

            if prev_macro != macro:
                logger.info("4H regime change for %s: %s → %s", pair, prev_macro, macro)

            logger.info("Regime for %s: %s", pair, macro)
        except Exception as e:
            logger.error("Regime task error for %s: %s", pair, e)

    await asyncio.gather(*[_regime(pair) for pair in config.PAIRS])


# ════════════════════════════════════════
# DAILY SUMMARY — runs at 9:00 AM UTC
# ════════════════════════════════════════

async def daily_summary() -> None:
    """Build and send a per-coin briefing via Telegram."""
    try:
        pair_data = []
        for pair in config.PAIRS:
            # Get latest 1h signal from live_state
            state = live_state.get(pair, {})
            last_signal = state.get("last_signal", {})
            price = state.get("last_price", 0.0)

            pair_data.append({
                "pair": pair,
                "price": price,
                "regime": last_signal.get("regime_state", "unknown"),
                "risk_color": last_signal.get("risk_color", "yellow"),
                "confidence": last_signal.get("confidence", 0),
                "trend": last_signal.get("trend_state", "unknown"),
                "action_bias": json.loads(last_signal.get("metadata", "{}")).get("action_bias", "stay_flat"),
                "oi_change": last_signal.get("oi_change_percent", 0.0),
                "vol_zscore": last_signal.get("volume_zscore", 0.0),
                "funding_rate": last_signal.get("funding_rate", 0.0),
                "macro_regime": state.get("macro_regime"),
            })

        agg_equity = demo_trader_aggressive.equity if demo_trader_aggressive else config.INITIAL_CAPITAL
        con_equity = demo_trader_conservative.equity if demo_trader_conservative else config.INITIAL_CAPITAL
        agg_open = len(demo_trader_aggressive.open_positions) if demo_trader_aggressive else 0
        con_open = len(demo_trader_conservative.open_positions) if demo_trader_conservative else 0

        text = telegram.build_daily_summary(
            pair_data=pair_data,
            demo_aggressive_equity=agg_equity,
            demo_conservative_equity=con_equity,
            aggressive_open=agg_open,
            conservative_open=con_open,
        )
        await telegram.send_message(text)
        logger.info("Daily summary sent via Telegram.")
    except Exception as e:
        logger.error("Daily summary error: %s", e, exc_info=True)


# ─── Signal Handlers ───

def _handle_signal(signum, _frame):
    logger.info("Received signal %d, shutting down gracefully...", signum)
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
