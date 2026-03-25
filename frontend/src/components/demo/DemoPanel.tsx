import { Card, CardHeader, CardBody } from '@/components/ui/Card'
import { PerformanceStats } from './PerformanceStats'
import { EquityCurve } from './EquityCurve'
import { OpenPositions } from './OpenPositions'
import { TradeHistory } from './TradeHistory'
import { useDemoMetrics, useDemoEquity, useDemoPositions, useDemoTrades } from '@/hooks/useApi'

export function DemoPanel() {
  const { data: metrics }    = useDemoMetrics()
  const { data: equityData } = useDemoEquity()
  const { data: posData }    = useDemoPositions()
  const { data: tradesData } = useDemoTrades()

  const defaultMetrics = {
    status: 'no_trades' as const,
    current_equity:  10000,
    initial_capital: 10000,
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader>
          <span>Demo Performance</span>
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
