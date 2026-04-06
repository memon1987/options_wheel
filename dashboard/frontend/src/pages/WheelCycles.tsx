import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface WheelCycle {
  symbol?: string;
  total_premium?: number;
  cycle_end?: string;
  date_et?: string;
  [key: string]: unknown;
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

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Wheel Cycles</h1>
        <p className="text-sm text-gray-400 mt-1 sm:mt-0">
          Full cycle: sell put -&gt; assigned -&gt; sell call -&gt; called away
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
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="card">
              <p className="card-header">Total Cycles</p>
              <p className="card-value text-white">{cycles.length}</p>
            </div>
            <div className="card">
              <p className="card-header">Total Premium</p>
              <p className="card-value profit">
                {formatCurrency(cycles.reduce((sum, c) => sum + (c.total_premium ?? 0), 0))}
              </p>
            </div>
            <div className="card">
              <p className="card-header">Avg Premium / Cycle</p>
              <p className="card-value text-white">
                {formatCurrency(
                  cycles.reduce((sum, c) => sum + (c.total_premium ?? 0), 0) / cycles.length,
                )}
              </p>
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
                    <th className="table-cell table-header text-right">Total Premium</th>
                    <th className="table-cell table-header">Cycle End</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {cycles.map((cycle, i) => (
                    <tr key={i} className="hover:bg-gray-700/50">
                      <td className="table-cell font-medium text-white">{cycle.symbol ?? '-'}</td>
                      <td className="table-cell text-right profit">
                        {formatCurrency(cycle.total_premium)}
                      </td>
                      <td className="table-cell text-gray-300">
                        {formatDate(cycle.cycle_end ?? cycle.date_et)}
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
