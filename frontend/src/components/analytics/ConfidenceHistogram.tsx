import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import type { ConfidenceDistribution } from '@/types/api'

function bucketColor(bucketStart: number): string {
  if (bucketStart >= 80) return '#059669'
  if (bucketStart >= 70) return '#34d399'
  if (bucketStart >= 50) return '#d97706'
  if (bucketStart >= 30) return '#ea580c'
  return '#dc2626'
}

interface Props {
  data: ConfidenceDistribution
}

export function ConfidenceHistogram({ data }: Props) {
  const chartData = data.buckets.map(b => {
    const start = parseInt(b.range.split('-')[0])
    return { bucket: b.range, count: b.count, start }
  })

  if (chartData.every(d => d.count === 0)) {
    return <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">No data yet</div>
  }

  return (
    <div>
      <div className="flex gap-4 text-xs text-muted-foreground mb-2">
        <span>Mean <span className="text-foreground">{data.mean.toFixed(1)}</span></span>
        <span>Median <span className="text-foreground">{data.median.toFixed(1)}</span></span>
        <span>σ <span className="text-foreground">{data.std_dev.toFixed(1)}</span></span>
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
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {chartData.map((entry) => (
              <Cell key={entry.bucket} fill={bucketColor(entry.start)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
