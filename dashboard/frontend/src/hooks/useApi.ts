import { useState, useEffect, useCallback } from 'react'

const API_BASE = '/api'

interface FetchState<T> {
  data: T | null
  loading: boolean
  error: string | null
  refetch: () => void
}

export function useFetch<T>(endpoint: string, refreshInterval?: number): FetchState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      const response = await fetch(`${API_BASE}${endpoint}`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      const result = await response.json()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }, [endpoint])

  useEffect(() => {
    fetchData()

    if (refreshInterval) {
      const interval = setInterval(fetchData, refreshInterval)
      return () => clearInterval(interval)
    }
  }, [fetchData, refreshInterval])

  return { data, loading, error, refetch: fetchData }
}

// Specific hooks for different data types
export function useAccount() {
  return useFetch<{
    portfolio_value: string
    cash: string
    buying_power: string
    equity: string
    status: string
    options_trading_level: number
  }>('/live/account', 30000) // Refresh every 30 seconds
}

export function usePositions() {
  return useFetch<Array<{
    symbol: string
    asset_class: string
    qty: string
    side: string
    market_value: string
    unrealized_pl: string
    cost_basis: string
  }>>('/live/positions', 30000)
}

export function useBotStatus() {
  return useFetch<{
    status: string
    market_open: boolean
    timestamp: string
    account_status: string
  }>('/live/status', 15000) // Refresh every 15 seconds
}

export function useTrades(days = 7) {
  return useFetch<Array<{
    timestamp_et?: string
    date_et?: string
    symbol: string
    event_type?: string
    event?: string
  }>>(`/history/trades?days=${days}`)
}

export function useDailySummary(days = 30) {
  return useFetch<Array<{
    date: string
    total_premium: number
    trades_count: number
    puts_sold: number
    calls_sold: number
    win_rate: number
  }>>(`/history/daily-summary?days=${days}`)
}

export function useMetricsSummary() {
  return useFetch<{
    portfolio_value: number
    total_premium_30d: number
    put_premium_30d: number
    call_premium_30d: number
    total_trades_30d: number
    win_rate: number
    avg_premium: number
    active_positions: number
    buying_power: number
    return_30d: number
  }>('/metrics/summary', 60000)
}

export function usePnLBySymbol() {
  return useFetch<Array<{
    symbol: string
    total_premium: number
    trades_count: number
    win_rate: number
    avg_premium: number
  }>>('/metrics/pnl-by-symbol')
}

export function usePortfolioChart(days = 30) {
  return useFetch<Array<{
    date: string
    portfolio_value: number
    daily_pnl: number
    cumulative_premium: number
  }>>(`/metrics/portfolio-chart?days=${days}`)
}

export function useExpirations(days = 30) {
  return useFetch<Array<{
    expiration_date: string
    positions: Array<{
      symbol: string
      strike: number
      option_type: string
      quantity: number
    }>
  }>>(`/metrics/expirations?days=${days}`)
}

export function useErrors(days = 7) {
  return useFetch<Array<{
    timestamp: string
    severity: string
    component: string
    message: string
  }>>(`/history/errors?days=${days}`)
}

export function useFilteringStats(days = 7) {
  return useFetch<Array<{
    timestamp: string
    symbol: string
    stage: string
    passed: boolean
    reason: string
    value: number
    threshold: number
  }>>(`/history/filtering?days=${days}`)
}

export function useConfig() {
  return useFetch<{
    strategy: Record<string, unknown>
    risk: Record<string, unknown>
    stocks: { symbols: string[] }
  }>('/live/config')
}

// Premium tracking hooks
export function usePremiumBySymbol(days = 30) {
  return useFetch<Array<{
    symbol: string
    total_premium: number
    put_premium: number
    call_premium: number
    trade_count: number
  }>>(`/metrics/premium-by-symbol?days=${days}`)
}

export function usePremiumByDay(days = 30) {
  return useFetch<Array<{
    date: string
    total_premium: number
    put_premium: number
    call_premium: number
    trade_count: number
  }>>(`/metrics/premium-by-day?days=${days}`)
}

export function useStockSnapshots(days = 30) {
  return useFetch<Array<{
    date_et: string
    symbol: string
    shares: number
    cost_basis: number
    current_price: number
    unrealized_pl: number
    unrealized_pl_pct: number
    days_held: number
  }>>(`/metrics/stock-snapshots?days=${days}`)
}

export function useWheelCycles() {
  return useFetch<Array<{
    symbol: string
    cycle_start: string
    cycle_end: string | null
    duration_days: number
    put_premium_collected: number
    call_premium_collected: number
    total_premium: number
    capital_gain: number
    total_return: number
    cost_basis: number
    exit_price: number | null
  }>>('/history/wheel-cycles')
}
