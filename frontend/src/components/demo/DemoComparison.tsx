import { useDemoComparison } from '@/hooks/useApi'
import { cn } from '@/lib/utils'
import type { DemoMetrics } from '@/types/api'

const METRICS: { key: keyof DemoMetrics; label: string; fmt: (v: number) => string; higherIsBetter: boolean }[] = [
  { key: 'current_equity',        label: 'Equity',          fmt: v => `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, higherIsBetter: true },
  { key: 'total_return_percent',  label: 'Total Return',    fmt: v => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`,   higherIsBetter: true },
  { key: 'total_trades',          label: 'Trades',          fmt: v => String(Math.round(v)),                     higherIsBetter: false },
  { key: 'win_rate',              label: 'Win Rate',        fmt: v => `${(v * 100).toFixed(1)}%`,                higherIsBetter: true },
  { key: 'profit_factor',         label: 'Profit Factor',   fmt: v => v >= 99 ? '∞' : v.toFixed(2),             higherIsBetter: true },
  { key: 'sharpe_ratio',          label: 'Sharpe',          fmt: v => v.toFixed(2),                              higherIsBetter: true },
  { key: 'max_drawdown_percent',  label: 'Max Drawdown',    fmt: v => `${v.toFixed(2)}%`,                        higherIsBetter: false },
  { key: 'expectancy_per_trade',  label: 'Expectancy/Trade',fmt: v => `$${v.toFixed(2)}`,                        higherIsBetter: true },
  { key: 'avg_trade_duration_hours', label: 'Avg Hold',     fmt: v => `${v.toFixed(1)}h`,                        higherIsBetter: false },
  { key: 'total_fees',            label: 'Total Fees',      fmt: v => `$${v.toFixed(0)}`,                        higherIsBetter: false },
]

function cell(metrics: DemoMetrics | null, key: keyof DemoMetrics, fmt: (v: number) => string) {
  if (!metrics || metrics.status !== 'ok') return <span className="text-muted-foreground">—</span>
  const v = metrics[key] as number
  if (v == null) return <span className="text-muted-foreground">—</span>
  return <>{fmt(v)}</>
}

function winner(agg: DemoMetrics | null, con: DemoMetrics | null, key: keyof DemoMetrics, higherIsBetter: boolean) {
  if (!agg || !con || agg.status !== 'ok' || con.status !== 'ok') return null
  const a = agg[key] as number
  const c = con[key] as number
  if (a === c) return null
  return higherIsBetter ? (a > c ? 'aggressive' : 'conservative') : (a < c ? 'aggressive' : 'conservative')
}

export function DemoComparison() {
  const { data, isLoading } = useDemoComparison()

  if (isLoading) {
    return <div className="text-xs text-muted-foreground text-center py-6">Loading comparison...</div>
  }

  const agg = (data?.comparison?.aggressive ?? null) as DemoMetrics | null
  const con = (data?.comparison?.conservative ?? null) as DemoMetrics | null

  const aggTrades = agg?.status === 'ok' ? agg.total_trades : 0
  const conTrades = con?.status === 'ok' ? con.total_trades : 0

  return (
    <div className="space-y-4">
      {/* Header cards */}
      <div className="grid grid-cols-2 gap-2">
        {(['aggressive', 'conservative'] as const).map(mode => {
          const m = mode === 'aggressive' ? agg : con
          const trades = mode === 'aggressive' ? aggTrades : conTrades
          const isOk = m?.status === 'ok'
          return (
            <div key={mode} className={cn(
              'rounded-lg border p-3 space-y-1',
              mode === 'aggressive' ? 'border-amber-500/40 bg-amber-500/5' : 'border-emerald-500/40 bg-emerald-500/5'
            )}>
              <div className="flex items-center gap-1.5">
                <span className={cn('w-2 h-2 rounded-full', mode === 'aggressive' ? 'bg-amber-500' : 'bg-emerald-500')} />
                <span className="text-xs font-semibold capitalize text-foreground">{mode}</span>
              </div>
              <div className="text-xs text-muted-foreground">
                {mode === 'aggressive' ? 'Yellow + Green signals' : 'Green signals only'}
              </div>
              {isOk ? (
                <div className="text-sm font-bold text-foreground">
                  ${(m as DemoMetrics).current_equity.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                  <span className={cn('ml-1 text-xs font-medium', (m as DemoMetrics).total_return_percent >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                    {(m as DemoMetrics).total_return_percent >= 0 ? '+' : ''}{(m as DemoMetrics).total_return_percent.toFixed(1)}%
                  </span>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">{trades === 0 ? 'No trades yet' : 'Initializing...'}</div>
              )}
              <div className="text-xs text-muted-foreground">{trades} trades</div>
            </div>
          )
        })}
      </div>

      {/* Metrics table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-1.5 px-2 text-left font-medium">Metric</th>
              <th className="py-1.5 px-2 text-right font-medium text-amber-600">Aggressive</th>
              <th className="py-1.5 px-2 text-right font-medium text-emerald-600">Conservative</th>
            </tr>
          </thead>
          <tbody>
            {METRICS.map(({ key, label, fmt, higherIsBetter }) => {
              const w = winner(agg, con, key, higherIsBetter)
              return (
                <tr key={key} className="border-b border-border/40 hover:bg-muted/50 transition-colors">
                  <td className="py-1.5 px-2 text-muted-foreground">{label}</td>
                  <td className={cn(
                    'py-1.5 px-2 text-right tabular-nums font-medium',
                    w === 'aggressive' ? 'text-amber-600' : 'text-foreground'
                  )}>
                    {cell(agg, key, fmt)}
                    {w === 'aggressive' && <span className="ml-1 text-amber-500">↑</span>}
                  </td>
                  <td className={cn(
                    'py-1.5 px-2 text-right tabular-nums font-medium',
                    w === 'conservative' ? 'text-emerald-600' : 'text-foreground'
                  )}>
                    {cell(con, key, fmt)}
                    {w === 'conservative' && <span className="ml-1 text-emerald-500">↑</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-muted-foreground text-center">
        ↑ indicates better value · updates every 60s
      </p>
    </div>
  )
}
