import { useConfig, useBotStatus, useErrors } from '../hooks/useApi'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorMessage from '../components/ErrorMessage'

export default function Settings() {
  const { data: config, loading: configLoading, error: configError } = useConfig()
  const { data: status } = useBotStatus()
  const { data: errors } = useErrors(10)

  if (configLoading) {
    return <LoadingSpinner />
  }

  if (configError) {
    return <ErrorMessage message={configError} />
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getSeverityBadge = (severity: string) => {
    switch (severity?.toUpperCase()) {
      case 'ERROR':
        return 'bg-red-900 text-red-300'
      case 'WARNING':
        return 'bg-yellow-900 text-yellow-300'
      default:
        return 'bg-gray-700 text-gray-300'
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <h1 className="text-2xl font-bold text-white">Settings & Status</h1>

      {/* Bot Status */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Bot Status</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <p className="text-sm text-gray-400">Status</p>
            <p className="text-white font-medium">{status?.status || 'Unknown'}</p>
          </div>
          <div>
            <p className="text-sm text-gray-400">Market</p>
            <p className={status?.market_open ? 'text-green-400' : 'text-gray-400'}>
              {status?.market_open ? 'Open' : 'Closed'}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-400">Account Status</p>
            <p className="text-white">{status?.account_status || 'N/A'}</p>
          </div>
          <div>
            <p className="text-sm text-gray-400">Last Check</p>
            <p className="text-white">
              {status?.timestamp ? formatDate(status.timestamp) : 'N/A'}
            </p>
          </div>
        </div>
      </div>

      {/* Strategy Configuration */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Strategy Configuration</h2>
        {config?.strategy ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(config.strategy).map(([key, value]) => (
              <div key={key} className="bg-gray-700 rounded-lg p-3">
                <p className="text-xs text-gray-400 mb-1">
                  {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                </p>
                <p className="text-white font-mono text-sm">
                  {Array.isArray(value)
                    ? `[${value.join(', ')}]`
                    : typeof value === 'number'
                    ? value.toString()
                    : String(value)}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-400">Configuration not available</p>
        )}
      </div>

      {/* Risk Configuration */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Risk Settings</h2>
        {config?.risk ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(config.risk).map(([key, value]) => (
              <div key={key} className="bg-gray-700 rounded-lg p-3">
                <p className="text-xs text-gray-400 mb-1">
                  {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                </p>
                <p className="text-white font-mono text-sm">
                  {typeof value === 'object'
                    ? JSON.stringify(value, null, 2).slice(0, 50)
                    : String(value)}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-400">Risk settings not available</p>
        )}
      </div>

      {/* Watched Symbols */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Watched Symbols</h2>
        {config?.stocks?.symbols ? (
          <div className="flex flex-wrap gap-2">
            {config.stocks.symbols.map((symbol) => (
              <span
                key={symbol}
                className="px-3 py-1 bg-blue-900 text-blue-300 rounded-full text-sm font-medium"
              >
                {symbol}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-gray-400">No symbols configured</p>
        )}
      </div>

      {/* Recent Errors */}
      <div className="card">
        <h2 className="text-lg font-semibold text-white mb-4">Recent Errors</h2>
        {errors && errors.length > 0 ? (
          <div className="space-y-3">
            {errors.map((error, index) => (
              <div
                key={index}
                className="bg-gray-700 rounded-lg p-3 border-l-4 border-red-500"
              >
                <div className="flex items-center justify-between mb-2">
                  <span
                    className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${getSeverityBadge(
                      error.severity
                    )}`}
                  >
                    {error.severity}
                  </span>
                  <span className="text-xs text-gray-400">
                    {formatDate(error.timestamp)}
                  </span>
                </div>
                <p className="text-sm text-gray-300">{error.message}</p>
                {error.component && (
                  <p className="text-xs text-gray-500 mt-1">
                    Component: {error.component}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-400 text-center py-4">No recent errors</p>
        )}
      </div>
    </div>
  )
}
