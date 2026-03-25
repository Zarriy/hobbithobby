# Crypto Signal Engine — Project Reference

> Read this file for full context before touching any code. It covers architecture, data models, signal logic, known issues, and what has been built vs planned.

---

## What This Is

A **local crypto risk posture system** (not a prediction engine). It filters when NOT to trade and identifies confluent entry zones using market structure + order flow data. Signals are generated for 5 Binance Futures pairs on 1h and 4h timeframes.

**It is not a "buy here" bot** — it surfaces regime state, risk color, and key price levels so a trader can make informed decisions.

---

## Stack

| Layer | Tech |
|---|---|
| Language | Python 3.13 |
| API server | FastAPI + uvicorn |
| Scheduler | APScheduler (AsyncIO) |
| Database | SQLite in WAL mode (`db/signals.db`) |
| HTTP client | httpx (async, with retry) |
| Math | numpy |
| Alerts | Telegram Bot API |
| No | Docker, Redis, WebSockets, ORM |

---

## Run Commands

```bash
# Install deps
pip install -r requirements.txt

# Run live signal engine (API at http://localhost:8000)
python main.py

# Run backtest (first run ~16 min to generate signal cache)
python -m backtest.runner --pair BTCUSDT --months 12 --confidence 70

# Force fresh data download
python -m backtest.runner --pair BTCUSDT --quick --regen-cache --force-download

# API docs (auto-generated)
http://localhost:8000/docs
```

---

## Directory Map

```
crypto-signal-engine/
├── CLAUDE.md                  ← you are here
├── config.py                  ← ALL tunable parameters (thresholds, pairs, intervals)
├── main.py                    ← FastAPI app + dual-loop scheduler entry point
├── requirements.txt
│
├── alerts/
│   └── telegram.py            ← Telegram alert builder + dedup sender
│
├── api/
│   └── routes.py              ← FastAPI REST endpoints (6 existing + 6 planned)
│
├── core/
│   ├── fetcher.py             ← Binance Futures API client (async, rate-limited, retry)
│   ├── backfill.py            ← Historical candle gap detection + fill
│   └── store.py               ← SQLite WAL wrapper — 5 tables, all DB access
│
├── engine/
│   ├── classifier.py          ← Signal matrix: regime + risk_color + confidence (0-100)
│   ├── indicators.py          ← ATR, VWAP, rolling z-score, VWAP deviation
│   ├── structure.py           ← Swing points, BOS/CHoCH, equal levels, premium/discount
│   ├── fvg.py                 ← Fair Value Gap detection + fill status
│   ├── orderblocks.py         ← Order Block detection + mitigation tracking
│   ├── liquidity.py           ← Liquidity sweep detection (wick + reversal)
│   ├── levels.py              ← Liquidation level estimation by leverage tier
│   ├── regime.py              ← 4H macro regime classification
│   └── volume_profile.py      ← Volume profile approximation (POC, HVN, LVN)
│
├── backtest/
│   ├── runner.py              ← CLI entry: orchestrates load → cache → sim → report
│   ├── simulator.py           ← Candle-by-candle backtesting engine (no future leak)
│   ├── rules.py               ← Mechanical entry/exit rules (check_entry, check_exit)
│   ├── data_loader.py         ← Historical data fetch + CSV caching
│   ├── metrics.py             ← calculate_metrics() → BacktestResult dataclass
│   ├── report.py              ← HTML/JSON report generation (equity curve, DD chart)
│   └── stress.py              ← Monte Carlo (1000 iter), walk-forward, sensitivity
│
├── demo/                      ← [PLANNED] Paper trading module
│   ├── trader.py              ← DemoTrader class (integrates with scheduler)
│   ├── store.py               ← 3 new DB tables: demo_positions, demo_trades, demo_equity
│   └── metrics.py             ← Adapter: demo_trades → TradeRecord → calculate_metrics()
│
├── frontend/                  ← [PLANNED] React dashboard
│
├── db/
│   └── signals.db             ← SQLite database (auto-created on startup)
│
├── data/historical/           ← CSV price data + signal cache pickles
│   ├── BTCUSDT_1h.csv
│   ├── ETHUSDT_1h.csv
│   └── signal_cache_*.pkl     ← Pre-computed signals for fast backtest rerun
│
└── reports/                   ← Auto-generated HTML backtest reports
```

---

## Scheduler Loops (`main.py`)

| Loop | Interval | What it does |
|---|---|---|
| `fast_pulse` | 60s | Fetch latest price + taker ratio. Alert on >3% moves. |
| `full_analysis` | 300s | Full signal pipeline for all pairs×timeframes. Persists to DB. |
| `hourly_task` | 3600s | Recalculate liquidation levels, update FVG/OB statuses. |
| `regime_task` | 14400s (4h) | Macro regime analysis on 4H candles. |

All loops use `asyncio.gather()` — concurrent across all pairs.

---

## Trading Pairs & Timeframes

```python
PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "TAOUSDT"]
TIMEFRAMES = ["1h", "4h"]
```

---

## Signal Output Schema (`engine/classifier.py → SignalOutput`)

| Field | Type | Values |
|---|---|---|
| `regime_state` | str | `accumulation`, `distribution`, `short_squeeze`, `long_liquidation`, `coiled_spring`, `deleveraging` |
| `risk_color` | str | `green`, `yellow`, `red` |
| `confidence` | int | 0–100 |
| `trend_state` | str | `uptrend`, `downtrend`, `ranging`, `transition` |
| `price_zone` | str | `premium`, `discount`, `equilibrium` |
| `action_bias` | str | `long_bias`, `short_bias`, `stay_flat`, `reduce_exposure` |

### Confidence Scoring (base 50)
- +20 volume confirmation (z-score > 2.0)
- +15 OI magnitude (change > 5%)
- +10 funding rate extreme
- +10 taker ratio alignment
- +10 trend confirmation
- +5 VWAP mean reversion
- -10 mixed signals in low volatility
- -20 stale data (age > 900s)
- Clamped to [0, 100]

### Regime Classification Matrix
| Regime | Conditions |
|---|---|
| `accumulation` | price up + OI up + high volume + no extreme funding |
| `distribution` | price down + OI up + high volume |
| `short_squeeze` | price up + OI up + extreme positive funding |
| `long_liquidation` | price down + OI up + extreme negative funding OR price down + OI down |
| `deleveraging` | OI unwinding + high volume → red signal |
| `coiled_spring` | flat price + OI spike + low volume |

---

## All Signal Fields Persisted to DB (`signals` table)

```
pair, timeframe, timestamp
regime_state, risk_color, confidence
trend_state, price_zone
nearest_bullish_fvg (JSON), nearest_bearish_fvg (JSON)
nearest_bullish_ob (JSON), nearest_bearish_ob (JSON)
equal_highs (JSON array), equal_lows (JSON array)
volume_zscore, oi_change_percent, funding_rate, taker_ratio, atr, vwap_deviation
metadata (JSON: {poc, macro_regime})
```

---

## SQLite Schema (`db/signals.db`)

### Existing Tables (5)

**`candles`** — OHLCV + enriched data
`pair, timeframe, timestamp, open, high, low, close, volume, open_interest, funding_rate, long_short_ratio, taker_buy_sell_ratio`

**`signals`** — All signal fields (see above)

**`fair_value_gaps`** — FVG detection + fill tracking
`pair, timeframe, detected_at, type (bullish/bearish), upper_bound, lower_bound, status (unfilled/partial/filled), filled_at`

**`order_blocks`** — OB detection + mitigation
`pair, timeframe, detected_at, type, upper_bound, lower_bound, fvg_overlap, status (active/mitigated), mitigated_at`

**`swing_points`** — Market structure
`pair, timeframe, timestamp, type (high/low), price`

### Planned Tables (3) — added by `demo/store.py`

**`demo_positions`** — Open + closed paper positions
`id, pair, timeframe, side, entry_price, stop_loss, tp1, tp2_target, size_usd, risk_distance, size_multiplier, entry_ts, exit_ts, regime_at_entry, risk_color_at_entry, entry_zone_type, confidence_at_entry, tp1_hit, partial_exit_pnl, status`

**`demo_trades`** — Closed trade ledger (write-once)
`id, position_id, pair, timeframe, side, entry_price, exit_price, entry_ts, exit_ts, exit_reason, pnl_usd, pnl_percent, fee_usd, net_pnl_usd, size_usd, regime_at_entry, confidence_at_entry, entry_zone_type, hold_hours`

**`demo_equity`** — Equity curve snapshots
`id, timestamp, equity, open_pnl, open_count`

---

## Key Config Thresholds (`config.py`)

```python
# Signal Quality
CONFIDENCE_THRESHOLD_TRADE = 70     # Min confidence to fire alert / take demo trade
OI_CHANGE_NOISE_FLOOR = 0.005       # Below 0.5% OI change = noise
OI_CHANGE_NOTABLE = 0.015           # Above 1.5% OI change = regime event
OI_CHANGE_LOOKBACK = 4              # OI change measured over 4 candles
FUNDING_RATE_EXTREME_POSITIVE = 0.0003
FUNDING_RATE_EXTREME_NEGATIVE = -0.0003
VOLUME_ZSCORE_LOOKBACK = 20
ATR_ZSCORE_LOOKBACK = 20
VWAP_DEVIATION_THRESHOLD = 2.0

# Market Structure
SWING_LOOKBACK = 5
EQUAL_LEVEL_TOLERANCE = 0.001       # 0.1% tolerance for equal highs/lows
FVG_MIN_GAP_PERCENT = 0.001
OB_IMPULSE_MIN_CANDLES = 3
OB_IMPULSE_MIN_RANGE_ATR = 2.0

# Risk Management (backtest + demo)
INITIAL_CAPITAL = 10000
RISK_PER_TRADE_PERCENT = 0.01       # 1% risk per trade
MAX_CONCURRENT_POSITIONS = 2
MAX_HOLD_HOURS = 48
SLIPPAGE_PERCENT = 0.0005
TAKER_FEE_PERCENT = 0.0004

# Confidence multipliers for position sizing
# 70-80% conf → 0.5× base risk
# 80-90% conf → 1.0× base risk
# 90%+ conf   → 1.5× base risk

# Scheduler
FAST_PULSE_INTERVAL_SECONDS = 60
FULL_ANALYSIS_INTERVAL_SECONDS = 300
HOURLY_TASK_INTERVAL_SECONDS = 3600
HTF_REGIME_INTERVAL_SECONDS = 14400

# Backtest
BACKTEST_MONTHS = 12
MONTE_CARLO_ITERATIONS = 1000

# Sessions (UTC)
ASIAN_SESSION = ("00:00", "08:00")
LONDON_SESSION = ("08:00", "16:00")
NEW_YORK_SESSION = ("13:00", "21:00")
```

---

## Trade Rules (`backtest/rules.py`)

### `check_entry(signal, bullish_fvg, bearish_fvg, bullish_ob, bearish_ob, current_price, open_positions, rules, current_ts, candle_low, candle_high) → dict | None`

Entry gates (ALL must pass):
1. `open_positions < MAX_CONCURRENT_POSITIONS`
2. `signal.confidence >= 70`
3. `signal.risk_color == "green"`
4. `signal.action_bias` is `long_bias` or `short_bias`
5. Trend confirmation: long needs `uptrend/transition/ranging`, short needs `downtrend/transition/ranging`
6. Price zone: long needs `discount/equilibrium`, short needs `premium/equilibrium`
7. Level touch: candle wick must be within 0.5% of nearest FVG or OB

Returns: `{side, entry_price, stop_loss, tp1, tp2_target (None), size_multiplier, risk_distance, reason, entry_zone, entry_ts, regime_at_entry, risk_color_at_entry}`

### `check_exit(position, current_candle, current_signal, rules) → dict | None`

Exit conditions (checked in priority order):
1. `hours_held >= MAX_HOLD_HOURS` → `time_exit`
2. `risk_color == "red"` → `regime_red_exit`
3. SL breach (conservative — checked before TP) → `stop_loss`
4. TP2 hit → `tp2`
5. TP1 hit (if not already partial) → `tp1`

Returns: `{exit_price, exit_reason, pnl_percent}`

### TP1 Partial Close Logic (in `backtest/simulator.py`)
When TP1 hit: close 50% of position, move stop to `entry_price`, set `tp2_target = entry_price ± risk_distance * 3.0`. Position stays open.

---

## Existing API Endpoints (`api/routes.py`)

| Endpoint | Description |
|---|---|
| `GET /api/status` | Scheduler health, last update times per pair |
| `GET /api/signals?pair=BTCUSDT` | Latest signal + full context for both timeframes |
| `GET /api/signals/history?pair=X&timeframe=1h&limit=100` | Historical signals from DB |
| `GET /api/candles?pair=X&timeframe=4h&limit=200` | Raw OHLCV candle data |
| `GET /api/levels?pair=X` | Active FVGs, OBs, swing points by timeframe |
| `GET /api/regime` | Current 4H macro regime per pair |

CORS enabled for `localhost:3000`, `localhost:8080`, `127.0.0.1:3000`.

### Planned API Endpoints (to be added)
| Endpoint | Description |
|---|---|
| `GET /api/demo/positions` | Open paper positions with MTM P&L |
| `GET /api/demo/trades?limit=50` | Closed paper trade history |
| `GET /api/demo/metrics` | Win rate, return%, Sharpe, max DD, profit factor |
| `GET /api/demo/equity?limit=500` | Equity curve time series |
| `GET /api/analytics/signal-history?pair=X&timeframe=1h&limit=200` | Signal confidence + regime over time |
| `GET /api/analytics/data-quality` | Per pair×tf: OI coverage %, funding coverage % |

---

## Known Data Gaps (CRITICAL for interpreting results)

| Data | Coverage | Issue |
|---|---|---|
| OHLCV | 100% | Fine |
| Open Interest | **0%** from Binance | Binance hard limit: ~30-60 days retention. Requires CoinGlass API key for history. |
| Funding Rate | ~5.8% | Pagination fixed — re-download with `--force-download` |
| Taker Buy/Sell Ratio | ~5.8% | Same, re-download needed (~90 days Binance retention) |
| Long/Short Ratio | 0% | Endpoint wired in data_loader, re-download to populate |

**Impact**: With 0% OI coverage, classifier falls back to volume-only path:
`volume_zscore > 2.0 + price direction` → `green` signal. This is why backtest results look unrealistically good.

### CoinGlass Setup (for real OI data)
```bash
export COINGLASS_API_KEY=<your_key>
python -m backtest.runner --force-download
```
Config: `COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")` in `config.py`

---

## Backtest Results (Last Run: 2025-03-28 → 2026-03-23, BTCUSDT 1h)

| Metric | Value | Note |
|---|---|---|
| Total Trades | 452 | |
| Win Rate | 77.9% | Likely overstated — volume-only fallback |
| Total Return | +945% | Likely overstated |
| Profit Factor | 3.48 | |
| Sharpe Ratio | 13.52 | Unrealistically high |
| Max Drawdown | 2.76% | |
| OI Data Coverage | 0% | Volume fallback used for all signals |

**Realistic expectation after adding CoinGlass OI**: Win rate will drop, return will compress. This is expected and honest.

---

## Signal Generation Pipeline (`_run_full_analysis` in `main.py`)

1. Fetch latest enriched candle (OHLCV + OI + funding + ratios)
2. Write candle to DB; detect and backfill any gaps
3. Load 200-candle rolling window
4. Compute: ATR, VWAP, volume z-score, ATR z-score, VWAP deviation, OI change
5. Detect market structure: swing points, BOS/CHoCH breaks, equal levels, premium/discount zone
6. Detect FVGs (bullish/bearish), update fill status, persist recent 20
7. Detect Order Blocks, update mitigation status, persist recent 20
8. Approximate volume profile → POC
9. Classify signal via `classifier.classify()` → `SignalOutput`
10. Persist full signal row to DB
11. **[PLANNED]** Call `demo_trader.on_signal()` ← integration point
12. Detect recent liquidity sweeps + CHoCH → Telegram alerts
13. Update `live_state[pair]` dict (shared with API routes)
14. Send Telegram signal alert if `confidence >= 70`

---

## Live State Pattern (`main.py`)

```python
live_state: dict[str, dict] = {}
# Per pair: { last_price, last_update_ts, last_signal, macro_regime, liq_levels }

routes.set_live_state(live_state)   # API routes read this for real-time data
```

The same pattern will be used for demo trader:
```python
demo_trader: DemoTrader = ...
routes.set_demo_trader(demo_trader)
```

---

## Planned: Demo Trading Module (`demo/`)

A paper trading engine that:
- Runs inside the existing 300s `full_analysis` scheduler loop
- Calls `backtest/rules.py` functions directly (no logic duplication)
- Persists open positions + closed trades + equity curve to SQLite
- Starts with `INITIAL_CAPITAL = $10,000`
- Uses `asyncio.Lock` to prevent double-entry from concurrent pair processing

### `DemoTrader` key methods
- `load_state()` — restore open positions from DB on restart
- `async on_signal(...)` — process exits then check new entry for one pair×tf
- `record_equity_snapshot(ts)` — called once per full_analysis cycle (not per pair)
- `mark_to_market(position, current_price) → float` — unrealized P&L

---

## Planned: Frontend Dashboard (`frontend/`)

- **React 18 + TypeScript + Vite** (runs on `localhost:3000`)
- **Tailwind CSS** dark theme
- **Recharts** for equity curve + signal history charts
- **TanStack Query v5** for polling (30-120s intervals, no WebSocket needed)
- **Vite proxy**: `/api` → `http://localhost:8000`

### Dashboard Layout
```
┌─────────────────────────────────────────────┐
│  StatusBar: scheduler health, last updates  │
├────────────────────────┬────────────────────┤
│  [Pair Tabs]           │                    │
│  SignalCard × 5        │   DemoPanel        │
│  - RegimeBadge         │   - PerformanceStats│
│  - ConfidenceMeter     │   - EquityCurve    │
│  - IndicatorsPanel     │   - OpenPositions  │
│  - PriceZonesPanel     │   - TradeHistory   │
├────────────────────────┴────────────────────┤
│  [Collapsible] Analytics                    │
│  SignalHistoryChart | DataQualityPanel       │
└─────────────────────────────────────────────┘
```

---

## Key Architectural Decisions

1. **No future leak in backtest**: All rolling calculations use `candles[:i+1]` slices only.
2. **Signal cache pattern**: Pre-compute signals once as pickle → iterate rules in sub-second for repeated backtest runs.
3. **WAL mode SQLite**: Concurrent reads (API) + writes (scheduler) safe without extra locking.
4. **Two-loop scheduler**: Fast pulse (60s) for price alerts, full analysis (300s) for signals. Keeps Telegram alerts responsive without re-running expensive indicators.
5. **Demo trader uses `asyncio.Lock`**: 10 concurrent `on_signal` calls (5 pairs × 2 TF) could both pass the `open_positions < 2` check without serialization.
6. **Demo metrics reuse `backtest/metrics.py`**: Thin dict→dataclass adapter, no logic copy.
7. **`TradeRecord` dataclass** (in `backtest/simulator.py`) fields: `id, side, entry_price, exit_price, entry_ts, exit_ts, exit_reason, pnl_usd, pnl_percent, fee_usd, slippage_usd, net_pnl_usd, size_usd, regime_at_entry, risk_color_at_entry, entry_zone_type, confidence_at_entry, hold_hours, had_fvg_overlap`

---

## Enhanced Plan — Feature Additions

### Feature Group 1: Data Quality Enhancements

**1A. Regime Distribution** — `GET /api/analytics/regime-distribution?pair=X&timeframe=1h&lookback=500`
- Query `signals` table, group by `regime_state`, return counts + percentages
- Frontend: `RegimeDistribution.tsx` — donut chart (Recharts PieChart) per pair

**1B. Confidence Histogram** — `GET /api/analytics/confidence-distribution?pair=X&timeframe=1h&lookback=500`
- Bucket `confidence` into 10-point bins, return counts + mean/median/std_dev
- Frontend: `ConfidenceHistogram.tsx` — BarChart with red→yellow→green gradient fill

**1C. Stale Data Alerts** — enhance `GET /api/status`
- Add per-pair staleness flags: `candles`, `signals`, `oi_data`, `funding`
- Thresholds: candles/signals >600s = amber, >1200s = red; OI always stale if never non-zero; funding >8h = amber
- Frontend: status dots on `StatusBar.tsx` + `StaleDataBanner.tsx` persistent warning

### Feature Group 2: Signal Reasoning + Mini Price Charts

**2A. Signal Reasoning** — add `reasoning` JSON field to signals
Structure:
```json
{
  "regime_factors": [{"factor", "value", "threshold", "direction", "impact", "note?"}],
  "confidence_breakdown": {"base_score", "regime_bonus", "zone_bonus", "volume_bonus", "oi_bonus", "penalties", "final"},
  "entry_conditions": {"in_fvg", "fvg_type", "in_ob", "price_vs_vwap", "atr_filter_passed"},
  "summary": "plain-English explanation"
}
```
- Store in `metadata` JSON column of `signals` table (no schema change needed)
- New endpoint: `GET /api/signals/{pair}/{timeframe}/reasoning`
- Frontend: `SignalReasoning.tsx` — expandable panel with factor list + confidence waterfall chart

**2B. Mini Price Charts** — `GET /api/charts/price-history?pair=X&timeframe=1h&limit=100`
- Returns candles + trade_markers (entry/tp1/exit) + zone overlays (FVG/OB bounds)
- Frontend: `MiniPriceChart.tsx` using **lightweight-charts** (TradingView open-source, ~45KB)
  - Candlestick chart, zone rectangles, trade markers (▲▼ triangles), dotted entry→exit lines

### Feature Group 3: Live Demo Trades with Leverage

**3A. Leverage schema additions** (to `demo_positions` and `demo_trades`):
```sql
ALTER TABLE demo_positions ADD COLUMN leverage REAL NOT NULL DEFAULT 10.0;
ALTER TABLE demo_positions ADD COLUMN margin_usd REAL NOT NULL DEFAULT 0.0;
ALTER TABLE demo_positions ADD COLUMN liquidation_price REAL;
ALTER TABLE demo_trades ADD COLUMN leverage REAL NOT NULL DEFAULT 10.0;
ALTER TABLE demo_trades ADD COLUMN margin_usd REAL NOT NULL DEFAULT 0.0;
ALTER TABLE demo_trades ADD COLUMN pnl_leveraged_pct REAL NOT NULL DEFAULT 0.0;
```

**New config.py constants:**
```python
DEFAULT_LEVERAGE = 10.0
MAINTENANCE_MARGIN_RATE = 0.005  # 0.5% Binance-style
```

**Leverage P&L formulas:**
```python
# Liquidation price
liq_long  = entry_price * (1 - (1/leverage) + MAINTENANCE_MARGIN_RATE)
liq_short = entry_price * (1 + (1/leverage) - MAINTENANCE_MARGIN_RATE)

# Leveraged P&L
price_change_pct = (current - entry) / entry  # flip sign for short
pnl_pct_leveraged = price_change_pct * leverage
pnl_usd = margin_usd * pnl_pct_leveraged
```

**Enhanced `/api/demo/positions` response includes:**
- `leverage`, `margin_usd`, `liquidation_price`, `risk_to_liq_pct`
- `unrealized_pnl: {usd, pct_unleveraged, pct_leveraged, roi_on_margin}`
- `risk_reward: {current_rr, target_rr_tp1, target_rr_tp2}`
- `portfolio_summary: {total_margin_used, total_unrealized_pnl_usd, total_notional_exposure, effective_leverage, margin_utilization_pct, available_margin}`

**3B. Frontend components:**
- `PortfolioSummary.tsx` — 4 stat cards: margin used, effective leverage, unrealized P&L, open count
- `LiquidationGauge.tsx` — progress bar from entry to liquidation with current price marker
- `OpenPositionsTable.tsx` — redesigned with leverage badge, liq price, ROI%, expandable rows
- `TradeHistory.tsx` — leverage col, ROI%, exit reason badges, pagination, filter bar

---

## All Planned API Endpoints (Complete List)

### Demo Trading (4)
| Endpoint | Description |
|---|---|
| `GET /api/demo/positions` | Open positions with leveraged MTM P&L + portfolio summary |
| `GET /api/demo/trades?limit=50` | Closed trade history with leverage + ROI% |
| `GET /api/demo/metrics` | Win rate, return%, Sharpe, max DD, profit factor |
| `GET /api/demo/equity?limit=500` | Equity curve time series |

### Analytics (5)
| Endpoint | Description |
|---|---|
| `GET /api/analytics/signal-history?pair=X&timeframe=1h` | Signal confidence + regime over time |
| `GET /api/analytics/data-quality` | Per pair×tf: OI coverage %, funding coverage % |
| `GET /api/analytics/regime-distribution?pair=X&timeframe=1h` | Time spent per regime |
| `GET /api/analytics/confidence-distribution?pair=X&timeframe=1h` | Confidence score histogram |
| `GET /api/signals/{pair}/{timeframe}/reasoning` | Latest signal reasoning breakdown |

### Charts (1)
| Endpoint | Description |
|---|---|
| `GET /api/charts/price-history?pair=X&timeframe=1h&limit=100` | Candles + trade markers + zone overlays |

---

## Frontend Stack (Final)

| Library | Purpose |
|---|---|
| React 18 + TypeScript + Vite | Framework + dev server |
| Tailwind CSS | Styling (dark theme) |
| **shadcn/ui** | UI components (Card, Badge, Table, Tooltip, Progress, Tabs) |
| Recharts | Equity curve, confidence histogram, regime donut, signal history |
| **lightweight-charts** | Candlestick charts with zone overlays + trade markers (~45KB) |
| TanStack Query v5 | Polling with stale-while-revalidate |
| Vite proxy | `/api` → `http://localhost:8000` (avoids CORS in dev) |

shadcn MCP: configured in `.mcp.json` → `npx shadcn@latest mcp`

---

## Complete Frontend Component List

### New Components
| Component | Location | Description |
|---|---|---|
| `RegimeDistribution.tsx` | `components/analytics/` | Donut chart: regime time distribution |
| `ConfidenceHistogram.tsx` | `components/analytics/` | Bar chart: confidence score buckets |
| `StaleDataBanner.tsx` | `components/` | Persistent critical data warning banner |
| `SignalReasoning.tsx` | `components/signals/` | Expandable factor breakdown + confidence waterfall |
| `MiniPriceChart.tsx` | `components/signals/` | lightweight-charts candlestick + trade markers + zones |
| `PortfolioSummary.tsx` | `components/demo/` | 4-card portfolio overview |
| `LiquidationGauge.tsx` | `components/demo/` | Proximity-to-liquidation visual indicator |

### Modified Components
| Component | Changes |
|---|---|
| `StatusBar.tsx` | Add per-pair staleness dots with hover tooltips |
| `SignalCard.tsx` | Add `SignalReasoning` + `MiniPriceChart` slots |
| `OpenPositions.tsx` | Redesign: leverage, liq price, ROI%, expandable rows |
| `TradeHistory.tsx` | Add leverage column, ROI%, filters, pagination |
| `DemoPanel.tsx` | Add `PortfolioSummary` above positions table |
| `DataQualityPanel.tsx` | Integrate regime + confidence charts |

### All Polling Hooks
| Hook | Endpoint | Interval |
|---|---|---|
| `useStatus` | `/api/status` | 30s |
| `useSignals(pair)` | `/api/signals?pair=X` | 60s |
| `useDemoPositions` | `/api/demo/positions` | 30s |
| `useDemoMetrics` | `/api/demo/metrics` | 60s |
| `useDemoEquity` | `/api/demo/equity` | 60s |
| `useDemoTrades` | `/api/demo/trades` | 60s |
| `useSignalHistory(pair)` | `/api/analytics/signal-history` | 120s |
| `useDataQuality` | `/api/analytics/data-quality` | 300s |
| `useRegimeDistribution(pair,tf)` | `/api/analytics/regime-distribution` | 300s |
| `useConfidenceDistribution(pair,tf)` | `/api/analytics/confidence-distribution` | 300s |
| `useSignalReasoning(pair,tf)` | `/api/signals/{pair}/{tf}/reasoning` | 60s |
| `usePriceHistory(pair,tf)` | `/api/charts/price-history` | 60s |

---

## Implementation Phases

| Phase | Features |
|---|---|
| **Phase 1** | Leverage in trader.py + enhanced positions API + OpenPositionsTable redesign |
| **Phase 2** | Signal reasoning (backend + frontend) + stale data alerts |
| **Phase 3** | Mini price charts with trade markers (lightweight-charts) |
| **Phase 4** | Regime distribution + confidence histogram |
