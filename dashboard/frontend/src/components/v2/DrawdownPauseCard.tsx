import type { UncoveredSymbols } from '../../types/v2';
import { fmtPercent } from '../../utils/format';

interface Props {
  data: UncoveredSymbols | null;
}

// FC-065 Phase 4 (repoints FC-031's card + FC-030's alert): held symbols with
// no covered call written against them. Read from the bot's own decision
// records — NOT inferred from prices any more. The old card inferred a
// "drawdown pause" from the latest OPASN put strike; there is no pause gate
// (OQ-3) and the bot's floor is Alpaca's avg_entry_price (Phase 1), so that
// inference described neither a real state nor the right number.
export default function UncoveredPositionsCard({ data }: Props) {
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Uncovered Positions</h3>
        <p className="text-sm text-gray-400 mt-2">Unavailable (live positions unreachable).</p>
      </div>
    );
  }

  const unknown = data.unknown_uncovered_days ?? [];

  // The decision table could not be read. Rendering the empty-state copy here
  // would assert "every held symbol has a call written against it" on the
  // strength of a failed query — the precise failure this card exists to end.
  if (data.decision_source_available === false) {
    return (
      <div className="rounded-lg border border-yellow-700/60 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Uncovered Positions</h3>
        <p className="text-sm text-yellow-400 mt-2">
          ⚠ Decision records unavailable — coverage state is <strong>unknown</strong>, not clear.
        </p>
        <p className="text-xs text-gray-500 mt-2">
          The bot may have stopped writing decision records (rolled-back revision, BigQuery
          outage). See docs/operations/DECISION_RECORDS.md.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">Uncovered Positions</h3>
        <span className="text-xs text-gray-500" title="Trading days uncovered at which the operator is emailed (FC-030, repointed by FC-065).">
          alert at {data.threshold_days}d · {data.source}
        </span>
      </div>
      {data.uncovered.length === 0 ? (
        <p className="text-sm text-gray-400 mt-2">
          {unknown.length > 0
            // Not an all-clear: at least one held symbol's coverage is unknown.
            ? 'No symbol is confirmed uncovered — but see the unknowns below.'
            : 'Every held symbol has a call written against it.'}
        </p>
      ) : (
        <table className="w-full mt-3 text-sm">
          <thead className="text-xs uppercase tracking-wide text-gray-400">
            <tr>
              <th className="text-left py-1">Symbol</th>
              <th className="text-right py-1" title="Alpaca avg_entry_price — the floor the bot enforces">Floor</th>
              <th className="text-right py-1">Last price</th>
              <th className="text-right py-1" title="Price vs floor; negative is below the floor">vs floor</th>
              <th className="text-right py-1" title="Consecutive trading days with no covered call written">Days</th>
              <th className="text-left py-1" title="The bot's own recorded verdict for this symbol">Last decision</th>
            </tr>
          </thead>
          <tbody>
            {data.uncovered.map((p) => (
              <tr key={p.symbol} className="border-t border-gray-700/50">
                <td className="py-1.5 font-mono text-blue-300">{p.symbol}</td>
                <td className="py-1.5 text-right text-gray-200">
                  {p.cost_basis_per_share != null ? `$${p.cost_basis_per_share.toFixed(2)}` : '—'}
                </td>
                <td className="py-1.5 text-right text-gray-200">
                  {p.last_price != null ? `$${p.last_price.toFixed(2)}` : '—'}
                </td>
                <td className={`py-1.5 text-right ${(p.underwater_pct ?? 0) < 0 ? 'text-red-300' : 'text-gray-200'}`}>
                  {p.underwater_pct != null ? fmtPercent(p.underwater_pct, 1) : '—'}
                </td>
                <td className={`py-1.5 text-right ${(p.uncovered_days ?? 0) >= data.threshold_days ? 'text-yellow-300 font-semibold' : 'text-gray-200'}`}>
                  {p.uncovered_days ?? '—'}
                </td>
                <td className="py-1.5 text-gray-400 text-xs">
                  {p.outcome}{p.reason ? ` · ${p.reason}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {unknown.length > 0 && (
        <p className="text-xs text-yellow-500 mt-2">
          ⚠ Uncovered days could not be derived for:{' '}
          {unknown.map((u) => u.symbol).join(', ')} — treat as unknown, not as covered.
        </p>
      )}
      {data.share_count_mismatches.length > 0 && (
        <p className="text-xs text-yellow-500 mt-2">
          ⚠ Ledger-vs-broker share mismatch on:{' '}
          {data.share_count_mismatches.map((m) => `${m.symbol} (${m.view_shares} vs ${m.live_shares})`).join(', ')}
          {' '}— see reconciliation.
        </p>
      )}
      <p className="text-xs text-gray-500 mt-3">
        From the bot's decision records (one row per held symbol per cycle). A symbol uncovered
        ≥{data.threshold_days} trading days is idle capital and emails the operator (FC-030).
      </p>
    </div>
  );
}
