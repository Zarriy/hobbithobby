"""
Stress testing: walk-forward analysis, sensitivity analysis, Monte Carlo simulation.
"""

import logging
import random
from typing import Optional

import config
from backtest.metrics import BacktestResult, calculate_metrics
from backtest.rules import TradeRule
from backtest.simulator import run_backtest_from_cache, generate_signal_cache, run_backtest

logger = logging.getLogger(__name__)

MS_PER_MONTH = 30 * 24 * 3_600_000


def walk_forward_analysis(
    candles: list[dict],
    rules: TradeRule,
    train_months: int = 6,
    test_months: int = 3,
    step_months: int = 3,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> list[dict]:
    """
    Sliding window walk-forward validation.
    Returns per-window results: {train_result, test_result, window_start, window_end}
    """
    if not candles:
        return []

    start_ts = candles[0]["timestamp"]
    end_ts = candles[-1]["timestamp"]
    total_ms = end_ts - start_ts

    train_ms = train_months * MS_PER_MONTH
    test_ms = test_months * MS_PER_MONTH
    step_ms = step_months * MS_PER_MONTH

    results = []
    window_start = start_ts

    while window_start + train_ms + test_ms <= end_ts:
        train_end = window_start + train_ms
        test_end = min(train_end + test_ms, end_ts)

        train_candles = [c for c in candles if window_start <= c["timestamp"] < train_end]
        test_candles = [c for c in candles if train_end <= c["timestamp"] < test_end]

        if len(train_candles) < 100 or len(test_candles) < 30:
            window_start += step_ms
            continue

        logger.info(
            "Walk-forward window: train=%d candles, test=%d candles",
            len(train_candles), len(test_candles)
        )

        # Generate signal cache independently for each window (no leak)
        train_cache = generate_signal_cache(train_candles)
        train_state = run_backtest_from_cache(
            train_candles, train_cache, rules, initial_capital=initial_capital
        )
        train_result = calculate_metrics(
            train_state.closed_trades,
            train_state.equity_curve,
            train_state.drawdown_curve,
            initial_capital,
        )

        test_cache = generate_signal_cache(test_candles)
        test_state = run_backtest_from_cache(
            test_candles, test_cache, rules, initial_capital=initial_capital
        )
        test_result = calculate_metrics(
            test_state.closed_trades,
            test_state.equity_curve,
            test_state.drawdown_curve,
            initial_capital,
        )

        results.append({
            "window_start": window_start,
            "window_end": test_end,
            "train_result": _result_summary(train_result),
            "test_result": _result_summary(test_result),
            "degradation": _compute_degradation(train_result, test_result),
        })

        window_start += step_ms

    return results


def sensitivity_analysis(
    candles: list[dict],
    base_rules: TradeRule,
    params_to_vary: dict,
    signal_cache: Optional[list] = None,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> dict:
    """
    Vary each parameter independently and re-run backtest.
    Flags parameters where ±20% change causes >30% profit factor change.

    params_to_vary example:
    {
        "confidence_above": [60, 65, 70, 75, 80],
        "take_profit_1_rr": [1.0, 1.5, 2.0, 2.5],
    }
    """
    if signal_cache is None:
        logger.info("Generating signal cache for sensitivity analysis...")
        signal_cache = generate_signal_cache(candles)

    # Baseline
    base_state = run_backtest_from_cache(candles, signal_cache, base_rules, initial_capital)
    base_result = calculate_metrics(
        base_state.closed_trades, base_state.equity_curve, base_state.drawdown_curve, initial_capital
    )
    base_pf = base_result.profit_factor

    results = {"baseline": _result_summary(base_result), "parameters": {}}

    for param_name, values in params_to_vary.items():
        param_results = []
        for val in values:
            # Create modified rules
            mod_rules = TradeRule(
                regime_is_green=base_rules.regime_is_green,
                confidence_above=base_rules.confidence_above,
                trend_confirmed=base_rules.trend_confirmed,
                price_in_zone=base_rules.price_in_zone,
                level_touched=base_rules.level_touched,
                entry_at=base_rules.entry_at,
                stop_loss=base_rules.stop_loss,
                take_profit_1_rr=base_rules.take_profit_1_rr,
                take_profit_2=base_rules.take_profit_2,
                regime_exit=base_rules.regime_exit,
                max_hold_hours=base_rules.max_hold_hours,
                risk_percent_base=base_rules.risk_percent_base,
                max_concurrent=base_rules.max_concurrent,
            )
            setattr(mod_rules, param_name, val)

            state = run_backtest_from_cache(candles, signal_cache, mod_rules, initial_capital)
            result = calculate_metrics(
                state.closed_trades, state.equity_curve, state.drawdown_curve, initial_capital
            )

            pf_change = abs(result.profit_factor - base_pf) / base_pf if base_pf > 0 else 0
            param_results.append({
                "value": val,
                "profit_factor": result.profit_factor,
                "total_return": result.total_return_percent,
                "win_rate": result.win_rate,
                "total_trades": result.total_trades,
                "pf_change_from_base": pf_change,
                "fragile": pf_change > 0.30,
            })

        results["parameters"][param_name] = param_results
        fragile_vals = [r["value"] for r in param_results if r["fragile"]]
        if fragile_vals:
            logger.warning(
                "Parameter '%s' is FRAGILE at values: %s (>30%% PF change)",
                param_name, fragile_vals
            )

    return results


def monte_carlo_simulation(
    trades: list,  # list of TradeRecord
    iterations: int = config.MONTE_CARLO_ITERATIONS,
    initial_capital: float = config.INITIAL_CAPITAL,
) -> dict:
    """
    Randomize trade order 1000 times to test robustness.
    Returns distribution of outcomes.
    """
    if not trades:
        return {
            "median_return": 0.0,
            "worst_case_return": 0.0,
            "best_case_return": 0.0,
            "median_max_drawdown": 0.0,
            "worst_case_max_drawdown": 0.0,
            "probability_of_ruin": 0.0,
        }

    pnls = [t.net_pnl_usd for t in trades]
    returns = []
    max_drawdowns = []
    ruin_count = 0
    ruin_threshold = initial_capital * 0.50  # >50% drawdown = ruin

    for _ in range(iterations):
        shuffled = pnls.copy()
        random.shuffle(shuffled)

        equity = initial_capital
        peak = initial_capital
        max_dd = 0.0

        for pnl in shuffled:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
            if equity <= 0:
                equity = 0
                break

        final_return = (equity - initial_capital) / initial_capital
        returns.append(final_return)
        max_drawdowns.append(max_dd)

        if max_dd >= 0.50:
            ruin_count += 1

    returns.sort()
    max_drawdowns.sort()

    n = len(returns)
    p5 = returns[int(n * 0.05)]
    p50 = returns[int(n * 0.50)]
    p95 = returns[int(n * 0.95)]

    dd_p50 = max_drawdowns[int(n * 0.50)]
    dd_p95 = max_drawdowns[int(n * 0.95)]

    return {
        "median_return": p50,
        "worst_case_return": p5,
        "best_case_return": p95,
        "median_max_drawdown": dd_p50,
        "worst_case_max_drawdown": dd_p95,
        "probability_of_ruin": ruin_count / iterations,
        "iterations": iterations,
        "returns_distribution": {
            "p5": p5, "p25": returns[int(n * 0.25)],
            "p50": p50, "p75": returns[int(n * 0.75)], "p95": p95
        },
    }


def regime_breakdown_stress(
    candles: list[dict],
    trades: list,
    btc_candles: Optional[list[dict]] = None,
) -> dict:
    """
    Split performance into bull / bear / range periods.
    Bull: BTC +20% in 30 days. Bear: BTC -20%. Range: else.
    Uses the pair's own price if btc_candles not provided.
    """
    ref_candles = btc_candles or candles
    if len(ref_candles) < 30:
        return {}

    MS_30D = 30 * 24 * 3_600_000
    ts_to_regime = {}

    for i, c in enumerate(ref_candles):
        ts = c["timestamp"]
        # Look back 30 days
        lookback_ts = ts - MS_30D
        old_candle = next(
            (ref_candles[j] for j in range(i - 1, -1, -1) if ref_candles[j]["timestamp"] <= lookback_ts),
            None
        )
        if old_candle and old_candle["close"] > 0:
            chg = (c["close"] - old_candle["close"]) / old_candle["close"]
            if chg >= 0.20:
                ts_to_regime[ts] = "bull"
            elif chg <= -0.20:
                ts_to_regime[ts] = "bear"
            else:
                ts_to_regime[ts] = "range"
        else:
            ts_to_regime[ts] = "range"

    def get_regime_for_ts(trade_ts):
        # Find closest candle timestamp
        best = min(ts_to_regime.keys(), key=lambda t: abs(t - trade_ts), default=None)
        return ts_to_regime.get(best, "range")

    buckets = {"bull": [], "bear": [], "range": []}
    for t in trades:
        r = get_regime_for_ts(t.entry_ts)
        buckets[r].append(t)

    result = {}
    for regime_name, regime_trades in buckets.items():
        if not regime_trades:
            result[regime_name] = {"trades": 0, "win_rate": 0.0, "total_pnl": 0.0}
            continue
        wins = [t for t in regime_trades if t.net_pnl_usd > 0]
        result[regime_name] = {
            "trades": len(regime_trades),
            "win_rate": len(wins) / len(regime_trades),
            "total_pnl": sum(t.net_pnl_usd for t in regime_trades),
            "avg_pnl": sum(t.net_pnl_usd for t in regime_trades) / len(regime_trades),
        }

    return result


def _result_summary(result: BacktestResult) -> dict:
    return {
        "total_return": result.total_return_percent,
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown_percent,
        "sharpe": result.sharpe_ratio,
        "expectancy": result.expectancy_per_trade,
    }


def _compute_degradation(train: BacktestResult, test: BacktestResult) -> dict:
    """How much did performance degrade from train to test?"""
    pf_deg = (test.profit_factor - train.profit_factor) / train.profit_factor if train.profit_factor > 0 else 0
    wr_deg = test.win_rate - train.win_rate
    ret_deg = test.total_return_percent - train.total_return_percent
    return {
        "profit_factor_change": pf_deg,
        "win_rate_change": wr_deg,
        "return_change": ret_deg,
        "likely_curve_fitted": pf_deg < -0.30,
    }
