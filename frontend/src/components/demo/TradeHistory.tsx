import { useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { formatPrice, formatDuration, exitReasonBadgeClass, cn, tsToDate } from '@/lib/utils'
import type { DemoTrade } from '@/types/api'

const EXIT_LABELS: Record<string, string> = {
  tp1: 'TP1', tp2: 'TP2', stop_loss: 'SL',
  regime_red_exit: 'Regime', time_exit: 'Time', forced_close_end: 'Forced',
}

const PAGE_SIZE = 20

export function TradeHistory({ trades }: { trades: DemoTrade[] }) {
  const [page, setPage]     = useState(0)
  const [filter, setFilter] = useState<string>('all')

  const filtered    = filter === 'all' ? trades : trades.filter(t => t.exit_reason === filter)
  const page_trades = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const totalPages  = Math.ceil(filtered.length / PAGE_SIZE)

  if (trades.length === 0) {
    return <div className="text-center text-muted-foreground py-6 text-sm">No closed trades yet</div>
  }

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex gap-1 flex-wrap">
        {['all', 'tp1', 'tp2', 'stop_loss', 'regime_red_exit', 'time_exit'].map(f => (
          <button
            key={f}
            onClick={() => { setFilter(f); setPage(0) }}
            className={cn(
              'text-xs px-2.5 py-1 rounded-md border transition-colors font-medium',
              filter === f
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            {f === 'all' ? 'All' : EXIT_LABELS[f] ?? f}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground self-center">{filtered.length} trades</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[560px]">
          <thead>
            <tr className="text-muted-foreground border-b border-border">
              <th className="px-2 py-2 text-left font-medium">#</th>
              <th className="px-2 py-2 text-left font-medium">Pair</th>
              <th className="px-2 py-2 text-left font-medium">Side</th>
              <th className="px-2 py-2 text-left font-medium">Lev</th>
              <th className="px-2 py-2 text-left font-medium">Entry → Exit</th>
              <th className="px-2 py-2 text-right font-medium">Net P&L</th>
              <th className="px-2 py-2 text-right font-medium">ROI%</th>
              <th className="px-2 py-2 text-left font-medium">Reason</th>
              <th className="px-2 py-2 text-left font-medium">Hold</th>
              <th className="px-2 py-2 text-left font-medium">Conf</th>
            </tr>
          </thead>
          <tbody>
            {page_trades.map(t => {
              const isProfit = t.net_pnl_usd > 0
              const roi      = t.pnl_leveraged_pct * 100
              return (
                <tr key={t.id} className="border-b border-border/60 hover:bg-muted transition-colors">
                  <td className="px-2 py-2 text-muted-foreground">{t.id}</td>
                  <td className="px-2 py-2 font-medium text-foreground">{t.pair.replace('USDT', '')}</td>
                  <td className="px-2 py-2">
                    <Badge variant={t.side === 'long' ? 'green' : 'red'}>
                      {t.side === 'long' ? '▲' : '▼'} {t.side.toUpperCase()}
                    </Badge>
                  </td>
                  <td className="px-2 py-2 text-muted-foreground">{t.leverage}×</td>
                  <td className="px-2 py-2 text-muted-foreground tabular-nums">
                    {formatPrice(t.entry_price)} → {formatPrice(t.exit_price)}
                  </td>
                  <td className={cn('px-2 py-2 text-right tabular-nums font-semibold', isProfit ? 'text-emerald-600' : 'text-rose-600')}>
                    {isProfit ? '+' : ''}${t.net_pnl_usd.toFixed(2)}
                  </td>
                  <td className={cn('px-2 py-2 text-right tabular-nums font-medium', isProfit ? 'text-emerald-600' : 'text-rose-600')}>
                    {roi >= 0 ? '+' : ''}{roi.toFixed(1)}%
                  </td>
                  <td className="px-2 py-2">
                    <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded border text-xs font-medium', exitReasonBadgeClass(t.exit_reason))}>
                      {EXIT_LABELS[t.exit_reason] ?? t.exit_reason}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-muted-foreground">{formatDuration(t.hold_hours)}</td>
                  <td className="px-2 py-2 text-muted-foreground">{t.confidence_at_entry}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center gap-2 justify-end text-xs text-muted-foreground">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 rounded border border-border disabled:opacity-30 hover:bg-muted transition-colors"
          >
            ←
          </button>
          <span>{page + 1} / {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 rounded border border-border disabled:opacity-30 hover:bg-muted transition-colors"
          >
            →
          </button>
        </div>
      )}
    </div>
  )
}
