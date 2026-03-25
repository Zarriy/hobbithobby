"""
Approximate volume profile from candle data.
Distributes each candle's volume across its high-low range into bins.
"""


def approximate_volume_profile(
    candles: list[dict],
    num_bins: int = 50,
    lookback: int = 100,
) -> dict:
    """
    Distribute each candle's volume evenly across its high-low range,
    binned into `num_bins` price levels.

    Returns:
    {
        "poc": float,           # Point of Control — highest volume price
        "hvn": [float],         # High Volume Nodes (top 20% bins)
        "lvn": [float],         # Low Volume Nodes (bottom 20% bins)
        "value_area_high": float,
        "value_area_low": float,
        "bins": [(price, volume)]
    }
    """
    if not candles:
        return _empty_profile()

    recent = candles[-lookback:] if len(candles) > lookback else candles

    # Determine price range
    price_high = max(c["high"] for c in recent)
    price_low = min(c["low"] for c in recent)

    if price_high <= price_low:
        return _empty_profile()

    bin_size = (price_high - price_low) / num_bins
    bin_volumes = [0.0] * num_bins
    bin_prices = [price_low + (i + 0.5) * bin_size for i in range(num_bins)]

    for c in recent:
        candle_range = c["high"] - c["low"]
        if candle_range < 1e-10:
            # Zero-range candle — put all volume in one bin
            idx = int((c["close"] - price_low) / bin_size)
            idx = max(0, min(num_bins - 1, idx))
            bin_volumes[idx] += c["volume"]
            continue

        # Distribute volume proportionally across bins the candle spans
        low_bin = max(0, int((c["low"] - price_low) / bin_size))
        high_bin = min(num_bins - 1, int((c["high"] - price_low) / bin_size))

        if low_bin == high_bin:
            bin_volumes[low_bin] += c["volume"]
        else:
            for b in range(low_bin, high_bin + 1):
                bin_low = price_low + b * bin_size
                bin_high = bin_low + bin_size
                overlap_low = max(c["low"], bin_low)
                overlap_high = min(c["high"], bin_high)
                overlap = max(0.0, overlap_high - overlap_low)
                fraction = overlap / candle_range
                bin_volumes[b] += c["volume"] * fraction

    # Point of Control
    poc_idx = bin_volumes.index(max(bin_volumes))
    poc = bin_prices[poc_idx]

    # Value Area: bins containing 70% of total volume, starting from POC
    total_vol = sum(bin_volumes)
    va_target = total_vol * 0.70

    va_indices = {poc_idx}
    va_vol = bin_volumes[poc_idx]
    lo_ptr = poc_idx - 1
    hi_ptr = poc_idx + 1

    while va_vol < va_target:
        add_low = bin_volumes[lo_ptr] if lo_ptr >= 0 else 0
        add_high = bin_volumes[hi_ptr] if hi_ptr < num_bins else 0

        if add_low == 0 and add_high == 0:
            break

        if add_low >= add_high and lo_ptr >= 0:
            va_indices.add(lo_ptr)
            va_vol += add_low
            lo_ptr -= 1
        elif hi_ptr < num_bins:
            va_indices.add(hi_ptr)
            va_vol += add_high
            hi_ptr += 1
        else:
            break

    va_high = bin_prices[max(va_indices)]
    va_low = bin_prices[min(va_indices)]

    # HVN/LVN classification (top/bottom 20% by volume)
    sorted_vols = sorted(bin_volumes)
    hvn_threshold = sorted_vols[int(num_bins * 0.80)]
    lvn_threshold = sorted_vols[int(num_bins * 0.20)]

    hvn = [bin_prices[i] for i, v in enumerate(bin_volumes) if v >= hvn_threshold]
    lvn = [bin_prices[i] for i, v in enumerate(bin_volumes) if v <= lvn_threshold and v > 0]

    return {
        "poc": poc,
        "hvn": hvn,
        "lvn": lvn,
        "value_area_high": va_high,
        "value_area_low": va_low,
        "bins": list(zip(bin_prices, bin_volumes)),
    }


def _empty_profile() -> dict:
    return {
        "poc": None,
        "hvn": [],
        "lvn": [],
        "value_area_high": None,
        "value_area_low": None,
        "bins": [],
    }
