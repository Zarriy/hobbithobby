import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { LiquidationGauge } from './LiquidationGauge'
import { formatPrice, formatUsd, cn } from '@/lib/utils'
import type { DemoPosition, PortfolioSummary } from '@/types/api'

function LeverageBadge({ lev }: { lev: number }) {
  const variant = lev >= 20 ? 'red' : lev >= 10 ? 'yellow' : 'default'
  return <Badge variant={variant}>{lev}×</Badge>
}

function PositionRow({ pos }: { pos: DemoPosition }) {
  const [expanded, setExpanded] = useState(false)
  const pnl      = pos.unrealized_pnl
  const isProfit = pnl.usd >= 0

  return (
    <>
      <tr
        className={cn(
          'border-b border-border hover:bg-muted/50 cursor-pointer transition-colors',
          isProfit ? 'bg-emerald-50/40' : 'bg-rose-50/40'
        )}
        onClick={() => setExpanded(v => !v)}
      >
        <td className="px-3 py-2 text-sm">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-foreground">{pos.pair.replace('USDT', '')}</span>
            <Badge variant={pos.side === 'long' ? 'green' : 'red'}>
              {pos.side === 'long' ? '▲' : '▼'} {pos.side.toUpperCase()}
            </Badge>
          </div>
        </td>
        <td className="px-2 py-2"><LeverageBadge lev={pos.leverage} /></td>
        <td className="px-2 py-2 text-xs text-muted-foreground tabular-nums">{formatPrice(pos.entry_price)}</td>
        <td className="px-2 py-2 text-xs text-foreground tabular-nums font-medium">{formatPrice(pos.current_price)}</td>
        <td className="px-2 py-2 text-xs text-muted-foreground tabular-nums">
          {pos.liquidation_price ? formatPrice(pos.liquidation_price) : '—'}
        </td>
        <td className={cn('px-2 py-2 text-sm font-semibold tabular-nums', isProfit ? 'text-emerald-600' : 'text-rose-600')}>
          {formatUsd(pnl.usd)}
        </td>
        <td className={cn('px-2 py-2 text-xs tabular-nums font-medium', isProfit ? 'text-emerald-600' : 'text-rose-600')}>
          {pnl.roi_on_margin >= 0 ? '+' : ''}{pnl.roi_on_margin.toFixed(2)}%
        </td>
        <td className="px-2 py-2 text-xs text-muted-foreground">{pos.hold_duration}</td>
        <td className="px-2 py-2 text-muted-foreground">
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </td>
      </tr>

      {expanded && (
        <tr className="bg-muted/30 border-b border-border">
          <td colSpan={9} className="px-4 py-3">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <div className="text-xs font-semibold text-muted-foreground mb-2">Liquidation Risk</div>
                {pos.liquidation_price ? (
                  <LiquidationGauge
                    entryPrice={pos.entry_price}
                    liquidationPrice={pos.liquidation_price}
                    currentPrice={pos.current_price}
                    side={pos.side}
                  />
                ) : <span className="text-xs text-muted-foreground">N/A</span>}
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="font-semibold text-muted-foreground mb-1">Trade Info</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Stop Loss</span><span className="tabular-nums font-medium">{formatPrice(pos.stop_loss)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">TP1</span><span className="tabular-nums font-medium">{formatPrice(pos.tp1)}{pos.tp1_hit ? ' ✓' : ''}</span></div>
                {pos.tp2_target && <div className="flex justify-between"><span className="text-muted-foreground">TP2</span><span className="tabular-nums font-medium">{formatPrice(pos.tp2_target)}</span></div>}
                <div className="flex justify-between"><span className="text-muted-foreground">R:R now</span><span className="font-medium">{pos.risk_reward.current_rr.toFixed(2)}R</span></div>
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="font-semibold text-muted-foreground mb-1">Entry Context</div>
                <div className="flex justify-between"><span className="text-muted-foreground">Regime</span><span className="font-medium">{pos.regime_at_entry}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Confidence</span><span className="font-medium">{pos.confidence_at_entry}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Zone</span><span className="font-medium">{pos.entry_zone_type ?? '—'}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Margin</span><span className="tabular-nums font-medium">${pos.margin_usd.toFixed(2)}</span></div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function OpenPositions({ positions, summary }: { positions: DemoPosition[]; summary?: PortfolioSummary }) {
  if (positions.length === 0) {
    return <div className="text-center text-muted-foreground py-6 text-sm">No open positions</div>
  }

  return (
    <div>
      {/* Portfolio summary */}
      {summary && (
        <div className="grid grid-cols-4 gap-2 mb-3 text-xs">
          <div className="bg-muted rounded-lg px-3 py-2">
            <div className="text-muted-foreground mb-0.5">Margin Used</div>
            <div className="font-semibold text-foreground tabular-nums">
              ${summary.total_margin_used.toFixed(0)}
              <span className="text-muted-foreground font-normal"> / ${summary.available_margin.toFixed(0)}</span>
            </div>
          </div>
          <div className="bg-muted rounded-lg px-3 py-2">
            <div className="text-muted-foreground mb-0.5">Eff. Leverage</div>
            <div className="font-semibold text-amber-600 tabular-nums">{summary.effective_leverage.toFixed(1)}×</div>
          </div>
          <div className="bg-muted rounded-lg px-3 py-2">
            <div className="text-muted-foreground mb-0.5">Open P&L</div>
            <div className={cn('font-semibold tabular-nums',
              summary.total_unrealized_pnl_usd >= 0 ? 'text-emerald-600' : 'text-rose-600'
            )}>
              {summary.total_unrealized_pnl_usd >= 0 ? '+' : ''}${summary.total_unrealized_pnl_usd.toFixed(2)}
            </div>
          </div>
          <div className="bg-muted rounded-lg px-3 py-2">
            <div className="text-muted-foreground mb-0.5">Equity</div>
            <div className="font-semibold text-foreground tabular-nums">${summary.current_equity.toFixed(2)}</div>
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[640px]">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="px-3 py-2 text-left font-medium">Pair</th>
              <th className="px-2 py-2 text-left font-medium">Lev</th>
              <th className="px-2 py-2 text-left font-medium">Entry</th>
              <th className="px-2 py-2 text-left font-medium">Current</th>
              <th className="px-2 py-2 text-left font-medium">Liq Price</th>
              <th className="px-2 py-2 text-left font-medium">Unrl P&L</th>
              <th className="px-2 py-2 text-left font-medium">ROI%</th>
              <th className="px-2 py-2 text-left font-medium">Hold</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {positions.map(pos => <PositionRow key={pos.id} pos={pos} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
