import { useState } from 'react'
import { useTrades, useDailySummary } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Trades() {
  const [limit, setLimit] = useState(50)
  const { data: trades, loading: tradesLoading, error: tradesError } = useTrades(limit)
  const { data: dailySummary } = useDailySummary(7)

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

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getStrategyBadge = (strategy: string) => {
    switch (strategy) {
      case 'sell_put':
        return 'bg-purple-900 text-purple-300'
      case 'sell_call':
        return 'bg-blue-900 text-blue-300'
      case 'buy_to_close':
        return 'bg-green-900 text-green-300'
      default:
        return 'bg-gray-700 text-gray-300'
    }
  }

  const totalPremium7d = dailySummary?.reduce((sum, d) => sum + d.total_premium, 0) || 0
  const totalTrades7d = dailySummary?.reduce((sum, d) => sum + d.trades_count, 0) || 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Trade History</h1>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="mt-2 sm:mt-0 bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600"
        >
          <option value={25}>Last 25 trades</option>
          <option value={50}>Last 50 trades</option>
          <option value={100}>Last 100 trades</option>
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
          <p className="card-value text-white">{trades?.length || 0}</p>
        </div>
      </div>

      {/* Trades Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-700">
              <tr>
                <th className="table-cell table-header">Date</th>
                <th className="table-cell table-header">Symbol</th>
                <th className="table-cell table-header">Strategy</th>
                <th className="table-cell table-header text-right">Strike</th>
                <th className="table-cell table-header text-right">Premium</th>
                <th className="table-cell table-header text-right">DTE</th>
                <th className="table-cell table-header">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {trades?.map((trade, index) => (
                <tr key={index} className="hover:bg-gray-750">
                  <td className="table-cell text-gray-300 whitespace-nowrap">
                    {formatDate(trade.timestamp)}
                  </td>
                  <td className="table-cell font-medium text-white">
                    {trade.underlying || trade.symbol}
                  </td>
                  <td className="table-cell">
                    <span
                      className={`inline-flex px-2 py-1 rounded text-xs font-medium ${getStrategyBadge(
                        trade.strategy
                      )}`}
                    >
                      {trade.strategy.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="table-cell text-right text-gray-300">
                    ${trade.strike_price?.toFixed(0)}
                  </td>
                  <td className="table-cell text-right profit">
                    {formatCurrency(trade.premium * 100)}
                  </td>
                  <td className="table-cell text-right text-gray-300">
                    {trade.dte}
                  </td>
                  <td className="table-cell">
                    <span
                      className={`inline-flex px-2 py-1 rounded text-xs font-medium ${
                        trade.status === 'filled'
                          ? 'bg-green-900 text-green-300'
                          : trade.status === 'pending'
                          ? 'bg-yellow-900 text-yellow-300'
                          : 'bg-gray-700 text-gray-300'
                      }`}
                    >
                      {trade.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {(!trades || trades.length === 0) && (
          <div className="text-center py-12">
            <p className="text-gray-400">No trades found</p>
          </div>
        )}
      </div>
    </div>
  )
}
