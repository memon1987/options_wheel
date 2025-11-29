import { useState, useMemo } from 'react'

// What BigQuery actually provides
interface RawTrade {
  timestamp_et?: string
  date_et?: string
  symbol: string
  event_type?: string
  event?: string
}

interface RecentTradesProps {
  trades: RawTrade[]
}

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

type SortField = 'date' | 'underlying' | 'strike' | 'expiration' | 'type'
type SortDirection = 'asc' | 'desc'

export default function RecentTrades({ trades }: RecentTradesProps) {
  const [sortField, setSortField] = useState<SortField>('date')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [filterTicker, setFilterTicker] = useState('')
  const [filterType, setFilterType] = useState<string>('')
  const [filterAction, setFilterAction] = useState<string>('')

  // Parse and transform trades
  const parsedTrades = useMemo(() => {
    return trades.map((trade) => {
      const parsed = parseOptionSymbol(trade.symbol)
      const strategy = mapEventToStrategy(trade.event_type || trade.event || '')
      const timestamp = trade.timestamp_et || trade.date_et || ''

      return {
        ...parsed,
        symbol: trade.symbol,
        strategy,
        timestamp,
        date: timestamp.split('T')[0],
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
      if (filterAction && trade.strategy !== filterAction) {
        return false
      }
      return true
    })
  }, [parsedTrades, filterTicker, filterType, filterAction])

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

  const formatDate = (dateStr: string) => {
    if (!dateStr) return 'N/A'
    // Return YYYY-MM-DD format
    return dateStr.split('T')[0]
  }

  const formatExpiration = (dateStr: string) => {
    if (!dateStr) return 'N/A'
    // Already in YYYY-MM-DD format from parseOptionSymbol
    return dateStr
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

  const getStrategyColor = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'text-purple-400'
      case 'sell_call':
        return 'text-blue-400'
      case 'buy_to_close':
        return 'text-yellow-400'
      case 'assignment':
        return 'text-red-400'
      case 'expiration':
        return 'text-green-400'
      default:
        return 'text-gray-400'
    }
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="text-gray-600">↕</span>
    return <span className="text-cyan-400">{sortDirection === 'asc' ? '↑' : '↓'}</span>
  }


  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Filter by ticker..."
          value={filterTicker}
          onChange={(e) => setFilterTicker(e.target.value)}
          className="px-3 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white placeholder-gray-400 focus:outline-none focus:border-cyan-500"
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="px-3 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-cyan-500"
        >
          <option value="">All Types</option>
          <option value="Put">Puts</option>
          <option value="Call">Calls</option>
        </select>
        <select
          value={filterAction}
          onChange={(e) => setFilterAction(e.target.value)}
          className="px-3 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white focus:outline-none focus:border-cyan-500"
        >
          <option value="">All Actions</option>
          <option value="sell_put">Sell Put</option>
          <option value="sell_call">Sell Call</option>
          <option value="buy_to_close">Close</option>
          <option value="assignment">Assigned</option>
          <option value="expiration">Expired</option>
        </select>
        <span className="text-gray-400 text-sm self-center">
          {sortedTrades.length} trades
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-700">
            <tr>
              <th
                className="table-cell table-header cursor-pointer hover:bg-gray-600"
                onClick={() => handleSort('date')}
              >
                Date <SortIcon field="date" />
              </th>
              <th
                className="table-cell table-header cursor-pointer hover:bg-gray-600"
                onClick={() => handleSort('underlying')}
              >
                Ticker <SortIcon field="underlying" />
              </th>
              <th
                className="table-cell table-header cursor-pointer hover:bg-gray-600"
                onClick={() => handleSort('type')}
              >
                Type <SortIcon field="type" />
              </th>
              <th
                className="table-cell table-header text-right cursor-pointer hover:bg-gray-600"
                onClick={() => handleSort('strike')}
              >
                Strike <SortIcon field="strike" />
              </th>
              <th
                className="table-cell table-header cursor-pointer hover:bg-gray-600"
                onClick={() => handleSort('expiration')}
              >
                Exp <SortIcon field="expiration" />
              </th>
              <th className="table-cell table-header">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {sortedTrades.length === 0 ? (
              <tr>
                <td colSpan={6} className="table-cell text-center text-gray-400 py-8">
                  No trades found
                </td>
              </tr>
            ) : (
              sortedTrades.map((trade, index) => (
                <tr key={index} className="hover:bg-gray-750">
                  <td className="table-cell text-gray-300">{formatDate(trade.timestamp)}</td>
                  <td className="table-cell font-medium text-white">{trade.underlying}</td>
                  <td className="table-cell">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        trade.type === 'Put'
                          ? 'bg-purple-900/50 text-purple-300'
                          : 'bg-blue-900/50 text-blue-300'
                      }`}
                    >
                      {trade.type || 'N/A'}
                    </span>
                  </td>
                  <td className="table-cell text-right text-gray-300">
                    {trade.strike > 0 ? `$${trade.strike.toFixed(2)}` : 'N/A'}
                  </td>
                  <td className="table-cell text-gray-300">{formatExpiration(trade.expiration)}</td>
                  <td className="table-cell">
                    <span className={`text-xs ${getStrategyColor(trade.strategy)}`}>
                      {getStrategyLabel(trade.strategy)}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
