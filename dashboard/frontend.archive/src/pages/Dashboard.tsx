import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface AccountData {
  portfolio_value?: string | number;
  cash?: string | number;
  buying_power?: string | number;
  equity?: string | number;
}

interface StatusData {
  status?: string;
  last_run?: string;
  last_scan?: string;
  positions?: number;
  pnl?: number;
  errors?: number;
}

interface Trade {
  timestamp_et?: string;
  date_et?: string;
  symbol?: string;
  underlying?: string;
  event_type?: string;
  strategy?: string;
  premium?: number;
  contracts?: number;
}

interface Position {
  symbol: string;
}

function formatCurrency(value: string | number | undefined | null): string {
  if (value === undefined || value === null) return '$0.00';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '$0.00';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num);
}

function formatTime(dateStr: string | undefined | null): string {
  if (!dateStr) return 'N/A';
  try {
    return new Date(dateStr).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return dateStr;
  }
}

export default function Dashboard() {
  const { data: account, loading: accountLoading, error: accountError, refetch: refetchAccount } =
    useApi<AccountData>('/api/live/account', { refreshInterval: 30_000 });

  const { data: status, loading: statusLoading, error: statusError, refetch: refetchStatus } =
    useApi<StatusData>('/api/live/status', { refreshInterval: 15_000 });

  const { data: trades, loading: tradesLoading, error: tradesError, refetch: refetchTrades } =
    useApi<Trade[]>('/api/history/trades', { refreshInterval: 60_000 });

  const { data: positions, loading: positionsLoading } =
    useApi<Position[]>('/api/live/positions', { refreshInterval: 30_000 });

  const recentTrades = trades?.slice(0, 10) ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Dashboard</h1>

      {/* Account Summary */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">Account Summary</h2>
        {accountLoading ? (
          <LoadingState message="Loading account..." />
        ) : accountError ? (
          <ErrorState message={accountError} onRetry={refetchAccount} />
        ) : account ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="card">
              <p className="card-header">Portfolio Value</p>
              <p className="card-value text-white">{formatCurrency(account.portfolio_value)}</p>
            </div>
            <div className="card">
              <p className="card-header">Cash</p>
              <p className="card-value text-white">{formatCurrency(account.cash)}</p>
            </div>
            <div className="card">
              <p className="card-header">Buying Power</p>
              <p className="card-value text-white">{formatCurrency(account.buying_power)}</p>
            </div>
            <div className="card">
              <p className="card-header">Equity</p>
              <p className="card-value text-white">{formatCurrency(account.equity)}</p>
            </div>
          </div>
        ) : (
          <p className="text-gray-400">No account data available</p>
        )}
      </section>

      {/* Status */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">Strategy Status</h2>
        {statusLoading ? (
          <LoadingState message="Loading status..." />
        ) : statusError ? (
          <ErrorState message={statusError} onRetry={refetchStatus} />
        ) : status ? (
          <div className="card">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <div>
                <p className="text-sm text-gray-400">Status</p>
                <p className="text-white font-medium">{status.status ?? 'Unknown'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Last Run</p>
                <p className="text-white">{formatTime(status.last_run)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Last Scan</p>
                <p className="text-white">{formatTime(status.last_scan)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-400">Positions</p>
                <p className="text-white font-medium">
                  {positionsLoading ? '...' : (positions?.length ?? status.positions ?? 0)}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-gray-400">No status data available</p>
        )}
      </section>

      {/* Recent Trades */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">Recent Trades</h2>
        {tradesLoading ? (
          <LoadingState message="Loading trades..." />
        ) : tradesError ? (
          <ErrorState message={tradesError} onRetry={refetchTrades} />
        ) : recentTrades.length > 0 ? (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-700">
                  <tr>
                    <th className="table-cell table-header">Date</th>
                    <th className="table-cell table-header">Symbol</th>
                    <th className="table-cell table-header">Event</th>
                    <th className="table-cell table-header">Strategy</th>
                    <th className="table-cell table-header text-right">Premium</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {recentTrades.map((trade, i) => (
                    <tr key={i} className="hover:bg-gray-700/50">
                      <td className="table-cell text-gray-300">
                        {formatTime(trade.timestamp_et ?? trade.date_et)}
                      </td>
                      <td className="table-cell font-medium text-white">
                        {trade.underlying ?? trade.symbol ?? '-'}
                      </td>
                      <td className="table-cell text-gray-300">{trade.event_type ?? '-'}</td>
                      <td className="table-cell text-gray-300">{trade.strategy ?? '-'}</td>
                      <td className="table-cell text-right profit">
                        {trade.premium ? formatCurrency(trade.premium) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="card text-center py-8">
            <p className="text-gray-400">No recent trades</p>
          </div>
        )}
      </section>
    </div>
  );
}
