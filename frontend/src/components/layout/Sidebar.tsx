import { useSignals } from '@/hooks/useApi'
import { cn, riskColorDot } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'

const PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'TAOUSDT']

const COIN_META: Record<string, { name: string; symbol: string }> = {
  BTCUSDT: { name: 'Bitcoin',  symbol: '₿' },
  ETHUSDT: { name: 'Ethereum', symbol: 'Ξ' },
  SOLUSDT: { name: 'Solana',   symbol: '◎' },
  XRPUSDT: { name: 'XRP',      symbol: '✕' },
  TAOUSDT: { name: 'Tao',      symbol: 'τ' },
}

function CoinNavItem({
  pair,
  isActive,
  onSelect,
}: {
  pair: string
  isActive: boolean
  onSelect: () => void
}) {
  const { data } = useSignals(pair)
  const signal1h = data?.signals?.['1h']
  const riskColor = signal1h?.risk_color ?? 'unknown'
  const confidence = signal1h?.confidence
  const meta = COIN_META[pair]

  // Get latest price from the most recent candle close approximation
  // We use vwap_deviation + the fact that current price isn't directly in signal
  // Show confidence instead which is always available
  const trendState = signal1h?.trend_state ?? ''

  return (
    <button
      onClick={onSelect}
      className={cn(
        'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors group',
        isActive
          ? 'bg-primary text-primary-foreground'
          : 'text-foreground hover:bg-muted'
      )}
    >
      {/* Coin symbol circle */}
      <div className={cn(
        'w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0',
        isActive
          ? 'bg-primary-foreground/20 text-primary-foreground'
          : 'bg-muted text-foreground'
      )}>
        {meta?.symbol}
      </div>

      {/* Name + meta */}
      <div className="flex-1 min-w-0">
        <div className={cn(
          'text-sm font-medium truncate',
          isActive ? 'text-primary-foreground' : 'text-foreground'
        )}>
          {meta?.name ?? pair.replace('USDT', '')}
        </div>
        {trendState && (
          <div className={cn(
            'text-xs truncate',
            isActive ? 'text-primary-foreground/70' : 'text-muted-foreground'
          )}>
            {trendState}
          </div>
        )}
      </div>

      {/* Regime dot + confidence */}
      <div className="flex flex-col items-end gap-1 shrink-0">
        <span className={cn('w-2 h-2 rounded-full', riskColorDot(riskColor))} />
        {confidence != null && (
          <span className={cn(
            'text-xs font-medium tabular-nums',
            isActive ? 'text-primary-foreground/80' : 'text-muted-foreground'
          )}>
            {confidence}
          </span>
        )}
      </div>
    </button>
  )
}

interface SidebarProps {
  activePair: string
  onSelect: (pair: string) => void
}

export function Sidebar({ activePair, onSelect }: SidebarProps) {
  return (
    <aside className="fixed left-0 top-12 bottom-0 w-56 bg-card border-r border-border flex flex-col z-20">
      {/* Markets section */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">
          Markets
        </div>
        <nav className="space-y-0.5">
          {PAIRS.map(pair => (
            <CoinNavItem
              key={pair}
              pair={pair}
              isActive={activePair === pair}
              onSelect={() => onSelect(pair)}
            />
          ))}
        </nav>
      </div>

      <Separator />

      {/* Footer */}
      <div className="px-4 py-3">
        <div className="text-xs text-muted-foreground">
          <div className="font-medium text-foreground mb-0.5">Demo Mode</div>
          Paper trading · $10,000 capital
        </div>
      </div>
    </aside>
  )
}
