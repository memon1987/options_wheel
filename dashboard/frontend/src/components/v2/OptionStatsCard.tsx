import type { OptionTradeStats } from '../../types/v2';
import { fmtCurrency, fmtPercent } from '../../utils/format';
import Stat from './Stat';

interface Props {
  data: OptionTradeStats | null;
  optionType: 'put' | 'call';
}

// FC-031: per-leg trade stats, one component for BOTH legs (Wheel Strategy
// Symmetry Principle — the put and call phases get equal observability).
// The per-contract win rate is mechanically high by strike selection
// (≈ 1 − |delta|) — a diagnostic, never a success KPI. The calibration stat
// is the held-to-expiry exercise rate: assignment rate for puts, called-away
// rate for calls (the FC-029 re-tuned side), vs the leg's live delta band.
export default function OptionStatsCard({ data, optionType }: Props) {
  const isPut = optionType === 'put';
  const title = isPut ? 'Put Trades' : 'Call Trades';
  const exercisedLabel = isPut ? 'assigned' : 'called away';
  const rateLabel = isPut ? 'Assign rate (held to expiry)' : 'Called-away rate (held to expiry)';

  if (!data || (data.closed_count === 0 && data.exercised_count === 0)) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">{title}</h3>
        <p className="text-sm text-gray-400 mt-2">No closed {optionType} trades yet.</p>
      </div>
    );
  }

  const heldToExpiry = data.exercised_count + data.expiration_count;
  const [dLo, dHi] = data.delta_band;
  const rate = data.exercise_rate_held_to_expiry;
  const outsideBand = rate !== null && (rate < dLo || rate > dHi);

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">{title}</h3>
        <span className="text-xs text-gray-500">
          {data.closed_count} closed without exercise · {data.exercised_count} {exercisedLabel}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-3">
        <Stat
          label="Win rate (diagnostic)"
          value={data.win_rate !== null ? fmtPercent(data.win_rate, 0) : '—'}
          hint={`Closed unexercised ${optionType}s with realized P&L > 0. Mechanically high for low-delta short options (≈ 1 − |delta| per contract) — a diagnostic, not a success KPI. Cycle win rate is the decision-grade number.`}
        />
        <Stat
          label="Net P&L"
          value={fmtCurrency(data.net_pnl)}
          tone={data.net_pnl}
          hint={`Net realized P&L across closed unexercised ${optionType} trades.`}
        />
        <Stat
          label="Closed early"
          value={data.pct_closed_early !== null ? fmtPercent(data.pct_closed_early, 0) : '—'}
          hint="Share of trades bought back before expiry (profit-taking bands). These never faced the expiry lottery, so they are excluded from the calibration stat."
        />
        <Stat
          label={rateLabel}
          warn={outsideBand}
          value={
            <>
              {rate !== null ? fmtPercent(rate, 0) : '—'}
              <span className="text-xs text-gray-500 font-normal"> vs Δ {fmtPercent(dLo, 0)}–{fmtPercent(dHi, 0)}</span>
            </>
          }
          hint={`${isPut ? 'Assignments' : 'Called-aways'} / (${isPut ? 'assignments' : 'called-aways'} + expirations) — held-to-expiry only (${data.exercised_count}/${heldToExpiry}). Delta approximates P(ITM at expiry), so this is the honest calibration against the ${fmtPercent(dLo, 0)}–${fmtPercent(dHi, 0)} ${optionType} delta band (live from bot config when reachable).`}
        />
      </div>
    </div>
  );
}
