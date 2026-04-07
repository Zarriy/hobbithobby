"""
Shared fixtures for the crypto signal engine test suite.
Provides realistic candle data, signals, FVGs, OBs, and helper factories.
"""

import sys
import os
import time
import numpy as np
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Candle Factory ───

def make_candle(
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
    pair: str = "BTCUSDT",
    timeframe: str = "1h",
    open_interest: float = None,
    funding_rate: float = None,
    taker_buy_sell_ratio: float = None,
    long_short_ratio: float = None,
) -> dict:
    return {
        "pair": pair,
        "timeframe": timeframe,
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
        "funding_rate": funding_rate,
        "taker_buy_sell_ratio": taker_buy_sell_ratio,
        "long_short_ratio": long_short_ratio,
    }


def make_trending_candles(
    start_price: float = 100.0,
    n: int = 50,
    direction: str = "up",
    step: float = 0.5,
    volatility: float = 1.0,
    start_ts: int = 1_000_000_000_000,
    tf_ms: int = 3_600_000,
    pair: str = "BTCUSDT",
    timeframe: str = "1h",
    base_volume: float = 1000.0,
    oi_start: float = None,
    oi_step: float = None,
) -> list[dict]:
    """Generate a realistic trending candle series."""
    candles = []
    price = start_price
    oi = oi_start

    for i in range(n):
        if direction == "up":
            c = price + step
        elif direction == "down":
            c = price - step
        else:
            c = price + np.random.uniform(-step, step)

        h = max(price, c) + volatility * np.random.uniform(0, 1)
        l = min(price, c) - volatility * np.random.uniform(0, 1)

        if oi is not None and oi_step is not None:
            oi += oi_step

        candles.append(make_candle(
            ts=start_ts + i * tf_ms,
            open_=price,
            high=h,
            low=l,
            close=c,
            volume=base_volume + np.random.uniform(-200, 200),
            pair=pair,
            timeframe=timeframe,
            open_interest=oi,
        ))
        price = c

    return candles


def make_flat_candles(
    price: float = 100.0,
    n: int = 50,
    noise: float = 0.1,
    start_ts: int = 1_000_000_000_000,
    tf_ms: int = 3_600_000,
    pair: str = "BTCUSDT",
    timeframe: str = "1h",
    volume: float = 500.0,
) -> list[dict]:
    """Generate flat/ranging candles."""
    candles = []
    for i in range(n):
        o = price + np.random.uniform(-noise, noise)
        c = price + np.random.uniform(-noise, noise)
        h = max(o, c) + abs(np.random.normal(0, noise))
        l = min(o, c) - abs(np.random.normal(0, noise))
        candles.append(make_candle(
            ts=start_ts + i * tf_ms,
            open_=o, high=h, low=l, close=c,
            volume=volume,
            pair=pair, timeframe=timeframe,
        ))
    return candles


@pytest.fixture
def btc_uptrend_candles():
    """50 candles of BTC trending up from 60000."""
    return make_trending_candles(
        start_price=60000, n=50, direction="up", step=100,
        volatility=50, base_volume=5000,
        oi_start=1_000_000, oi_step=5000,
    )


@pytest.fixture
def btc_downtrend_candles():
    """50 candles of BTC trending down from 65000."""
    return make_trending_candles(
        start_price=65000, n=50, direction="down", step=100,
        volatility=50, base_volume=5000,
        oi_start=1_000_000, oi_step=5000,
    )


@pytest.fixture
def btc_flat_candles():
    """50 flat candles around 62000."""
    return make_flat_candles(price=62000, n=50, noise=20, volume=500)


@pytest.fixture
def minimal_candles():
    """Just 5 candles — used for edge case testing."""
    return make_trending_candles(start_price=100, n=5, direction="up", step=1, volatility=0.5)


@pytest.fixture
def fvg_candles():
    """3 candles forming a bullish FVG: candle[0].high < candle[2].low."""
    ts = 1_000_000_000_000
    return [
        make_candle(ts, 100, 102, 99, 101),       # candle 0: high=102
        make_candle(ts + 3600000, 101, 106, 100, 105),  # candle 1: big bullish
        make_candle(ts + 7200000, 105, 108, 104, 107),  # candle 2: low=104 > candle0.high=102
    ]


@pytest.fixture
def bearish_fvg_candles():
    """3 candles forming a bearish FVG: candle[0].low > candle[2].high."""
    ts = 1_000_000_000_000
    return [
        make_candle(ts, 108, 110, 106, 107),       # candle 0: low=106
        make_candle(ts + 3600000, 107, 108, 100, 101),  # candle 1: big bearish
        make_candle(ts + 7200000, 101, 104, 99, 100),   # candle 2: high=104 < candle0.low=106
    ]
