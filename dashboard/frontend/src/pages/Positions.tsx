import { useApi } from '../hooks/useApi';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

interface Position {
  symbol: string;
  qty: string | number;
  side: string;
  market_value: string | number;
  unrealized_pl: string | number;
  cost_basis: string | number;
  asset_class: string;
  avg_entry_price?: string | number;
  current_price?: string | number;
}

function toNum(val: string | number | undefined | null): number {
  if (val === undefined || val === null) return 0;
  const n = typeof val === 'string' ? parseFloat(val) : val;
  return isNaN(n) ? 0 : n;
}

function formatCurrency(value: string | number | undefined | null): string {
  const num = toNum(value);
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num);
}

function PositionsTable({ positions, title }: { positions: Position[]; title: string }) {
  if (positions.length === 0) return null;

  return (
    <div className="card overflow-hidden">
      <h2 className="text-lg font-semibold text-white mb-4">{title}</h2>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-700">
            <tr>
              <th className="table-cell table-header">Symbol</th>
              <th className="table-cell table-header text-right">Qty</th>
              <th className="table-cell table-header">Side</th>
              <th className="table-cell table-header text-right">Market Value</th>
              <th className="table-cell table-header text-right">Unrealized P&L</th>
              <th className="table-cell table-header text-right">Cost Basis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {positions.map((pos, i) => {
              const pl = toNum(pos.unrealized_pl);
              return (
                <tr key={i} className="hover:bg-gray-700/50">
                  <td className="table-cell font-medium text-white">{pos.symbol}</td>
                  <td className="table-cell text-right text-gray-300">{pos.qty}</td>
                  <td className="table-cell text-gray-300">{pos.side}</td>
                  <td className="table-cell text-right text-gray-300">{formatCurrency(pos.market_value)}</td>
                  <td className={`table-cell text-right ${pl >= 0 ? 'profit' : 'loss'}`}>
                    {formatCurrency(pos.unrealized_pl)}
                  </td>
                  <td className="table-cell text-right text-gray-300">{formatCurrency(pos.cost_basis)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Positions() {
  const { data: positions, loading, error, refetch } =
    useApi<Position[]>('/api/live/positions', { refreshInterval: 30_000 });

  const stockPositions = positions?.filter((p) => p.asset_class === 'us_equity') ?? [];
  const optionPositions = positions?.filter((p) => p.asset_class === 'us_option') ?? [];
  const otherPositions = positions?.filter(
    (p) => p.asset_class !== 'us_equity' && p.asset_class !== 'us_option',
  ) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-white">Positions</h1>
        {!loading && (
          <button
            onClick={refetch}
            className="mt-2 sm:mt-0 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Refresh
          </button>
        )}
      </div>

      {loading ? (
        <LoadingState message="Loading positions..." />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : !positions || positions.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 text-lg">No active positions</p>
          <p className="text-gray-500 mt-2">Positions will appear here when the bot opens new trades</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="card">
              <p className="card-header">Total Positions</p>
              <p className="card-value text-white">{positions.length}</p>
            </div>
            <div className="card">
              <p className="card-header">Stock Positions</p>
              <p className="card-value text-white">{stockPositions.length}</p>
            </div>
            <div className="card">
              <p className="card-header">Option Positions</p>
              <p className="card-value text-white">{optionPositions.length}</p>
            </div>
          </div>

          <PositionsTable positions={stockPositions} title="Stock Positions" />
          <PositionsTable positions={optionPositions} title="Option Positions" />
          <PositionsTable positions={otherPositions} title="Other Positions" />
        </>
      )}
    </div>
  );
}
