"""
Numpy-based technical indicators.
All functions accept and return numpy arrays. No pandas.
"""

import numpy as np


def rolling_mean(values: np.ndarray, lookback: int) -> np.ndarray:
    """Simple rolling mean. Returns NaN for positions where window not full."""
    result = np.full_like(values, np.nan, dtype=float)
    n = len(values)
    for i in range(lookback - 1, n):
        result[i] = np.mean(values[i - lookback + 1 : i + 1])
    return result


def rolling_std(values: np.ndarray, lookback: int) -> np.ndarray:
    """Rolling standard deviation (ddof=1)."""
    result = np.full_like(values, np.nan, dtype=float)
    n = len(values)
    for i in range(lookback - 1, n):
        window = values[i - lookback + 1 : i + 1]
        result[i] = np.std(window, ddof=1)
    return result


def rolling_zscore(values: np.ndarray, lookback: int) -> np.ndarray:
    """
    Z-score of each value relative to its own rolling window.
    Returns NaN for the first (lookback-1) positions.
    """
    result = np.full_like(values, np.nan, dtype=float)
    n = len(values)
    for i in range(lookback - 1, n):
        window = values[i - lookback + 1 : i + 1]
        mu = np.mean(window)
        sigma = np.std(window, ddof=1)
        if sigma > 1e-10:
            result[i] = (values[i] - mu) / sigma
        else:
            result[i] = 0.0
    return result


def rate_of_change(values: np.ndarray, period: int) -> np.ndarray:
    """Percentage change over N periods. Returns NaN for first N positions."""
    result = np.full_like(values, np.nan, dtype=float)
    n = len(values)
    for i in range(period, n):
        prev = values[i - period]
        if prev != 0:
            result[i] = (values[i] - prev) / abs(prev)
        else:
            result[i] = 0.0
    return result


def true_range(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
) -> np.ndarray:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    n = len(highs)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hpc = abs(highs[i] - closes[i - 1])
        lpc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hpc, lpc)
    return tr


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range using Wilder's smoothing."""
    tr = true_range(highs, lows, closes)
    result = np.full(len(highs), np.nan)
    if len(tr) < period:
        return result

    # First ATR = simple average of first `period` TRs
    result[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


def vwap(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> np.ndarray:
    """
    Cumulative VWAP from start of data.
    Typical price = (high + low + close) / 3
    """
    typical = (highs + lows + closes) / 3.0
    cum_tpv = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    # Avoid division by zero
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(cum_vol > 0, cum_tpv / cum_vol, np.nan)
    return result


def vwap_deviation(
    closes: np.ndarray,
    vwap_values: np.ndarray,
    period: int = 50,
) -> np.ndarray:
    """
    Rolling standard deviation of (close - vwap), then normalize to stddev units.
    Returns how many std devs the close is from VWAP.
    """
    diff = closes - vwap_values
    std = rolling_std(diff, period)
    result = np.full_like(closes, np.nan, dtype=float)
    for i in range(len(closes)):
        if not np.isnan(std[i]) and std[i] > 1e-10 and not np.isnan(vwap_values[i]):
            result[i] = diff[i] / std[i]
    return result


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    result = np.full_like(values, np.nan, dtype=float)
    k = 2.0 / (period + 1)
    # Seed with first valid SMA
    for i in range(period - 1, len(values)):
        if i == period - 1:
            result[i] = np.mean(values[:period])
        else:
            result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def highest(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling max over `period` bars."""
    result = np.full_like(values, np.nan, dtype=float)
    for i in range(period - 1, len(values)):
        result[i] = np.max(values[i - period + 1 : i + 1])
    return result


def lowest(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling min over `period` bars."""
    result = np.full_like(values, np.nan, dtype=float)
    for i in range(period - 1, len(values)):
        result[i] = np.min(values[i - period + 1 : i + 1])
    return result
