import { useState } from 'react'
import { useMetricsSummary, usePnLBySymbol, usePortfolioChart, useDailySummary } from '../hooks/useApi'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Performance() {
  const [timeRange, setTimeRange] = useState(30)
  const { data: metrics, loading: metricsLoading, error: metricsError } = useMetricsSummary()
  const { data: pnlBySymbol } = usePnLBySymbol()
  const { data: portfolioChart } = usePortfolioChart(timeRange)
  const { data: dailySummary } = useDailySummary(timeRange)

  if (metricsLoading) {
    return <LoadingSpinner />
  }

  if (metricsError) {
    return <ErrorMessage message={metricsError} />
  }

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(1)}%`
  }

  // Prepare chart data
  const chartData = portfolioChart?.map(d => ({
    date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    value: d.portfolio_value,
    premium: d.cumulative_premium,
  })) || []

  const dailyPremiumData = dailySummary?.slice().reverse().map(d => ({
    date: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    premium: d.total_premium,
    trades: d.trades_count,
  })) || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Performance</h1>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(Number(e.target.value))}
          className="mt-2 sm:mt-0 bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <p className="card-header">Total Premium</p>
          <p className="card-value profit">
            {formatCurrency(metrics?.total_premium_30d || 0)}
          </p>
          <p className="text-xs text-gray-400 mt-1">{timeRange} days</p>
        </div>
        <div className="card">
          <p className="card-header">Win Rate</p>
          <p className="card-value text-white">
            {formatPercent(metrics?.win_rate || 0)}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            {metrics?.total_trades_30d || 0} trades
          </p>
        </div>
        <div className="card">
          <p className="card-header">Avg Premium</p>
          <p className="card-value text-white">
            {formatCurrency(metrics?.avg_premium || 0)}
          </p>
          <p className="text-xs text-gray-400 mt-1">per trade</p>
        </div>
        <div className="card">
          <p className="card-header">Return</p>
          <p className={`card-value ${(metrics?.return_30d || 0) >= 0 ? 'profit' : 'loss'}`}>
            {formatPercent(metrics?.return_30d || 0)}
          </p>
          <p className="text-xs text-gray-400 mt-1">{timeRange} days</p>
        </div>
      </div>

      {/* Portfolio Value Chart */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Portfolio Value</h2>
        {chartData.length > 0 ? (
          <div className="h-64 lg:h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9CA3AF" fontSize={12} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                  labelStyle={{ color: '#9CA3AF' }}
                  formatter={(value: number) => [formatCurrency(value), 'Value']}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#3B82F6"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-gray-400 text-center py-8">No data available</p>
        )}
      </div>

      {/* Daily Premium Chart */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Daily Premium Collected</h2>
        {dailyPremiumData.length > 0 ? (
          <div className="h-64 lg:h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dailyPremiumData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="date" stroke="#9CA3AF" fontSize={12} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #374151' }}
                  labelStyle={{ color: '#9CA3AF' }}
                  formatter={(value: number, name: string) => [
                    name === 'premium' ? formatCurrency(value) : value,
                    name === 'premium' ? 'Premium' : 'Trades',
                  ]}
                />
                <Bar dataKey="premium" fill="#10B981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-gray-400 text-center py-8">No data available</p>
        )}
      </div>

      {/* P&L by Symbol */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">P&L by Symbol</h2>
        {pnlBySymbol && pnlBySymbol.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-700">
                <tr>
                  <th className="table-cell table-header">Symbol</th>
                  <th className="table-cell table-header text-right">Total Premium</th>
                  <th className="table-cell table-header text-right">Trades</th>
                  <th className="table-cell table-header text-right">Win Rate</th>
                  <th className="table-cell table-header text-right">Avg Premium</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {pnlBySymbol.map((item) => (
                  <tr key={item.symbol} className="hover:bg-gray-750">
                    <td className="table-cell font-medium text-white">{item.symbol}</td>
                    <td className="table-cell text-right profit">
                      {formatCurrency(item.total_premium)}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {item.trades_count}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {formatPercent(item.win_rate)}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {formatCurrency(item.avg_premium)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-400 text-center py-8">No data available</p>
        )}
      </div>
    </div>
  )
}
