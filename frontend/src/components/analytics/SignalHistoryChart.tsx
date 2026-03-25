import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { tsToDate } from '@/lib/utils'
import type { SignalHistoryEntry } from '@/types/api'

interface Props {
  data: SignalHistoryEntry[]
}

function riskColorHex(color: string): string {
  switch (color) {
    case 'green': return '#059669'
    case 'yellow': return '#d97706'
    case 'red': return '#dc2626'
    default: return '#94a3b8'
  }
}

export function SignalHistoryChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">
        No signal history yet
      </div>
    )
  }

  const chartData = data.map(p => ({
    ts: p.timestamp,
    confidence: p.confidence,
    risk_color: p.risk_color,
    color: riskColorHex(p.risk_color),
  }))

  return (
    <ResponsiveContainer width="100%" height={120}>
      <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="confGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#6366f1" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="ts"
          tickFormatter={ts => tsToDate(ts)}
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={80}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: '#475569', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={28}
          ticks={[0, 25, 50, 70, 100]}
        />
        <Tooltip
          contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 6 }}
          labelStyle={{ color: '#64748b', fontSize: 11 }}
          formatter={(value, _name, props) => [
            `${value as number} (${(props as { payload?: { risk_color?: string } })?.payload?.risk_color ?? ''})`,
            'Confidence',
          ]}
          labelFormatter={ts => tsToDate(ts as number)}
        />
        <ReferenceLine y={70} stroke="#e2e8f0" strokeDasharray="4 4" />
        <Area
          type="monotone"
          dataKey="confidence"
          stroke="#6366f1"
          strokeWidth={1.5}
          fill="url(#confGrad)"
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
