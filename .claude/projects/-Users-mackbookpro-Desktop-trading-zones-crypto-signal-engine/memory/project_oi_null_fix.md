---
name: OI null/small-change fix
description: oi_change is now Optional[float]=None when no OI data; volume-only fallback in classifier only fires on None, not on small OI values
type: project
---

**Critical result-accuracy fix applied 2026-03-27.**

Previously `oi_change = 0.0` was used for both "no OI data" and "OI data present but barely changed." The classifier's volume-only green fallback (`abs(oi_change) < OI_CHANGE_NOISE_FLOOR`) fired in both cases, inflating green signals when OI data was available but small.

**Fix:** `oi_change` is now `Optional[float]`:
- `None` = no OI data at all → volume-only fallback fires
- numeric (even 0.001) = OI data present → full regime matrix used, falls to yellow/default if weak

**Files changed:**
- `engine/classifier.py`: signature `oi_change: Optional[float]`, `_oi = oi_change or 0.0` for boolean flags, fallback checks `oi_change is None`, OI confidence bonus guarded by `if oi_change is not None`, `oi_change_percent` stored as `oi_change if oi_change is not None else 0.0`
- `main.py`: `oi_change: Optional[float] = None`, oi_pct/oi_note/summary all guard on `is None`, signal_row stores `0.0` when None
- `backtest/simulator.py`: same oi_change None pattern in `_compute_signals_at()`

**Why:** Without this fix, a 0.3% OI change would trigger the volume-only green path, creating ~20-35% more green signals and inflating backtest win rate from realistic ~72-79% toward the "without OI" inflated ~77-80%.
