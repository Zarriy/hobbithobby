"""
REST API endpoints for dashboard consumption.
"""

import json
import time
from typing import Optional, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query

import config
from core import store

if TYPE_CHECKING:
    from demo.trader import DemoTrader

router = APIRouter()

# In-memory references set by main.py
_live_state: dict = {}
_scheduler_status: dict = {}
_demo_trader: Optional["DemoTrader"] = None


def set_live_state(state: dict) -> None:
    global _live_state
    _live_state = state


def set_scheduler_status(status: dict) -> None:
    global _scheduler_status
    _scheduler_status = status


def set_demo_trader(trader: "DemoTrader") -> None:
    global _demo_trader
    _demo_trader = trader


@router.get("/api/status")
async def get_status():
    """System health, last update time, scheduler status."""
    return {
        "status": "running",
        "timestamp": int(time.time() * 1000),
        "scheduler": _scheduler_status,
        "pairs": list(_live_state.keys()),
        "last_updates": {
            pair: data.get("last_update_ts") for pair, data in _live_state.items()
        },
    }


@router.get("/api/signals")
async def get_signals(pair: str = Query(..., description="e.g. BTCUSDT")):
    """Latest signal + full context for a pair."""
    # Try both timeframes; return the 1h signal with 4h context
    signals = {}
    for tf in ["1h", "4h"]:
        sig = store.fetch_latest_signal(pair, tf)
        if sig:
            # Parse JSON fields
            for field in ["nearest_bullish_fvg", "nearest_bearish_fvg",
                          "nearest_bullish_ob", "nearest_bearish_ob",
                          "equal_highs", "equal_lows", "metadata"]:
                if sig.get(field) and isinstance(sig[field], str):
                    try:
                        sig[field] = json.loads(sig[field])
                    except json.JSONDecodeError:
                        pass
            signals[tf] = sig

    if not signals:
        raise HTTPException(status_code=404, detail=f"No signals found for {pair}")

    return {"pair": pair, "signals": signals}


@router.get("/api/signals/history")
async def get_signal_history(
    pair: str = Query(...),
    timeframe: str = Query("1h"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Historical signals for a pair/timeframe."""
    signals = store.fetch_signal_history(pair, timeframe, limit)
    if not signals:
        raise HTTPException(status_code=404, detail=f"No signal history for {pair} {timeframe}")

    for sig in signals:
        for field in ["nearest_bullish_fvg", "nearest_bearish_fvg",
                      "nearest_bullish_ob", "nearest_bearish_ob",
                      "equal_highs", "equal_lows", "metadata"]:
            if sig.get(field) and isinstance(sig[field], str):
                try:
                    sig[field] = json.loads(sig[field])
                except json.JSONDecodeError:
                    pass

    return {"pair": pair, "timeframe": timeframe, "count": len(signals), "signals": signals}


@router.get("/api/candles")
async def get_candles(
    pair: str = Query(...),
    timeframe: str = Query("4h"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Raw candle data for a pair/timeframe."""
    candles = store.fetch_candles(pair, timeframe, limit)
    if not candles:
        raise HTTPException(status_code=404, detail=f"No candle data for {pair} {timeframe}")
    return {"pair": pair, "timeframe": timeframe, "count": len(candles), "candles": candles}


@router.get("/api/levels")
async def get_levels(pair: str = Query(...)):
    """Active FVGs, OBs, swing points for a pair."""
    result = {}
    for tf in ["1h", "4h"]:
        fvgs = store.fetch_active_fvgs(pair, tf)
        obs = store.fetch_active_obs(pair, tf)
        swings = store.fetch_swing_points(pair, tf, limit=20)
        result[tf] = {
            "fvgs": fvgs,
            "order_blocks": obs,
            "swing_points": swings,
        }
    return {"pair": pair, "levels": result}


@router.get("/api/regime")
async def get_regime():
    """Current macro regime per pair."""
    regimes = {}
    for pair, data in _live_state.items():
        regimes[pair] = {
            "macro_regime": data.get("macro_regime", "unknown"),
            "last_update": data.get("last_regime_update"),
        }
    return {"regimes": regimes}


# ════════════════════════════════════════
# ENHANCED STATUS — staleness flags
# ════════════════════════════════════════

@router.get("/api/status/detail")
async def get_status_detail():
    """Per-pair staleness flags for all data sources."""
    now_ms = int(time.time() * 1000)
    now_s = now_ms / 1000
    warn_s = config.STALE_WARNING_CYCLES * config.FULL_ANALYSIS_INTERVAL_SECONDS
    crit_s = config.STALE_CRITICAL_CYCLES * config.FULL_ANALYSIS_INTERVAL_SECONDS
    funding_warn_s = config.STALE_FUNDING_WARNING_HOURS * 3600
    funding_crit_s = config.STALE_FUNDING_CRITICAL_HOURS * 3600

    pairs_detail = {}
    for pair in config.PAIRS:
        data = _live_state.get(pair, {})
        last_update_ts = data.get("last_update_ts", 0)
        last_update_s = last_update_ts / 1000 if last_update_ts else 0
        age_s = now_s - last_update_s if last_update_s else None

        # Check candle freshness from DB
        candles = store.fetch_candles(pair, "1h", limit=5)
        last_candle_ts = candles[-1]["timestamp"] / 1000 if candles else 0
        candle_age_s = now_s - last_candle_ts if last_candle_ts else None

        # OI coverage check (last 10 candles)
        oi_candles = store.fetch_candles(pair, "1h", limit=10)
        oi_real_count = sum(1 for c in oi_candles if c.get("open_interest") and c["open_interest"] > 0)
        oi_ever_nonzero = oi_real_count > 0

        # Funding freshness
        funding_ts = next(
            (c["timestamp"] / 1000 for c in reversed(oi_candles)
             if c.get("funding_rate") is not None and c["funding_rate"] != 0),
            None,
        )
        funding_age_s = now_s - funding_ts if funding_ts else None

        def _flag(age, warn, crit):
            if age is None:
                return "unknown"
            if age > crit:
                return "critical"
            if age > warn:
                return "warning"
            return "ok"

        pairs_detail[pair] = {
            "last_signal_age_s": round(age_s, 0) if age_s else None,
            "last_candle_age_s": round(candle_age_s, 0) if candle_age_s else None,
            "oi_ever_nonzero": oi_ever_nonzero,
            "funding_age_s": round(funding_age_s, 0) if funding_age_s else None,
            "stale_flags": {
                "signals": _flag(age_s, warn_s, crit_s),
                "candles": _flag(candle_age_s, warn_s, crit_s),
                "oi_data": "critical" if not oi_ever_nonzero else "ok",
                "funding": _flag(funding_age_s, funding_warn_s, funding_crit_s),
            },
        }

    return {
        "timestamp": now_ms,
        "scheduler": _scheduler_status,
        "pairs": pairs_detail,
    }


# ════════════════════════════════════════
# DEMO TRADING
# ════════════════════════════════════════

@router.get("/api/demo/positions")
async def get_demo_positions():
    """Open paper positions with leveraged mark-to-market P&L and portfolio summary."""
    if _demo_trader is None:
        return {"positions": [], "count": 0, "portfolio_summary": {}}
    positions = _demo_trader.get_positions_with_mtm(_live_state)
    summary = _demo_trader.get_portfolio_summary(_live_state)
    return {"positions": positions, "count": len(positions), "portfolio_summary": summary}


@router.get("/api/demo/trades")
async def get_demo_trades(limit: int = Query(50, ge=1, le=500)):
    """Closed paper trade history."""
    from demo import store as demo_store
    trades = demo_store.fetch_closed_trades(limit)
    return {"trades": trades, "count": len(trades)}


@router.get("/api/demo/metrics")
async def get_demo_metrics():
    """Aggregated performance: win rate, return%, Sharpe, max DD, profit factor."""
    if _demo_trader is None:
        return {"status": "not_initialized", "initial_capital": config.INITIAL_CAPITAL}
    from demo.metrics import compute_demo_metrics
    result = compute_demo_metrics(current_equity=_demo_trader.equity)
    if result is None:
        return {"status": "no_trades", "initial_capital": config.INITIAL_CAPITAL,
                "current_equity": _demo_trader.equity}
    result["status"] = "ok"
    return result


@router.get("/api/demo/equity")
async def get_demo_equity(limit: int = Query(500, ge=1, le=5000)):
    """Equity curve time series."""
    from demo import store as demo_store
    rows = demo_store.fetch_equity_curve(limit)
    return {"equity_curve": rows, "count": len(rows)}


# ════════════════════════════════════════
# ANALYTICS
# ════════════════════════════════════════

@router.get("/api/analytics/signal-history")
async def get_signal_history_analytics(
    pair: str = Query(...),
    timeframe: str = Query("1h"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Signal confidence + regime + risk_color breakdown over time for charting."""
    rows = store.fetch_signal_history(pair, timeframe, limit)
    history = []
    for r in rows:
        metadata = {}
        if r.get("metadata") and isinstance(r["metadata"], str):
            try:
                metadata = json.loads(r["metadata"])
            except json.JSONDecodeError:
                pass
        history.append({
            "timestamp": r["timestamp"],
            "regime_state": r["regime_state"],
            "risk_color": r["risk_color"],
            "confidence": r["confidence"],
            "action_bias": metadata.get("action_bias"),
            "trend_state": r.get("trend_state"),
        })
    return {"pair": pair, "timeframe": timeframe, "count": len(history), "history": history}


@router.get("/api/analytics/data-quality")
async def get_data_quality():
    """Per pair×tf: OI coverage %, funding coverage %, total candles sampled."""
    result = {}
    for pair in config.PAIRS:
        for tf in config.TIMEFRAMES:
            rows = store.fetch_candles(pair, tf, limit=500)
            total = len(rows)
            if total == 0:
                result[f"{pair}_{tf}"] = {
                    "pair": pair, "timeframe": tf, "total_candles": 0,
                    "oi_coverage_pct": 0.0, "funding_coverage_pct": 0.0,
                }
                continue
            oi_real = sum(1 for r in rows if r.get("open_interest") and r["open_interest"] > 0)
            funding_real = sum(1 for r in rows if r.get("funding_rate") is not None and r["funding_rate"] != 0)
            result[f"{pair}_{tf}"] = {
                "pair": pair,
                "timeframe": tf,
                "total_candles": total,
                "oi_coverage_pct": round(oi_real / total * 100, 1),
                "funding_coverage_pct": round(funding_real / total * 100, 1),
            }
    return {"data_quality": result}


@router.get("/api/analytics/regime-distribution")
async def get_regime_distribution(
    pair: str = Query(...),
    timeframe: str = Query("1h"),
    lookback: int = Query(500, ge=10, le=2000),
):
    """Time spent per regime state — reveals whether signal types are actually tested."""
    rows = store.fetch_signal_history(pair, timeframe, lookback)
    if not rows:
        return {"pair": pair, "timeframe": timeframe, "total_signals": 0, "distribution": {}}

    from collections import Counter
    counts = Counter(r["regime_state"] for r in rows)
    total = len(rows)
    distribution = {
        regime: {"count": cnt, "pct": round(cnt / total * 100, 1)}
        for regime, cnt in counts.most_common()
    }
    return {
        "pair": pair, "timeframe": timeframe,
        "total_signals": total, "distribution": distribution,
    }


@router.get("/api/analytics/confidence-distribution")
async def get_confidence_distribution(
    pair: str = Query(...),
    timeframe: str = Query("1h"),
    lookback: int = Query(500, ge=10, le=2000),
):
    """Confidence score histogram — shows whether scoring actually discriminates."""
    rows = store.fetch_signal_history(pair, timeframe, lookback)
    if not rows:
        return {"pair": pair, "timeframe": timeframe, "buckets": [], "mean": 0, "median": 0, "std_dev": 0}

    scores = [r["confidence"] for r in rows if r.get("confidence") is not None]
    if not scores:
        return {"pair": pair, "timeframe": timeframe, "buckets": [], "mean": 0, "median": 0, "std_dev": 0}

    # 10-point bins
    bins = {f"{i*10}-{i*10+9}": 0 for i in range(10)}
    for s in scores:
        bucket_idx = min(s // 10, 9)
        key = f"{bucket_idx*10}-{bucket_idx*10+9}"
        bins[key] += 1

    buckets = [{"range": k, "count": v} for k, v in bins.items()]

    import math
    mean = sum(scores) / len(scores)
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    median = sorted_scores[n // 2] if n % 2 == 1 else (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
    variance = sum((s - mean) ** 2 for s in scores) / n
    std_dev = math.sqrt(variance)

    return {
        "pair": pair,
        "timeframe": timeframe,
        "total": len(scores),
        "buckets": buckets,
        "mean": round(mean, 1),
        "median": round(median, 1),
        "std_dev": round(std_dev, 1),
    }


def _build_reasoning_summary(sig: dict) -> str:
    oi_pct = (sig.get("oi_change_percent") or 0) * 100
    oi_part = "OI data unavailable — volume fallback" if oi_pct == 0 else f"oi_chg={round(oi_pct, 2)}%"
    return (
        f"{sig.get('regime_state', 'unknown')} regime | "
        f"conf={sig.get('confidence', 0)} | "
        f"vol_z={round(sig.get('volume_zscore') or 0, 2)} | "
        + oi_part
    )


@router.get("/api/signals/{pair}/{timeframe}/reasoning")
async def get_signal_reasoning(pair: str, timeframe: str):
    """Latest signal reasoning breakdown for a pair×timeframe."""
    sig = store.fetch_latest_signal(pair, timeframe)
    if not sig:
        raise HTTPException(status_code=404, detail=f"No signal found for {pair} {timeframe}")

    metadata = {}
    if sig.get("metadata") and isinstance(sig["metadata"], str):
        try:
            metadata = json.loads(sig["metadata"])
        except json.JSONDecodeError:
            pass

    reasoning = metadata.get("reasoning")
    if not reasoning:
        # Build a basic reasoning from available fields
        reasoning = {
            "regime_factors": [
                {"factor": "volume_zscore", "value": sig.get("volume_zscore", 0),
                 "threshold": 1.5, "direction": "above" if (sig.get("volume_zscore") or 0) >= 1.5 else "below",
                 "impact": "bullish" if (sig.get("volume_zscore") or 0) >= 1.5 else "neutral"},
                {"factor": "oi_change_pct", "value": round((sig.get("oi_change_percent") or 0) * 100, 3),
                 "threshold": 1.5, "direction": "above" if (sig.get("oi_change_percent") or 0) >= 0.015 else "below",
                 "impact": "bullish" if (sig.get("oi_change_percent") or 0) >= 0.015 else "neutral",
                 "note": "OI data unavailable — volume fallback used" if (sig.get("oi_change_percent") or 0) == 0 else None},
                {"factor": "funding_rate", "value": sig.get("funding_rate", 0),
                 "threshold": 0.0003, "direction": "above" if abs(sig.get("funding_rate") or 0) >= 0.0003 else "below",
                 "impact": "extreme" if abs(sig.get("funding_rate") or 0) >= 0.0003 else "neutral"},
                {"factor": "taker_ratio", "value": sig.get("taker_ratio", 0.5),
                 "threshold": 0.55, "direction": "above" if (sig.get("taker_ratio") or 0.5) >= 0.55 else "below",
                 "impact": "bullish" if (sig.get("taker_ratio") or 0.5) >= 0.55 else "neutral"},
            ],
            "confidence_breakdown": {
                "base_score": 50,
                "final": sig.get("confidence", 0),
                "note": "Detailed breakdown requires reasoning to be stored during signal generation",
            },
            "summary": _build_reasoning_summary(sig),
        }

    return {
        "pair": pair,
        "timeframe": timeframe,
        "timestamp": sig.get("timestamp"),
        "regime_state": sig.get("regime_state"),
        "risk_color": sig.get("risk_color"),
        "confidence": sig.get("confidence"),
        "reasoning": reasoning,
    }


# ════════════════════════════════════════
# CHARTS
# ════════════════════════════════════════

@router.get("/api/charts/price-history")
async def get_price_history(
    pair: str = Query(...),
    timeframe: str = Query("1h"),
    limit: int = Query(100, ge=10, le=500),
):
    """Candles + demo trade markers + active FVG/OB zone overlays."""
    candles_raw = store.fetch_candles(pair, timeframe, limit)
    if not candles_raw:
        raise HTTPException(status_code=404, detail=f"No candles for {pair} {timeframe}")

    candles = [
        {"ts": c["timestamp"], "o": c["open"], "h": c["high"],
         "l": c["low"], "c": c["close"], "v": c["volume"]}
        for c in candles_raw
    ]

    # Trade markers from demo trades within the candle time range
    trade_markers = []
    if _demo_trader is not None:
        from demo import store as demo_store
        trades = demo_store.fetch_closed_trades(limit=200)
        min_ts = candles_raw[0]["timestamp"]
        max_ts = candles_raw[-1]["timestamp"]
        for t in trades:
            if t["pair"] != pair or t["timeframe"] != timeframe:
                continue
            if min_ts <= t["entry_ts"] <= max_ts:
                trade_markers.append({
                    "type": "entry",
                    "side": t["side"],
                    "price": t["entry_price"],
                    "ts": t["entry_ts"],
                    "position_id": t["position_id"],
                })
            if min_ts <= t["exit_ts"] <= max_ts:
                trade_markers.append({
                    "type": t["exit_reason"],
                    "side": t["side"],
                    "price": t["exit_price"],
                    "ts": t["exit_ts"],
                    "position_id": t["position_id"],
                    "pnl_usd": t["net_pnl_usd"],
                })
        # Open positions
        for p in _demo_trader.open_positions:
            if p["pair"] != pair or p["timeframe"] != timeframe:
                continue
            if min_ts <= p["entry_ts"] <= max_ts:
                trade_markers.append({
                    "type": "entry",
                    "side": p["side"],
                    "price": p["entry_price"],
                    "ts": p["entry_ts"],
                    "position_id": p["id"],
                    "open": True,
                })

    # Active zone overlays from latest signal
    sig = store.fetch_latest_signal(pair, timeframe)
    zones: dict = {}
    if sig:
        for field in ["nearest_bullish_fvg", "nearest_bearish_fvg",
                      "nearest_bullish_ob", "nearest_bearish_ob"]:
            val = sig.get(field)
            if val and isinstance(val, str):
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    val = None
            if val:
                zones[field] = {"top": val.get("upper_bound"), "bottom": val.get("lower_bound")}

    return {
        "pair": pair,
        "timeframe": timeframe,
        "candles": candles,
        "trade_markers": sorted(trade_markers, key=lambda x: x["ts"]),
        "zones": zones,
    }
