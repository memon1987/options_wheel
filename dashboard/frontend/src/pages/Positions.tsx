import { usePositions, useAccount, useStockSnapshots } from '../hooks/useApi'
import PositionsTable from '../components/PositionsTable'
import StockPositionCard from '../components/StockPositionCard'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Positions() {
  const { data: positions, loading: positionsLoading, error: positionsError, refetch } = usePositions()
  const { data: account } = useAccount()
  const { data: stockSnapshots } = useStockSnapshots(30)

  if (positionsLoading) {
    return <LoadingSpinner />
  }

  if (positionsError) {
    return <ErrorMessage message={positionsError} />
  }

  const optionPositions = positions?.filter(p => p.asset_class === 'us_option') || []
  const stockPositions = positions?.filter(p => p.asset_class === 'us_equity') || []

  const totalUnrealizedPL = positions?.reduce(
    (sum, p) => sum + parseFloat(p.unrealized_pl || '0'),
    0
  ) || 0

  const formatCurrency = (value: number | string) => {
    const num = typeof value === 'string' ? parseFloat(value) : value
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
    }).format(num)
  }

  // Get the most recent snapshot for each symbol and historical data for sparklines
  const getStockSnapshotData = (symbol: string) => {
    if (!stockSnapshots) return null
    const symbolSnapshots = stockSnapshots
      .filter(s => s.symbol === symbol)
      .sort((a, b) => new Date(a.date_et).getTime() - new Date(b.date_et).getTime())

    if (symbolSnapshots.length === 0) return null

    const latest = symbolSnapshots[symbolSnapshots.length - 1]
    return {
      ...latest,
      historicalData: symbolSnapshots.map(s => ({
        date: s.date_et,
        unrealized_pl: s.unrealized_pl
      }))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Positions</h1>
        <button
          onClick={refetch}
          className="btn-primary mt-2 sm:mt-0"
        >
          Refresh
        </button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card">
          <p className="card-header">Option Positions</p>
          <p className="card-value text-white">{optionPositions.length}</p>
        </div>
        <div className="card">
          <p className="card-header">Stock Positions</p>
          <p className="card-value text-white">{stockPositions.length}</p>
        </div>
        <div className="card">
          <p className="card-header">Unrealized P&L</p>
          <p className={`card-value ${totalUnrealizedPL >= 0 ? 'profit' : 'loss'}`}>
            {formatCurrency(totalUnrealizedPL)}
          </p>
        </div>
        <div className="card">
          <p className="card-header">Buying Power</p>
          <p className="card-value text-white">
            {formatCurrency(account?.buying_power || '0')}
          </p>
        </div>
      </div>

      {/* Option Positions */}
      {optionPositions.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold text-white mb-4">Option Positions</h2>
          <PositionsTable positions={optionPositions} />
        </div>
      )}

      {/* Stock Positions - Table View */}
      {stockPositions.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold text-white mb-4">Stock Positions</h2>
          <PositionsTable positions={stockPositions} />
        </div>
      )}

      {/* Stock Position P&L with Sparklines */}
      {stockSnapshots && stockSnapshots.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-4">Stock Position P&L History</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {/* Get unique symbols from snapshots */}
            {Array.from(new Set(stockSnapshots.map(s => s.symbol))).map(symbol => {
              const data = getStockSnapshotData(symbol)
              if (!data) return null
              return (
                <StockPositionCard
                  key={symbol}
                  symbol={symbol}
                  shares={data.shares}
                  costBasis={data.cost_basis}
                  currentPrice={data.current_price}
                  unrealizedPL={data.unrealized_pl}
                  unrealizedPLPct={data.unrealized_pl_pct}
                  daysHeld={data.days_held}
                  historicalData={data.historicalData}
                />
              )
            })}
          </div>
        </div>
      )}

      {/* Empty State */}
      {positions?.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No active positions</p>
          <p className="text-gray-500 mt-2">
            Positions will appear here when the bot opens new trades
          </p>
        </div>
      )}
    </div>
  )
}
