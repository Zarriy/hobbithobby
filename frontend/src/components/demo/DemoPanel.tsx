import { useState } from 'react'
import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { PerformanceStats } from './PerformanceStats'
import { EquityCurve } from './EquityCurve'
import { OpenPositions } from './OpenPositions'
import { TradeHistory } from './TradeHistory'
import { DemoComparison } from './DemoComparison'
import { useDemoMetrics, useDemoEquity, useDemoPositions, useDemoTrades } from '@/hooks/useApi'
import { cn } from '@/lib/utils'
import type { DemoMode } from '@/types/api'

const TABS: { id: DemoMode | 'compare'; label: string; sub: string }[] = [
  { id: 'aggressive', label: 'Aggressive', sub: 'Yellow+Green' },
  { id: 'conservative', label: 'Conservative', sub: 'Green only' },
  { id: 'compare', label: 'Compare', sub: 'vs' },
]

function ModeDemoContent({ mode }: { mode: DemoMode }) {
  const { data: metrics }    = useDemoMetrics(mode)
  const { data: equityData } = useDemoEquity(500, mode)
  const { data: posData }    = useDemoPositions(mode)
  const { data: tradesData } = useDemoTrades(50, mode)

  const defaultMetrics = {
    status: 'no_trades' as const,
    current_equity:  10000,
    initial_capital: 10000,
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <span>Performance</span>
          <span className="text-xs text-muted-foreground font-normal">Paper trading</span>
        </CardHeader>
        <CardBody>
          <PerformanceStats metrics={metrics ?? defaultMetrics} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Equity Curve</CardHeader>
        <CardBody>
          <EquityCurve
            data={equityData?.equity_curve ?? []}
            initialCapital={metrics?.initial_capital ?? 10000}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <span>Open Positions</span>
          {posData && posData.count > 0 && (
            <span className="text-xs text-muted-foreground font-normal">{posData.count} open</span>
          )}
        </CardHeader>
        <CardBody>
          <OpenPositions
            positions={posData?.positions ?? []}
            summary={posData?.portfolio_summary}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <span>Trade History</span>
          {tradesData && (
            <span className="text-xs text-muted-foreground font-normal">{tradesData.count} closed</span>
          )}
        </CardHeader>
        <CardBody>
          <TradeHistory trades={tradesData?.trades ?? []} />
        </CardBody>
      </Card>
    </div>
  )
}

export function DemoPanel() {
  const [activeTab, setActiveTab] = useState<DemoMode | 'compare'>('aggressive')

  return (
    <div className="space-y-3">
      {/* Tab bar */}
      <div className="flex rounded-lg border border-border overflow-hidden text-xs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex-1 py-2 px-1 flex flex-col items-center gap-0.5 transition-colors border-r border-border last:border-r-0',
              activeTab === tab.id
                ? tab.id === 'aggressive'
                  ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
                  : tab.id === 'conservative'
                  ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
                  : 'bg-primary/10 text-primary'
                : 'bg-card text-muted-foreground hover:bg-muted'
            )}
          >
            <span className="font-semibold">{tab.label}</span>
            <span className="text-[10px] opacity-70">{tab.sub}</span>
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'aggressive' && <ModeDemoContent mode="aggressive" />}
      {activeTab === 'conservative' && <ModeDemoContent mode="conservative" />}
      {activeTab === 'compare' && (
        <Card>
          <CardHeader>
            <span>Mode Comparison</span>
            <span className="text-xs text-muted-foreground font-normal">Aggressive vs Conservative</span>
          </CardHeader>
          <CardBody>
            <DemoComparison />
          </CardBody>
        </Card>
      )}
    </div>
  )
}
