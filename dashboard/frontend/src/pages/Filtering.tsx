import { useState } from 'react'
import { useFilteringStats } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Filtering() {
  const [limit, setLimit] = useState(100)
  const { data: stats, loading, error } = useFilteringStats(limit)

  if (loading) {
    return <LoadingSpinner />
  }

  if (error) {
    return <ErrorMessage message={error} />
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // Group stats by stage
  const stageStats =
    stats?.reduce((acc, stat) => {
      if (!acc[stat.stage]) {
        acc[stat.stage] = { passed: 0, failed: 0 }
      }
      if (stat.passed) {
        acc[stat.stage].passed++
      } else {
        acc[stat.stage].failed++
      }
      return acc
    }, {} as Record<string, { passed: number; failed: number }>) || {}

  // Group by symbol
  const symbolStats =
    stats?.reduce((acc, stat) => {
      if (!acc[stat.symbol]) {
        acc[stat.symbol] = { passed: 0, failed: 0 }
      }
      if (stat.passed) {
        acc[stat.symbol].passed++
      } else {
        acc[stat.symbol].failed++
      }
      return acc
    }, {} as Record<string, { passed: number; failed: number }>) || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Filtering Pipeline</h1>
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="mt-2 sm:mt-0 bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600"
        >
          <option value={50}>Last 50 checks</option>
          <option value={100}>Last 100 checks</option>
          <option value={200}>Last 200 checks</option>
        </select>
      </div>

      {/* Stage Summary */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Pass Rate by Stage</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Object.entries(stageStats).map(([stage, { passed, failed }]) => {
            const total = passed + failed
            const passRate = total > 0 ? (passed / total) * 100 : 0
            return (
              <div key={stage} className="bg-gray-700 rounded-lg p-4">
                <p className="text-sm text-gray-400 mb-1">{stage}</p>
                <p className="text-2xl font-bold text-white">{passRate.toFixed(0)}%</p>
                <p className="text-xs text-gray-500 mt-1">
                  {passed} passed / {failed} failed
                </p>
                <div className="mt-2 h-2 bg-gray-600 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 rounded-full"
                    style={{ width: `${passRate}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Symbol Summary */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">By Symbol</h2>
        <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
          {Object.entries(symbolStats)
            .sort((a, b) => b[1].passed + b[1].failed - (a[1].passed + a[1].failed))
            .slice(0, 12)
            .map(([symbol, { passed, failed }]) => {
              const total = passed + failed
              const passRate = total > 0 ? (passed / total) * 100 : 0
              return (
                <div key={symbol} className="flex items-center justify-between p-3 bg-gray-700 rounded-lg">
                  <span className="font-medium text-white">{symbol}</span>
                  <div className="text-right">
                    <span
                      className={`text-sm ${
                        passRate >= 50 ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {passRate.toFixed(0)}%
                    </span>
                    <p className="text-xs text-gray-500">{total} checks</p>
                  </div>
                </div>
              )
            })}
        </div>
      </div>

      {/* Recent Failures */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Recent Filter Failures</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-700">
              <tr>
                <th className="table-cell table-header">Time</th>
                <th className="table-cell table-header">Symbol</th>
                <th className="table-cell table-header">Stage</th>
                <th className="table-cell table-header">Reason</th>
                <th className="table-cell table-header text-right">Value</th>
                <th className="table-cell table-header text-right">Threshold</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {stats
                ?.filter((s) => !s.passed)
                .slice(0, 20)
                .map((stat, index) => (
                  <tr key={index} className="hover:bg-gray-750">
                    <td className="table-cell text-gray-300 whitespace-nowrap">
                      {formatDate(stat.timestamp)}
                    </td>
                    <td className="table-cell font-medium text-white">{stat.symbol}</td>
                    <td className="table-cell text-gray-300">{stat.stage}</td>
                    <td className="table-cell text-red-400 max-w-xs truncate">
                      {stat.reason}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {stat.value?.toFixed(2)}
                    </td>
                    <td className="table-cell text-right text-gray-300">
                      {stat.threshold?.toFixed(2)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        {stats?.filter((s) => !s.passed).length === 0 && (
          <p className="text-gray-400 text-center py-8">No recent filter failures</p>
        )}
      </div>
    </div>
  )
}
