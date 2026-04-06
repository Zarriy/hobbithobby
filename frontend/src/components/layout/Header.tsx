import { useState, useEffect } from 'react'
import { Moon, Sun } from 'lucide-react'
import { useStatusDetail } from '@/hooks/useApi'
import { stalenessClass, tsToTime } from '@/lib/utils'
import { cn } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

function useTheme() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('theme')
    if (saved === 'dark') return true
    if (saved === 'light') return false
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    const root = document.documentElement
    if (dark) {
      root.classList.add('dark')
      root.classList.remove('light')
      localStorage.setItem('theme', 'dark')
    } else {
      root.classList.add('light')
      root.classList.remove('dark')
      localStorage.setItem('theme', 'light')
    }
  }, [dark])

  return { dark, toggle: () => setDark(v => !v) }
}

const PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'TAOUSDT']

function StaleDot({ flag, label }: { flag: string; label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-block w-2 h-2 rounded-full cursor-default', stalenessClass(flag))} />
      </TooltipTrigger>
      <TooltipContent>
        {label}: <span className="font-medium">{flag}</span>
      </TooltipContent>
    </Tooltip>
  )
}

export function Header() {
  const { data, isError } = useStatusDetail()
  const { dark, toggle } = useTheme()

  const anyStale = data && Object.values(data.pairs).some(p =>
    Object.values(p.stale_flags).some(f => f === 'critical')
  )

  return (
    <TooltipProvider delayDuration={300}>
      <div className="fixed top-0 left-0 right-0 z-30">
        {/* Critical staleness banner */}
        {anyStale && (
          <div className="bg-rose-50 border-b border-rose-200 px-4 py-1.5 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse inline-block" />
            <span className="text-xs text-rose-700 font-medium">
              Data quality issue — stale data detected
            </span>
          </div>
        )}

        {/* Main header bar */}
        <header className="h-12 bg-card border-b border-border flex items-center px-4 gap-3">
          {/* Brand */}
          <div className="flex items-center gap-2 shrink-0">
            <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
              <span className="text-primary-foreground text-xs font-bold">S</span>
            </div>
            <span className="text-sm font-semibold text-foreground">Signal Engine</span>
          </div>

          <Separator orientation="vertical" className="h-4" />

          {/* Status indicator */}
          <span className={cn(
            'text-xs font-medium px-2 py-0.5 rounded-full',
            isError
              ? 'bg-rose-50 text-rose-600'
              : data
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-muted text-muted-foreground'
          )}>
            {isError ? '⚠ Offline' : data ? '● Live' : '○ Connecting'}
          </span>

          {/* Per-pair staleness dots */}
          <div className="flex items-center gap-4 overflow-x-auto flex-1 ml-2">
            {PAIRS.map(pair => {
              const pairData = data?.pairs[pair]
              const flags = pairData?.stale_flags
              const age = pairData?.last_signal_age_s

              return (
                <div key={pair} className="flex items-center gap-1.5 shrink-0">
                  <span className="text-xs text-muted-foreground font-medium">
                    {pair.replace('USDT', '')}
                  </span>
                  {flags ? (
                    <div className="flex gap-0.5">
                      <StaleDot flag={flags.signals} label="Signals" />
                      <StaleDot flag={flags.candles} label="Candles" />
                      <StaleDot flag={flags.oi_data} label="OI" />
                      <StaleDot flag={flags.funding} label="Funding" />
                    </div>
                  ) : (
                    <span className="w-2 h-2 rounded-full bg-slate-200 inline-block" />
                  )}
                  {age != null && (
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {age < 60 ? `${Math.round(age)}s` : `${Math.round(age / 60)}m`}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* Theme toggle + Clock */}
          <div className="flex items-center gap-2 shrink-0 ml-auto">
            <button
              onClick={toggle}
              className="w-7 h-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {dark ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {data ? tsToTime(data.timestamp) : '--:--'}
            </span>
          </div>
        </header>
      </div>
    </TooltipProvider>
  )
}
