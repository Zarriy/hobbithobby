# Backtest Guide

Complete reference for running backtests on the crypto signal engine.

---

## TL;DR — Quick Commands

```bash
# 2-day demo on all pairs (uses cached data, no download)
python demo_2day_test.py

# 2-day demo, aggressive mode (yellow + green signals)
python demo_2day_test.py --aggressive

# 2-day demo, conservative mode (green only — needs OI data)
python demo_2day_test.py --conservative

# Custom window
python demo_2day_test.py --days 7

# Full 12-month backtest, single pair (downloads fresh data + regenerates cache)
python -m backtest.runner --pair BTCUSDT --months 12 --quick --force-download

# Full backtest with CoinGlass OI (realistic results)
export COINGLASS_API_KEY=<your_key>
python -m backtest.runner --pair BTCUSDT --months 12 --quick --force-download
```

---

## File Map

```
backtest/
├── runner.py       — CLI entry point (argparse, orchestrates everything)
├── simulator.py    — Candle-by-candle engine: generate_signal_cache(), run_backtest()
├── rules.py        — TradeRule dataclass + check_entry() / check_exit()
├── data_loader.py  — load_historical_data(): CSV cache → Binance download fallback
├── metrics.py      — calculate_metrics() → BacktestResult dataclass
├── report.py       — HTML report generator
└── stress.py       — Monte Carlo, walk-forward, sensitivity analysis

data/historical/
├── BTCUSDT_1h.csv               — raw OHLCV + OI + funding (auto-updated)
├── ETHUSDT_1h.csv
├── SOLUSDT_1h.csv
├── XRPUSDT_1h.csv
├── TAOUSDT_1h.csv
├── signal_cache_BTCUSDT_1h_12m.pkl  — pre-computed signals for 12-month run
├── signal_cache_BTCUSDT_1h_1m.pkl   — pre-computed signals for 1-month run
└── ... (same pattern for all pairs)

demo_2day_test.py   — short-window demo script (uses cached CSV + pkl)
reports/            — auto-generated HTML reports from runner.py
```

---

## How the Backtest Works

### Step 1 — Load Data
`data_loader.load_historical_data(pair, timeframe, months)` checks `data/historical/PAIR_TF.csv`.
- If CSV exists and is fresh (< 1 day stale, covers required period): use it.
- Otherwise: download from Binance klines + OI + funding + taker ratios, write new CSV.
- With `COINGLASS_API_KEY` set: OI comes from CoinGlass (2+ years history). Without: Binance only (~20 days).

### Step 2 — Generate Signal Cache
`simulator.generate_signal_cache(candles)` iterates every candle from index 30 onward and runs the full signal pipeline using only data up to that point (no future leak). Output is a list of `SignalOutput` objects — one per candle, first 30 are `None`.

The cache is saved as a `.pkl` file so repeated backtest runs on the same data are sub-second.

### Step 3 — Run Simulation
`simulator.run_backtest_from_cache(candles, signal_cache, rules)` loops candle-by-candle:
1. Check all open positions for exits (SL, TP1, TP2, time, regime red).
2. If signal passes all entry gates: open a new position.
3. Record equity + drawdown at each step.
4. At the end, force-close any still-open positions at last price.

### Step 4 — Metrics & Report
`metrics.calculate_metrics(trades, equity_curve, drawdown_curve)` produces `BacktestResult`.
`report.generate_report(...)` writes an HTML file to `reports/`.

---

## Entry Gates (ALL must pass)

| Gate | Aggressive | Conservative |
|------|-----------|--------------|
| Max open positions | < 2 | < 2 |
| Confidence | ≥ 70 | ≥ 70 |
| Risk color | green **or** yellow | green only |
| Action bias | `long_bias` or `short_bias` | same |
| Trend confirmation | long↔uptrend/ranging/transition; short↔downtrend/ranging/transition | same |
| Price zone | long↔discount/equilibrium; short↔premium/equilibrium | same |
| Level touch | candle wick within 0.5% of nearest FVG or OB | same |

> **Conservative mode almost never fires without `COINGLASS_API_KEY`** — green signals require full OI regime data. Without it, the classifier falls back to volume-only, producing mostly yellow.

---

## Exit Conditions (priority order)

1. `time_exit` — held ≥ 48h
2. `regime_red_exit` — signal turns red
3. `stop_loss` — price hits SL (just below FVG/OB zone)
4. `tp2` — price hits 3R target (after TP1 already hit)
5. `tp1` — price hits 1.5R target → close 50%, move stop to breakeven, set TP2

---

## Position Sizing

```
risk_usd = equity × 0.01 × size_multiplier

size_multiplier:
  conf 70–79 → 0.5×
  conf 80–89 → 1.0×
  conf 90+   → 1.5×

Leverage: 10× (default, config.DEFAULT_LEVERAGE)
Entry fee deducted immediately. Exit fee + slippage at close.
Funding cost: ~0.01% per 8h hold period.
```

---

## Signal Cache Alignment Rule

The signal cache is index-aligned with the candles list. When slicing for a short-window test:

```python
candles_2d = candles[-window:]
cache_2d   = cache[-window:]
```

This is safe because each signal at position `i` was computed using only `candles[:i+1]` — no future data. The slice preserves correctness.

If `len(candles) != len(cache)`, align by taking the minimum tail:
```python
min_len = min(len(candles), len(cache))
candles = candles[-min_len:]
cache   = cache[-min_len:]
```

---

## runner.py CLI Reference

```
python -m backtest.runner [options]

--pair BTCUSDT          Which pair (default: BTCUSDT)
--timeframe 1h          Timeframe (default: 1h; only 1h CSVs exist in cache)
--months 12             Lookback window in months (default: config.BACKTEST_MONTHS)
--confidence 70         Minimum confidence to enter (default: config.CONFIDENCE_THRESHOLD_TRADE)
--capital 10000         Starting capital in USD
--max-hold-hours 48     Force-exit after N hours
--quick                 Skip stress tests (walk-forward, Monte Carlo, sensitivity)
--no-report             Skip HTML report generation
--force-download        Re-download data even if CSV cache is fresh
--regen-cache           Recompute signal cache even if .pkl exists
--stress-only           Run stress tests only (skip full report)
```

### Example: Run all 5 pairs at 12 months

```bash
for pair in BTCUSDT ETHUSDT SOLUSDT XRPUSDT TAOUSDT; do
  python -m backtest.runner --pair $pair --months 12 --quick --force-download
done
```

---

## demo_2day_test.py Reference

Designed for rapid short-window testing on **already-cached data**. No downloads.

```
python demo_2day_test.py [options]

--days N         Number of days to test (default: 2)
--aggressive     Yellow + green signals (default)
--conservative   Green signals only
```

Output shows per-pair: trade count, sides (long/short), win/loss, net P&L, final equity.

---

## OI Data Impact on Results

| Scenario | OI Source | Typical WR | Typical Trades (12m) | Notes |
|----------|-----------|-----------|----------------------|-------|
| With CoinGlass key | CoinGlass 2yr history | 71–79% | ~270–350/pair | Realistic |
| Without key | Binance ~20d only | 77–80% | ~285–445/pair | Inflated — do not trust |

The difference: without OI, the classifier uses `volume_zscore > 2.0 + price direction` only, which generates more green signals and fires more trades. With OI, the full regime matrix (accumulation/distribution/squeeze/liquidation etc.) is active.

---

## Updating the Cache After New Data

If you add new candles to a CSV (e.g. after pulling fresh data from Binance) without regenerating the cache, the CSV and pkl will be out of sync. Fix:

```bash
python -m backtest.runner --pair BTCUSDT --months 12 --regen-cache
```

Or delete the stale pkl and re-run:

```bash
rm data/historical/signal_cache_BTCUSDT_1h_12m.pkl
python -m backtest.runner --pair BTCUSDT --months 12 --quick
```

---

## 2-Day Test Results (2026-03-23 → 2026-03-25, aggressive mode)

| Pair | Trades | Longs | Shorts | Wins | Losses | WR | Net P&L |
|------|--------|-------|--------|------|--------|----|---------|
| BTCUSDT | 2 | 0 | 2 | 2 | 0 | 100% | +$206.69 |
| ETHUSDT | 0 | — | — | — | — | — | — |
| SOLUSDT | 0 | — | — | — | — | — | — |
| XRPUSDT | 0 | — | — | — | — | — | — |
| TAOUSDT | 0 | — | — | — | — | — | — |
| **TOTAL** | **2** | 0 | 2 | 2 | 0 | **100%** | **+$206.69** |

> Low trade count over 2 days is expected and correct — the level-touch gate (candle wick within 0.5% of FVG/OB) is the most selective filter. On 48 candles per pair, few wicks will coincide with active zones at sufficient confidence.
