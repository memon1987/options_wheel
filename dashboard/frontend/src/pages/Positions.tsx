import { usePositions, useAccount } from '../hooks/useApi'
import PositionsTable from '../components/PositionsTable'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Positions() {
  const { data: positions, loading: positionsLoading, error: positionsError, refetch } = usePositions()
  const { data: account } = useAccount()

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

      {/* Stock Positions */}
      {stockPositions.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold text-white mb-4">Stock Positions</h2>
          <PositionsTable positions={stockPositions} />
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
