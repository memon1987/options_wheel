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
  calls_in_cycle: number | null;
  cycle_call_gross_premium: number | null;
  cycle_call_net_realized: number | null;
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
          Each row = one wheel from put assignment to called-away. Total Premium rolls up every covered call sold during the cycle (includes rolls). Cycle P&amp;L = Total Premium + Cap Gain.
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
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Number of covered calls sold during this cycle (rolls inflate this — each early-closed-and-resold call counts separately)">Calls Rolled</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Realized capital gain on shares during the cycle window — actual cash in (called-away) minus actual cash out (assigned), per Alpaca activity history.">Cap Gain</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Net option premium kept across the cycle: put kept + sum of call realized P&L (after roll buybacks). Does NOT include share-side capital gain.">Total Premium</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="True cycle P&L = Total Premium + Cap Gain. Includes both option-side (premium kept after rolls) and share-side (called-away vs assigned strike) cash flow.">Cycle P&L</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Return on collateral: Cycle P&L / (put strike × shares). Simple period return — NOT annualized, and collateral is approximated as put-strike notional throughout the cycle.">RoC</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Cycle P&L per day per $1,000 of collateral — compares cycles of different lengths without annualizing. Valid per row only: never average this column (aggregate = Σ P&L / Σ collateral·days, shown on the Overview cycle stats).">$/day/$1k</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Days</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              // True cycle P&L = option-side net premium kept + share-side
              // capital gain. FC-027: previously displayed as a single
              // "Cycle P&L" column showing only total_premium, which masked
              // share-side losses (e.g., UNH cycle 1: $1,218 option vs −$532
              // true cycle outcome).
              const cyclePnl =
                r.total_premium === null && r.capital_gain === null
                  ? null
                  : (r.total_premium ?? 0) + (r.capital_gain ?? 0);
              // FC-031: ONE definition (the old column silently fell back to
              // a server total_return with different semantics). Collateral
              // approximated as put-strike notional; shares default 100.
              const collateral =
                r.put_strike !== null ? r.put_strike * (r.shares ?? 100) : null;
              const roc =
                cyclePnl !== null && collateral !== null && collateral > 0
                  ? cyclePnl / collateral
                  : null;
              // Hold-time normalizer. GREATEST(days, 1) guards same-day
              // assignment/called-away rows (review F11).
              const days = Math.max(r.duration_days ?? 1, 1);
              const perDayPer1k =
                cyclePnl !== null && collateral !== null && collateral > 0
                  ? (cyclePnl / days / collateral) * 1000
                  : null;
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
                    {fmtNumber(r.calls_in_cycle)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(r.capital_gain)}`}>
                    {fmtCurrency(r.capital_gain)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(r.total_premium)}`}>
                    {fmtCurrency(r.total_premium)}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right font-semibold ${pnlColor(cyclePnl)}`}>
                    {cyclePnl !== null ? fmtCurrency(cyclePnl) : '—'}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(roc)}`}>
                    {roc !== null ? fmtPercent(roc, 2) : '—'}
                  </td>
                  <td className={`px-3 py-2 text-sm text-right ${pnlColor(perDayPer1k)}`}>
                    {perDayPer1k !== null
                      ? <span>{`$${perDayPer1k.toFixed(2)}`}{(r.duration_days ?? 1) < 1 && <span className="text-xs text-yellow-500" title="Same-day cycle — rate uses a 1-day floor"> &lt;1d</span>}</span>
                      : '—'}
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
