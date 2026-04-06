---
name: Full codebase audit + all fixes — 2026-03-27
description: Complete audit pass covering all bugs found and fixed; all tests passing as of 2026-03-27
type: project
---

**Full audit completed 2026-03-27. All tests passing.**

## Bugs fixed

### 1. OI null/small-change distinction (highest impact)
`oi_change: Optional[float]` — `None` = no OI data, numeric = OI present.
- `engine/classifier.py`: `_oi = oi_change if oi_change is not None else 0.0` for all boolean flags; `elif _oi < -0.05` (line 123 fix); volume-only fallback checks `oi_change is None`; OI confidence bonus guarded by `if oi_change is not None`
- `main.py`: `oi_change: Optional[float] = None`; all downstream guards on `is None`
- `backtest/simulator.py`: same `None` pattern in `_compute_signals_at()`

### 2. Security: real API key in .env.example
`COINGLASS_API_KEY=a187679aaa4945efaffd814a764d9b6f` replaced with placeholder. **User should consider rotating this key** if it was ever pushed to git.

### 3. demo/store.py equity table migration
Added `BEGIN TRANSACTION; ... COMMIT;` inside `executescript()` for safety during the demo_equity table schema migration.

### 4. core/backfill.py + backtest/data_loader.py silent failure
CoinGlass empty-response loop was `continue` without logging — changed to `logger.warning + break` so stalled OI fetches are visible.

### 5. live-movemint.md docs errors (3 fixes)
- Diagram: `FastAPI :8000` → `:8001`
- CORS troubleshooting: removed reference to `FRONTEND_URL` env var (CORS is hardcoded)
- 502 troubleshooting: `systemctl status signal-engine` → `tmux ls` + `tmux attach`

### 6. main.py startup warnings
Added warnings when `TELEGRAM_BOT_TOKEN` or `COINGLASS_API_KEY` are missing.

### 7. main.py shutdown
Added `await fetcher.close_cg_client()` alongside existing `close_client()`.

## All test outcomes (verified clean)
- 8 classifier unit tests (OI None, small OI ≠ green, deleveraging, stale data, confidence clamp)
- 8 entry/exit rules tests (mode gates, TP1, time_exit, regime_red_exit, SL priority)
- 6 indicator tests (ATR, VWAP, z-score, vwap_deviation, edge cases)
- Engine tests: FVG (28 detected), OB (20 detected), market structure, volume profile
- 2-day demo test: 2 BTC trades, 50% WR
- 12-month backtest all 5 pairs: results match documented "without OI" benchmarks
- Trade math deep validation: 449 BTC trades, all PnL/fee/hold hours correct
- Position sizing: multipliers, formula, 5x cap, liquidation prices all verified
- Metrics cross-validation: total_return, win_rate, profit_factor manually verified

## Pending (not a bug, operational)
Existing signal caches (.pkl) were built without CoinGlass OI → produce inflated "without OI" results.
**To get realistic results**, regenerate with key set:
```bash
export COINGLASS_API_KEY=<key>
python -m backtest.runner --pair BTCUSDT --months 12 --quick --force-download
# repeat for ETHUSDT, SOLUSDT, XRPUSDT, TAOUSDT
```
Expected with OI: ~347 BTC trades, 79.4% WR, +465%, Sharpe 3.23 (vs inflated 444 trades, +1436%).

**Why:** classifier needs `oi_change is not None` to activate full regime matrix. Without CoinGlass key, Binance OI only covers ~20 days; backfill produces `None` for older candles → volume-only green path fires more → 20-35% more trades, 2-4× inflated returns.
