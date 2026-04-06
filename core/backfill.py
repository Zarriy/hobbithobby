"""
Historical data bootstrap.
Runs synchronously at startup to ensure rolling indicators have enough data.
"""

import asyncio
import logging
import time
from typing import Optional

import config
from core import fetcher, store

logger = logging.getLogger(__name__)

MS_PER_DAY = 86_400_000
MS_PER_MONTH = 30 * MS_PER_DAY

TIMEFRAME_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


async def _download_range(
    pair: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> int:
    """Download candles in paginated chunks. Returns total candles written."""
    tf_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
    batch_size = 500
    total = 0
    cursor = start_ms

    # Fetch OI history once per range for enrichment.
    # CoinGlass HOBBYIST plan supports 4h, 6h, 8h, 12h, 1d, 1w — NOT 1h.
    # For 1h candles we always use Binance OI (~20 days history).
    _CG_SUPPORTED_INTERVALS = {"4h", "6h", "8h", "12h", "1d", "1w"}
    use_coinglass = config.COINGLASS_API_KEY and timeframe in _CG_SUPPORTED_INTERVALS
    HR_MS = 3_600_000

    oi_map: dict[int, float] = {}
    oi_bucket_ms = tf_ms if use_coinglass else HR_MS  # bucket size matches OI source

    if use_coinglass:
        logger.info("Fetching OI from CoinGlass (%s interval) for %s", timeframe, pair)
        cg_cursor = start_ms
        while cg_cursor < end_ms:
            oi_hist = await fetcher.fetch_coinglass_oi_history(
                pair, interval=timeframe, start_time=cg_cursor, end_time=end_ms, limit=4380
            )
            if not oi_hist:
                logger.warning(
                    "CoinGlass returned empty OI for %s %s at cursor %d — stopping OI fetch",
                    pair, timeframe, cg_cursor,
                )
                break
            for o in oi_hist:
                bucket = (o["timestamp"] // tf_ms) * tf_ms
                oi_map[bucket] = o["open_interest"]
            last_ts = oi_hist[-1]["timestamp"]
            if last_ts <= cg_cursor:
                break
            cg_cursor = last_ts + tf_ms
            await asyncio.sleep(0.15)
        logger.info("CoinGlass OI: %d %s buckets for %s", len(oi_map), timeframe, pair)
    elif config.COINGLASS_API_KEY:
        logger.info(
            "Timeframe %s not supported by CoinGlass HOBBYIST plan for %s — using Binance OI",
            timeframe, pair,
        )

    # Fall back to Binance OI if CoinGlass is unavailable or returned nothing.
    # Binance retains ~20 days of 1h OI — partial coverage is better than none.
    if not oi_map:
        logger.info("Fetching OI from Binance for %s %s (~20 days)", pair, timeframe)
        oi_hist_binance = await fetcher.fetch_open_interest_hist(
            pair, period="1h", limit=500, start_time=start_ms, end_time=end_ms
        )
        if oi_hist_binance:
            for o in oi_hist_binance:
                bucket = (o["timestamp"] // HR_MS) * HR_MS
                oi_map[bucket] = o["open_interest"]
            oi_bucket_ms = HR_MS  # Binance OI is always 1h bucketed
        logger.info("Binance OI: %d hourly buckets for %s", len(oi_map), pair)

    funding_hist = await fetcher.fetch_funding_rate(
        pair, limit=500, start_time=start_ms, end_time=end_ms
    )
    funding_map: dict[int, float] = {}
    if funding_hist:
        for f in funding_hist:
            bucket = (f["timestamp"] // 3_600_000) * 3_600_000
            funding_map[bucket] = f["funding_rate"]

    while cursor < end_ms:
        batch_end = min(cursor + batch_size * tf_ms, end_ms)
        candles = await fetcher.fetch_klines(
            pair, timeframe, limit=batch_size, start_time=cursor, end_time=batch_end
        )
        if not candles:
            logger.warning("No candles returned for %s %s at %d", pair, timeframe, cursor)
            cursor = batch_end + tf_ms
            continue

        # Enrich with OI + funding where available
        for c in candles:
            hour_bucket = (c["timestamp"] // HR_MS) * HR_MS
            oi_bucket = (c["timestamp"] // oi_bucket_ms) * oi_bucket_ms
            c["open_interest"] = oi_map.get(oi_bucket)
            c["funding_rate"] = funding_map.get(hour_bucket)

        written = store.upsert_candles(candles)
        total += written
        logger.debug("Wrote %d candles for %s %s (cursor=%d)", written, pair, timeframe, cursor)

        # Advance cursor past the last candle we got
        cursor = candles[-1]["timestamp"] + tf_ms
        await asyncio.sleep(0.1)  # Be gentle with the API

    return total


async def backfill_pair(pair: str, timeframe: str, days: int) -> None:
    """Ensure we have at least `days` of candle history for a pair/timeframe."""
    now_ms = int(time.time() * 1000)
    target_start = now_ms - days * MS_PER_DAY

    latest_ts = store.get_latest_timestamp(pair, timeframe)

    if latest_ts is None:
        # No data at all — download everything
        logger.info("No data for %s %s. Downloading %d days.", pair, timeframe, days)
        written = await _download_range(pair, timeframe, target_start, now_ms)
        logger.info("Backfill complete: %d candles for %s %s", written, pair, timeframe)
    else:
        if latest_ts >= now_ms - TIMEFRAME_MS.get(timeframe, 3_600_000) * 2:
            # Already up-to-date
            logger.info("%s %s is up-to-date (latest: %d)", pair, timeframe, latest_ts)
        else:
            # Fill the gap from latest to now
            gap_start = latest_ts + TIMEFRAME_MS.get(timeframe, 3_600_000)
            logger.info(
                "Filling gap for %s %s from %d to %d",
                pair, timeframe, gap_start, now_ms,
            )
            written = await _download_range(pair, timeframe, gap_start, now_ms)
            logger.info("Gap fill complete: %d candles for %s %s", written, pair, timeframe)

        # Also check for internal gaps
        gaps = store.detect_and_log_gaps(pair, timeframe)
        for gap_start, gap_end in gaps:
            logger.info("Filling internal gap %d-%d for %s %s", gap_start, gap_end, pair, timeframe)
            await _download_range(pair, timeframe, gap_start, gap_end)


async def backfill_all_live() -> None:
    """Bootstrap all configured pairs/timeframes for live mode (7 days)."""
    tasks = []
    for pair in config.PAIRS:
        for tf in config.TIMEFRAMES:
            tasks.append(backfill_pair(pair, tf, config.LIVE_BACKFILL_DAYS))
    await asyncio.gather(*tasks)
    logger.info("Live backfill complete for all pairs.")


async def backfill_all_backtest() -> None:
    """Bootstrap all configured pairs/timeframes for backtest mode (12 months)."""
    days = config.BACKTEST_MONTHS * 30
    tasks = []
    for pair in config.PAIRS:
        for tf in config.TIMEFRAMES:
            tasks.append(backfill_pair(pair, tf, days))
    await asyncio.gather(*tasks)
    logger.info("Backtest backfill complete for all pairs.")


def run_live_backfill() -> None:
    """Synchronous entry point called from main startup."""
    asyncio.run(backfill_all_live())
