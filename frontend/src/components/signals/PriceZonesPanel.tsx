import { formatPrice } from '@/lib/utils'
import type { Signal } from '@/types/api'

function ZoneRow({ label, top, bottom, color }: {
  label: string; top?: number; bottom?: number; color: string
}) {
  if (!top || !bottom) return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs text-muted-foreground/50">—</span>
    </div>
  )
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-muted-foreground flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${color}`} />
        {label}
      </span>
      <span className="text-xs text-foreground tabular-nums font-medium">
        {formatPrice(top)} — {formatPrice(bottom)}
      </span>
    </div>
  )
}

export function PriceZonesPanel({ signal }: { signal: Signal }) {
  const bFvg  = signal.nearest_bullish_fvg
  const bearFvg = signal.nearest_bearish_fvg
  const bOb   = signal.nearest_bullish_ob
  const bearOb  = signal.nearest_bearish_ob

  return (
    <div className="divide-y divide-border">
      <ZoneRow label="Bull FVG" top={bFvg?.upper_bound}   bottom={bFvg?.lower_bound}   color="bg-emerald-400" />
      <ZoneRow label="Bear FVG" top={bearFvg?.upper_bound} bottom={bearFvg?.lower_bound} color="bg-rose-400" />
      <ZoneRow label="Bull OB"  top={bOb?.upper_bound}    bottom={bOb?.lower_bound}    color="bg-emerald-600" />
      <ZoneRow label="Bear OB"  top={bearOb?.upper_bound}  bottom={bearOb?.lower_bound}  color="bg-rose-600" />
    </div>
  )
}
