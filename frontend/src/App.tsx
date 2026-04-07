import { useState } from 'react'
import { Header } from '@/components/layout/Header'
import { Sidebar } from '@/components/layout/Sidebar'
import { SignalCard } from '@/components/signals/SignalCard'
import { DemoPanel } from '@/components/demo/DemoPanel'
import { RegimeDistributionChart } from '@/components/analytics/RegimeDistribution'
import { ConfidenceHistogram } from '@/components/analytics/ConfidenceHistogram'
import { SignalHistoryChart } from '@/components/analytics/SignalHistoryChart'
import { DataQualityPanel } from '@/components/analytics/DataQualityPanel'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { useSignals, useRegimeDistribution, useConfidenceDistribution, useSignalHistory, useDataQuality } from '@/hooks/useApi'
import { cn } from '@/lib/utils'
import type { Signal } from '@/types/api'

// ── Signal content for selected pair ─────────────────────────────────────────

function PairSignalContent({ pair }: { pair: string }) {
  const { data, isLoading, error } = useSignals(pair)

  if (isLoading) {
    return (
      <Card className="animate-pulse">
        <CardBody>
          <div className="space-y-3">
            <div className="h-5 bg-muted rounded w-32" />
            <div className="h-3 bg-muted rounded w-full" />
            <div className="h-3 bg-muted rounded w-3/4" />
            <div className="h-3 bg-muted rounded w-1/2" />
          </div>
        </CardBody>
      </Card>
    )
  }

  if (error || !data?.signals) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-muted-foreground text-center py-4">
            No signal data available for {pair.replace('USDT', '')}
          </p>
        </CardBody>
      </Card>
    )
  }

  const signal1h = (data.signals as Record<string, Signal>)['1h']
  const signal4h = (data.signals as Record<string, Signal>)['4h']

  if (!signal1h) return null

  return <SignalCard pair={pair} signal1h={signal1h} signal4h={signal4h} />
}

// ── Analytics section for selected pair ──────────────────────────────────────

function AnalyticsSection({ activePair }: { activePair: string }) {
  const [open, setOpen] = useState(true)
  const [activeTf, setActiveTf] = useState<'1h' | '4h'>('1h')

  const { data: regimeDist } = useRegimeDistribution(activePair, activeTf)
  const { data: confDist } = useConfidenceDistribution(activePair, activeTf)
  const { data: signalHistory } = useSignalHistory(activePair, activeTf)
  const { data: dataQuality } = useDataQuality()

  return (
    <div className="border border-border rounded-xl bg-card overflow-hidden shadow-sm">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted transition-colors text-left"
      >
        <span className="text-sm font-semibold text-foreground">Analytics & Data Quality</span>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {activePair.replace('USDT', '')} · {activeTf}
          </span>
          <span className="text-muted-foreground text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-border p-4 space-y-4 bg-background">
          {/* Timeframe selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Timeframe:</span>
            <div className="flex gap-1">
              {(['1h', '4h'] as const).map(tf => (
                <button
                  key={tf}
                  onClick={() => setActiveTf(tf)}
                  className={cn(
                    'text-xs px-3 py-1 rounded-md border transition-colors font-medium',
                    activeTf === tf
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted'
                  )}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader>Confidence History</CardHeader>
              <CardBody>
                <SignalHistoryChart data={signalHistory?.history ?? []} />
              </CardBody>
            </Card>

            <Card>
              <CardHeader>Regime Distribution</CardHeader>
              <CardBody>
                {regimeDist
                  ? <RegimeDistributionChart data={regimeDist} />
                  : <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
                }
              </CardBody>
            </Card>

            <Card>
              <CardHeader>Confidence Histogram</CardHeader>
              <CardBody>
                {confDist
                  ? <ConfidenceHistogram data={confDist} />
                  : <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
                }
              </CardBody>
            </Card>

            <Card>
              <CardHeader>Data Quality</CardHeader>
              <CardBody>
                {dataQuality
                  ? <DataQualityPanel data={dataQuality} />
                  : <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
                }
              </CardBody>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Root app ──────────────────────────────────────────────────────────────────

export default function App() {
  const [activePair, setActivePair] = useState('BTCUSDT')

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <Sidebar activePair={activePair} onSelect={setActivePair} />

      {/* Content offset: sidebar (224px) + header (48px) */}
      <main className="pl-56 pt-12">
        <div className="max-w-[1280px] mx-auto px-5 py-5 space-y-4">

          {/* Coin header */}
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-foreground">
              {activePair.replace('USDT', '')}
              <span className="text-muted-foreground font-normal text-base ml-1">/ USDT</span>
            </h1>
          </div>

          {/* Main grid: signal card + demo panel */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
            <PairSignalContent pair={activePair} />

            <div className="lg:sticky lg:top-[calc(3rem+1.25rem)] lg:self-start">
              <DemoPanel />
            </div>
          </div>

          {/* Analytics */}
          <AnalyticsSection activePair={activePair} />
        </div>
      </main>
    </div>
  )
}
