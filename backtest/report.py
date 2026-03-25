"""
HTML report generator with embedded charts (matplotlib → base64).
Produces a single self-contained HTML file.
"""

import base64
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _ts_to_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fig_to_base64(fig) -> str:
    """Convert matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor="#1a1a2e")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _render_equity_chart(equity_curve: list, drawdown_curve: list) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec

        timestamps = [t for t, _ in equity_curve]
        equities = [e for _, e in equity_curve]
        dds = [d * 100 for _, d in drawdown_curve]

        dates = [datetime.fromtimestamp(t / 1000, tz=timezone.utc) for t in timestamps]

        fig = plt.figure(figsize=(14, 8), facecolor="#1a1a2e")
        gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1], hspace=0.1)

        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor("#16213e")
        ax1.plot(dates, equities, color="#00d2ff", linewidth=1.5, label="Equity")
        ax1.fill_between(dates, equities, min(equities) if equities else 0, alpha=0.15, color="#00d2ff")
        ax1.set_ylabel("Equity (USDT)", color="#e0e0e0")
        ax1.tick_params(colors="#e0e0e0")
        ax1.legend(facecolor="#16213e", labelcolor="#e0e0e0")
        ax1.grid(True, alpha=0.2, color="#444")
        ax1.spines["bottom"].set_color("#444")
        ax1.spines["top"].set_color("#444")
        ax1.spines["left"].set_color("#444")
        ax1.spines["right"].set_color("#444")
        plt.setp(ax1.get_xticklabels(), visible=False)

        ax2 = fig.add_subplot(gs[1])
        ax2.set_facecolor("#16213e")
        ax2.fill_between(dates, dds, color="#ff4757", alpha=0.7)
        ax2.plot(dates, dds, color="#ff4757", linewidth=0.8)
        ax2.set_ylabel("Drawdown %", color="#e0e0e0")
        ax2.tick_params(colors="#e0e0e0")
        ax2.invert_yaxis()
        ax2.grid(True, alpha=0.2, color="#444")
        for spine in ax2.spines.values():
            spine.set_color("#444")

        return _fig_to_base64(fig)
    except ImportError:
        return ""


def _render_monthly_heatmap(monthly_returns: dict) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        if not monthly_returns:
            return ""

        years = sorted(set(k[:4] for k in monthly_returns.keys()))
        months = [f"{m:02d}" for m in range(1, 13)]
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        data = np.zeros((len(years), 12))
        data[:] = np.nan

        for key, val in monthly_returns.items():
            year, month = key.split("-")
            if year in years and month in months:
                y_idx = years.index(year)
                m_idx = int(month) - 1
                data[y_idx][m_idx] = val * 100

        fig, ax = plt.subplots(figsize=(14, max(3, len(years) * 1.2)), facecolor="#1a1a2e")
        ax.set_facecolor("#16213e")

        vmax = max(abs(data[~np.isnan(data)]).max() if not np.all(np.isnan(data)) else 5, 5)
        im = ax.imshow(data, aspect="auto", cmap="RdYlGn", vmin=-vmax, vmax=vmax)

        ax.set_xticks(range(12))
        ax.set_xticklabels(month_names, color="#e0e0e0")
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years, color="#e0e0e0")

        for y in range(len(years)):
            for m in range(12):
                val = data[y, m]
                if not np.isnan(val):
                    color = "white" if abs(val) > vmax * 0.6 else "#e0e0e0"
                    ax.text(m, y, f"{val:.1f}%", ha="center", va="center",
                            fontsize=8, color=color)

        plt.colorbar(im, ax=ax, label="Return %")
        ax.set_title("Monthly Returns", color="#e0e0e0", pad=10)

        return _fig_to_base64(fig)
    except ImportError:
        return ""


def _render_trade_distribution(trades: list) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not trades:
            return ""

        pnls = [t["net_pnl_usd"] for t in trades]
        fig, axes = plt.subplots(1, 2, figsize=(14, 5), facecolor="#1a1a2e")

        # P&L distribution
        ax = axes[0]
        ax.set_facecolor("#16213e")
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        ax.hist(wins, bins=20, color="#2ed573", alpha=0.7, label="Wins")
        ax.hist(losses, bins=20, color="#ff4757", alpha=0.7, label="Losses")
        ax.set_xlabel("P&L (USDT)", color="#e0e0e0")
        ax.set_ylabel("Count", color="#e0e0e0")
        ax.set_title("P&L Distribution", color="#e0e0e0")
        ax.legend(facecolor="#16213e", labelcolor="#e0e0e0")
        ax.tick_params(colors="#e0e0e0")
        for spine in ax.spines.values():
            spine.set_color("#444")

        # Exit reason breakdown
        ax2 = axes[1]
        ax2.set_facecolor("#16213e")
        reasons = {}
        for t in trades:
            r = t.get("exit_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1

        labels = list(reasons.keys())
        sizes = list(reasons.values())
        colors = ["#2ed573", "#ffa502", "#ff4757", "#1e90ff", "#a29bfe"]
        ax2.pie(sizes, labels=labels, autopct="%1.1f%%",
                colors=colors[:len(labels)],
                textprops={"color": "#e0e0e0"})
        ax2.set_title("Exit Reasons", color="#e0e0e0")

        return _fig_to_base64(fig)
    except ImportError:
        return ""


def generate_report(
    result,  # BacktestResult
    walk_forward: Optional[list] = None,
    sensitivity: Optional[dict] = None,
    monte_carlo: Optional[dict] = None,
    regime_breakdown: Optional[dict] = None,
    output_path: str = "reports/backtest_report.html",
    pair: str = "BTCUSDT",
    timeframe: str = "1h",
) -> str:
    """Generate self-contained HTML report."""
    full_path = Path(__file__).parent.parent / output_path

    equity_img = _render_equity_chart(result.equity_curve, result.drawdown_curve)
    monthly_img = _render_monthly_heatmap(result.monthly_returns)
    dist_img = _render_trade_distribution(result.trade_log)

    color_return = "#2ed573" if result.total_return_percent >= 0 else "#ff4757"
    color_dd = "#ff4757"

    monthly_html = ""
    for _, val in sorted(result.monthly_returns.items()):
        color = "#2ed573" if val >= 0 else "#ff4757"
        monthly_html += f'<td style="color:{color}">{val*100:.1f}%</td>'

    trade_rows = ""
    for t in result.trade_log[:500]:  # Limit to 500 rows in HTML
        pnl_color = "#2ed573" if t["net_pnl_usd"] > 0 else "#ff4757"
        trade_rows += f"""
        <tr>
            <td>{t['id']}</td>
            <td>{t['side'].upper()}</td>
            <td>${t['entry_price']:,.2f}</td>
            <td>${t['exit_price']:,.2f}</td>
            <td>{_ts_to_date(t['entry_ts'])}</td>
            <td>{t['hold_hours']:.1f}h</td>
            <td>{t['exit_reason']}</td>
            <td>{t['regime_at_entry']}</td>
            <td style="color:{pnl_color}">${t['net_pnl_usd']:+,.2f}</td>
        </tr>"""

    wf_rows = ""
    if walk_forward:
        for w in walk_forward:
            color = "#2ed573" if not w.get("degradation", {}).get("likely_curve_fitted") else "#ff4757"
            wf_rows += f"""
            <tr style="color:{color}">
                <td>{_ts_to_date(w['window_start'])} – {_ts_to_date(w['window_end'])}</td>
                <td>{w['train_result']['profit_factor']:.2f}</td>
                <td>{w['test_result']['profit_factor']:.2f}</td>
                <td>{_pct(w['train_result']['win_rate'])}</td>
                <td>{_pct(w['test_result']['win_rate'])}</td>
                <td>{_pct(w['train_result']['total_return'])}</td>
                <td>{_pct(w['test_result']['total_return'])}</td>
            </tr>"""

    mc_section = ""
    if monte_carlo:
        mc = monte_carlo
        mc_section = f"""
        <div class="card">
            <h2>Monte Carlo ({mc.get('iterations', 1000)} iterations)</h2>
            <div class="stats-grid">
                <div class="stat"><div class="label">Median Return</div><div class="value">{_pct(mc['median_return'])}</div></div>
                <div class="stat"><div class="label">Worst Case (5th %ile)</div><div class="value" style="color:#ff4757">{_pct(mc['worst_case_return'])}</div></div>
                <div class="stat"><div class="label">Best Case (95th %ile)</div><div class="value" style="color:#2ed573">{_pct(mc['best_case_return'])}</div></div>
                <div class="stat"><div class="label">Median Max DD</div><div class="value">{_pct(mc['median_max_drawdown'])}</div></div>
                <div class="stat"><div class="label">Worst Case Max DD</div><div class="value" style="color:#ff4757">{_pct(mc['worst_case_max_drawdown'])}</div></div>
                <div class="stat"><div class="label">Probability of Ruin</div><div class="value" style="color:#ff4757">{_pct(mc['probability_of_ruin'])}</div></div>
            </div>
        </div>"""

    regime_section = ""
    if regime_breakdown:
        regime_rows = ""
        for r_name, r_data in regime_breakdown.items():
            pnl_color = "#2ed573" if r_data.get("total_pnl", 0) >= 0 else "#ff4757"
            regime_rows += f"""
            <tr>
                <td>{r_name.title()}</td>
                <td>{r_data.get('trades', 0)}</td>
                <td>{_pct(r_data.get('win_rate', 0))}</td>
                <td style="color:{pnl_color}">${r_data.get('total_pnl', 0):+,.2f}</td>
            </tr>"""
        regime_section = f"""
        <div class="card">
            <h2>Regime Breakdown</h2>
            <table><tr><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Total P&L</th></tr>
            {regime_rows}</table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report — {pair} {timeframe.upper()}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f0f1a; color: #e0e0e0; font-family: 'Courier New', monospace; padding: 20px; }}
h1 {{ color: #00d2ff; margin-bottom: 20px; }}
h2 {{ color: #7ecfff; margin-bottom: 12px; font-size: 1.1em; }}
.card {{ background: #16213e; border: 1px solid #1a3a5c; border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
.stat {{ background: #0f0f1a; padding: 12px; border-radius: 6px; text-align: center; }}
.label {{ font-size: 0.75em; color: #888; margin-bottom: 4px; }}
.value {{ font-size: 1.3em; font-weight: bold; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
th {{ background: #0f3460; color: #7ecfff; padding: 8px; text-align: left; }}
td {{ border-bottom: 1px solid #1a3a5c; padding: 6px 8px; }}
tr:hover td {{ background: #1a2a4a; }}
img {{ max-width: 100%; height: auto; border-radius: 6px; }}
.generated {{ color: #555; font-size: 0.8em; margin-top: 20px; }}
</style>
</head>
<body>
<h1>Backtest Report — {pair} {timeframe.upper()}</h1>
<p style="color:#888;margin-bottom:20px">Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>

<!-- Executive Summary -->
<div class="card">
<h2>Executive Summary</h2>
<div class="stats-grid">
  <div class="stat"><div class="label">Total Return</div><div class="value" style="color:{color_return}">{_pct(result.total_return_percent)}</div></div>
  <div class="stat"><div class="label">Sharpe Ratio</div><div class="value">{result.sharpe_ratio:.2f}</div></div>
  <div class="stat"><div class="label">Sortino Ratio</div><div class="value">{result.sortino_ratio:.2f}</div></div>
  <div class="stat"><div class="label">Max Drawdown</div><div class="value" style="color:{color_dd}">{_pct(result.max_drawdown_percent)}</div></div>
  <div class="stat"><div class="label">Win Rate</div><div class="value">{_pct(result.win_rate)}</div></div>
  <div class="stat"><div class="label">Profit Factor</div><div class="value">{result.profit_factor:.2f}</div></div>
  <div class="stat"><div class="label">Total Trades</div><div class="value">{result.total_trades}</div></div>
  <div class="stat"><div class="label">Expectancy/Trade</div><div class="value">${result.expectancy_per_trade:.2f}</div></div>
  <div class="stat"><div class="label">Avg Hold</div><div class="value">{result.avg_trade_duration_hours:.1f}h</div></div>
  <div class="stat"><div class="label">Max Consec Losses</div><div class="value">{result.max_consecutive_losses}</div></div>
  <div class="stat"><div class="label">Final Equity</div><div class="value">${result.final_equity:,.0f}</div></div>
  <div class="stat"><div class="label">Total Fees</div><div class="value" style="color:#ff4757">${result.total_fees:,.2f}</div></div>
</div>
</div>

<!-- Equity Curve -->
<div class="card">
<h2>Equity Curve &amp; Drawdown</h2>
{'<img src="data:image/png;base64,' + equity_img + '">' if equity_img else '<p style="color:#555">matplotlib not available for chart rendering.</p>'}
</div>

<!-- Monthly Returns -->
<div class="card">
<h2>Monthly Returns</h2>
{'<img src="data:image/png;base64,' + monthly_img + '">' if monthly_img else '<p style="color:#555">Chart not available.</p>'}
</div>

<!-- Trade Distribution -->
<div class="card">
<h2>Trade Distribution</h2>
{'<img src="data:image/png;base64,' + dist_img + '">' if dist_img else '<p style="color:#555">Chart not available.</p>'}
</div>

<!-- Level Type Breakdown -->
<div class="card">
<h2>Entry Zone Breakdown</h2>
<table>
<tr><th>Zone Type</th><th>Trades</th><th>Win Rate</th></tr>
<tr><td>FVG Only</td><td>{result.trades_at_fvg_only}</td><td>{_pct(result.win_rate_fvg_only)}</td></tr>
<tr><td>OB Only</td><td>{result.trades_at_ob_only}</td><td>{_pct(result.win_rate_ob_only)}</td></tr>
<tr><td>FVG + OB Overlap</td><td>{result.trades_at_fvg_ob_overlap}</td><td style="color:#2ed573">{_pct(result.win_rate_fvg_ob_overlap)}</td></tr>
</table>
</div>

<!-- Walk-Forward -->
{"<div class='card'><h2>Walk-Forward Analysis</h2><table><tr><th>Window</th><th>Train PF</th><th>Test PF</th><th>Train WR</th><th>Test WR</th><th>Train Return</th><th>Test Return</th></tr>" + wf_rows + "</table></div>" if walk_forward else ""}

{mc_section}

{regime_section}

<!-- Full Trade Log -->
<div class="card">
<h2>Trade Log (first 500)</h2>
<table>
<tr><th>#</th><th>Side</th><th>Entry</th><th>Exit</th><th>Date</th><th>Hold</th><th>Reason</th><th>Regime</th><th>Net P&L</th></tr>
{trade_rows}
</table>
</div>

<p class="generated">Generated by Crypto Signal Engine</p>
</body>
</html>"""

    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("Report saved to %s", full_path)
    return str(full_path)
