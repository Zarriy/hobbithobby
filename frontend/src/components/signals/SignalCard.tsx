import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Card, CardBody } from '@/components/ui/Card'
import { Separator } from '@/components/ui/separator'
import { RegimeBadge } from './RegimeBadge'
import { ConfidenceMeter } from './ConfidenceMeter'
import { IndicatorsPanel } from './IndicatorsPanel'
import { PriceZonesPanel } from './PriceZonesPanel'
import { SignalReasoning } from './SignalReasoning'
import { MiniPriceChart } from './MiniPriceChart'
import { useSignalReasoning, usePriceHistory } from '@/hooks/useApi'
import { formatPrice, cn } from '@/lib/utils'
import type { Signal } from '@/types/api'

const ACTION_META: Record<string, { label: string; color: string; bg: string }> = {
  long_bias:       { label: 'Long Bias',  color: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  short_bias:      { label: 'Short Bias', color: 'text-rose-700',    bg: 'bg-rose-50 border-rose-200' },
  stay_flat:       { label: 'Stay Flat',  color: 'text-muted-foreground', bg: 'bg-muted border-border' },
  reduce_exposure: { label: 'Reduce',     color: 'text-amber-700',   bg: 'bg-amber-50 border-amber-200' },
}

interface Props { pair: string; signal1h: Signal; signal4h?: Signal }

export function SignalCard({ pair, signal1h, signal4h }: Props) {
  const [showChart, setShowChart] = useState(false)
  const [activeTab, setActiveTab] = useState<'1h' | '4h'>('1h')
  const signal = activeTab === '1h' ? signal1h : (signal4h ?? signal1h)

  const { data: reasoning } = useSignalReasoning(pair, activeTab)
  const { data: priceData } = usePriceHistory(pair, activeTab, 80)

  const action = ACTION_META[signal.metadata?.action_bias ?? 'stay_flat']
  const macroRegime = signal.metadata?.macro_regime

  const ageS = Math.floor((Date.now() - signal.timestamp) / 1000)
  const ageLabel = ageS < 60 ? `${ageS}s ago` : `${Math.floor(ageS / 60)}m ago`

  return (
    <Card>
      {/* Card header: pair + timeframe tabs + action bias */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-3">
          {/* Timeframe tabs */}
          <div className="flex gap-1 bg-muted rounded-lg p-1">
            {(['1h', '4h'] as const).map(tf => (
              <button
                key={tf}
                onClick={() => setActiveTab(tf)}
                className={cn(
                  'text-xs px-3 py-1 rounded-md font-medium transition-all',
                  activeTab === tf
                    ? 'bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {tf}
              </button>
            ))}
          </div>
          {macroRegime && (
            <span className="text-xs text-muted-foreground">
              4H: {macroRegime}
            </span>
          )}
          <span className="text-xs text-muted-foreground tabular-nums">
            {ageLabel}
          </span>
        </div>

        {/* Action bias badge */}
        <span className={cn(
          'text-xs font-semibold px-2.5 py-1 rounded-full border',
          action.color, action.bg
        )}>
          {action.label}
        </span>
      </div>

      <CardBody className="space-y-4">
        {/* Regime + Confidence */}
        <div className="flex items-center justify-between gap-3">
          <RegimeBadge regime={signal.regime_state} color={signal.risk_color} />
          <div className="text-xs text-muted-foreground text-right">
            <div>{signal.trend_state}</div>
            <div>{signal.price_zone}</div>
          </div>
        </div>

        <ConfidenceMeter value={signal.confidence} />

        <Separator />

        {/* Indicators */}
        <IndicatorsPanel signal={signal} />

        <Separator />

        {/* Key Levels */}
        <div>
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Key Levels
          </div>
          <PriceZonesPanel signal={signal} />
        </div>

        {/* Reasoning */}
        {reasoning?.reasoning && (
          <SignalReasoning reasoning={reasoning.reasoning} />
        )}

        {/* Chart toggle */}
        <button
          onClick={() => setShowChart(v => !v)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
        >
          {showChart ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {showChart ? 'Hide chart' : 'Show price chart'}
          {priceData && (
            <span className="ml-auto tabular-nums font-medium text-foreground">
              {formatPrice(priceData.candles.at(-1)?.c ?? 0)}
            </span>
          )}
        </button>

        {showChart && priceData && (
          <MiniPriceChart data={priceData} />
        )}
      </CardBody>
    </Card>
  )
}
