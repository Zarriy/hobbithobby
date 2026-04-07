import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts'
import { formatPrice } from '@/lib/utils'
import type { ConfidenceDistribution, TradeableSignal } from '@/types/api'

function bucketColor(bucketStart: number): string {
  if (bucketStart >= 80) return '#059669'
  if (bucketStart >= 70) return '#34d399'
  if (bucketStart >= 50) return '#d97706'
  if (bucketStart >= 30) return '#ea580c'
  return '#dc2626'
}

const RISK_DOT: Record<string, string> = {
  green: 'bg-emerald-500',
  yellow: 'bg-amber-500',
  red: 'bg-red-500',
}

const BIAS_LABEL: Record<string, string> = {
  long_bias: 'LONG',
  short_bias: 'SHORT',
  stay_flat: 'FLAT',
  reduce_exposure: 'REDUCE',
}

const BIAS_COLOR: Record<string, string> = {
  long_bias: 'text-emerald-400',
  short_bias: 'text-red-400',
  stay_flat: 'text-slate-400',
  reduce_exposure: 'text-amber-400',
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffH = Math.floor(diffMs / 3_600_000)

  if (diffH < 1) return `${Math.floor(diffMs / 60_000)}m ago`
  if (diffH < 24) return `${diffH}h ago`

  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

function SignalRow({ signal }: { signal: TradeableSignal }) {
  return (
    <div className="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-muted/50 text-xs">
      <span className={`w-2 h-2 rounded-full shrink-0 ${RISK_DOT[signal.risk_color] ?? 'bg-slate-500'}`} />
      <span className="text-muted-foreground w-16 shrink-0">{formatTime(signal.timestamp)}</span>
      <span className="font-mono font-medium w-6 text-right">{signal.confidence}</span>
      <span className="font-mono text-foreground w-20 text-right shrink-0">
        {signal.price != null ? formatPrice(signal.price) : '—'}
      </span>
      <span className="text-muted-foreground truncate w-24">{signal.regime_state.replace('_', ' ')}</span>
      <span className={`font-medium w-12 text-right ${BIAS_COLOR[signal.action_bias] ?? 'text-slate-400'}`}>
        {BIAS_LABEL[signal.action_bias] ?? signal.action_bias}
      </span>
      <span className="text-muted-foreground ml-auto text-[10px] capitalize">{(signal.trend_state ?? '').replace('_', ' ')}</span>
    </div>
  )
}

interface Props {
  data: ConfidenceDistribution
}

export function ConfidenceHistogram({ data }: Props) {
  const chartData = data.buckets.map(b => {
    const start = parseInt(b.range.split('-')[0])
    return { bucket: b.range, count: b.count, start }
  })

  const tradeableCount = data.tradeable_signals?.length ?? 0
  const isEmpty = chartData.every(d => d.count === 0)

  if (isEmpty) {
    return <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">No data yet</div>
  }

  return (
    <div>
      <div className="flex gap-4 text-xs text-muted-foreground mb-2">
        <span>Mean <span className="text-foreground">{data.mean.toFixed(1)}</span></span>
        <span>Median <span className="text-foreground">{data.median.toFixed(1)}</span></span>
        <span>&sigma; <span className="text-foreground">{data.std_dev.toFixed(1)}</span></span>
        <span className="ml-auto">{data.total} signals</span>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={2}>
          <XAxis
            dataKey="bucket"
            tick={{ fill: '#475569', fontSize: 9 }}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <YAxis
            tick={{ fill: '#475569', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={24}
          />
          <Tooltip
            contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 6 }}
            labelStyle={{ color: '#64748b', fontSize: 11 }}
            formatter={(value) => [`${value as number} signals`, 'Count']}
          />
          <ReferenceLine x="70-79" stroke="#34d399" strokeDasharray="3 3" strokeWidth={1.5} />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {chartData.map((entry) => (
              <Cell key={entry.bucket} fill={bucketColor(entry.start)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Tradeable signals list (confidence >= 70) */}
      <div className="mt-3 border-t pt-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-foreground">
            Tradeable Signals <span className="text-emerald-500">(&ge;70)</span>
          </span>
          <span className="text-xs text-muted-foreground">{tradeableCount} signals</span>
        </div>
        {tradeableCount === 0 ? (
          <div className="text-xs text-muted-foreground py-2 text-center">No signals at or above 70 confidence</div>
        ) : (
          <div className="max-h-48 overflow-y-auto space-y-0.5">
            <div className="flex items-center gap-2 px-2 text-[10px] text-muted-foreground font-medium uppercase tracking-wider">
              <span className="w-2 shrink-0" />
              <span className="w-16 shrink-0">When</span>
              <span className="w-6 text-right">Conf</span>
              <span className="w-20 text-right shrink-0">Price</span>
              <span className="w-24">Regime</span>
              <span className="w-12 text-right">Bias</span>
              <span className="ml-auto">Trend</span>
            </div>
            {data.tradeable_signals.map((sig, i) => (
              <SignalRow key={`${sig.timestamp}-${i}`} signal={sig} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
