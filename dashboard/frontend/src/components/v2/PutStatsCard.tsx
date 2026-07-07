import type { PutStats } from '../../types/v2';
import { fmtCurrency, fmtPercent, pnlColor } from '../../utils/format';

interface Props {
  data: PutStats | null;
}

// FC-031: unassigned-put trade stats, kept SEPARATE from cycle stats.
// The win rate here is mechanically high by strike selection (selling
// 10–20Δ puts wins ~80–90% of contracts) — it is a diagnostic, not a
// success KPI. The calibration stat is assignment rate among puts HELD TO
// EXPIRY only: early closes never faced the expiry lottery.
export default function PutStatsCard({ data }: Props) {
  if (!data || data.closed_count === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Put Trades (no assignment)</h3>
        <p className="text-sm text-gray-400 mt-2">No closed put trades yet.</p>
      </div>
    );
  }

  const heldToExpiry = data.assignment_count + data.expiration_count;
  const [dLo, dHi] = data.put_delta_band;
  const rate = data.assignment_rate_held_to_expiry;
  const outsideBand = rate !== null && (rate < dLo || rate > dHi);

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">Put Trades</h3>
        <span className="text-xs text-gray-500">
          {data.closed_count} closed without assignment · {data.assignment_count} assigned
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-3">
        <div title="Closed unassigned puts with realized P&L > 0. Mechanically high for low-delta short puts (≈ 1 − |delta| per contract) — a diagnostic, not a success KPI. Cycle win rate is the decision-grade number.">
          <div className="text-xs uppercase tracking-wide text-gray-400">Win rate (diagnostic)</div>
          <div className="text-base font-semibold mt-0.5 text-white">
            {data.win_rate !== null ? fmtPercent(data.win_rate, 0) : '—'}
          </div>
        </div>
        <div title="Net realized P&L across closed unassigned puts.">
          <div className="text-xs uppercase tracking-wide text-gray-400">Net P&L</div>
          <div className={`text-base font-semibold mt-0.5 ${pnlColor(data.net_pnl)}`}>
            {fmtCurrency(data.net_pnl)}
          </div>
        </div>
        <div title="Share of puts bought back before expiry (profit-taking bands). These never faced the expiry lottery, so they are excluded from the calibration stat.">
          <div className="text-xs uppercase tracking-wide text-gray-400">Closed early</div>
          <div className="text-base font-semibold mt-0.5 text-white">
            {data.pct_closed_early !== null ? fmtPercent(data.pct_closed_early, 0) : '—'}
          </div>
        </div>
        <div title={`Assignments / (assignments + expirations) — held-to-expiry only (${data.assignment_count}/${heldToExpiry}). Delta approximates P(ITM at expiry), so this is the honest calibration against the ${fmtPercent(dLo, 0)}–${fmtPercent(dHi, 0)} put delta band.`}>
          <div className="text-xs uppercase tracking-wide text-gray-400">Assign rate (held to expiry)</div>
          <div className={`text-base font-semibold mt-0.5 ${outsideBand ? 'text-yellow-300' : 'text-white'}`}>
            {rate !== null ? fmtPercent(rate, 0) : '—'}
            <span className="text-xs text-gray-500 font-normal"> vs Δ {fmtPercent(dLo, 0)}–{fmtPercent(dHi, 0)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
