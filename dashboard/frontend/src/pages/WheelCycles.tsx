import { useWheelCycles } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function WheelCycles() {
  const { data: cycles, loading, error } = useWheelCycles()

  if (loading) {
    return <LoadingSpinner />
  }

  if (error) {
    return <ErrorMessage message={error} />
  }

  const formatCurrency = (value: number | null) => {
    if (value === null || value === undefined) return '-'
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

  // Calculate summary stats
  const totalPutPremium = cycles?.reduce((sum, c) => sum + (c.put_premium_collected || 0), 0) || 0
  const totalCallPremium = cycles?.reduce((sum, c) => sum + (c.call_premium_collected || 0), 0) || 0
  const totalCapitalGain = cycles?.reduce((sum, c) => sum + (c.capital_gain || 0), 0) || 0
  const totalReturn = cycles?.reduce((sum, c) => sum + (c.total_return || 0), 0) || 0
  const avgDuration = cycles && cycles.length > 0
    ? Math.round(cycles.reduce((sum, c) => sum + (c.duration_days || 0), 0) / cycles.length)
    : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Completed Wheel Cycles</h1>
        <p className="text-sm text-gray-400 mt-1 sm:mt-0">
          Full cycle: sell put → assigned → sell call → called away
        </p>
      </div>

      {/* Summary Cards */}
      {cycles && cycles.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="card">
            <p className="card-header">Total Return</p>
            <p className={`card-value ${totalReturn >= 0 ? 'profit' : 'loss'}`}>
              {formatCurrency(totalReturn)}
            </p>
            <p className="text-xs text-gray-400 mt-1">{cycles.length} cycles</p>
          </div>
          <div className="card">
            <p className="card-header">Put Premium</p>
            <p className="card-value text-purple-400">
              {formatCurrency(totalPutPremium)}
            </p>
            <p className="text-xs text-gray-400 mt-1">from selling puts</p>
          </div>
          <div className="card">
            <p className="card-header">Call Premium</p>
            <p className="card-value text-blue-400">
              {formatCurrency(totalCallPremium)}
            </p>
            <p className="text-xs text-gray-400 mt-1">from selling calls</p>
          </div>
          <div className="card">
            <p className="card-header">Capital Gains</p>
            <p className={`card-value ${totalCapitalGain >= 0 ? 'profit' : 'loss'}`}>
              {formatCurrency(totalCapitalGain)}
            </p>
            <p className="text-xs text-gray-400 mt-1">stock appreciation</p>
          </div>
          <div className="card">
            <p className="card-header">Avg Duration</p>
            <p className="card-value text-white">
              {avgDuration} days
            </p>
            <p className="text-xs text-gray-400 mt-1">per cycle</p>
          </div>
        </div>
      )}

      {/* Completed Cycles Table */}
      {cycles && cycles.length > 0 ? (
        <div className="card overflow-hidden">
          <h2 className="text-lg font-semibold text-white mb-4">Cycle Details</h2>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-700">
                <tr>
                  <th className="table-cell table-header">Symbol</th>
                  <th className="table-cell table-header">Completed</th>
                  <th className="table-cell table-header text-right">Days</th>
                  <th className="table-cell table-header text-right">Put $</th>
                  <th className="table-cell table-header text-right">Call $</th>
                  <th className="table-cell table-header text-right">Capital Gain</th>
                  <th className="table-cell table-header text-right">Total Return</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {cycles.map((cycle, index) => (
                  <tr key={index} className="hover:bg-gray-750">
                    <td className="table-cell font-medium text-white">{cycle.symbol}</td>
                    <td className="table-cell text-gray-300">
                      {cycle.cycle_end ? formatDate(cycle.cycle_end) : '-'}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {cycle.duration_days || '-'}
                    </td>
                    <td className="table-cell text-right text-purple-400">
                      {formatCurrency(cycle.put_premium_collected)}
                    </td>
                    <td className="table-cell text-right text-blue-400">
                      {formatCurrency(cycle.call_premium_collected)}
                    </td>
                    <td className={`table-cell text-right ${(cycle.capital_gain || 0) >= 0 ? 'profit' : 'loss'}`}>
                      {formatCurrency(cycle.capital_gain)}
                    </td>
                    <td className={`table-cell text-right font-medium ${(cycle.total_return || 0) >= 0 ? 'profit' : 'loss'}`}>
                      {formatCurrency(cycle.total_return)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No completed wheel cycles found</p>
          <p className="text-gray-500 mt-2">
            Completed cycles will appear here when stock gets called away
          </p>
          <p className="text-gray-500 mt-1 text-sm">
            Cycle completes: sell put → assigned → sell call → called away
          </p>
        </div>
      )}
    </div>
  )
}
