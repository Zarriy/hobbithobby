import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { tsToDate } from '@/lib/utils'
import type { EquityPoint } from '@/types/api'

interface Props { data: EquityPoint[]; initialCapital?: number }

export function EquityCurve({ data, initialCapital = 10000 }: Props) {
  if (data.length === 0) {
    return (
      <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">
        Equity curve will appear after first trades
      </div>
    )
  }

  const chartData = data.map(p => ({
    ts:     p.timestamp,
    equity: p.equity,
    total:  p.equity + p.open_pnl,
  }))

  return (
    <ResponsiveContainer width="100%" height={160}>
      <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
        <XAxis
          dataKey="ts"
          tickFormatter={ts => tsToDate(ts)}
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={80}
        />
        <YAxis
          domain={['auto', 'auto']}
          tick={{ fill: '#94a3b8', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={v => `$${(v / 1000).toFixed(1)}k`}
          width={46}
        />
        <Tooltip
          contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8 }}
          labelStyle={{ color: '#64748b', fontSize: 11 }}
          formatter={(value: number, name: string) => [
            `$${value.toFixed(2)}`,
            name === 'equity' ? 'Realized' : 'Total (incl. open P&L)',
          ]}
          labelFormatter={ts => tsToDate(ts as number)}
        />
        <ReferenceLine y={initialCapital} stroke="#e2e8f0" strokeDasharray="4 4" />
        <Line dataKey="total"  stroke="#6366f1" strokeWidth={1}   dot={false} strokeDasharray="4 2" />
        <Line dataKey="equity" stroke="#059669" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
