import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface Trade {
  timestamp_et?: string;
  date_et?: string;
  symbol?: string;
  underlying?: string;
  event_type?: string;
  strategy?: string;
  premium?: number;
  contracts?: number;
  strike_price?: number;
  dte?: number;
  collateral_required?: number;
  limit_price?: number;
  order_id?: string;
}

function formatCurrency(value: number | undefined | null): string {
  if (value === undefined || value === null) return '-';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value);
}

function formatDate(dateStr: string | undefined | null): string {
  if (!dateStr) return '-';
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
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

export default function Trades() {
  const [days, setDays] = useState(30);

  const { data: trades, loading, error, refetch } = useApi<Trade[]>(
    `/api/history/trades?days=${days}`,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Trade History</h1>
        <div className="flex items-center gap-3 mt-2 sm:mt-0">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-gray-700 text-white rounded-lg px-4 py-2 border border-gray-600 text-sm"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </div>

      {loading ? (
        <LoadingState message="Loading trades..." />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : !trades || trades.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No trades found</p>
          <p className="text-gray-500 mt-2">
            Trades will appear here after the bot executes orders
          </p>
        </div>
      ) : (
        <>
          <div className="card">
            <p className="text-sm text-gray-400">
              Showing <span className="text-white font-medium">{trades.length}</span> trades
              from the last <span className="text-white font-medium">{days}</span> days
            </p>
          </div>

          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-700">
                  <tr>
                    <th className="table-cell table-header">Date (ET)</th>
                    <th className="table-cell table-header">Symbol</th>
                    <th className="table-cell table-header">Event</th>
                    <th className="table-cell table-header">Strategy</th>
                    <th className="table-cell table-header text-right">Premium</th>
                    <th className="table-cell table-header text-right">Contracts</th>
                    <th className="table-cell table-header text-right">Strike</th>
                    <th className="table-cell table-header text-right">DTE</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {trades.map((trade, i) => (
                    <tr key={i} className="hover:bg-gray-700/50">
                      <td className="table-cell text-gray-300 whitespace-nowrap">
                        {formatDate(trade.timestamp_et ?? trade.date_et)}
                      </td>
                      <td className="table-cell font-medium text-white">
                        {trade.underlying ?? trade.symbol ?? '-'}
                      </td>
                      <td className="table-cell text-gray-300">{trade.event_type ?? '-'}</td>
                      <td className="table-cell">
                        {trade.strategy ? (
                          <span className="px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded text-xs">
                            {trade.strategy}
                          </span>
                        ) : (
                          <span className="text-gray-500">-</span>
                        )}
                      </td>
                      <td className="table-cell text-right profit">
                        {formatCurrency(trade.premium)}
                      </td>
                      <td className="table-cell text-right text-gray-300">
                        {trade.contracts ?? '-'}
                      </td>
                      <td className="table-cell text-right text-gray-300">
                        {trade.strike_price ? `$${trade.strike_price.toFixed(2)}` : '-'}
                      </td>
                      <td className="table-cell text-right text-gray-300">
                        {trade.dte ?? '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
