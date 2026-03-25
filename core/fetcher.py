"""
Binance Futures async API client with retry + exponential backoff.
Returns typed dicts, never raw JSON.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)

# Rate limit tracking
_request_count = 0
_rate_window_start = time.monotonic()
_RATE_LIMIT_PER_MIN = 1100  # Stay below 1200 with a buffer


def _reset_rate_counter() -> None:
    global _request_count, _rate_window_start
    _request_count = 0
    _rate_window_start = time.monotonic()


async def _rate_check() -> None:
    global _request_count
    _request_count += 1
    elapsed = time.monotonic() - _rate_window_start
    if elapsed >= 60:
        _reset_rate_counter()
        return
    if _request_count >= _RATE_LIMIT_PER_MIN:
        sleep_time = 60 - elapsed + 1
        logger.warning("Rate limit approaching, sleeping %.1fs", sleep_time)
        await asyncio.sleep(sleep_time)
        _reset_rate_counter()


def _retry_async(max_attempts: int = 3, backoff_base: int = 2):
    """Decorator for async functions with exponential backoff."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        wait = backoff_base ** (attempt + 1)
                        logger.warning(
                            "%s attempt %d/%d failed: %s. Retrying in %ds",
                            func.__name__, attempt + 1, max_attempts, e, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error("%s failed after %d attempts: %s", func.__name__, max_attempts, e)
            return None
        return wrapper
    return decorator


_client: Optional[httpx.AsyncClient] = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=config.BINANCE_FUTURES_BASE,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_klines(
    pair: str,
    timeframe: str,
    limit: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Optional[list[dict]]:
    """Fetch OHLCV candles from Binance Futures."""
    await _rate_check()
    client = await get_client()
    params = {"symbol": pair, "interval": timeframe, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    resp = await client.get("/fapi/v1/klines", params=params)
    resp.raise_for_status()
    raw = resp.json()

    candles = []
    for k in raw:
        candles.append({
            "pair": pair,
            "timeframe": timeframe,
            "timestamp": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "open_interest": None,
            "funding_rate": None,
            "long_short_ratio": None,
            "taker_buy_sell_ratio": None,
        })
    return candles


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_open_interest(pair: str) -> Optional[dict]:
    """Fetch current open interest."""
    await _rate_check()
    client = await get_client()
    resp = await client.get("/fapi/v1/openInterest", params={"symbol": pair})
    resp.raise_for_status()
    data = resp.json()
    return {
        "pair": pair,
        "open_interest": float(data["openInterest"]),
        "timestamp": int(data["time"]),
    }


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_open_interest_hist(
    pair: str,
    period: str = "1h",
    limit: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Optional[list[dict]]:
    """Fetch historical open interest snapshots."""
    await _rate_check()
    client = await get_client()
    params = {"symbol": pair, "period": period, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    resp = await client.get("/futures/data/openInterestHist", params=params)
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "pair": pair,
            "open_interest": float(r["sumOpenInterest"]),
            "oi_value": float(r["sumOpenInterestValue"]),
            "timestamp": int(r["timestamp"]),
        }
        for r in raw
    ]


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_funding_rate(
    pair: str,
    limit: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Optional[list[dict]]:
    """Fetch funding rate history."""
    await _rate_check()
    client = await get_client()
    params = {"symbol": pair, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    resp = await client.get("/fapi/v1/fundingRate", params=params)
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "pair": pair,
            "funding_rate": float(r["fundingRate"]),
            "timestamp": int(r["fundingTime"]),
        }
        for r in raw
    ]


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_long_short_ratio(
    pair: str,
    period: str = "1h",
    limit: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Optional[list[dict]]:
    """Fetch global long/short account ratio."""
    await _rate_check()
    client = await get_client()
    params = {"symbol": pair, "period": period, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    resp = await client.get("/futures/data/globalLongShortAccountRatio", params=params)
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "pair": pair,
            "long_short_ratio": float(r["longShortRatio"]),
            "long_account": float(r["longAccount"]),
            "short_account": float(r["shortAccount"]),
            "timestamp": int(r["timestamp"]),
        }
        for r in raw
    ]


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_taker_long_short_ratio(
    pair: str,
    period: str = "1h",
    limit: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Optional[list[dict]]:
    """Fetch taker buy/sell volume ratio."""
    await _rate_check()
    client = await get_client()
    params = {"symbol": pair, "period": period, "limit": limit}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    resp = await client.get("/futures/data/takerlongshortRatio", params=params)
    resp.raise_for_status()
    raw = resp.json()
    return [
        {
            "pair": pair,
            "taker_buy_sell_ratio": float(r["buySellRatio"]),
            "buy_vol": float(r["buyVol"]),
            "sell_vol": float(r["sellVol"]),
            "timestamp": int(r["timestamp"]),
        }
        for r in raw
    ]


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_latest_price(pair: str) -> Optional[dict]:
    """Fetch latest price — used in fast pulse."""
    await _rate_check()
    client = await get_client()
    resp = await client.get("/fapi/v1/ticker/price", params={"symbol": pair})
    resp.raise_for_status()
    data = resp.json()
    return {
        "pair": pair,
        "price": float(data["price"]),
        "timestamp": int(time.time() * 1000),
    }


# ─── CoinGlass Client ───────────────────────────────────────────────────────

_cg_client: Optional[httpx.AsyncClient] = None


async def _get_cg_client() -> httpx.AsyncClient:
    global _cg_client
    if _cg_client is None or _cg_client.is_closed:
        headers = {}
        if config.COINGLASS_API_KEY:
            headers["CG-API-KEY"] = config.COINGLASS_API_KEY
        _cg_client = httpx.AsyncClient(
            base_url=config.COINGLASS_BASE,
            headers=headers,
            timeout=httpx.Timeout(15.0, connect=5.0),
        )
    return _cg_client


@_retry_async(max_attempts=config.MAX_RETRIES, backoff_base=config.RETRY_BACKOFF_BASE)
async def fetch_coinglass_oi_history(
    pair: str,
    interval: str = "1h",
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: int = 4380,
) -> Optional[list[dict]]:
    """
    Fetch historical OI from CoinGlass (up to 2 years of 1h data).
    Requires COINGLASS_API_KEY env var.
    Returns list of {timestamp_ms, open_interest}.
    """
    if not config.COINGLASS_API_KEY:
        return None

    await _rate_check()
    client = await _get_cg_client()

    # CoinGlass symbol format: BTCUSDT → BTC
    symbol = pair.replace("USDT", "").replace("BUSD", "")
    params: dict = {
        "ex": "Binance",
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = start_time // 1000  # CoinGlass uses seconds
    if end_time:
        params["endTime"] = end_time // 1000

    resp = await client.get("/public/futures/openInterest/ohlc-history", params=params)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != "0" or not data.get("data"):
        logger.warning("CoinGlass OI: unexpected response: %s", data.get("msg", "unknown"))
        return None

    results = []
    for row in data["data"]:
        ts_ms = int(row["t"]) * 1000 if int(row["t"]) < 1e12 else int(row["t"])
        results.append({
            "pair": pair,
            "open_interest": float(row["c"]),  # use close OI of the candle
            "timestamp": ts_ms,
        })
    return results


async def close_cg_client() -> None:
    global _cg_client
    if _cg_client and not _cg_client.is_closed:
        await _cg_client.aclose()
        _cg_client = None


async def fetch_full_candle_snapshot(pair: str, timeframe: str) -> Optional[dict]:
    """
    Fetch OHLCV + latest OI + funding + ratios and merge into enriched candle dict.
    Used during full analysis cycle.
    """
    klines, oi, funding, ls_ratio, taker = await asyncio.gather(
        fetch_klines(pair, timeframe, limit=2),
        fetch_open_interest(pair),
        fetch_funding_rate(pair, limit=1),
        fetch_long_short_ratio(pair, period="1h", limit=1),
        fetch_taker_long_short_ratio(pair, period="1h", limit=1),
        return_exceptions=False,
    )

    if not klines:
        return None

    candle = klines[-1].copy()
    if oi:
        candle["open_interest"] = oi["open_interest"]
    if funding:
        candle["funding_rate"] = funding[-1]["funding_rate"]
    if ls_ratio:
        candle["long_short_ratio"] = ls_ratio[-1]["long_short_ratio"]
    if taker:
        candle["taker_buy_sell_ratio"] = taker[-1]["taker_buy_sell_ratio"]

    return candle
