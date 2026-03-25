import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import type { RegimeDistribution } from '@/types/api'

const REGIME_COLORS: Record<string, string> = {
  accumulation:    '#059669',
  distribution:    '#dc2626',
  short_squeeze:   '#f59e0b',
  long_liquidation:'#ef4444',
  coiled_spring:   '#8b5cf6',
  deleveraging:    '#f97316',
  // legacy fallbacks
  bullish_trending: '#059669',
  bullish_ranging: '#34d399',
  bearish_trending: '#dc2626',
  bearish_ranging: '#f87171',
  neutral: '#94a3b8',
  choppy: '#64748b',
}

const REGIME_LABELS: Record<string, string> = {
  accumulation:     'Accumulation',
  distribution:     'Distribution',
  short_squeeze:    'Short Squeeze',
  long_liquidation: 'Long Liq.',
  coiled_spring:    'Coiled Spring',
  deleveraging:     'Deleveraging',
  // legacy fallbacks
  bullish_trending: 'Bull Trend',
  bullish_ranging: 'Bull Range',
  bearish_trending: 'Bear Trend',
  bearish_ranging: 'Bear Range',
  neutral: 'Neutral',
  choppy: 'Choppy',
}

interface Props {
  data: RegimeDistribution
}

export function RegimeDistributionChart({ data }: Props) {
  const chartData = Object.entries(data.distribution)
    .filter(([, v]) => v.count > 0)
    .map(([regime, v]) => ({
      name: REGIME_LABELS[regime] ?? regime,
      value: v.count,
      regime,
    }))

  if (chartData.length === 0) {
    return <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">No data yet</div>
  }

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-1">
        {data.total_signals} signals — {data.pair} {data.timeframe}
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={40}
            outerRadius={65}
            paddingAngle={2}
            dataKey="value"
          >
            {chartData.map((entry) => (
              <Cell
                key={entry.regime}
                fill={REGIME_COLORS[entry.regime] ?? '#64748b'}
                stroke="transparent"
              />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 6 }}
            labelStyle={{ color: '#64748b', fontSize: 11 }}
            formatter={(value, name) => {
              const n = value as number
              return [`${n} (${((n / data.total_signals) * 100).toFixed(1)}%)`, name as string]
            }}
          />
          <Legend
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 10, color: '#64748b' }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
