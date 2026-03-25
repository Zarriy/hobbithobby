import { StatCard } from '@/components/ui/Card'
import { formatPct, formatUsd } from '@/lib/utils'
import type { DemoMetrics } from '@/types/api'

export function PerformanceStats({ metrics }: { metrics: DemoMetrics }) {
  if (metrics.status !== 'ok') {
    return (
      <div className="grid grid-cols-2 gap-2">
        <StatCard
          label="Equity"
          value={`$${metrics.current_equity?.toFixed(0) ?? '10,000'}`}
          tooltip="Current paper trading account value"
        />
        <StatCard
          label="Trades"
          value="0"
          sub="No trades yet"
          tooltip="Total number of completed trades"
        />
        <StatCard
          label="Win Rate"
          value="—"
          tooltip="Percentage of trades that closed in profit"
        />
        <StatCard
          label="Sharpe"
          value="—"
          tooltip="Risk-adjusted return ratio. Above 1.0 is good, above 2.0 is strong"
        />
      </div>
    )
  }

  const returnPct    = metrics.total_return_percent ?? 0
  const returnClass  = returnPct >= 0 ? 'text-emerald-600' : 'text-rose-600'

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <StatCard
        label="Return"
        value={formatPct(returnPct)}
        valueClass={returnClass}
        sub={`$${metrics.final_equity?.toFixed(0)}`}
        tooltip="Total return % vs starting capital of $10,000"
      />
      <StatCard
        label="Win Rate"
        value={`${((metrics.win_rate ?? 0) * 100).toFixed(1)}%`}
        valueClass={(metrics.win_rate ?? 0) >= 0.5 ? 'text-emerald-600' : 'text-rose-600'}
        sub={`${metrics.total_trades} trades`}
        tooltip="Percentage of trades that closed in profit"
      />
      <StatCard
        label="Profit Factor"
        value={
          (metrics.profit_factor === Infinity || metrics.profit_factor > 99)
            ? '∞'
            : (metrics.profit_factor ?? 0).toFixed(2)
        }
        valueClass={(metrics.profit_factor ?? 0) >= 1.5 ? 'text-emerald-600' : 'text-muted-foreground'}
        tooltip="Gross profit divided by gross loss. Above 1.5 is good, above 2.0 is strong"
      />
      <StatCard
        label="Max DD"
        value={formatPct(-(metrics.max_drawdown_percent ?? 0))}
        valueClass="text-rose-600"
        tooltip="Largest peak-to-trough equity decline. Lower is better"
      />
      <StatCard
        label="Sharpe"
        value={(metrics.sharpe_ratio ?? 0).toFixed(2)}
        valueClass={(metrics.sharpe_ratio ?? 0) >= 1 ? 'text-emerald-600' : 'text-muted-foreground'}
        sub={`Sortino ${(metrics.sortino_ratio ?? 0).toFixed(2)}`}
        tooltip="Risk-adjusted return (annualised). Above 1.0 is good, above 2.0 is strong"
      />
    </div>
  )
}
