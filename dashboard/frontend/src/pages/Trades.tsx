import { useState, useMemo } from 'react'
import { useTrades, useDailySummary } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

interface ParsedOption {
  underlying: string
  expiration: string
  type: string
  strike: number
}

// Parse OCC option symbol: GOOGL251205P00307500
function parseOptionSymbol(symbol: string | null | undefined): ParsedOption {
  if (!symbol) {
    return { underlying: 'Unknown', expiration: '', type: '', strike: 0 }
  }
  const match = symbol.match(/^([A-Z]+)(\d{6})([PC])(\d{8})$/)
  if (match) {
    const [, underlying, expDate, type, strikeRaw] = match
    return {
      underlying,
      expiration: `20${expDate.slice(0, 2)}-${expDate.slice(2, 4)}-${expDate.slice(4, 6)}`,
      type: type === 'P' ? 'Put' : 'Call',
      strike: parseInt(strikeRaw) / 1000,
    }
  }
  return { underlying: symbol, expiration: '', type: '', strike: 0 }
}

// Map event_type to strategy
function mapEventToStrategy(eventType: string): string {
  if (eventType.includes('put_sale') || eventType.includes('sell_put')) return 'sell_put'
  if (eventType.includes('call_sale') || eventType.includes('sell_call')) return 'sell_call'
  if (eventType.includes('close') || eventType.includes('buy_to_close')) return 'buy_to_close'
  if (eventType.includes('assignment')) return 'assignment'
  if (eventType.includes('expiration')) return 'expiration'
  return eventType
}

// Map order_status from BigQuery to display status
// order_status is from the polling job: 'pending', 'filled', 'expired', 'canceled'
// Falls back to event_type for assignment/expiration events
function mapToDisplayStatus(orderStatus: string | undefined, eventType: string): string {
  // First check order_status from polling job (most accurate)
  if (orderStatus) {
    switch (orderStatus.toLowerCase()) {
      case 'filled':
        return 'Filled'
      case 'expired':
        return 'Expired'
      case 'canceled':
      case 'cancelled':
        return 'Canceled'
      case 'pending':
        return 'Pending'
    }
  }

  // Fall back to event_type for special cases
  if (eventType.includes('assignment')) return 'Assigned'
  if (eventType.includes('expir')) return 'Expired'
  if (eventType === 'buy_to_close_executed') return 'Closed'

  // Order was submitted but no status update yet
  if (eventType === 'put_sale_executed' || eventType === 'call_sale_executed') return 'Pending'

  return 'Unknown'
}

type SortField = 'date' | 'underlying' | 'strike' | 'expiration' | 'type' | 'strategy' | 'status' | 'qty' | 'premium'
type SortDirection = 'asc' | 'desc'

export default function Trades() {
  const [days, setDays] = useState(30)
  const [sortField, setSortField] = useState<SortField>('date')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [filterTicker, setFilterTicker] = useState('')
  const [filterType, setFilterType] = useState<string>('')

  const { data: trades, loading: tradesLoading, error: tradesError } = useTrades(days)
  const { data: dailySummary } = useDailySummary(7)

  // Parse and transform trades
  const parsedTrades = useMemo(() => {
    if (!trades) return []
    return trades.map((trade) => {
      const parsed = parseOptionSymbol(trade.symbol)
      const eventType = trade.event_type || trade.event || ''
      const strategy = mapEventToStrategy(eventType)
      // Use order_status from BigQuery join with fallback to event_type
      const status = mapToDisplayStatus(trade.order_status, eventType)
      const timestamp = trade.timestamp_et || trade.date_et || ''

      // Calculate premium collected (premium * contracts * 100)
      const contracts = trade.contracts || 1
      const premium = trade.premium || 0
      const premiumCollected = premium > 0 ? premium * contracts * 100 : null

      return {
        ...parsed,
        symbol: trade.symbol,
        strategy,
        status,
        timestamp,
        date: timestamp.split('T')[0],
        qty: contracts,
        limitPrice: trade.limit_price || null,
        premium: premium,
        premiumCollected,
        orderId: trade.order_id,
        finalFillPrice: trade.final_fill_price,
        filledAt: trade.filled_at,
      }
    })
  }, [trades])

  // Filter trades
  const filteredTrades = useMemo(() => {
    return parsedTrades.filter((trade) => {
      if (filterTicker && !trade.underlying.toLowerCase().includes(filterTicker.toLowerCase())) {
        return false
      }
      if (filterType && trade.type !== filterType) {
        return false
      }
      return true
    })
  }, [parsedTrades, filterTicker, filterType])

  // Sort trades
  const sortedTrades = useMemo(() => {
    return [...filteredTrades].sort((a, b) => {
      let comparison = 0
      switch (sortField) {
        case 'date':
          comparison = a.timestamp.localeCompare(b.timestamp)
          break
        case 'underlying':
          comparison = a.underlying.localeCompare(b.underlying)
          break
        case 'strike':
          comparison = a.strike - b.strike
          break
        case 'expiration':
          comparison = a.expiration.localeCompare(b.expiration)
          break
        case 'type':
          comparison = a.type.localeCompare(b.type)
          break
        case 'strategy':
          comparison = a.strategy.localeCompare(b.strategy)
          break
        case 'status':
          comparison = a.status.localeCompare(b.status)
          break
        case 'qty':
          comparison = a.qty - b.qty
          break
        case 'premium':
          comparison = (a.premiumCollected || 0) - (b.premiumCollected || 0)
          break
      }
      return sortDirection === 'desc' ? -comparison : comparison
    })
  }, [filteredTrades, sortField, sortDirection])

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('desc')
    }
  }

  if (tradesLoading) {
    return <LoadingSpinner />
  }

  if (tradesError) {
    return <ErrorMessage message={tradesError} />
  }

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value)
  }

  const formatDateTime = (dateStr: string) => {
    if (!dateStr) return 'N/A'
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    })
  }

  const formatExpiration = (dateStr: string) => {
    if (!dateStr) return 'N/A'
    // Already in YYYY-MM-DD format from parseOptionSymbol
    return dateStr
  }

  const getStrategyBadge = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'bg-purple-900 text-purple-300'
      case 'sell_call':
        return 'bg-blue-900 text-blue-300'
      case 'buy_to_close':
        return 'bg-yellow-900 text-yellow-300'
      case 'assignment':
        return 'bg-red-900 text-red-300'
      case 'expiration':
        return 'bg-green-900 text-green-300'
      default:
        return 'bg-gray-700 text-gray-300'
    }
  }

  const getStrategyLabel = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'Sell Put'
      case 'sell_call':
        return 'Sell Call'
      case 'buy_to_close':
        return 'Close'
      case 'assignment':
        return 'Assigned'
      case 'expiration':
        return 'Expired'
      default:
        return strategy
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Filled':
        return 'bg-green-900 text-green-300'
      case 'Assigned':
        return 'bg-red-900 text-red-300'
      case 'Expired':
        return 'bg-gray-700 text-gray-300'
      case 'Closed':
        return 'bg-yellow-900 text-yellow-300'
      case 'Pending':
        return 'bg-orange-900 text-orange-300'
      case 'Canceled':
        return 'bg-red-900/50 text-red-300'
      default:
        return 'bg-gray-700 text-gray-300'
    }
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="text-gray-600 ml-1">↕</span>
    return <span className="text-cyan-400 ml-1">{sortDirection === 'asc' ? '↑' : '↓'}</span>
  }

  const totalPremium7d = dailySummary?.reduce((sum, d) => sum + d.total_premium, 0) || 0
  const totalTrades7d = dailySummary?.reduce((sum, d) => sum + d.trades_count, 0) || 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Trade History</h1>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="mt-2 sm:mt-0 bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <p className="card-header">7-Day Premium</p>
          <p className="card-value profit">{formatCurrency(totalPremium7d)}</p>
        </div>
        <div className="card">
          <p className="card-header">7-Day Trades</p>
          <p className="card-value text-white">{totalTrades7d}</p>
        </div>
        <div className="card">
          <p className="card-header">Avg Premium</p>
          <p className="card-value text-white">
            {totalTrades7d > 0 ? formatCurrency(totalPremium7d / totalTrades7d) : '$0'}
          </p>
        </div>
        <div className="card">
          <p className="card-header">Showing</p>
          <p className="card-value text-white">{sortedTrades.length}</p>
        </div>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex gap-3 flex-wrap items-center">
          <input
            type="text"
            placeholder="Filter by ticker..."
            value={filterTicker}
            onChange={(e) => setFilterTicker(e.target.value)}
            className="px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white placeholder-gray-400 focus:outline-none focus:border-cyan-500"
          />
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-cyan-500"
          >
            <option value="">All Types</option>
            <option value="Put">Puts</option>
            <option value="Call">Calls</option>
          </select>
          <span className="text-gray-400 text-sm">
            {sortedTrades.length} of {parsedTrades.length} trades
          </span>
        </div>
      </div>

      {/* Trades Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-700">
              <tr>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('date')}
                >
                  Date/Time (ET)<SortIcon field="date" />
                </th>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('underlying')}
                >
                  Ticker<SortIcon field="underlying" />
                </th>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('type')}
                >
                  Type<SortIcon field="type" />
                </th>
                <th
                  className="table-cell table-header text-right cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('strike')}
                >
                  Strike<SortIcon field="strike" />
                </th>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('expiration')}
                >
                  Exp<SortIcon field="expiration" />
                </th>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('strategy')}
                >
                  Action<SortIcon field="strategy" />
                </th>
                <th
                  className="table-cell table-header cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('status')}
                >
                  Status<SortIcon field="status" />
                </th>
                <th
                  className="table-cell table-header text-center cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('qty')}
                >
                  Qty<SortIcon field="qty" />
                </th>
                <th className="table-cell table-header">
                  Order Type
                </th>
                <th
                  className="table-cell table-header text-right cursor-pointer hover:bg-gray-600"
                  onClick={() => handleSort('premium')}
                >
                  Premium<SortIcon field="premium" />
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {sortedTrades.length === 0 ? (
                <tr>
                  <td colSpan={10} className="table-cell text-center text-gray-400 py-8">
                    No trades found
                  </td>
                </tr>
              ) : (
                sortedTrades.map((trade, index) => (
                  <tr key={index} className="hover:bg-gray-750">
                    <td className="table-cell text-gray-300 whitespace-nowrap">
                      {formatDateTime(trade.timestamp)}
                    </td>
                    <td className="table-cell font-medium text-white">
                      {trade.underlying}
                    </td>
                    <td className="table-cell">
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${
                          trade.type === 'Put'
                            ? 'bg-purple-900/50 text-purple-300'
                            : trade.type === 'Call'
                            ? 'bg-blue-900/50 text-blue-300'
                            : 'bg-gray-700 text-gray-300'
                        }`}
                      >
                        {trade.type || 'N/A'}
                      </span>
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {trade.strike > 0 ? `$${trade.strike.toFixed(2)}` : 'N/A'}
                    </td>
                    <td className="table-cell text-gray-300">
                      {formatExpiration(trade.expiration)}
                    </td>
                    <td className="table-cell">
                      <span
                        className={`inline-flex px-2 py-1 rounded text-xs font-medium ${getStrategyBadge(
                          trade.strategy
                        )}`}
                      >
                        {getStrategyLabel(trade.strategy)}
                      </span>
                    </td>
                    <td className="table-cell">
                      <span className={`px-2 py-0.5 rounded text-xs ${getStatusBadge(trade.status)}`}>
                        {trade.status}
                      </span>
                    </td>
                    <td className="table-cell text-center text-gray-300">
                      {trade.qty}
                    </td>
                    <td className="table-cell text-gray-300">
                      {trade.limitPrice ? `Limit @ $${trade.limitPrice.toFixed(2)}` : 'N/A'}
                    </td>
                    <td className="table-cell text-right profit">
                      {trade.premiumCollected ? formatCurrency(trade.premiumCollected) : 'N/A'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
