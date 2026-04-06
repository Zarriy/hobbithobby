# CoinGlass API V4 — Reference

> Saved 2026-03-27. Source: https://docs.coinglass.com/reference

---

## Overview

CoinGlass API V4 is a professional-grade crypto market data and analytics API delivering unified access to real-time and historical data across derivatives, options, spot, ETF and on-chain markets from major global cryptocurrency exchanges (Binance, OKX, Bybit, Coinbase).

**Covers:** 2,000+ crypto derivatives instruments and global options products.

---

## Base URL

```
https://open-api-v4.coinglass.com
```

> ⚠️ The old V3 base `https://open-api.coinglass.com` is deprecated and returns HTTP 500 on all endpoints.

---

## Authentication

All requests require a `CG-API-KEY` header:

```bash
curl -X GET "https://open-api-v4.coinglass.com/api/futures/supported-coins" \
  -H "accept: application/json" \
  -H "CG-API-KEY: YOUR_API_KEY"
```

**Get your key:** https://www.coinglass.com/account → API Key Dashboard

**Response headers:**
| Header | Description |
|---|---|
| `API-KEY-MAX-LIMIT` | Max requests per minute for your plan |
| `API-KEY-USE-LIMIT` | Requests used in current window |

**Error codes:**
| Code | Meaning |
|---|---|
| 401 | Missing or invalid API key |
| 400 | Invalid parameters |
| 200 | Success |

---

## Data Categories

| Category | Description |
|---|---|
| **Futures** | OHLC, Open Interest, Funding Rates, Long/Short Ratios, Liquidation, Order Book, Taker metrics |
| **Spot** | Order book, taker buy/sell volume, cumulative volume delta |
| **Options** | Analytics and vol data |
| **On-Chain** | Reserve monitoring, ERC20 transfers |
| **ETF** | Net flows, premium/discount tracking |
| **Indicators** | Fear & Greed Index, Stock-to-Flow, Rainbow Charts |
| **WebSocket** | Real-time streaming |

---

## Key Endpoints

### Futures — Supported Coins

```
GET /api/futures/supported-coins
```

Returns array of valid coin symbols: `BTC, ETH, SOL, XRP, BNB, DOGE, ...`

Use this to validate symbols before other calls.

---

### Futures — Open Interest OHLC History ⭐

```
GET /api/futures/open-interest/history
```

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `exchange` | string | Yes | Exchange name e.g. `Binance` |
| `symbol` | string | Yes | Coin symbol e.g. `BTC` (not `BTCUSDT`) |
| `interval` | string | Yes | Candle interval: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` |
| `limit` | int | No | Number of records to return |
| `startTime` | int | No | Unix timestamp in **seconds** |
| `endTime` | int | No | Unix timestamp in **seconds** |

**Response fields (OHLC candle):**

| Field | Description |
|---|---|
| `t` | Timestamp |
| `o` | Open OI |
| `h` | High OI |
| `l` | Low OI |
| `c` | Close OI ← use this for current OI value |

**Example:**

```bash
curl -X GET "https://open-api-v4.coinglass.com/api/futures/open-interest/history?exchange=Binance&symbol=BTC&interval=1h&limit=10" \
  -H "CG-API-KEY: YOUR_API_KEY"
```

---

## V3 → V4 Migration (Breaking Changes)

| What changed | V3 (old — broken) | V4 (current) |
|---|---|---|
| Base URL | `open-api.coinglass.com` | `open-api-v4.coinglass.com` |
| OI endpoint path | `/public/futures/openInterest/ohlc-history` | `/api/futures/open-interest/history` |
| Exchange parameter | `ex=Binance` | `exchange=Binance` |

---

## Code Changes Required (fetcher.py + config.py)

### config.py
```python
# OLD
COINGLASS_BASE = "https://open-api.coinglass.com"

# NEW
COINGLASS_BASE = "https://open-api-v4.coinglass.com"
```

### fetcher.py — fetch_coinglass_oi_history()
```python
# OLD endpoint + param
resp = await client.get("/public/futures/openInterest/ohlc-history", params={
    "ex": "Binance",
    ...
})

# NEW endpoint + param
resp = await client.get("/api/futures/open-interest/history", params={
    "exchange": "Binance",
    ...
})
```

### Response parsing
```python
# OLD: data["code"] == "0" check
# NEW: check HTTP status only, data is direct array or {"data": [...]}
```
