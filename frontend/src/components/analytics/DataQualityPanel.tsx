import { cn } from '@/lib/utils'
import type { DataQualityResponse } from '@/types/api'

function CoverageBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 30 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className={cn('text-xs tabular-nums w-10 text-right',
        pct >= 80 ? 'text-emerald-600' : pct >= 30 ? 'text-amber-600' : 'text-rose-600'
      )}>
        {pct.toFixed(1)}%
      </span>
    </div>
  )
}

interface Props {
  data: DataQualityResponse
}

export function DataQualityPanel({ data }: Props) {
  const entries = Object.entries(data.data_quality).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs min-w-[460px]">
        <thead>
          <tr className="text-muted-foreground border-b border-border">
            <th className="px-2 py-1.5 text-left">Pair × TF</th>
            <th className="px-2 py-1.5 text-left">OI Coverage</th>
            <th className="px-2 py-1.5 text-left">Funding Coverage</th>
            <th className="px-2 py-1.5 text-right">Candles</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, q]) => (
            <tr key={key} className="border-b border-border hover:bg-muted transition-colors">
              <td className="px-2 py-1.5 text-foreground font-medium">{key.replace('_', ' ')}</td>
              <td className="px-2 py-1.5 w-40">
                <CoverageBar pct={q.oi_coverage_pct} />
              </td>
              <td className="px-2 py-1.5 w-40">
                <CoverageBar pct={q.funding_coverage_pct} />
              </td>
              <td className="px-2 py-1.5 text-right text-muted-foreground">{q.total_candles}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted-foreground">
        OI at 0% means volume-only fallback is in use — backtest results are overstated.
        Add a CoinGlass API key to fix.
      </p>
    </div>
  )
}
