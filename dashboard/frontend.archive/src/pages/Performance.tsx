import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface MetricsSummary {
  total_trades?: number;
  total_premium?: number;
  total_errors?: number;
  avg_premium?: number;
  [key: string]: unknown;
}

interface Trade {
  timestamp_et?: string;
  date_et?: string;
  premium?: number;
  strategy?: string;
}

function formatCurrency(value: number | undefined | null): string {
  if (value === undefined || value === null) return '$0.00';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Group trades by YYYY-MM and sum premium */
function premiumByMonth(trades: Trade[]): Array<{ month: string; premium: number; count: number }> {
  const map = new Map<string, { premium: number; count: number }>();

  for (const t of trades) {
    const dateStr = t.timestamp_et ?? t.date_et;
    if (!dateStr) continue;
    const month = dateStr.slice(0, 7); // "YYYY-MM"
    const entry = map.get(month) ?? { premium: 0, count: 0 };
    entry.premium += t.premium ?? 0;
    entry.count += 1;
    map.set(month, entry);
  }

  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, data]) => ({ month, ...data }));
}

export default function Performance() {
  const { data: metrics, loading: metricsLoading, error: metricsError, refetch: refetchMetrics } =
    useApi<MetricsSummary>('/api/metrics/summary', { refreshInterval: 60_000 });

  const { data: trades, loading: tradesLoading, error: tradesError, refetch: refetchTrades } =
    useApi<Trade[]>('/api/history/trades?days=365');

  const monthlyData = trades ? premiumByMonth(trades) : [];
  const loading = metricsLoading || tradesLoading;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Performance</h1>

      {/* Metrics Summary */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
          Summary Metrics
        </h2>
        {metricsLoading ? (
          <LoadingState message="Loading metrics..." />
        ) : metricsError ? (
          <ErrorState message={metricsError} onRetry={refetchMetrics} />
        ) : metrics ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="card">
              <p className="card-header">Total Trades</p>
              <p className="card-value text-white">{metrics.total_trades ?? 0}</p>
            </div>
            <div className="card">
              <p className="card-header">Total Premium</p>
              <p className="card-value profit">{formatCurrency(metrics.total_premium)}</p>
            </div>
            <div className="card">
              <p className="card-header">Avg Premium</p>
              <p className="card-value text-white">{formatCurrency(metrics.avg_premium)}</p>
            </div>
            <div className="card">
              <p className="card-header">Errors</p>
              <p className="card-value text-white">{metrics.total_errors ?? 0}</p>
            </div>
          </div>
        ) : (
          <p className="text-gray-400">No metrics available</p>
        )}
      </section>

      {/* Premium by Month */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
          Premium by Month
        </h2>
        {loading ? (
          <LoadingState message="Loading monthly data..." />
        ) : tradesError ? (
          <ErrorState message={tradesError} onRetry={refetchTrades} />
        ) : monthlyData.length > 0 ? (
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-700">
                  <tr>
                    <th className="table-cell table-header">Month</th>
                    <th className="table-cell table-header text-right">Premium</th>
                    <th className="table-cell table-header text-right">Trades</th>
                    <th className="table-cell table-header text-right">Avg / Trade</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {monthlyData.map((row) => (
                    <tr key={row.month} className="hover:bg-gray-700/50">
                      <td className="table-cell font-medium text-white">{row.month}</td>
                      <td className="table-cell text-right profit">{formatCurrency(row.premium)}</td>
                      <td className="table-cell text-right text-gray-300">{row.count}</td>
                      <td className="table-cell text-right text-gray-300">
                        {row.count > 0 ? formatCurrency(row.premium / row.count) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="card text-center py-8">
            <p className="text-gray-400">No trade data available for monthly breakdown</p>
          </div>
        )}
      </section>
    </div>
  );
}
