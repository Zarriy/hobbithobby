// ─── Signal Types ────────────────────────────────────────────────────────────

export type RiskColor = 'green' | 'yellow' | 'red'
export type RegimeState =
  | 'accumulation' | 'distribution' | 'short_squeeze'
  | 'long_liquidation' | 'coiled_spring' | 'deleveraging'
export type ActionBias = 'long_bias' | 'short_bias' | 'stay_flat' | 'reduce_exposure'
export type TrendState = 'uptrend' | 'downtrend' | 'ranging' | 'transition'
export type PriceZone = 'premium' | 'discount' | 'equilibrium'

export interface FVGLevel {
  upper_bound: number
  lower_bound: number
  status: string
  type: string
}

export interface OBLevel {
  upper_bound: number
  lower_bound: number
  status: string
  type: string
  fvg_overlap: boolean
}

export interface SignalMetadata {
  poc: number | null
  macro_regime: string | null
  action_bias: ActionBias
  reasoning?: SignalReasoning
}

export interface Signal {
  id: number
  pair: string
  timeframe: string
  timestamp: number
  regime_state: RegimeState
  risk_color: RiskColor
  confidence: number
  trend_state: TrendState
  price_zone: PriceZone
  nearest_bullish_fvg: FVGLevel | null
  nearest_bearish_fvg: FVGLevel | null
  nearest_bullish_ob: OBLevel | null
  nearest_bearish_ob: OBLevel | null
  equal_highs: number[]
  equal_lows: number[]
  volume_zscore: number
  oi_change_percent: number
  funding_rate: number
  taker_ratio: number
  atr: number
  vwap_deviation: number
  metadata: SignalMetadata
}

export interface SignalsResponse {
  pair: string
  signals: Record<string, Signal>  // keyed by timeframe: "1h" | "4h"
}

// ─── Reasoning Types ─────────────────────────────────────────────────────────

export interface RegimeFactor {
  factor: string
  value: number
  threshold: number
  direction: 'above' | 'below'
  impact: 'bullish' | 'bearish' | 'neutral' | 'extreme'
  note?: string | null
}

export interface ConfidenceBreakdown {
  base_score: number
  volume_bonus?: number
  oi_bonus?: number
  funding_bonus?: number
  taker_bonus?: number
  penalties?: number
  final: number
  note?: string
}

export interface EntryConditions {
  in_fvg: boolean
  fvg_type?: string
  in_ob: boolean
  price_zone: string
  trend_state: string
  action_bias: string
}

export interface SignalReasoning {
  regime_factors: RegimeFactor[]
  confidence_breakdown: ConfidenceBreakdown
  entry_conditions: EntryConditions
  summary: string
}

export interface ReasoningResponse {
  pair: string
  timeframe: string
  timestamp: number
  regime_state: RegimeState
  risk_color: RiskColor
  confidence: number
  reasoning: SignalReasoning
}

// ─── Status Types ─────────────────────────────────────────────────────────────

export interface StalenessFlags {
  signals: 'ok' | 'warning' | 'critical' | 'unknown'
  candles: 'ok' | 'warning' | 'critical' | 'unknown'
  oi_data: 'ok' | 'critical'
  funding: 'ok' | 'warning' | 'critical' | 'unknown'
}

export interface PairStatusDetail {
  last_signal_age_s: number | null
  last_candle_age_s: number | null
  oi_ever_nonzero: boolean
  funding_age_s: number | null
  stale_flags: StalenessFlags
}

export interface StatusDetailResponse {
  timestamp: number
  scheduler: { running: boolean; jobs: string[]; started_at: number }
  pairs: Record<string, PairStatusDetail>
}

// ─── Demo Trading Types ───────────────────────────────────────────────────────

export interface UnrealizedPnl {
  usd: number
  pct_unleveraged: number
  pct_leveraged: number
  roi_on_margin: number
}

export interface RiskReward {
  current_rr: number
  target_rr_tp1: number
  target_rr_tp2: number | null
}

export interface DemoPosition {
  id: number
  pair: string
  timeframe: string
  side: 'long' | 'short'
  leverage: number
  entry_price: number
  current_price: number
  stop_loss: number
  tp1: number
  tp2_target: number | null
  tp1_hit: number
  size_usd: number
  margin_usd: number
  liquidation_price: number | null
  risk_to_liq_pct: number
  unrealized_pnl: UnrealizedPnl
  risk_reward: RiskReward
  hold_duration: string
  entry_ts: number
  regime_at_entry: string
  confidence_at_entry: number
  entry_zone_type: string | null
}

export interface PortfolioSummary {
  total_margin_used: number
  total_unrealized_pnl_usd: number
  total_notional_exposure: number
  effective_leverage: number
  margin_utilization_pct: number
  available_margin: number
  current_equity: number
}

export interface DemoPositionsResponse {
  positions: DemoPosition[]
  count: number
  portfolio_summary: PortfolioSummary
}

export interface DemoTrade {
  id: number
  position_id: number
  pair: string
  timeframe: string
  side: 'long' | 'short'
  entry_price: number
  exit_price: number
  entry_ts: number
  exit_ts: number
  exit_reason: string
  pnl_usd: number
  pnl_percent: number
  fee_usd: number
  net_pnl_usd: number
  size_usd: number
  leverage: number
  margin_usd: number
  pnl_leveraged_pct: number
  regime_at_entry: string
  confidence_at_entry: number
  entry_zone_type: string | null
  hold_hours: number
}

export interface DemoTradesResponse {
  trades: DemoTrade[]
  count: number
}

export interface DemoMetrics {
  status: 'ok' | 'no_trades' | 'not_initialized'
  initial_capital: number
  current_equity: number
  total_return_percent: number
  total_trades: number
  win_rate: number
  profit_factor: number | null
  max_drawdown_percent: number
  sharpe_ratio: number
  sortino_ratio: number
  expectancy_per_trade: number | null
  avg_trade_duration_hours: number
  final_equity: number
  gross_profit: number
  gross_loss: number
  total_fees: number
}

export interface EquityPoint {
  timestamp: number
  equity: number
  open_pnl: number
  open_count: number
}

export interface DemoEquityResponse {
  equity_curve: EquityPoint[]
  count: number
}

// ─── Analytics Types ──────────────────────────────────────────────────────────

export interface RegimeDistributionEntry {
  count: number
  pct: number
}

export interface RegimeDistribution {
  pair: string
  timeframe: string
  total_signals: number
  distribution: Record<string, RegimeDistributionEntry>
}

export interface ConfidenceBucket {
  range: string
  count: number
}

export interface TradeableSignal {
  timestamp: number
  confidence: number
  regime_state: RegimeState
  risk_color: RiskColor
  trend_state: TrendState | string
  action_bias: ActionBias | string
}

export interface ConfidenceDistribution {
  pair: string
  timeframe: string
  total: number
  buckets: ConfidenceBucket[]
  mean: number
  median: number
  std_dev: number
  tradeable_signals: TradeableSignal[]
}

export interface DataQualityEntry {
  pair: string
  timeframe: string
  total_candles: number
  oi_coverage_pct: number
  funding_coverage_pct: number
}

export interface DataQualityResponse {
  data_quality: Record<string, DataQualityEntry>
}

export interface SignalHistoryEntry {
  timestamp: number
  regime_state: RegimeState
  risk_color: RiskColor
  confidence: number
  action_bias: ActionBias | null
  trend_state: TrendState | null
}

export interface SignalHistoryResponse {
  pair: string
  timeframe: string
  count: number
  history: SignalHistoryEntry[]
}

// ─── Chart Types ──────────────────────────────────────────────────────────────

export interface OHLCBar {
  ts: number
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface TradeMarker {
  type: string
  side: 'long' | 'short'
  price: number
  ts: number
  position_id: number
  pnl_usd?: number
  open?: boolean
}

export interface ZoneOverlay {
  top: number
  bottom: number
}

export interface PriceHistoryResponse {
  pair: string
  timeframe: string
  candles: OHLCBar[]
  trade_markers: TradeMarker[]
  zones: Record<string, ZoneOverlay>
}

// ─── Demo Comparison ──────────────────────────────────────────────────────────

export type DemoMode = 'aggressive' | 'conservative'

export interface DemoComparisonResponse {
  comparison: Record<DemoMode, DemoMetrics | { status: string; initial_capital: number; current_equity?: number }>
}
