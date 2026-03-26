import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

const PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'TAOUSDT']

// ── Status ─────────────────────────────────────────────────────────────────

export function useStatusDetail() {
  return useQuery({
    queryKey: ['status-detail'],
    queryFn: api.getStatusDetail,
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
}

// ── Signals ────────────────────────────────────────────────────────────────

export function useSignals(pair: string) {
  return useQuery({
    queryKey: ['signals', pair],
    queryFn: () => api.getSignals(pair),
    refetchInterval: 60_000,
    staleTime: 55_000,
    enabled: !!pair,
  })
}

export function useAllSignals() {
  return PAIRS.map((pair) => ({
    pair,
    // eslint-disable-next-line react-hooks/rules-of-hooks
    query: useQuery({
      queryKey: ['signals', pair],
      queryFn: () => api.getSignals(pair),
      refetchInterval: 60_000,
      staleTime: 55_000,
    }),
  }))
}

export function useSignalHistory(pair: string, timeframe = '1h') {
  return useQuery({
    queryKey: ['signal-history', pair, timeframe],
    queryFn: () => api.getSignalHistory(pair, timeframe),
    refetchInterval: 120_000,
    staleTime: 115_000,
    enabled: !!pair,
  })
}

export function useSignalReasoning(pair: string, timeframe = '1h') {
  return useQuery({
    queryKey: ['signal-reasoning', pair, timeframe],
    queryFn: () => api.getSignalReasoning(pair, timeframe),
    refetchInterval: 60_000,
    staleTime: 55_000,
    enabled: !!pair,
  })
}

// ── Demo Trading ────────────────────────────────────────────────────────────

export function useDemoPositions(mode = 'aggressive') {
  return useQuery({
    queryKey: ['demo-positions', mode],
    queryFn: () => api.getDemoPositions(mode),
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
}

export function useDemoTrades(limit = 50, mode = 'aggressive') {
  return useQuery({
    queryKey: ['demo-trades', limit, mode],
    queryFn: () => api.getDemoTrades(limit, mode),
    refetchInterval: 60_000,
    staleTime: 55_000,
  })
}

export function useDemoMetrics(mode = 'aggressive') {
  return useQuery({
    queryKey: ['demo-metrics', mode],
    queryFn: () => api.getDemoMetrics(mode),
    refetchInterval: 60_000,
    staleTime: 55_000,
  })
}

export function useDemoEquity(limit = 500, mode = 'aggressive') {
  return useQuery({
    queryKey: ['demo-equity', limit, mode],
    queryFn: () => api.getDemoEquity(limit, mode),
    refetchInterval: 60_000,
    staleTime: 55_000,
  })
}

export function useDemoComparison() {
  return useQuery({
    queryKey: ['demo-comparison'],
    queryFn: api.getDemoComparison,
    refetchInterval: 60_000,
    staleTime: 55_000,
  })
}

// ── Analytics ───────────────────────────────────────────────────────────────

export function useDataQuality() {
  return useQuery({
    queryKey: ['data-quality'],
    queryFn: api.getDataQuality,
    refetchInterval: 300_000,
    staleTime: 290_000,
  })
}

export function useRegimeDistribution(pair: string, timeframe = '1h') {
  return useQuery({
    queryKey: ['regime-distribution', pair, timeframe],
    queryFn: () => api.getRegimeDistribution(pair, timeframe),
    refetchInterval: 300_000,
    staleTime: 290_000,
    enabled: !!pair,
  })
}

export function useConfidenceDistribution(pair: string, timeframe = '1h') {
  return useQuery({
    queryKey: ['confidence-distribution', pair, timeframe],
    queryFn: () => api.getConfidenceDistribution(pair, timeframe),
    refetchInterval: 300_000,
    staleTime: 290_000,
    enabled: !!pair,
  })
}

// ── Charts ──────────────────────────────────────────────────────────────────

export function usePriceHistory(pair: string, timeframe = '1h', limit = 100) {
  return useQuery({
    queryKey: ['price-history', pair, timeframe, limit],
    queryFn: () => api.getPriceHistory(pair, timeframe, limit),
    refetchInterval: 60_000,
    staleTime: 55_000,
    enabled: !!pair,
  })
}
