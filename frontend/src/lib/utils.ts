import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatPrice(price: number): string {
  if (price >= 1000) return `$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
  if (price >= 1) return `$${price.toFixed(4)}`
  return `$${price.toFixed(6)}`
}

export function formatPct(value: number, decimals = 2): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(decimals)}%`
}

export function formatUsd(value: number): string {
  const sign = value >= 0 ? '+' : '-'
  return `${sign}$${Math.abs(value).toFixed(2)}`
}

export function riskColorClass(color: string): string {
  switch (color) {
    case 'green':  return 'text-emerald-700 bg-emerald-50 border-emerald-200'
    case 'yellow': return 'text-amber-700 bg-amber-50 border-amber-200'
    case 'red':    return 'text-rose-700 bg-rose-50 border-rose-200'
    default:       return 'text-slate-600 bg-slate-100 border-slate-200'
  }
}

export function riskColorDot(color: string): string {
  switch (color) {
    case 'green':  return 'bg-emerald-500'
    case 'yellow': return 'bg-amber-500'
    case 'red':    return 'bg-rose-500'
    default:       return 'bg-slate-300'
  }
}

export function stalenessClass(flag: string): string {
  switch (flag) {
    case 'ok':       return 'bg-emerald-500'
    case 'warning':  return 'bg-amber-500 animate-pulse'
    case 'critical': return 'bg-rose-500 animate-pulse'
    default:         return 'bg-slate-300'
  }
}

export function regimeColor(regime: string): string {
  const map: Record<string, string> = {
    accumulation:     '#059669',
    distribution:     '#dc2626',
    short_squeeze:    '#7c3aed',
    long_liquidation: '#ea580c',
    coiled_spring:    '#d97706',
    deleveraging:     '#ef4444',
  }
  return map[regime] ?? '#94a3b8'
}

export function exitReasonBadgeClass(reason: string): string {
  switch (reason) {
    case 'tp1':             return 'bg-sky-50 text-sky-700 border-sky-200'
    case 'tp2':             return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    case 'stop_loss':       return 'bg-rose-50 text-rose-700 border-rose-200'
    case 'regime_red_exit': return 'bg-orange-50 text-orange-700 border-orange-200'
    case 'time_exit':       return 'bg-slate-100 text-slate-600 border-slate-200'
    default:                return 'bg-slate-100 text-slate-600 border-slate-200'
  }
}

export function formatDuration(hours: number): string {
  const h = Math.floor(hours)
  const m = Math.round((hours - h) * 60)
  if (h === 0) return `${m}m`
  if (m === 0) return `${h}h`
  return `${h}h ${m}m`
}

export function tsToTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function tsToDate(ts: number): string {
  return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}
