import type {
  SignalsResponse, StatusDetailResponse, DemoPositionsResponse,
  DemoTradesResponse, DemoMetrics, DemoEquityResponse,
  SignalHistoryResponse, DataQualityResponse, RegimeDistribution,
  ConfidenceDistribution, ReasoningResponse, PriceHistoryResponse,
  DemoComparisonResponse,
} from '@/types/api'

const BASE = import.meta.env.VITE_API_URL ?? ''  // set VITE_API_URL in prod (e.g. https://api.hobbithobby.quest)

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`)
  return res.json() as Promise<T>
}

export const api = {
  // ── Signals ──────────────────────────────────────────────────────────────
  getSignals: (pair: string) =>
    get<SignalsResponse>(`/api/signals?pair=${pair}`),

  getSignalHistory: (pair: string, timeframe = '1h', limit = 200) =>
    get<SignalHistoryResponse>(`/api/analytics/signal-history?pair=${pair}&timeframe=${timeframe}&limit=${limit}`),

  getSignalReasoning: (pair: string, timeframe = '1h') =>
    get<ReasoningResponse>(`/api/signals/${pair}/${timeframe}/reasoning`),

  // ── Status ────────────────────────────────────────────────────────────────
  getStatusDetail: () =>
    get<StatusDetailResponse>('/api/status/detail'),

  // ── Demo Trading ──────────────────────────────────────────────────────────
  getDemoPositions: (mode = 'aggressive') =>
    get<DemoPositionsResponse>(`/api/demo/positions?mode=${mode}`),

  getDemoTrades: (limit = 50, mode = 'aggressive') =>
    get<DemoTradesResponse>(`/api/demo/trades?limit=${limit}&mode=${mode}`),

  getDemoMetrics: (mode = 'aggressive') =>
    get<DemoMetrics>(`/api/demo/metrics?mode=${mode}`),

  getDemoEquity: (limit = 500, mode = 'aggressive') =>
    get<DemoEquityResponse>(`/api/demo/equity?limit=${limit}&mode=${mode}`),

  getDemoComparison: () =>
    get<DemoComparisonResponse>('/api/demo/comparison'),

  // ── Analytics ─────────────────────────────────────────────────────────────
  getDataQuality: () =>
    get<DataQualityResponse>('/api/analytics/data-quality'),

  getRegimeDistribution: (pair: string, timeframe = '1h', lookback = 500) =>
    get<RegimeDistribution>(`/api/analytics/regime-distribution?pair=${pair}&timeframe=${timeframe}&lookback=${lookback}`),

  getConfidenceDistribution: (pair: string, timeframe = '1h', lookback = 500) =>
    get<ConfidenceDistribution>(`/api/analytics/confidence-distribution?pair=${pair}&timeframe=${timeframe}&lookback=${lookback}`),

  // ── Charts ────────────────────────────────────────────────────────────────
  getPriceHistory: (pair: string, timeframe = '1h', limit = 100) =>
    get<PriceHistoryResponse>(`/api/charts/price-history?pair=${pair}&timeframe=${timeframe}&limit=${limit}`),
}
