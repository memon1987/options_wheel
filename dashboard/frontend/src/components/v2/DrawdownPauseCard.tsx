import type { DrawdownPauses } from '../../types/v2';
import { fmtPercent } from '../../utils/format';

interface Props {
  data: DrawdownPauses | null;
}

// FC-031 (absorbs FC-030's dashboard half): symbols the R3 drawdown pause is
// blocking from covered-call writes. INFERRED from prices vs the assignment
// strike — not bot telemetry — and computed against LIVE share counts, so
// view-vs-broker mismatches (the AMD anomaly) surface as badges, not rows.
export default function DrawdownPauseCard({ data }: Props) {
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Drawdown Pauses</h3>
        <p className="text-sm text-gray-400 mt-2">Unavailable (live positions unreachable).</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">Drawdown Pauses</h3>
        <span className="text-xs text-gray-500" title="Threshold below the assignment strike at which the bot stops selling covered calls (FC-029 R3).">
          threshold {fmtPercent(data.threshold, 0)} · {data.threshold_source}
        </span>
      </div>
      {data.paused.length === 0 ? (
        <p className="text-sm text-gray-400 mt-2">No held symbol is below its pause floor.</p>
      ) : (
        <table className="w-full mt-3 text-sm">
          <thead className="text-xs uppercase tracking-wide text-gray-400">
            <tr>
              <th className="text-left py-1">Symbol</th>
              <th className="text-right py-1" title="Latest put assignment strike — the bot's pause reference">Assign strike</th>
              <th className="text-right py-1">Last close</th>
              <th className="text-right py-1">Below strike</th>
              <th className="text-right py-1" title="Consecutive trading days below the pause floor, bounded at the open lot's acquisition date">Days paused</th>
            </tr>
          </thead>
          <tbody>
            {data.paused.map((p) => (
              <tr key={p.symbol} className="border-t border-gray-700/50">
                <td className="py-1.5 font-mono text-blue-300">{p.symbol}</td>
                <td className="py-1.5 text-right text-gray-200">${p.assignment_strike.toFixed(2)}</td>
                <td className="py-1.5 text-right text-gray-200">
                  ${p.last_close.toFixed(2)}
                  <span className="text-xs text-gray-500"> ({p.last_close_date})</span>
                </td>
                <td className="py-1.5 text-right text-red-300">{fmtPercent(p.pct_below_strike, 1)}</td>
                <td className={`py-1.5 text-right ${p.trading_days_paused >= 7 ? 'text-yellow-300 font-semibold' : 'text-gray-200'}`}>
                  {p.trading_days_paused}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.share_count_mismatches.length > 0 && (
        <p className="text-xs text-yellow-500 mt-2">
          ⚠ Ledger-vs-broker share mismatch on:{' '}
          {data.share_count_mismatches.map((m) => `${m.symbol} (${m.view_shares} vs ${m.live_shares})`).join(', ')}
          {' '}— see reconciliation.
        </p>
      )}
      <p className="text-xs text-gray-500 mt-3">
        Inferred from prices vs the assignment strike — not bot telemetry. An extended pause
        (≥7 trading days) is idle capital; consider manual review (FC-030).
      </p>
    </div>
  );
}
