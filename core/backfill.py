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

    # Fetch OI history once per range for enrichment
    oi_hist = await fetcher.fetch_open_interest_hist(
        pair, period="1h", limit=500, start_time=start_ms, end_time=end_ms
    )
    oi_map: dict[int, float] = {}
    if oi_hist:
        for o in oi_hist:
            # Round to nearest hour
            bucket = (o["timestamp"] // 3_600_000) * 3_600_000
            oi_map[bucket] = o["open_interest"]

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
            hour_bucket = (c["timestamp"] // 3_600_000) * 3_600_000
            c["open_interest"] = oi_map.get(hour_bucket)
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
