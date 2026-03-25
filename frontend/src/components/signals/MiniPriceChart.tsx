import { useEffect, useRef } from 'react'
import { createChart, ColorType, CandlestickSeries, type IChartApi } from 'lightweight-charts'
import type { PriceHistoryResponse } from '@/types/api'

export function MiniPriceChart({ data }: { data: PriceHistoryResponse }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#64748b',
      },
      grid: {
        vertLines: { color: '#f1f5f9' },
        horzLines: { color: '#f1f5f9' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#e2e8f0' },
      timeScale: { borderColor: '#e2e8f0', timeVisible: true },
      height: 200,
    })
    chartRef.current = chart

    const series = chart.addSeries(CandlestickSeries, {
      upColor:        '#059669',
      downColor:      '#dc2626',
      borderUpColor:  '#059669',
      borderDownColor: '#dc2626',
      wickUpColor:    '#059669',
      wickDownColor:  '#dc2626',
    })

    const candles = data.candles.map(c => ({
      time: Math.floor(c.ts / 1000) as unknown as import('lightweight-charts').Time,
      open: c.o, high: c.h, low: c.l, close: c.c,
    }))
    series.setData(candles)

    // Zone overlays as price lines
    const zoneColors: Record<string, string> = {
      nearest_bullish_fvg: '#05966960',
      nearest_bearish_fvg: '#dc262660',
      nearest_bullish_ob:  '#22c55e40',
      nearest_bearish_ob:  '#ef444440',
    }
    Object.entries(data.zones).forEach(([key, zone]) => {
      if (!zone) return
      series.createPriceLine({ price: zone.top,    color: zoneColors[key] ?? '#94a3b8', lineWidth: 1, lineStyle: 2 })
      series.createPriceLine({ price: zone.bottom, color: zoneColors[key] ?? '#94a3b8', lineWidth: 1, lineStyle: 2 })
    })

    // Trade markers
    data.trade_markers.forEach(m => {
      const isEntry = m.type === 'entry'
      const color = isEntry
        ? (m.side === 'long' ? '#059669' : '#dc2626')
        : ((m.pnl_usd ?? 0) >= 0 ? '#059669' : '#dc2626')
      series.createPriceLine({
        price:     m.price,
        color,
        lineWidth: 1,
        lineStyle: isEntry ? 0 : 2,
        title:     isEntry ? (m.side === 'long' ? '▲' : '▼') : m.type,
      })
    })

    chart.timeScale().fitContent()

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current?.clientWidth ?? 400 })
    })
    if (containerRef.current) observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
    }
  }, [data])

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden border border-border" />
}
