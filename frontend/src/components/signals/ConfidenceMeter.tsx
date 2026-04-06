import { cn } from '@/lib/utils'

export function ConfidenceMeter({ value }: { value: number }) {
  const barColor =
    value >= 80 ? 'bg-emerald-500' :
    value >= 70 ? 'bg-amber-500' :
    'bg-slate-300'

  const textColor =
    value >= 80 ? 'text-emerald-600' :
    value >= 70 ? 'text-amber-600' :
    'text-muted-foreground'

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 relative">
        <div className="h-2 bg-muted rounded-full overflow-hidden">
          <div
            className={cn('h-full rounded-full transition-all duration-500', barColor)}
            style={{ width: `${value}%` }}
          />
        </div>
        {/* Trade entry threshold marker at 70 */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-px h-4 bg-slate-400 dark:bg-slate-500 opacity-70"
          style={{ left: '70%' }}
          title="Min. trade threshold (70)"
        />
      </div>
      <span className={cn('text-sm font-semibold tabular-nums w-8 text-right', textColor)}>
        {value}
      </span>
    </div>
  )
}
