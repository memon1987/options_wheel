import { useMetricsSummary, useBotStatus, usePositions, useTrades } from '../hooks/useApi'
import StatusCard from '../components/StatusCard'
import PositionsTable from '../components/PositionsTable'
import RecentTrades from '../components/RecentTrades'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Dashboard() {
  const { data: metrics, loading: metricsLoading, error: metricsError } = useMetricsSummary()
  const { data: status, loading: statusLoading } = useBotStatus()
  const { data: positions, loading: positionsLoading } = usePositions()
  const { data: trades, loading: tradesLoading } = useTrades(5)

  if (metricsLoading && statusLoading) {
    return <LoadingSpinner />
  }

  if (metricsError) {
    return <ErrorMessage message={metricsError} />
  }

  const formatCurrency = (value: number | undefined) => {
    if (value === undefined) return '$0.00'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(value)
  }

  const formatPercent = (value: number | undefined) => {
    if (value === undefined) return '0.0%'
    return `${(value * 100).toFixed(1)}%`
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <div className="flex items-center mt-2 sm:mt-0">
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
              status?.market_open
                ? 'bg-green-900 text-green-300'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            <span
              className={`w-2 h-2 mr-2 rounded-full ${
                status?.market_open ? 'bg-green-400' : 'bg-gray-500'
              }`}
            />
            {status?.market_open ? 'Market Open' : 'Market Closed'}
          </span>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard
          title="Portfolio Value"
          value={formatCurrency(metrics?.portfolio_value)}
          trend={metrics?.return_30d}
          trendLabel="30d return"
        />
        <StatusCard
          title="Buying Power"
          value={formatCurrency(metrics?.buying_power)}
        />
        <StatusCard
          title="30d Premium"
          value={formatCurrency(metrics?.total_premium_30d)}
          subtitle={`${metrics?.total_trades_30d || 0} trades`}
        />
        <StatusCard
          title="Win Rate"
          value={formatPercent(metrics?.win_rate)}
          subtitle={`Avg ${formatCurrency(metrics?.avg_premium)}`}
        />
      </div>

      {/* Active Positions */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Active Positions</h2>
          <span className="text-sm text-gray-400">
            {positions?.length || 0} position{positions?.length !== 1 ? 's' : ''}
          </span>
        </div>
        {positionsLoading ? (
          <LoadingSpinner />
        ) : positions && positions.length > 0 ? (
          <PositionsTable positions={positions} compact />
        ) : (
          <p className="text-gray-400 text-center py-8">No active positions</p>
        )}
      </div>

      {/* Recent Trades */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Recent Trades</h2>
          <a href="/trades" className="text-sm text-blue-400 hover:text-blue-300">
            View all →
          </a>
        </div>
        {tradesLoading ? (
          <LoadingSpinner />
        ) : trades && trades.length > 0 ? (
          <RecentTrades trades={trades} />
        ) : (
          <p className="text-gray-400 text-center py-8">No recent trades</p>
        )}
      </div>
    </div>
  )
}
