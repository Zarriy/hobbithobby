import { riskColorClass } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { RiskColor, RegimeState } from '@/types/api'

const REGIME_LABELS: Record<string, string> = {
  accumulation:     'Accumulation',
  distribution:     'Distribution',
  short_squeeze:    'Short Squeeze',
  long_liquidation: 'Long Liq.',
  coiled_spring:    'Coiled Spring',
  deleveraging:     'Deleveraging',
}

export function RegimeBadge({ regime, color }: { regime: RegimeState; color: RiskColor }) {
  return (
    <div className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-sm font-medium',
      riskColorClass(color)
    )}>
      <span className={cn(
        'w-2 h-2 rounded-full flex-shrink-0',
        color === 'green' ? 'bg-emerald-500' : color === 'yellow' ? 'bg-amber-500' : 'bg-rose-500'
      )} />
      {REGIME_LABELS[regime] ?? regime}
    </div>
  )
}
