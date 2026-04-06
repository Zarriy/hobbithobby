"""
Trade simulation engine.
Iterates candle-by-candle with strict no-future-leak guarantees.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import config
from backtest.rules import TradeRule, check_entry, check_exit
from engine import indicators
from engine.classifier import SignalOutput, classify
from engine.fvg import detect_fvgs, get_nearest_fvg, update_fvg_status
from engine.orderblocks import detect_order_blocks, get_nearest_ob, update_ob_status
from engine.structure import (
    detect_swing_points,
    detect_structure_breaks,
    detect_equal_levels,
    get_premium_discount_zone,
)

logger = logging.getLogger(__name__)


@dataclass
class Position:
    id: int
    side: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2_target: Optional[float]
    size_multiplier: float
    risk_distance: float
    reason: str
    entry_zone: Optional[dict]
    entry_ts: int
    regime_at_entry: str
    risk_color_at_entry: str
    size_usd: float        # dollar risk amount
    contracts: float       # notional size / entry_price
    tp1_hit: bool = False
    tp1_exit_price: Optional[float] = None
    partial_exit_pnl: float = 0.0


@dataclass
class TradeRecord:
    id: int
    side: str
    entry_price: float
    exit_price: float
    entry_ts: int
    exit_ts: int
    exit_reason: str
    pnl_usd: float
    pnl_percent: float
    fee_usd: float
    slippage_usd: float
    net_pnl_usd: float
    size_usd: float
    regime_at_entry: str
    risk_color_at_entry: str
    entry_zone_type: Optional[str]
    confidence_at_entry: int = 0
    hold_hours: float = 0.0
    had_fvg_overlap: bool = False


@dataclass
class BacktestState:
    equity: float
    open_positions: list[Position] = field(default_factory=list)
    closed_trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[tuple] = field(default_factory=list)  # (ts, equity)
    peak_equity: float = 0.0
    drawdown_curve: list[tuple] = field(default_factory=list)
    next_trade_id: int = 1


def _compute_signals_at(
    candles: list[dict],
    idx: int,
) -> Optional[SignalOutput]:
    """
    Compute signal using ONLY data up to candle[idx]. No future leak.
    """
    window = candles[: idx + 1]
    if len(window) < 30:
        return None

    closes = np.array([c["close"] for c in window])
    highs = np.array([c["high"] for c in window])
    lows = np.array([c["low"] for c in window])
    volumes = np.array([c["volume"] for c in window])

    atr_vals = indicators.atr(highs, lows, closes, period=14)
    vwap_vals = indicators.vwap(highs, lows, closes, volumes)
    vol_zscore_arr = indicators.rolling_zscore(volumes, config.VOLUME_ZSCORE_LOOKBACK)
    atr_zscore_arr = indicators.rolling_zscore(atr_vals, config.ATR_ZSCORE_LOOKBACK)
    vwap_dev_arr = indicators.vwap_deviation(closes, vwap_vals, period=50)

    current_atr = float(atr_vals[-1]) if not np.isnan(atr_vals[-1]) else 0.0
    vol_zscore = float(vol_zscore_arr[-1]) if not np.isnan(vol_zscore_arr[-1]) else 0.0
    atr_zscore = float(atr_zscore_arr[-1]) if not np.isnan(atr_zscore_arr[-1]) else 0.0
    vwap_dev = float(vwap_dev_arr[-1]) if not np.isnan(vwap_dev_arr[-1]) else 0.0

    current_price = float(closes[-1])
    prev_close = float(closes[-2]) if len(closes) >= 2 else current_price
    price_change = (current_price - prev_close) / prev_close if prev_close > 0 else 0.0

    oi_change: Optional[float] = None
    lookback = config.OI_CHANGE_LOOKBACK
    # Use position-aligned lookback so OI change reflects the correct time span.
    # Filtering out Nones (old approach) shifts the index and measures the wrong period.
    if len(window) > lookback:
        oi_now = window[-1].get("open_interest")
        oi_back = window[-1 - lookback].get("open_interest")
        if oi_now is not None and oi_back is not None and oi_back > 0:
            oi_change = (oi_now - oi_back) / oi_back
        elif oi_now is not None:
            # Aligned candle has no OI — walk backward to the nearest valid reading
            for c in reversed(window[-lookback - 1 : -1]):
                oi_prior = c.get("open_interest")
                if oi_prior is not None and oi_prior > 0:
                    oi_change = (oi_now - oi_prior) / oi_prior
                    break

    funding_rate = window[-1].get("funding_rate") or 0.0
    taker_ratio = window[-1].get("taker_buy_sell_ratio") or 0.5
    long_short_ratio = window[-1].get("long_short_ratio") or 1.0

    swings = detect_swing_points(window, lookback=config.SWING_LOOKBACK)
    _, trend_state = detect_structure_breaks(swings)
    price_zone = get_premium_discount_zone(swings, current_price)

    signal = classify(
        price_change=price_change,
        oi_change=oi_change,
        volume_zscore=vol_zscore,
        funding_rate=funding_rate,
        taker_ratio=taker_ratio,
        long_short_ratio=long_short_ratio,
        trend_state=trend_state,
        vwap_deviation=vwap_dev,
        atr_zscore=atr_zscore,
        pair=window[-1].get("pair", ""),
        timeframe=window[-1].get("timeframe", ""),
        timestamp=window[-1].get("timestamp", 0),
        price_zone=price_zone,
        current_price=current_price,
        atr=current_atr,
    )
    return signal


def generate_signal_cache(
    candles: list[dict],
    verbose: bool = False,
) -> list[Optional[SignalOutput]]:
    """
    Pre-compute all signals over candle history.
    Each entry corresponds to the signal available at that candle index.
    First 30 entries will be None (insufficient data).
    """
    n = len(candles)
    cache: list[Optional[SignalOutput]] = [None] * n

    for i in range(30, n):
        if verbose and i % 100 == 0:
            logger.info("Signal cache: %d/%d (%.0f%%)", i, n, 100 * i / n)
        cache[i] = _compute_signals_at(candles, i)

    return cache


def run_backtest(
    candles: list[dict],
    rules: TradeRule,
    initial_capital: float = config.INITIAL_CAPITAL,
    slippage: float = config.SLIPPAGE_PERCENT,
    fees: float = config.TAKER_FEE_PERCENT,
    signal_cache: Optional[list[Optional[SignalOutput]]] = None,
    verbose: bool = False,
) -> "BacktestState":
    """
    Main backtest loop. Returns BacktestState with full trade log and equity curve.
    """
    state = BacktestState(equity=initial_capital, peak_equity=initial_capital)

    # Generate signals if no cache provided
    if signal_cache is None:
        logger.info("Generating signal cache for %d candles...", len(candles))
        signal_cache = generate_signal_cache(candles, verbose=verbose)

    n = len(candles)

    for i in range(1, n):
        candle = candles[i]
        ts = candle["timestamp"]
        signal = signal_cache[i]

        # ─── Update / Exit Open Positions ───
        positions_to_close = []
        for pos in state.open_positions:
            if signal is None:
                continue

            exit_result = check_exit(
                position={
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "tp1": pos.tp1,
                    "tp2_target": pos.tp2_target,
                    "entry_ts": pos.entry_ts,
                    "tp1_hit": pos.tp1_hit,
                },
                current_candle=candle,
                current_signal=signal,
                rules=rules,
            )

            if exit_result:
                # Handle TP1 partial exit (close 50%, let other 50% run)
                if exit_result["exit_reason"] == "tp1" and not pos.tp1_hit:
                    pos.tp1_hit = True
                    pos.tp1_exit_price = exit_result["exit_price"]

                    # Close 50% of position
                    partial_contracts = pos.contracts * 0.5
                    gross_pnl = exit_result["pnl_percent"] * pos.size_usd * 0.5
                    fee = abs(partial_contracts * exit_result["exit_price"]) * fees  # exit fee only (entry already deducted at open)
                    slip = abs(partial_contracts * exit_result["exit_price"]) * slippage

                    net = gross_pnl - fee - slip
                    state.equity += net
                    pos.partial_exit_pnl = net

                    # Adjust position for remaining 50%
                    pos.contracts *= 0.5
                    pos.size_usd *= 0.5

                    # Set TP2 as next swing high/low if not already set
                    # (simplified: set TP2 at 3R if not defined)
                    if pos.tp2_target is None:
                        if pos.side == "long":
                            pos.tp2_target = pos.entry_price + pos.risk_distance * 3.0
                        else:
                            pos.tp2_target = pos.entry_price - pos.risk_distance * 3.0

                    # Move stop to breakeven after TP1
                    pos.stop_loss = pos.entry_price
                    continue

                # Full close
                gross_pnl = exit_result["pnl_percent"] * pos.size_usd
                fee_cost = abs(pos.contracts * exit_result["exit_price"]) * fees  # exit fee only (entry already deducted at open)
                slip_cost = abs(pos.contracts * exit_result["exit_price"]) * slippage

                # Include funding cost if applicable (simplified: flat rate during hold)
                hold_hours = (ts - pos.entry_ts) / 3_600_000
                funding_periods = int(hold_hours / 8)
                funding_cost = abs(pos.size_usd) * 0.0001 * funding_periods  # ~0.01% per 8h

                net_pnl = gross_pnl - fee_cost - slip_cost - funding_cost + pos.partial_exit_pnl

                state.equity += net_pnl

                record = TradeRecord(
                    id=pos.id,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=exit_result["exit_price"],
                    entry_ts=pos.entry_ts,
                    exit_ts=ts,
                    exit_reason=exit_result["exit_reason"],
                    pnl_usd=gross_pnl,
                    pnl_percent=exit_result["pnl_percent"],
                    fee_usd=fee_cost,
                    slippage_usd=slip_cost,
                    net_pnl_usd=net_pnl,
                    size_usd=pos.size_usd,
                    regime_at_entry=pos.regime_at_entry,
                    risk_color_at_entry=pos.risk_color_at_entry,
                    entry_zone_type=pos.entry_zone.get("type") if pos.entry_zone else None,
                    hold_hours=hold_hours,
                    had_fvg_overlap=pos.entry_zone.get("has_fvg_overlap", False) if pos.entry_zone else False,
                )
                state.closed_trades.append(record)
                positions_to_close.append(pos)

        for p in positions_to_close:
            state.open_positions.remove(p)

        # ─── Check for New Entry ───
        if signal is not None:
            # Get levels from candle history (no leak)
            window = candles[: i + 1]
            atr_vals = None
            fvgs = detect_fvgs(window[-100:])
            obs = detect_order_blocks(window[-100:], fvgs)

            current_price = candle["close"]
            bullish_fvg = get_nearest_fvg(fvgs, current_price, "bullish")
            bearish_fvg = get_nearest_fvg(fvgs, current_price, "bearish")
            bullish_ob = get_nearest_ob(obs, current_price, "bullish")
            bearish_ob = get_nearest_ob(obs, current_price, "bearish")

            entry = check_entry(
                signal=signal,
                bullish_fvg=bullish_fvg,
                bearish_fvg=bearish_fvg,
                bullish_ob=bullish_ob,
                bearish_ob=bearish_ob,
                current_price=current_price,
                open_positions=len(state.open_positions),
                rules=rules,
                current_ts=ts,
                candle_low=candle["low"],
                candle_high=candle["high"],
            )

            if entry:
                # Volatility-adjusted slippage — scales with ATR z-score
                atr_z = signal.atr_zscore if signal else 0.0
                dynamic_slippage = slippage * (1.0 + max(0.0, atr_z) * 0.5)
                slip_entry = entry["entry_price"] * dynamic_slippage
                if entry["side"] == "long":
                    actual_entry = entry["entry_price"] + slip_entry
                else:
                    actual_entry = entry["entry_price"] - slip_entry

                # Recalculate risk distance and TP1 from actual fill price.
                # SL stays at the zone boundary (absolute level); TP shifts with entry.
                sl_price = entry["stop_loss"]
                actual_risk_distance = abs(actual_entry - sl_price)

                if actual_risk_distance >= actual_entry * 0.0001:
                    if entry["side"] == "long":
                        actual_tp1 = actual_entry + actual_risk_distance * rules.take_profit_1_rr
                    else:
                        actual_tp1 = actual_entry - actual_risk_distance * rules.take_profit_1_rr

                    # Size from actual risk distance so 1% risk rule stays accurate
                    risk_usd = state.equity * rules.risk_percent_base * entry["size_multiplier"]
                    size_usd = risk_usd / (actual_risk_distance / actual_entry)

                    if size_usd > 0 and size_usd <= state.equity * 5:  # Max 5x leverage check
                        entry_fee = size_usd * fees

                        pos = Position(
                            id=state.next_trade_id,
                            side=entry["side"],
                            entry_price=actual_entry,
                            stop_loss=sl_price,
                            tp1=actual_tp1,
                            tp2_target=entry.get("tp2_target"),
                            size_multiplier=entry["size_multiplier"],
                            risk_distance=actual_risk_distance,
                            reason=entry["reason"],
                            entry_zone=entry.get("entry_zone"),
                            entry_ts=ts,
                            regime_at_entry=entry["regime_at_entry"],
                            risk_color_at_entry=entry["risk_color_at_entry"],
                            size_usd=size_usd,
                            contracts=size_usd / actual_entry,
                        )
                        state.open_positions.append(pos)
                        state.equity -= entry_fee  # Deduct entry fee immediately
                        state.next_trade_id += 1

        # ─── Record Equity & Drawdown ───
        state.equity_curve.append((ts, state.equity))
        if state.equity > state.peak_equity:
            state.peak_equity = state.equity
        dd = (state.peak_equity - state.equity) / state.peak_equity if state.peak_equity > 0 else 0
        state.drawdown_curve.append((ts, dd))

    # Force-close any remaining positions at last price
    last_candle = candles[-1]
    for pos in list(state.open_positions):
        close_price = last_candle["close"]
        if pos.side == "long":
            pnl_pct = (close_price - pos.entry_price) / pos.entry_price
        else:
            pnl_pct = (pos.entry_price - close_price) / pos.entry_price

        gross = pnl_pct * pos.size_usd
        fee = abs(pos.contracts * close_price) * fees  # exit fee only (entry already deducted at open)
        net = gross - fee + pos.partial_exit_pnl

        state.equity += net
        hold_hours = (last_candle["timestamp"] - pos.entry_ts) / 3_600_000
        record = TradeRecord(
            id=pos.id,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=close_price,
            entry_ts=pos.entry_ts,
            exit_ts=last_candle["timestamp"],
            exit_reason="forced_close_end",
            pnl_usd=gross,
            pnl_percent=pnl_pct,
            fee_usd=fee,
            slippage_usd=0,
            net_pnl_usd=net,
            size_usd=pos.size_usd,
            regime_at_entry=pos.regime_at_entry,
            risk_color_at_entry=pos.risk_color_at_entry,
            entry_zone_type=pos.entry_zone.get("type") if pos.entry_zone else None,
            hold_hours=hold_hours,
        )
        state.closed_trades.append(record)
    state.open_positions.clear()

    return state


def run_backtest_from_cache(
    candles: list[dict],
    signal_cache: list[Optional[SignalOutput]],
    rules: TradeRule,
    initial_capital: float = config.INITIAL_CAPITAL,
    slippage: float = config.SLIPPAGE_PERCENT,
    fees: float = config.TAKER_FEE_PERCENT,
) -> BacktestState:
    """Use pre-cached signals — sub-second execution for rule iteration."""
    return run_backtest(
        candles=candles,
        rules=rules,
        initial_capital=initial_capital,
        slippage=slippage,
        fees=fees,
        signal_cache=signal_cache,
    )
