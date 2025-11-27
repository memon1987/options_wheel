import { useFetch } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

interface WheelCycle {
  underlying: string
  start_date: string
  current_stage: 'put' | 'assignment' | 'call'
  total_premium: number
  trades_count: number
  current_position: string | null
  days_in_cycle: number
}

export default function WheelCycles() {
  const { data: cycles, loading, error } = useFetch<WheelCycle[]>('/history/wheel-cycles')

  if (loading) {
    return <LoadingSpinner />
  }

  if (error) {
    return <ErrorMessage message={error} />
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
      year: 'numeric',
    })
  }

  const getStageColor = (stage: string) => {
    switch (stage) {
      case 'put':
        return 'bg-purple-900 text-purple-300 border-purple-500'
      case 'assignment':
        return 'bg-yellow-900 text-yellow-300 border-yellow-500'
      case 'call':
        return 'bg-blue-900 text-blue-300 border-blue-500'
      default:
        return 'bg-gray-700 text-gray-300 border-gray-500'
    }
  }

  const getStageLabel = (stage: string) => {
    switch (stage) {
      case 'put':
        return 'Selling Puts'
      case 'assignment':
        return 'Assigned (Hold Stock)'
      case 'call':
        return 'Selling Calls'
      default:
        return stage
    }
  }

  const activeCycles = cycles?.filter((c) => c.current_position !== null) || []
  const completedCycles = cycles?.filter((c) => c.current_position === null) || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Wheel Cycles</h1>
        <p className="text-sm text-gray-400 mt-1 sm:mt-0">
          Track your wheel strategy progress by underlying
        </p>
      </div>

      {/* Active Cycles */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-4">Active Cycles</h2>
        {activeCycles.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {activeCycles.map((cycle) => (
              <div
                key={cycle.underlying}
                className={`card border-l-4 ${getStageColor(cycle.current_stage)}`}
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-xl font-bold text-white">{cycle.underlying}</h3>
                  <span
                    className={`px-2 py-1 rounded text-xs font-medium ${getStageColor(
                      cycle.current_stage
                    )}`}
                  >
                    {getStageLabel(cycle.current_stage)}
                  </span>
                </div>

                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Started</span>
                    <span className="text-white">{formatDate(cycle.start_date)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Days in Cycle</span>
                    <span className="text-white">{cycle.days_in_cycle}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Total Premium</span>
                    <span className="profit">{formatCurrency(cycle.total_premium)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Trades</span>
                    <span className="text-white">{cycle.trades_count}</span>
                  </div>
                </div>

                {cycle.current_position && (
                  <div className="mt-3 pt-3 border-t border-gray-700">
                    <p className="text-xs text-gray-400">Current Position</p>
                    <p className="text-sm text-white font-mono">{cycle.current_position}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="card text-center py-8">
            <p className="text-gray-400">No active wheel cycles</p>
          </div>
        )}
      </div>

      {/* Completed Cycles */}
      {completedCycles.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-4">Completed Cycles</h2>
          <div className="card overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-700">
                <tr>
                  <th className="table-cell table-header">Symbol</th>
                  <th className="table-cell table-header">Started</th>
                  <th className="table-cell table-header text-right">Days</th>
                  <th className="table-cell table-header text-right">Trades</th>
                  <th className="table-cell table-header text-right">Premium</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {completedCycles.map((cycle, index) => (
                  <tr key={index} className="hover:bg-gray-750">
                    <td className="table-cell font-medium text-white">{cycle.underlying}</td>
                    <td className="table-cell text-gray-300">{formatDate(cycle.start_date)}</td>
                    <td className="table-cell text-right text-gray-300">{cycle.days_in_cycle}</td>
                    <td className="table-cell text-right text-gray-300">{cycle.trades_count}</td>
                    <td className="table-cell text-right profit">
                      {formatCurrency(cycle.total_premium)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!cycles || cycles.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No wheel cycles found</p>
          <p className="text-gray-500 mt-2">
            Cycles will appear here as the bot executes the wheel strategy
          </p>
        </div>
      ) : null}
    </div>
  )
}
