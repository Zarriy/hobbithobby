import { cn } from '@/lib/utils'
import type { Signal } from '@/types/api'

function Indicator({ label, value, sub, alert }: {
  label: string; value: string; sub?: string; alert?: boolean
}) {
  return (
    <div className="flex flex-col gap-0.5 p-2.5 rounded-lg bg-muted">
      <span className="text-xs text-muted-foreground font-medium">{label}</span>
      <span className={cn('text-sm font-semibold tabular-nums', alert ? 'text-amber-600' : 'text-foreground')}>
        {value}
      </span>
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
    </div>
  )
}

export function IndicatorsPanel({ signal }: { signal: Signal }) {
  const oiPct = (signal.oi_change_percent ?? 0) * 100
  const noOI = oiPct === 0

  return (
    <div className="grid grid-cols-3 gap-2">
      <Indicator
        label="Vol Z-Score"
        value={(signal.volume_zscore ?? 0).toFixed(2)}
        alert={(signal.volume_zscore ?? 0) >= 2}
        sub={(signal.volume_zscore ?? 0) >= 2 ? 'elevated' : undefined}
      />
      <Indicator
        label="OI Change"
        value={noOI ? 'N/A' : `${oiPct >= 0 ? '+' : ''}${oiPct.toFixed(2)}%`}
        alert={noOI}
        sub={noOI ? 'vol fallback' : undefined}
      />
      <Indicator
        label="Funding"
        value={((signal.funding_rate ?? 0) * 100).toFixed(4) + '%'}
        alert={Math.abs(signal.funding_rate ?? 0) >= 0.0003}
      />
      <Indicator
        label="Taker Ratio"
        value={(signal.taker_ratio ?? 0.5).toFixed(3)}
        sub={
          (signal.taker_ratio ?? 0.5) >= 0.55 ? 'buy heavy' :
          (signal.taker_ratio ?? 0.5) <= 0.45 ? 'sell heavy' :
          'neutral'
        }
      />
      <Indicator
        label="ATR"
        value={
          (signal.atr ?? 0) >= 1000
            ? `$${((signal.atr ?? 0) / 1000).toFixed(1)}k`
            : `$${(signal.atr ?? 0).toFixed(2)}`
        }
      />
      <Indicator
        label="VWAP Dev"
        value={`${(signal.vwap_deviation ?? 0) >= 0 ? '+' : ''}${(signal.vwap_deviation ?? 0).toFixed(2)}σ`}
        alert={Math.abs(signal.vwap_deviation ?? 0) >= 2}
      />
    </div>
  )
}
