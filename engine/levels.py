"""
Liquidation level estimation from OI clusters and common leverage levels.
"""

from typing import Optional


def estimate_liquidation_levels(
    current_price: float,
    open_interest: float,
    recent_oi_changes: list[dict],
    leverage_assumptions: Optional[list[int]] = None,
) -> dict:
    """
    Estimate where liquidation clusters exist.

    Method:
    1. For each significant OI increase in recent_oi_changes, record the price at that time
       as a likely position entry level.
    2. For each common leverage, compute liq prices from those entries.

    Liq price for long at leverage L entered at entry_price:
        liq = entry_price * (1 - 1/L)
    Liq price for short at leverage L entered at entry_price:
        liq = entry_price * (1 + 1/L)

    Returns:
    {
        leverage: {
            "long_liq_levels": [float],
            "short_liq_levels": [float],
            "from_current": {
                "long_liq": float,   # liq price if entered right now
                "short_liq": float,
            }
        }
    }
    """
    if leverage_assumptions is None:
        leverage_assumptions = [5, 10, 20, 50, 100]

    result = {}

    for lev in leverage_assumptions:
        liq_long_current = current_price * (1 - 1.0 / lev)
        liq_short_current = current_price * (1 + 1.0 / lev)

        long_liq_from_entries = []
        short_liq_from_entries = []

        for entry in recent_oi_changes:
            entry_price = entry.get("price")
            oi_change = entry.get("oi_change_percent", 0)
            if entry_price is None or abs(oi_change) < 0.02:
                continue
            long_liq_from_entries.append(entry_price * (1 - 1.0 / lev))
            short_liq_from_entries.append(entry_price * (1 + 1.0 / lev))

        result[lev] = {
            "long_liq_levels": sorted(set(long_liq_from_entries)),
            "short_liq_levels": sorted(set(short_liq_from_entries)),
            "from_current": {
                "long_liq": liq_long_current,
                "short_liq": liq_short_current,
            },
        }

    return result


def find_nearest_liquidation_cluster(
    liq_levels: dict,
    current_price: float,
    direction: str = "below",  # "below" or "above"
    max_leverages: Optional[list[int]] = None,
) -> Optional[float]:
    """
    Find the nearest liquidation price cluster in the given direction.
    Cluster = multiple leverage levels within 0.5% of each other.
    """
    if max_leverages is None:
        max_leverages = [10, 20, 50]

    all_levels = []
    for lev in max_leverages:
        data = liq_levels.get(lev, {})
        if direction == "below":
            levels = data.get("long_liq_levels", []) + [data.get("from_current", {}).get("long_liq")]
        else:
            levels = data.get("short_liq_levels", []) + [data.get("from_current", {}).get("short_liq")]
        all_levels.extend([l for l in levels if l is not None])

    if direction == "below":
        candidates = [l for l in all_levels if l < current_price]
        return max(candidates) if candidates else None
    else:
        candidates = [l for l in all_levels if l > current_price]
        return min(candidates) if candidates else None
