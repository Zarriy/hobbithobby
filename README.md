# Crypto Signal Engine

A local Python-based crypto market analysis system. Classifies market regimes, identifies tactical entry zones, and delivers risk posture signals via Telegram. Includes a full backtesting framework.

**This is a risk posture system, not a prediction engine.** Its primary value is knowing when NOT to trade and where to enter when conditions align.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
export TELEGRAM_BOT_TOKEN=your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id

# 3. Run live signal engine
python main.py

# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

---

## Backtesting

```bash
# Full backtest (12 months, BTC 1h)
python -m backtest.runner

# Custom parameters
python -m backtest.runner --pair BTCUSDT --months 12 --confidence 70

# Quick run (no stress tests)
python -m backtest.runner --quick

# Stress tests only (uses cached signals)
python -m backtest.runner --stress-only

# Force re-download data
python -m backtest.runner --force-download

# Regenerate signal cache
python -m backtest.runner --regen-cache
```

Reports are saved to `reports/backtest_*.html`.

---

## Architecture

```
Fast Pulse (60s)    — price + taker ratio check, emergency alerts
Full Analysis (5m)  — complete pipeline: indicators, FVGs, OBs, structure, classifier
Hourly Task (1h)    — liquidation level recalculation
4H Regime (4h)      — macro regime context update
```

### Signal Logic

The classifier maps market conditions to regime states:

| Regime | Condition | Risk | Bias |
|--------|-----------|------|------|
| Accumulation | Price↑, OI↑, Vol↑, Funding neutral | 🟢 | Long |
| Distribution | Price↓, OI↑, Vol↑, Funding neutral | 🟢 | Short |
| Short Squeeze | Price↑, Funding extreme+ | 🟡 | Flat |
| Long Liquidation | Price↓, OI↓, Vol↑ | 🔴 | Reduce |
| Coiled Spring | Price flat, OI spike | 🟡 | Wait |
| Deleveraging | OI↓↓, Vol↑ | 🔴 | Reduce |

### Entry Zones

Trades are taken only at confluent structural levels:
- **FVG** (Fair Value Gap) — price imbalance zones
- **Order Block** — last opposing candle before impulsive move
- **FVG + OB overlap** — highest confluence, best edge

### Backtest Rules

All mechanical. No discretion:
1. Regime color must be **green**
2. Confidence ≥ 70
3. BOS confirmed in trade direction (4H)
4. Price in discount (longs) or premium (shorts)
5. Price touches FVG or OB zone
6. Stop: below zone low (longs) / above zone high (shorts)
7. TP1: 1.5R → close 50%, move stop to breakeven
8. TP2: next opposing level or 3R
9. Regime exit: if risk color → RED, exit immediately
10. Time exit: 48h max hold

---

## API Endpoints

```
GET /api/status                           — system health
GET /api/signals?pair=BTCUSDT             — latest signal
GET /api/signals/history?pair=BTCUSDT     — signal history
GET /api/candles?pair=BTCUSDT&timeframe=4h — raw candles
GET /api/levels?pair=BTCUSDT              — active FVGs, OBs, swings
GET /api/regime                           — macro regime per pair
```

---

## Configuration

All parameters in `config.py`. Key settings:

```python
PAIRS = ["BTCUSDT", "ETHUSDT"]
CONFIDENCE_THRESHOLD_TRADE = 70    # Minimum confidence for alerts
FVG_MIN_GAP_PERCENT = 0.001        # Filter tiny FVGs
SWING_LOOKBACK = 5                 # Candles each side for swing detection
MAX_HOLD_HOURS = 48                # Backtest time-based exit
```

---

## Telegram Alert Format

```
🟢 BTC-USDT | ACCUMULATION
Trend: Uptrend | HTF: Markup
Price: $67,240 | Zone: Discount (below midpoint)

Regime: OI +3.8% | Vol 2.1σ | Funding -0.012%
Taker: 61% buy | Confidence: 82/100

Nearest levels:
  → Bullish FVG: $66,180-$66,420 (unfilled)
  → Bullish OB: $65,880-$66,050 (FVG overlap ✓)
  → Equal lows: $65,500 (liquidity below)
  → POC: $67,100

Session: London open in 40min
Volatility: Low (ATR z-score: -0.8)
Risk posture: LONG BIAS
```

---

## Notes

- **No future data leakage**: every rolling calculation uses only data available at that candle index
- **Fees and slippage included**: 0.04% taker fee + 0.05% slippage per side
- **Conservative SL**: if both SL and TP could trigger in same candle, SL wins
- **Signal cache**: signal computation and trade simulation are independent — cached signals make rule-tuning sub-second
- SQLite with WAL mode — no external database required
- No Docker, no Redis. Single terminal command to run.
