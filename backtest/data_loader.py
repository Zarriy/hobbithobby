"""
Historical data loader for backtesting.
Checks local CSV cache first, downloads from Binance if missing.
"""

import asyncio
import csv
import logging
import time
from pathlib import Path

import config
from core import fetcher

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data" / "historical"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MS_PER_DAY = 86_400_000
MS_PER_MONTH = 30 * MS_PER_DAY

TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

CANDLE_FIELDS = [
    "pair", "timeframe", "timestamp", "open", "high", "low", "close", "volume",
    "open_interest", "funding_rate", "long_short_ratio", "taker_buy_sell_ratio",
]


def _csv_path(pair: str, timeframe: str) -> Path:
    return DATA_DIR / f"{pair}_{timeframe}.csv"


def _write_csv(candles: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDLE_FIELDS)
        writer.writeheader()
        for c in candles:
            row = {k: c.get(k, "") for k in CANDLE_FIELDS}
            writer.writerow(row)
    logger.info("Saved %d candles to %s", len(candles), path)


def _read_csv(path: Path) -> list[dict]:
    candles = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candle = {}
            for k in CANDLE_FIELDS:
                val = row.get(k, "")
                if k == "pair" or k == "timeframe":
                    candle[k] = val
                elif val == "" or val is None:
                    candle[k] = None
                else:
                    try:
                        candle[k] = int(val) if k == "timestamp" else float(val)
                    except ValueError:
                        candle[k] = None
            candles.append(candle)
    return sorted(candles, key=lambda c: c["timestamp"])


async def _download_historical(
    pair: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> list[dict]:
    """Download OHLCV + OI + funding + ratios from Binance, merge by timestamp."""
    tf_ms = TIMEFRAME_MS.get(timeframe, 3_600_000)
    batch_size = 500
    all_candles: dict[int, dict] = {}

    # Download klines in batches
    cursor = start_ms
    while cursor < end_ms:
        batch_end = min(cursor + batch_size * tf_ms, end_ms)
        klines = await fetcher.fetch_klines(
            pair, timeframe, limit=batch_size, start_time=cursor, end_time=batch_end
        )
        if klines:
            for k in klines:
                all_candles[k["timestamp"]] = k
            cursor = klines[-1]["timestamp"] + tf_ms
        else:
            cursor = batch_end + tf_ms
        await asyncio.sleep(0.1)

    if not all_candles:
        return []

    HR_MS = 3_600_000  # 1 hour in milliseconds

    # CoinGlass HOBBYIST plan supported intervals (1h is NOT supported)
    _CG_SUPPORTED = {"4h", "6h", "8h", "12h", "1d", "1w"}
    cg_interval = timeframe if timeframe in _CG_SUPPORTED else None
    cg_interval_ms = TIMEFRAME_MS.get(cg_interval, HR_MS) if cg_interval else HR_MS

    # ── OI history ──────────────────────────────────────────────────────────
    # Prefer CoinGlass (years of history); fall back to Binance (~30-60 days).
    oi_map: dict[int, float] = {}

    if config.COINGLASS_API_KEY and cg_interval:
        logger.info("Fetching OI from CoinGlass at %s interval (full history)...", cg_interval)
        cg_cursor = start_ms
        while cg_cursor < end_ms:
            cg_hist = await fetcher.fetch_coinglass_oi_history(
                pair, interval=cg_interval, start_time=cg_cursor, end_time=end_ms, limit=4380
            )
            if not cg_hist:
                logger.warning(
                    "CoinGlass returned empty OI for %s at cursor %d — stopping OI fetch",
                    pair, cg_cursor,
                )
                break
            for entry in cg_hist:
                bucket = (entry["timestamp"] // cg_interval_ms) * cg_interval_ms
                oi_map[bucket] = entry["open_interest"]
            last_cg_ts = cg_hist[-1]["timestamp"]
            if last_cg_ts <= cg_cursor:
                break
            cg_cursor = last_cg_ts + cg_interval_ms
            await asyncio.sleep(0.15)
        logger.info("CoinGlass OI: %d %s buckets", len(oi_map), cg_interval)
    elif config.COINGLASS_API_KEY and not cg_interval:
        logger.info(
            "Timeframe %s not supported by CoinGlass HOBBYIST plan — skipping CoinGlass OI fetch",
            timeframe,
        )

    # Fall back to Binance OI if CoinGlass is unavailable or returned nothing.
    # Binance retains ~20 days of 1h OI — partial coverage is better than none.
    if not oi_map:
        logger.info(
            "CoinGlass OI unavailable for %s — falling back to Binance OI (~20 days)", pair
        )
        oi_hist = await fetcher.fetch_open_interest_hist(pair, period="1h", limit=500)
        if oi_hist:
            for entry in oi_hist:
                bucket = (entry["timestamp"] // HR_MS) * HR_MS
                oi_map[bucket] = entry["open_interest"]
        logger.info("Binance OI fallback: %d hourly buckets (covering ~%d days)",
                    len(oi_map), len(oi_map) // 24 if oi_map else 0)

    # ── Funding rate (every 8h, full history on Binance) ────────────────────
    funding_map: dict[int, float] = {}
    FUNDING_INTERVAL_MS = 8 * HR_MS
    funding_cursor = start_ms
    while funding_cursor < end_ms:
        funding_hist = await fetcher.fetch_funding_rate(
            pair, limit=500, start_time=funding_cursor, end_time=end_ms
        )
        if not funding_hist:
            break
        for entry in funding_hist:
            bucket = (entry["timestamp"] // HR_MS) * HR_MS
            funding_map[bucket] = entry["funding_rate"]
        last_funding_ts = funding_hist[-1]["timestamp"]
        if last_funding_ts <= funding_cursor:
            break
        funding_cursor = last_funding_ts + FUNDING_INTERVAL_MS
        await asyncio.sleep(0.1)

    # ── Taker buy/sell ratio (1h, ~20 days — Binance rejects startTime with 400)
    taker_map: dict[int, float] = {}
    taker_hist = await fetcher.fetch_taker_long_short_ratio(pair, period="1h", limit=500)
    if taker_hist:
        for entry in taker_hist:
            bucket = (entry["timestamp"] // HR_MS) * HR_MS
            taker_map[bucket] = entry["taker_buy_sell_ratio"]

    # ── Long/short account ratio (1h, ~20 days — same Binance retention limit)
    ls_map: dict[int, float] = {}
    ls_hist = await fetcher.fetch_long_short_ratio(pair, period="1h", limit=500)
    if ls_hist:
        for entry in ls_hist:
            bucket = (entry["timestamp"] // HR_MS) * HR_MS
            ls_map[bucket] = entry["long_short_ratio"]

    # Enrich candles — OI uses cg_interval_ms bucket alignment when CoinGlass data present
    oi_bucket_ms = cg_interval_ms if oi_map and cg_interval else HR_MS
    for ts, candle in all_candles.items():
        hour_bucket = (ts // HR_MS) * HR_MS
        oi_bucket = (ts // oi_bucket_ms) * oi_bucket_ms
        candle["open_interest"] = oi_map.get(oi_bucket)
        candle["funding_rate"] = funding_map.get(hour_bucket)
        candle["taker_buy_sell_ratio"] = taker_map.get(hour_bucket)
        candle["long_short_ratio"] = ls_map.get(hour_bucket)

    return sorted(all_candles.values(), key=lambda c: c["timestamp"])


def load_historical_data(
    pair: str,
    timeframe: str,
    months: int = config.BACKTEST_MONTHS,
    force_download: bool = False,
) -> list[dict]:
    """
    Load historical candle data.
    1. Check CSV cache
    2. If missing or stale, download from Binance
    3. Save to CSV
    4. Return sorted list of dicts
    """
    csv_path = _csv_path(pair, timeframe)
    now_ms = int(time.time() * 1000)
    target_start = now_ms - months * MS_PER_MONTH

    # Check cache
    if not force_download and csv_path.exists():
        candles = _read_csv(csv_path)
        if candles:
            earliest = candles[0]["timestamp"]
            latest = candles[-1]["timestamp"]
            # Cache is good if it covers the required period and isn't too stale (>1 day)
            if earliest <= target_start + MS_PER_DAY and latest >= now_ms - MS_PER_DAY:
                logger.info(
                    "Loaded %d candles from cache: %s %s",
                    len(candles), pair, timeframe
                )
                return candles
            else:
                logger.info(
                    "Cache exists but stale/incomplete for %s %s. Redownloading.",
                    pair, timeframe
                )

    # Download
    logger.info("Downloading %d months of %s %s data from Binance...", months, pair, timeframe)
    candles = asyncio.run(
        _download_historical(pair, timeframe, target_start, now_ms)
    )

    if not candles:
        logger.error("Failed to download data for %s %s", pair, timeframe)
        # Return from cache if available even if stale
        if csv_path.exists():
            return _read_csv(csv_path)
        return []

    _write_csv(candles, csv_path)
    logger.info("Downloaded %d candles for %s %s", len(candles), pair, timeframe)
    return candles


def load_multi_timeframe(
    pair: str,
    timeframes: list[str],
    months: int = config.BACKTEST_MONTHS,
) -> dict[str, list[dict]]:
    """Load data for multiple timeframes of the same pair."""
    return {tf: load_historical_data(pair, tf, months) for tf in timeframes}
