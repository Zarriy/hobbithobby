# Crypto Signal Engine — Project Reference

> Read this file for full context before touching any code. It covers architecture, data models, signal logic, deployment, and current state of everything built.

---

## What This Is

A **crypto risk posture system** (not a prediction engine). It filters when NOT to trade and identifies confluent entry zones using market structure + order flow data. Signals are generated for 5 Binance Futures pairs on 1h and 4h timeframes.

**It is not a "buy here" bot** — it surfaces regime state, risk color, and key price levels so a trader can make informed decisions. It also runs dual paper trading in the background to track theoretical performance.

---

## Stack

| Layer | Tech |
|---|---|
| Language | Python 3.13 |
| API server | FastAPI + uvicorn (port **8001**) |
| Scheduler | APScheduler (AsyncIO) |
| Database | SQLite in WAL mode (`db/signals.db`) |
| HTTP client | httpx (async, with retry) |
| OI data | CoinGlass API (2+ years history vs Binance ~30 days) |
| Alerts | Telegram Bot API |
| Frontend | React 18 + TypeScript + Vite (Tailwind CSS, Recharts, shadcn/ui) |
| Deployment | VPS (backend) + Netlify (frontend) |
| Domain | hobbithobby.quest (Namecheap DNS) |
| No | Docker, Redis, WebSockets, ORM |

---

## Run Commands

```bash
# Install deps
pip install -r requirements.txt

# Run live signal engine (API at http://localhost:8001)
# Must set COINGLASS_API_KEY in .env for real OI data
python main.py

# Run backtest WITH CoinGlass OI (realistic results)
export COINGLASS_API_KEY=<your_key>
python -m backtest.runner --pair BTCUSDT --months 12 --quick --force-download

# Run backtest WITHOUT OI (volume-only fallback, inflated results)
unset COINGLASS_API_KEY
python -m backtest.runner --pair BTCUSDT --months 12 --quick --regen-cache --force-download

# API docs (auto-generated)
http://localhost:8001/docs
```

### VPS Process Management (tmux)
```bash
# Backend runs in tmux — DO NOT use systemd
tmux new -s signal-engine
python main.py
# Ctrl+B, D to detach

tmux attach -t signal-engine   # reattach
```

---

## Deployment

### Backend (VPS)
- **URL**: `https://api.hobbithobby.quest`
- **Port**: 8001 (nginx proxies 443 → 8001)
- **Process**: tmux session `signal-engine`
- **Config file**: `/home/signalbot/app/.env` — contains `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `COINGLASS_API_KEY`, `FRONTEND_URL`
- **Nginx config**: `/etc/nginx/sites-available/signal-api`

### Frontend (Netlify)
- **URL**: `https://hobbithobby.quest`
- **Build**: `npm run build` in `frontend/` — outputs `frontend/dist/`
- **Config**: `frontend/netlify.toml` sets `VITE_API_URL=https://api.hobbithobby.quest`
- **Local dev**: `frontend/.env.local` sets `VITE_API_URL=https://api.hobbithobby.quest` (points local dev to prod API)
- **Proxy**: `vite.config.ts` proxies `/api` → `localhost:8001` for local dev without `.env.local`

### CORS
Hardcoded in `main.py` (not env var — env var approach had issues on VPS):
```python
allow_origins=[
    "http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000",
    "https://hobbithobby.quest", "https://www.hobbithobby.quest",
]
```

---

## Directory Map

```
crypto-signal-engine/
├── CLAUDE.md                  ← you are here
├── config.py                  ← ALL tunable parameters (thresholds, pairs, intervals)
├── main.py                    ← FastAPI app + dual-loop scheduler + two DemoTrader instances
├── requirements.txt
├── .env.example               ← template for VPS .env file
├── live-movemint.md           ← step-by-step deployment guide
│
├── alerts/
│   └── telegram.py            ← Telegram alert builder + dedup sender
│
├── api/
│   └── routes.py              ← All REST endpoints (fully implemented)
│
├── core/
│   ├── fetcher.py             ← Binance Futures + CoinGlass API client (async, rate-limited)
│   ├── backfill.py            ← Historical candle gap detection + fill (uses CoinGlass when key set)
│   └── store.py               ← SQLite WAL wrapper — all DB access
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
│   ├── report.py              ← HTML/JSON report generation
│   └── stress.py              ← Monte Carlo (1000 iter), walk-forward, sensitivity
│
├── demo/                      ← LIVE — paper trading module
│   ├── trader.py              ← DemoTrader class with mode (aggressive/conservative)
│   ├── store.py               ← 3 DB tables with mode column
│   └── metrics.py             ← Adapter: demo_trades → TradeRecord → calculate_metrics()
│
├── frontend/                  ← LIVE — React dashboard
│   ├── netlify.toml           ← Netlify build config
│   ├── .env.local             ← Local dev env (points to prod API)
│   ├── vite.config.ts         ← Proxy /api → localhost:8001
│   └── src/
│       ├── App.tsx
│       ├── api/client.ts      ← All API calls with mode params
│       ├── hooks/useApi.ts    ← TanStack Query hooks (all demo hooks accept mode)
│       ├── types/api.ts       ← Full TypeScript type definitions
│       └── components/
│           ├── analytics/     ← RegimeDistribution, ConfidenceHistogram, DataQualityPanel, SignalHistoryChart
│           ├── demo/          ← DemoPanel (3 tabs), PerformanceStats, EquityCurve, OpenPositions, TradeHistory, DemoComparison
│           ├── layout/        ← Header, Sidebar
│           ├── signals/       ← SignalCard, IndicatorsPanel, ConfidenceMeter, PriceZonesPanel, RegimeBadge, SignalReasoning, MiniPriceChart
│           └── ui/            ← shadcn/ui components
│
├── db/
│   └── signals.db             ← SQLite database (auto-created on startup)
│
├── data/historical/           ← CSV price data + signal cache pickles
│
└── reports/                   ← Auto-generated HTML backtest reports
```

---

## Scheduler Loops (`main.py`)

| Loop | Interval | What it does |
|---|---|---|
| `fast_pulse` | 60s | Fetch latest price + taker ratio. Alert on >3% moves. |
| `full_analysis` | 300s | Full signal pipeline for all pairs×timeframes. Calls both DemoTraders. |
| `hourly_task` | 3600s | Recalculate liquidation levels, update FVG/OB statuses. |
| `regime_task` | 14400s (4h) | Macro regime analysis on 4H candles. |

All loops use `asyncio.gather()` — concurrent across all pairs.

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
| Regime | Conditions | Action Bias |
|---|---|---|
| `accumulation` | price up + OI up + high volume + no extreme funding | `long_bias` |
| `distribution` | price down + OI up + high volume | `short_bias` |
| `short_squeeze` | price up + OI up + extreme positive funding | `long_bias` |
| `long_liquidation` | price down + OI up + extreme negative funding OR price down + OI down | `short_bias` |
| `deleveraging` | OI unwinding + high volume | `reduce_exposure` (red signal) |
| `coiled_spring` | flat price + OI spike + low volume | `stay_flat` (yellow signal) |

**Critical**: Without OI data (`COINGLASS_API_KEY` not set), the classifier falls back to `volume_zscore > 2.0 + price direction` only. This produces inflated backtest results. With OI data, the full regime matrix activates.

---

## SQLite Schema (`db/signals.db`)

### Core Tables (5)

**`candles`** — OHLCV + enriched data
`pair, timeframe, timestamp, open, high, low, close, volume, open_interest, funding_rate, long_short_ratio, taker_buy_sell_ratio`

**`signals`** — All signal output fields
`pair, timeframe, timestamp, regime_state, risk_color, confidence, trend_state, price_zone, nearest_bullish_fvg (JSON), nearest_bearish_fvg (JSON), nearest_bullish_ob (JSON), nearest_bearish_ob (JSON), equal_highs (JSON), equal_lows (JSON), volume_zscore, oi_change_percent, funding_rate, taker_ratio, atr, vwap_deviation, metadata (JSON: {poc, macro_regime, action_bias, reasoning})`

**`fair_value_gaps`** — FVG detection + fill tracking
**`order_blocks`** — OB detection + mitigation
**`swing_points`** — Market structure

### Demo Trading Tables (3) — added by `demo/store.py`

**`demo_positions`** — Open + closed paper positions
`..., leverage, margin_usd, liquidation_price, tp1_hit, partial_exit_pnl, status, mode`

**`demo_trades`** — Closed trade ledger (write-once)
`..., leverage, margin_usd, pnl_leveraged_pct, hold_hours, mode`

**`demo_equity`** — Equity curve snapshots
`id, timestamp, mode, equity, open_pnl, open_count` — **UNIQUE(timestamp, mode)**

> `mode` column on all 3 tables: `'aggressive'` or `'conservative'`. Auto-migrated on startup if column missing.

---

## Dual Demo Trading System

Two `DemoTrader` instances run simultaneously, processing every signal in `_run_full_analysis`:

| Mode | `regime_is_green` | Enters on | Expected behavior |
|---|---|---|---|
| `aggressive` | `False` | yellow + green signals (conf ≥ 70) | More trades, higher theoretical return |
| `conservative` | `True` | green signals only (conf ≥ 70) | Fewer trades, requires real OI data to produce greens |

### Entry Gates (ALL must pass)
1. `open_positions < 2`
2. `confidence >= 70`
3. `risk_color == 'green'` (conservative) OR `risk_color in ['green', 'yellow']` (aggressive)
4. `action_bias` is `long_bias` or `short_bias`
5. Trend confirmation (long ↔ uptrend/ranging/transition; short ↔ downtrend/ranging/transition)
6. Price zone (long ↔ discount/equilibrium; short ↔ premium/equilibrium)
7. **Candle wick within 0.5% of nearest FVG or OB** — most selective gate

### Exit Conditions (priority order)
1. Hold ≥ 48h → `time_exit`
2. Signal turns red → `regime_red_exit`
3. Stop loss breach → `stop_loss`
4. TP2 hit (3R) → `tp2`
5. TP1 hit (1.5R) → partial close 50%, move stop to breakeven, set TP2

### Position Sizing
- Base risk = 1% of equity × size_multiplier
- conf 70–79 → 0.5× | conf 80–89 → 1.0× | conf 90+ → 1.5×
- Leverage: 10× (default)
- Liquidation: `entry * (1 - 1/lev + 0.005)` for long, `entry * (1 + 1/lev - 0.005)` for short

---

## API Endpoints (all implemented)

### Signals
| Endpoint | Description |
|---|---|
| `GET /api/status` | Scheduler health |
| `GET /api/status/detail` | Per-pair staleness flags (signals/candles/OI/funding) |
| `GET /api/signals?pair=X` | Latest signal + context for both timeframes |
| `GET /api/signals/history?pair=X&timeframe=1h&limit=100` | Historical signals |
| `GET /api/signals/{pair}/{tf}/reasoning` | Signal reasoning breakdown |
| `GET /api/candles?pair=X&timeframe=4h&limit=200` | Raw OHLCV |
| `GET /api/levels?pair=X` | Active FVGs, OBs, swing points |
| `GET /api/regime` | Current 4H macro regime per pair |

### Demo Trading (all accept `?mode=aggressive|conservative`)
| Endpoint | Description |
|---|---|
| `GET /api/demo/positions?mode=X` | Open positions with leveraged MTM P&L + portfolio summary |
| `GET /api/demo/trades?limit=50&mode=X` | Closed trade history |
| `GET /api/demo/metrics?mode=X` | Win rate, return%, Sharpe, max DD, profit factor |
| `GET /api/demo/equity?limit=500&mode=X` | Equity curve time series |
| `GET /api/demo/comparison` | Side-by-side metrics for both modes |

### Analytics
| Endpoint | Description |
|---|---|
| `GET /api/analytics/signal-history?pair=X&timeframe=1h` | Signal confidence + regime over time |
| `GET /api/analytics/data-quality` | Per pair×tf: OI coverage %, funding coverage % |
| `GET /api/analytics/regime-distribution?pair=X&timeframe=1h` | Time spent per regime |
| `GET /api/analytics/confidence-distribution?pair=X&timeframe=1h` | Confidence histogram |
| `GET /api/charts/price-history?pair=X&timeframe=1h&limit=100` | Candles + trade markers + FVG/OB zones |

---

## CoinGlass OI Integration

- **Key location**: `COINGLASS_API_KEY` in VPS `.env` and `config.py` (`os.getenv`)
- **Used in**: `core/backfill.py` (historical backfill) and `core/fetcher.py` (`fetch_coinglass_oi_history`)
- **Fallback**: When key absent, `backfill.py` falls back to Binance OI (~30 day retention only)
- **Coverage**: CoinGlass provides 2+ years of hourly OI history per pair
- **Format**: `fetch_coinglass_oi_history(pair, interval='1h', start_time, end_time, limit=4380)`

### Why it matters
- Without OI: classifier uses `volume_zscore > 2.0` only → inflated backtest WR ~77-80%
- With OI: full regime matrix activates → realistic WR ~71-79%, Sharpe 2.4–3.2

---

## Backtest Results (12 months: Mar 2025 – Mar 2026)

### With CoinGlass OI (realistic)
| Pair | Trades | Win Rate | Return | Sharpe | Max DD | Final Equity |
|------|--------|----------|--------|--------|--------|-------------|
| BTCUSDT | 347 | 79.4% | +465% | 3.23 | 3.58% | $56,515 |
| SOLUSDT | 292 | 74.7% | +292% | 2.93 | 3.35% | $39,166 |
| XRPUSDT | 272 | 72.8% | +229% | 2.63 | 2.67% | $32,932 |
| ETHUSDT | 286 | 72.0% | +206% | 2.52 | 2.90% | $30,558 |
| TAOUSDT | 224 | 71.0% | +200% | 2.40 | 4.62% | $29,951 |

### Without OI (volume fallback — inflated, do not trust)
| Pair | Trades | Win Rate | Return | Sharpe | Max DD | Final Equity |
|------|--------|----------|--------|--------|--------|-------------|
| BTCUSDT | 444 | 79.5% | +1,436% | 4.39 | 2.47% | $153,551 |
| XRPUSDT | 368 | 76.9% | +858% | 3.84 | 2.91% | $95,824 |
| SOLUSDT | 383 | 74.7% | +819% | 3.64 | 2.46% | $91,907 |
| ETHUSDT | 359 | 77.7% | +691% | 3.66 | 2.71% | $79,146 |
| TAOUSDT | 286 | 72.4% | +346% | 2.92 | 2.14% | $44,597 |

**Key insight**: Without OI, 20–35% more trades fire (volume-only greens are easier to trigger), inflating returns 2–4×. The Sharpe drop from ~4 to ~2.4 when adding OI represents the real cost of proper regime filtering.

---

## Key Config Thresholds (`config.py`)

```python
# Signal Quality
CONFIDENCE_THRESHOLD_TRADE = 70
OI_CHANGE_NOISE_FLOOR = 0.005
OI_CHANGE_NOTABLE = 0.015
OI_CHANGE_LOOKBACK = 4
FUNDING_RATE_EXTREME_POSITIVE = 0.0003
FUNDING_RATE_EXTREME_NEGATIVE = -0.0003
VOLUME_ZSCORE_LOOKBACK = 20

# Risk Management
INITIAL_CAPITAL = 10000
RISK_PER_TRADE_PERCENT = 0.01       # 1% per trade
MAX_CONCURRENT_POSITIONS = 2
MAX_HOLD_HOURS = 48
SLIPPAGE_PERCENT = 0.0005
TAKER_FEE_PERCENT = 0.0004
DEFAULT_LEVERAGE = 10.0
MAINTENANCE_MARGIN_RATE = 0.005     # 0.5% Binance-style

# Scheduler
FAST_PULSE_INTERVAL_SECONDS = 60
FULL_ANALYSIS_INTERVAL_SECONDS = 300
HOURLY_TASK_INTERVAL_SECONDS = 3600
HTF_REGIME_INTERVAL_SECONDS = 14400
```

---

## Signal Generation Pipeline (`_run_full_analysis` in `main.py`)

Called every 300s for each (pair, timeframe) pair — 10 concurrent calls:

1. Fetch latest enriched candle (OHLCV + OI + funding + ratios)
2. Write candle to DB; detect and backfill any gaps
3. Load 200-candle rolling window
4. Compute: ATR, VWAP, volume z-score, ATR z-score, VWAP deviation, OI change
5. Detect market structure: swing points, BOS/CHoCH breaks, equal levels, premium/discount zone
6. Detect FVGs (bullish/bearish), update fill status, persist recent 20
7. Detect Order Blocks, update mitigation status, persist recent 20
8. Approximate volume profile → POC
9. Classify signal → `SignalOutput`
10. Build reasoning JSON (stored in `signals.metadata`)
11. Persist full signal row to DB
12. **Call both demo traders** (`demo_trader_aggressive.on_signal(...)`, `demo_trader_conservative.on_signal(...)`)
13. Detect recent liquidity sweeps + CHoCH → Telegram alerts
14. Update `live_state[pair]`
15. Send Telegram signal alert if `confidence >= 70`

---

## Frontend Components (all implemented)

### Layout
| Component | Description |
|---|---|
| `Header.tsx` | Top bar with status dot + last update time |
| `Sidebar.tsx` | Pair selector with regime dot + confidence |

### Signal Display
| Component | Description |
|---|---|
| `SignalCard.tsx` | Main card: timeframe tabs, regime badge, confidence, indicators, price zones, reasoning, mini chart |
| `RegimeBadge.tsx` | Color-coded regime + risk_color pill |
| `ConfidenceMeter.tsx` | Circular/linear progress 0–100 |
| `IndicatorsPanel.tsx` | Vol Z-Score, OI Change (shows "CoinGlass OI ✓" or "vol fallback"), Funding, Taker Ratio, ATR, VWAP Dev |
| `PriceZonesPanel.tsx` | FVG, OB, equal highs/lows key levels |
| `SignalReasoning.tsx` | Expandable factor breakdown |
| `MiniPriceChart.tsx` | Candlestick + FVG/OB zones + trade markers |

### Demo Panel (tabbed: Aggressive | Conservative | Compare)
| Component | Description |
|---|---|
| `DemoPanel.tsx` | 3-tab wrapper — amber=Aggressive, green=Conservative, Compare |
| `PerformanceStats.tsx` | KPI stat cards: Return, Win Rate, Profit Factor, Max DD, Sharpe |
| `EquityCurve.tsx` | Recharts area chart of equity over time |
| `OpenPositions.tsx` | Table with leverage, liq price, ROI%, expandable rows + `LiquidationGauge` |
| `TradeHistory.tsx` | Paginated table, filter by exit reason, leverage + ROI% columns |
| `DemoComparison.tsx` | Side-by-side metrics table; ↑ arrow marks the winner per metric |

### Analytics (collapsible section)
| Component | Description |
|---|---|
| `RegimeDistribution.tsx` | Donut chart: time spent per regime state |
| `ConfidenceHistogram.tsx` | Bar chart: confidence score distribution |
| `SignalHistoryChart.tsx` | Line chart: confidence + risk_color over time |
| `DataQualityPanel.tsx` | OI/funding coverage % per pair×tf |

### All Polling Hooks (`hooks/useApi.ts`)
| Hook | Endpoint | Interval |
|---|---|---|
| `useStatusDetail()` | `/api/status/detail` | 30s |
| `useSignals(pair)` | `/api/signals?pair=X` | 60s |
| `useDemoPositions(mode)` | `/api/demo/positions?mode=X` | 30s |
| `useDemoMetrics(mode)` | `/api/demo/metrics?mode=X` | 60s |
| `useDemoEquity(limit, mode)` | `/api/demo/equity?mode=X` | 60s |
| `useDemoTrades(limit, mode)` | `/api/demo/trades?mode=X` | 60s |
| `useDemoComparison()` | `/api/demo/comparison` | 60s |
| `useSignalHistory(pair, tf)` | `/api/analytics/signal-history` | 120s |
| `useDataQuality()` | `/api/analytics/data-quality` | 300s |
| `useRegimeDistribution(pair, tf)` | `/api/analytics/regime-distribution` | 300s |
| `useConfidenceDistribution(pair, tf)` | `/api/analytics/confidence-distribution` | 300s |
| `useSignalReasoning(pair, tf)` | `/api/signals/{pair}/{tf}/reasoning` | 60s |
| `usePriceHistory(pair, tf)` | `/api/charts/price-history` | 60s |

---

## Key Architectural Decisions

1. **No future leak in backtest**: All rolling calculations use `candles[:i+1]` slices only.
2. **Signal cache pattern**: Pre-compute signals once as pickle → iterate rules in sub-second for repeated backtest runs.
3. **WAL mode SQLite**: Concurrent reads (API) + writes (scheduler) safe without extra locking.
4. **Two-loop scheduler**: Fast pulse (60s) for price alerts, full analysis (300s) for signals.
5. **Two DemoTrader instances** with `asyncio.Lock` each: 10 concurrent `on_signal` calls (5 pairs × 2 TF) safely serialized per trader.
6. **`mode` column** on all demo tables: aggressive/conservative rows coexist in same tables, zero schema duplication.
7. **Demo metrics reuse `backtest/metrics.py`**: Thin dict→dataclass adapter in `demo/metrics.py`, no logic copy.
8. **CORS hardcoded** (not env var): env var approach failed to pick up on VPS. Hardcoded both `hobbithobby.quest` and `www.hobbithobby.quest`.
9. **Port 8001** (not 8000): 8000 conflicted with another service running on the VPS.
10. **CoinGlass in backfill, not just backtest**: `core/backfill.py` uses CoinGlass when key is set, so the live engine also gets real OI data on startup backfill.

---

## Data Quality

| Data | Coverage (with CoinGlass key) | Coverage (without) |
|---|---|---|
| OHLCV | 100% | 100% |
| Open Interest | ~95%+ (CoinGlass 2yr history) | ~0% (Binance 30-day only) |
| Funding Rate | ~60% (Binance 90-day retention) | ~60% |
| Taker Buy/Sell | ~60% | ~60% |

**Without `COINGLASS_API_KEY`**: Conservative demo trader will almost never trade (no green signals). Aggressive trader will trade on volume-only yellow signals.

**To activate conservative trader**: Add `COINGLASS_API_KEY` to VPS `.env`, restart engine. OI will be backfilled on startup and green signals will begin generating.

---

## Live State Pattern (`main.py`)

```python
live_state: dict[str, dict] = {}
# Per pair: { last_price, last_update_ts, last_signal, macro_regime, liq_levels }

demo_trader_aggressive: DemoTrader  # mode='aggressive', TradeRule(regime_is_green=False)
demo_trader_conservative: DemoTrader  # mode='conservative', TradeRule(regime_is_green=True)

routes.set_live_state(live_state)
routes.set_demo_traders(demo_trader_aggressive, demo_trader_conservative)
```
