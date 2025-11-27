import { useState } from 'react'
import { useExpirations } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

interface ExpirationPosition {
  symbol: string
  strike: number
  option_type: string
  quantity: number
}

interface Expiration {
  expiration_date: string
  positions: ExpirationPosition[]
}

export default function Calendar() {
  const [daysAhead, setDaysAhead] = useState(30)
  const { data: expirations, loading, error } = useExpirations(daysAhead)

  if (loading) {
    return <LoadingSpinner />
  }

  if (error) {
    return <ErrorMessage message={error} />
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return {
      day: date.toLocaleDateString('en-US', { weekday: 'short' }),
      date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      full: date.toLocaleDateString('en-US', {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      }),
    }
  }

  const getDaysUntil = (dateStr: string) => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const expDate = new Date(dateStr)
    expDate.setHours(0, 0, 0, 0)
    const diffTime = expDate.getTime() - today.getTime()
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    return diffDays
  }

  const getUrgencyColor = (daysUntil: number) => {
    if (daysUntil <= 2) return 'border-red-500 bg-red-900/20'
    if (daysUntil <= 5) return 'border-yellow-500 bg-yellow-900/20'
    return 'border-gray-600 bg-gray-800'
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Expiration Calendar</h1>
        <select
          value={daysAhead}
          onChange={(e) => setDaysAhead(Number(e.target.value))}
          className="mt-2 sm:mt-0 bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600"
        >
          <option value={7}>Next 7 days</option>
          <option value={14}>Next 14 days</option>
          <option value={30}>Next 30 days</option>
          <option value={60}>Next 60 days</option>
        </select>
      </div>

      {/* Calendar View */}
      {expirations && expirations.length > 0 ? (
        <div className="space-y-4">
          {expirations.map((expiration) => {
            const dateInfo = formatDate(expiration.expiration_date)
            const daysUntil = getDaysUntil(expiration.expiration_date)

            return (
              <div
                key={expiration.expiration_date}
                className={`card border-l-4 ${getUrgencyColor(daysUntil)}`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <p className="text-lg font-semibold text-white">{dateInfo.date}</p>
                    <p className="text-sm text-gray-400">{dateInfo.day}</p>
                  </div>
                  <span
                    className={`px-3 py-1 rounded-full text-sm font-medium ${
                      daysUntil <= 2
                        ? 'bg-red-900 text-red-300'
                        : daysUntil <= 5
                        ? 'bg-yellow-900 text-yellow-300'
                        : 'bg-gray-700 text-gray-300'
                    }`}
                  >
                    {daysUntil === 0
                      ? 'Today'
                      : daysUntil === 1
                      ? 'Tomorrow'
                      : `${daysUntil} days`}
                  </span>
                </div>

                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {expiration.positions.map((pos, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between p-3 bg-gray-700 rounded-lg"
                    >
                      <div>
                        <p className="font-medium text-white">{pos.symbol}</p>
                        <p className="text-xs text-gray-400">
                          ${pos.strike} {pos.option_type}
                        </p>
                      </div>
                      <div className="text-right">
                        <span
                          className={`text-sm ${
                            pos.option_type === 'put' ? 'text-purple-400' : 'text-blue-400'
                          }`}
                        >
                          {pos.quantity}x
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No upcoming expirations</p>
          <p className="text-gray-500 mt-2">
            Positions with upcoming expirations will appear here
          </p>
        </div>
      )}

      {/* Legend */}
      <div className="card">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Urgency Legend</h3>
        <div className="flex flex-wrap gap-4">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded border-2 border-red-500 bg-red-900/20"></div>
            <span className="text-sm text-gray-300">Expiring in 0-2 days</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded border-2 border-yellow-500 bg-yellow-900/20"></div>
            <span className="text-sm text-gray-300">Expiring in 3-5 days</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded border-2 border-gray-600 bg-gray-800"></div>
            <span className="text-sm text-gray-300">Expiring in 6+ days</span>
          </div>
        </div>
      </div>
    </div>
  )
}
