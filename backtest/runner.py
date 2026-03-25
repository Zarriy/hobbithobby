"""
Backtest CLI entry point.

Usage:
  python -m backtest.runner
  python -m backtest.runner --pair BTCUSDT --months 12 --confidence 70
  python -m backtest.runner --stress-only
  python -m backtest.runner --report-only
"""

import argparse
import json
import logging
import pickle
import sys
import time
from pathlib import Path

import config
from backtest.data_loader import load_historical_data
from backtest.metrics import calculate_metrics
from backtest.report import generate_report
from backtest.rules import TradeRule
from backtest.simulator import generate_signal_cache, run_backtest_from_cache
from backtest.stress import (
    monte_carlo_simulation,
    regime_breakdown_stress,
    sensitivity_analysis,
    walk_forward_analysis,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent.parent / "data" / "historical"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _signal_cache_path(pair: str, timeframe: str, months: int) -> Path:
    return CACHE_DIR / f"signal_cache_{pair}_{timeframe}_{months}m.pkl"


def _load_or_generate_cache(candles: list, pair: str, timeframe: str, months: int, force: bool = False):
    cache_path = _signal_cache_path(pair, timeframe, months)
    if not force and cache_path.exists():
        logger.info("Loading signal cache from %s", cache_path)
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    logger.info("Generating signal cache for %d candles...", len(candles))
    t0 = time.time()
    cache = generate_signal_cache(candles, verbose=True)
    elapsed = time.time() - t0
    logger.info("Signal cache generated in %.1fs. Saving.", elapsed)
    with open(cache_path, "wb") as f:
        pickle.dump(cache, f)
    return cache


def run_full_backtest(args) -> None:
    pair = args.pair
    timeframe = args.timeframe
    months = args.months
    confidence = args.confidence

    logger.info("=== BACKTEST: %s %s | %d months | conf>=%d ===", pair, timeframe, months, confidence)

    # Load data
    logger.info("Loading historical data...")
    candles = load_historical_data(pair, timeframe, months=months, force_download=args.force_download)
    if not candles:
        logger.error("No data loaded. Exiting.")
        sys.exit(1)
    logger.info("Loaded %d candles (%s to %s)",
                len(candles),
                _ts_to_date(candles[0]["timestamp"]),
                _ts_to_date(candles[-1]["timestamp"]))

    # Generate/load signal cache
    signal_cache = _load_or_generate_cache(candles, pair, timeframe, months, force=args.regen_cache)

    # Build trade rules
    rules = TradeRule(
        confidence_above=confidence,
        max_hold_hours=args.max_hold_hours,
    )

    # Run backtest
    logger.info("Running backtest simulation...")
    t0 = time.time()
    state = run_backtest_from_cache(
        candles, signal_cache, rules,
        initial_capital=args.capital,
        slippage=config.SLIPPAGE_PERCENT,
        fees=config.TAKER_FEE_PERCENT,
    )
    elapsed = time.time() - t0
    logger.info("Simulation complete in %.2fs. %d trades.", elapsed, len(state.closed_trades))

    # Calculate metrics
    result = calculate_metrics(
        state.closed_trades,
        state.equity_curve,
        state.drawdown_curve,
        initial_capital=args.capital,
    )

    # Print summary
    _print_summary(result)

    if args.stress_only:
        _run_stress(candles, state, rules, signal_cache, pair, timeframe, args.capital)
        return

    # Walk-forward
    wf_results = None
    mc_results = None
    regime_results = None
    sens_results = None

    if not args.quick:
        logger.info("Running walk-forward analysis...")
        wf_results = walk_forward_analysis(
            candles, rules,
            train_months=6, test_months=3, step_months=3,
            initial_capital=args.capital,
        )
        _print_walk_forward(wf_results)

        if state.closed_trades:
            logger.info("Running Monte Carlo simulation...")
            mc_results = monte_carlo_simulation(state.closed_trades, iterations=config.MONTE_CARLO_ITERATIONS)
            _print_monte_carlo(mc_results)

            logger.info("Running regime breakdown...")
            regime_results = regime_breakdown_stress(candles, state.closed_trades)
            _print_regime_breakdown(regime_results)

        logger.info("Running sensitivity analysis...")
        sens_results = sensitivity_analysis(
            candles, rules,
            params_to_vary={
                "confidence_above": [60, 65, 70, 75, 80],
                "take_profit_1_rr": [1.0, 1.5, 2.0, 2.5, 3.0],
                "max_hold_hours": [24, 48, 72, 96],
            },
            signal_cache=signal_cache,
            initial_capital=args.capital,
        )
        _print_sensitivity(sens_results)

    # Generate HTML report
    if not args.no_report:
        report_name = f"reports/backtest_{pair}_{timeframe}_{months}m.html"
        logger.info("Generating HTML report...")
        report_path = generate_report(
            result=result,
            walk_forward=wf_results,
            sensitivity=sens_results,
            monte_carlo=mc_results,
            regime_breakdown=regime_results,
            output_path=report_name,
            pair=pair,
            timeframe=timeframe,
        )
        logger.info("Report saved: %s", report_path)


def _run_stress(candles, state, rules, signal_cache, pair, timeframe, capital) -> None:
    if state.closed_trades:
        logger.info("Running Monte Carlo simulation...")
        mc = monte_carlo_simulation(state.closed_trades)
        _print_monte_carlo(mc)

    logger.info("Running walk-forward...")
    wf = walk_forward_analysis(candles, rules, initial_capital=capital)
    _print_walk_forward(wf)

    logger.info("Running sensitivity...")
    sens = sensitivity_analysis(
        candles, rules,
        params_to_vary={"confidence_above": [60, 65, 70, 75, 80]},
        signal_cache=signal_cache,
        initial_capital=capital,
    )
    _print_sensitivity(sens)


def _print_summary(result) -> None:
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Return:     {result.total_return_percent * 100:+.2f}%")
    print(f"Total Trades:     {result.total_trades}")
    print(f"Win Rate:         {result.win_rate * 100:.1f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print(f"Max Drawdown:     {result.max_drawdown_percent * 100:.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}  (monthly)")
    print(f"Sortino Ratio:    {result.sortino_ratio:.2f}  (monthly)")
    print(f"Avg Monthly Ret:  {result.avg_monthly_return * 100:+.2f}%")
    print(f"Expectancy/Trade: ${result.expectancy_per_trade:.2f}")
    print(f"Avg Hold:         {result.avg_trade_duration_hours:.1f}h")
    print(f"Max Consec Loss:  {result.max_consecutive_losses}")
    print(f"Total Fees:       ${result.total_fees:.2f}")
    print(f"Final Equity:     ${result.final_equity:,.2f}")
    print()
    print("Level Type Breakdown:")
    print(f"  FVG only:       {result.trades_at_fvg_only} trades | WR {result.win_rate_fvg_only * 100:.1f}%")
    print(f"  OB only:        {result.trades_at_ob_only} trades | WR {result.win_rate_ob_only * 100:.1f}%")
    print(f"  FVG+OB overlap: {result.trades_at_fvg_ob_overlap} trades | WR {result.win_rate_fvg_ob_overlap * 100:.1f}%")
    print()
    print("Monthly Returns:")
    for k, v in sorted(result.monthly_returns.items()):
        bar = "+" * int(abs(v * 100)) if v >= 0 else "-" * int(abs(v * 100))
        print(f"  {k}:  {v * 100:+6.2f}%  {bar[:40]}")
    print("=" * 60)


def _print_walk_forward(results: list) -> None:
    if not results:
        return
    print("\nWALK-FORWARD ANALYSIS:")
    for w in results:
        flag = "⚠️ CURVE-FITTED" if w.get("degradation", {}).get("likely_curve_fitted") else "✓"
        print(f"  {_ts_to_date(w['window_start'])} | "
              f"Train PF={w['train_result']['profit_factor']:.2f} "
              f"Test PF={w['test_result']['profit_factor']:.2f} "
              f"| WR {w['test_result']['win_rate'] * 100:.0f}% {flag}")


def _print_monte_carlo(mc: dict) -> None:
    print(f"\nMONTE CARLO ({mc.get('iterations', 1000)} runs):")
    print(f"  Median return:    {mc['median_return'] * 100:+.2f}%")
    print(f"  Worst case (p5):  {mc['worst_case_return'] * 100:+.2f}%")
    print(f"  Best case (p95):  {mc['best_case_return'] * 100:+.2f}%")
    print(f"  Median max DD:    {mc['median_max_drawdown'] * 100:.2f}%")
    print(f"  Worst max DD:     {mc['worst_case_max_drawdown'] * 100:.2f}%")
    print(f"  Prob of ruin:     {mc['probability_of_ruin'] * 100:.1f}%")


def _print_regime_breakdown(rb: dict) -> None:
    print("\nREGIME BREAKDOWN:")
    for regime, data in rb.items():
        print(f"  {regime.title():8}: {data['trades']:3} trades | WR {data.get('win_rate', 0) * 100:.0f}% | P&L ${data.get('total_pnl', 0):+,.0f}")


def _print_sensitivity(sens: dict) -> None:
    print("\nSENSITIVITY ANALYSIS:")
    for param, values in sens.get("parameters", {}).items():
        fragile = [str(v["value"]) for v in values if v.get("fragile")]
        status = f"⚠️ FRAGILE at {fragile}" if fragile else "✓ STABLE"
        print(f"  {param}: {status}")


def _ts_to_date(ts_ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto Signal Engine Backtester")
    parser.add_argument("--pair", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--months", type=int, default=config.BACKTEST_MONTHS)
    parser.add_argument("--confidence", type=int, default=config.CONFIDENCE_THRESHOLD_TRADE)
    parser.add_argument("--capital", type=float, default=config.INITIAL_CAPITAL)
    parser.add_argument("--max-hold-hours", type=int, default=config.MAX_HOLD_HOURS)
    parser.add_argument("--stress-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--quick", action="store_true", help="Skip stress tests")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--regen-cache", action="store_true")

    args = parser.parse_args()

    if args.report_only:
        logger.warning("--report-only: not yet implemented. Run a full backtest first.")
        sys.exit(0)

    run_full_backtest(args)


if __name__ == "__main__":
    main()
