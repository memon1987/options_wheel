import { fmtCurrency, fmtDate, fmtNumber, fmtPercent, pnlColor } from '../../utils/format';

interface CycleRow {
  timestamp: string;
  symbol: string;
  put_date: string | null;
  put_strike: number | null;
  put_premium: number | null;
  assignment_date: string | null;
  call_date: string | null;
  call_strike: number | null;
  call_premium: number | null;
  capital_gain: number | null;
  total_premium: number | null;
  total_return: number | null;
  duration_days: number | null;
  shares: number | null;
}

interface Props {
  rows: CycleRow[];
}

export default function CycleTable({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Cycles</h3>
        <p className="text-sm text-gray-400 mt-2">No completed cycles for this symbol.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-700">
        <h3 className="text-base font-semibold text-white">Cycles</h3>
        <p className="text-xs text-gray-400 mt-1">
          Each row is one wheel: put sold → assigned → call sold → called away
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50">
            <tr>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Put Date</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Put Strike</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Put Prem</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Assigned</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Call Strike</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Call Prem</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Cap Gain</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Total</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Return</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Days</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const totalReturn =
                r.total_premium !== null &&
                r.put_strike !== null &&
                r.shares !== null &&
                r.put_strike * r.shares > 0
                  ? (r.total_premium + (r.capital_gain ?? 0)) / (r.put_strike * r.shares)
                  : r.total_return;
              return (
                <tr key={`${r.put_date}-${i}`} className="border-t border-gray-700/50">
                  <td className="px-3 py-2 text-sm text-gray-200">{fmtDate(r.put_date)}</td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {r.put_strike !== null ? `$${r.put_strike.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(r.put_premium)}
                  </td>
                  <td className="px-3 py-2 text-sm text-gray-200">
                    {fmtDate(r.assignment_date)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {r.call_strike !== null ? `$${r.call_strike.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(r.call_premium)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(r.capital_gain)}`}>
                    {fmtCurrency(r.capital_gain)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(r.total_premium)}`}>
                    {fmtCurrency(r.total_premium)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(totalReturn)}`}>
                    {fmtPercent(totalReturn, 2)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtNumber(r.duration_days)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
