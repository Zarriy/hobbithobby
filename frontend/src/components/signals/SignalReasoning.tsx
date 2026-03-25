import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SignalReasoning as Reasoning } from '@/types/api'

function ImpactDot({ impact }: { impact: string }) {
  return (
    <span className={cn('w-2 h-2 rounded-full flex-shrink-0',
      impact === 'bullish' ? 'bg-emerald-500'
      : impact === 'bearish' ? 'bg-rose-500'
      : impact === 'extreme' ? 'bg-orange-500 animate-pulse'
      : 'bg-slate-300'
    )} />
  )
}

export function SignalReasoning({ reasoning }: { reasoning: Reasoning }) {
  const [open, setOpen] = useState(false)
  const bd = reasoning.confidence_breakdown

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-muted transition-colors"
      >
        <span className="text-xs text-muted-foreground leading-snug flex-1 mr-2">{reasoning.summary}</span>
        {open
          ? <ChevronUp size={14} className="text-muted-foreground flex-shrink-0" />
          : <ChevronDown size={14} className="text-muted-foreground flex-shrink-0" />
        }
      </button>

      {open && (
        <div className="border-t border-border bg-muted/30 px-3 py-3 space-y-4">
          {/* Factors */}
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Regime Factors
            </div>
            {reasoning.regime_factors.map((f, i) => (
              <div key={i} className={cn('flex items-center gap-2 text-xs', f.note ? 'opacity-60' : '')}>
                <ImpactDot impact={f.impact} />
                <span className="text-muted-foreground w-24 flex-shrink-0">{f.factor}</span>
                <span className="text-foreground tabular-nums font-medium">
                  {typeof f.value === 'number' ? f.value.toFixed(4) : f.value}
                </span>
                <span className="text-muted-foreground/60">vs {f.threshold}</span>
                <span className={cn('ml-auto text-xs font-medium',
                  f.direction === 'above' ? 'text-emerald-600' : 'text-muted-foreground'
                )}>
                  {f.direction}
                </span>
                {f.note && <span className="text-amber-600 text-xs italic">{f.note}</span>}
              </div>
            ))}
          </div>

          {/* Confidence waterfall */}
          <div>
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Confidence Breakdown
            </div>
            <div className="flex items-end gap-1 h-10">
              {[
                { label: 'base',  val: bd.base_score ?? 50,    color: 'bg-slate-300' },
                { label: 'vol',   val: bd.volume_bonus ?? 0,   color: 'bg-emerald-400' },
                { label: 'OI',    val: bd.oi_bonus ?? 0,       color: 'bg-sky-400' },
                { label: 'fund',  val: bd.funding_bonus ?? 0,  color: 'bg-violet-400' },
                { label: 'taker', val: bd.taker_bonus ?? 0,    color: 'bg-teal-400' },
                { label: 'pen',   val: -(bd.penalties ?? 0),   color: 'bg-rose-400' },
              ].map(({ label, val, color }) => (
                <div key={label} className="flex flex-col items-center gap-0.5 flex-1">
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {val > 0 ? `+${val}` : val}
                  </span>
                  <div
                    className={cn('w-full rounded-sm', color)}
                    style={{ height: `${Math.max(Math.abs(val) / 100 * 32, 2)}px` }}
                  />
                  <span className="text-xs text-muted-foreground">{label}</span>
                </div>
              ))}
              <div className="flex flex-col items-center gap-0.5 flex-1 border-l border-border pl-1">
                <span className="text-xs text-amber-600 font-bold">{bd.final}</span>
                <div className="w-full h-8 bg-amber-100 rounded-sm border border-amber-200" />
                <span className="text-xs text-muted-foreground">final</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
