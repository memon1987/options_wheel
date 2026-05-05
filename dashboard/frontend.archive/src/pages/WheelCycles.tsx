import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface WheelCycle {
  symbol?: string;
  capital_gain?: number;
  put_strike?: number;
  call_strike?: number;
  duration_days?: number;
  put_assignment_date?: string;
  call_assignment_date?: string;
  shares?: number;
  total_premium?: number;
  cycle_end?: string;
  date_et?: string;
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
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

export default function WheelCycles() {
  const { data: cycles, loading, error, refetch } = useApi<WheelCycle[]>(
    '/api/history/wheel-cycles',
    { refreshInterval: 120_000 },
  );

  const totalCapitalGain = cycles?.reduce((sum, c) => sum + (c.capital_gain ?? 0), 0) ?? 0;
  const totalPremium = cycles?.reduce((sum, c) => sum + (c.total_premium ?? 0), 0) ?? 0;
  const avgDuration = cycles && cycles.length > 0
    ? Math.round(cycles.reduce((sum, c) => sum + (c.duration_days ?? 0), 0) / cycles.length)
    : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Wheel Cycles</h1>
        <p className="text-sm text-gray-400 mt-1 sm:mt-0">
          Full cycle: sell put &rarr; assigned &rarr; sell call &rarr; called away
        </p>
      </div>

      {loading ? (
        <LoadingState message="Loading wheel cycles..." />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : !cycles || cycles.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No completed cycles yet</p>
          <p className="text-gray-500 mt-2">
            Completed wheel cycles will appear here when stock gets called away
          </p>
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="card">
              <p className="card-header">Total Cycles</p>
              <p className="card-value text-white">{cycles.length}</p>
            </div>
            <div className="card">
              <p className="card-header">Capital Gain/Loss</p>
              <p className={`card-value ${totalCapitalGain >= 0 ? 'profit' : 'loss'}`}>
                {formatCurrency(totalCapitalGain)}
              </p>
            </div>
            <div className="card">
              <p className="card-header">Premium Collected</p>
              <p className="card-value profit">{formatCurrency(totalPremium)}</p>
            </div>
            <div className="card">
              <p className="card-header">Avg Cycle Duration</p>
              <p className="card-value text-white">{avgDuration} days</p>
            </div>
          </div>

          {/* Cycles Table */}
          <div className="card overflow-hidden">
            <h2 className="text-lg font-semibold text-white mb-4">Cycle Details</h2>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-700">
                  <tr>
                    <th className="table-cell table-header">Symbol</th>
                    <th className="table-cell table-header">Put Assigned</th>
                    <th className="table-cell table-header text-right">Put Strike</th>
                    <th className="table-cell table-header">Call Assigned</th>
                    <th className="table-cell table-header text-right">Call Strike</th>
                    <th className="table-cell table-header text-right">Capital Gain</th>
                    <th className="table-cell table-header text-right">Duration</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {cycles.map((cycle, i) => {
                    const gain = cycle.capital_gain ?? 0;
                    return (
                      <tr key={i} className="hover:bg-gray-700/50">
                        <td className="table-cell font-medium text-white">{cycle.symbol ?? '-'}</td>
                        <td className="table-cell text-gray-300">
                          {formatDate(cycle.put_assignment_date)}
                        </td>
                        <td className="table-cell text-right text-gray-300">
                          {formatCurrency(cycle.put_strike)}
                        </td>
                        <td className="table-cell text-gray-300">
                          {formatDate(cycle.call_assignment_date)}
                        </td>
                        <td className="table-cell text-right text-gray-300">
                          {formatCurrency(cycle.call_strike)}
                        </td>
                        <td className={`table-cell text-right ${gain >= 0 ? 'profit' : 'loss'}`}>
                          {formatCurrency(gain)}
                        </td>
                        <td className="table-cell text-right text-gray-300">
                          {cycle.duration_days ?? '-'}d
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
