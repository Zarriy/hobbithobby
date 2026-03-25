import { cn } from '@/lib/utils'
import { formatPrice } from '@/lib/utils'

interface Props {
  entryPrice:       number
  liquidationPrice: number
  currentPrice:     number
  side:             'long' | 'short'
}

export function LiquidationGauge({ entryPrice, liquidationPrice, currentPrice }: Props) {
  const totalRange = Math.abs(entryPrice - liquidationPrice)
  if (totalRange === 0) return null

  const distToLiq = Math.abs(currentPrice - liquidationPrice)
  const riskPct   = (1 - distToLiq / totalRange) * 100  // 0 = safe, 100 = liquidated

  const safeZone    = riskPct < 50
  const warningZone = riskPct >= 50 && riskPct < 75
  const dangerZone  = riskPct >= 75

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Entry {formatPrice(entryPrice)}</span>
        <span className={cn(dangerZone ? 'text-rose-600 font-medium' : 'text-muted-foreground')}>
          Liq {formatPrice(liquidationPrice)}
        </span>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            safeZone    ? 'bg-emerald-500' :
            warningZone ? 'bg-amber-500' :
            'bg-rose-500 animate-pulse'
          )}
          style={{ width: `${Math.min(riskPct, 100)}%` }}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        {distToLiq > 0
          ? `${((distToLiq / currentPrice) * 100).toFixed(1)}% to liquidation`
          : <span className="text-rose-600 font-medium">Liquidated</span>
        }
      </div>
    </div>
  )
}
