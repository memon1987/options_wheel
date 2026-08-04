import type { CycleStats } from '../../types/v2';
import { fmtCurrency, fmtPercent } from '../../utils/format';
import Stat from './Stat';

interface Props {
  data: CycleStats | null;
}

// FC-031: closed WHEEL-CYCLE stats — deliberately separate from put-trade
// stats (blending them re-creates the per-contract win-rate delta artifact).
// Open cycles are shown beside closed stats because losing cycles stay open
// longest (survivorship); overlapping-lot symbols are excluded until FC-020
// fixes their per-cycle pairing, and the exclusion is disclosed.
export default function CycleStatsCard({ data }: Props) {
  // Defensive: `?? 0` + optional-chained regimes so a degraded backend
  // payload renders the empty state instead of crashing the Overview page
  // (review C2 — the backend failure path also returns the full shape now).
  if (!data || ((data.closed_count ?? 0) === 0 && (data.open_count ?? 0) === 0)) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Wheel Cycles</h3>
        <p className="text-sm text-gray-400 mt-2">No completed cycles yet.</p>
      </div>
    );
  }

  const post = data.regime_post_fc029;

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">Wheel Cycles (assignment → called away)</h3>
        <span className="text-xs text-gray-500">
          {data.closed_count} closed · {data.open_count} open
          {(data.excluded_overlapping_symbols ?? []).length > 0 && (
            <span
              className="text-yellow-500"
              title={`Per-cycle rows for these symbols are mis-paired until FC-020 (overlapping share lots): ${(data.excluded_overlapping_symbols ?? []).join(', ')}. They are excluded from these aggregates.`}
            >
              {' '}· {(data.excluded_overlapping_symbols ?? []).length} symbol(s) excluded (FC-020)
            </span>
          )}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-3">
        <Stat
          label="Cycle win rate"
          value={data.win_rate !== null ? fmtPercent(data.win_rate, 0) : '—'}
          hint="Closed cycles with P&L > 0 / closed cycles. Cycle P&L = net option premium + share cash (FC-027)."
        />
        <Stat
          label="Expectancy / cycle"
          value={data.expectancy !== null ? fmtCurrency(data.expectancy) : '—'}
          tone={data.expectancy}
          hint={`Mean cycle P&L. Avg win ${fmtCurrency(data.avg_win)} · avg loss ${fmtCurrency(data.avg_loss)}.`}
        />
        <Stat
          label="P&L / $1k·day"
          value={data.pnl_per_collateral_day !== null
            ? `$${(data.pnl_per_collateral_day * 1000).toFixed(2)}`
            : '—'}
          tone={data.pnl_per_collateral_day}
          hint="Σ cycle P&L / Σ (collateral × days), scaled to $1k of collateral — the only valid aggregate rate across cycles of different lengths. Collateral approximated as put strike × 100."
        />
        <Stat
          label="Open cycles MTM"
          value={fmtCurrency(data.open_mtm_to_date)}
          tone={data.open_mtm_to_date}
          hint="Cycle-to-date net cash plus current market value of held shares for in-flight cycles. Shown because losing cycles stay open longest — closed-cycle stats alone overstate."
        />
      </div>
      {post && post.count > 0 && (
        /* The deploy note describes what FC-029 shipped on that date, which is
           what splits the regimes. The drawdown pause it shipped no longer
           exists (FC-065 OQ-3 killed the gate; FC-069 item 9 deleted the
           knob) — said so here so the tooltip does not read as a description
           of the current system. */
        <div className="text-xs text-gray-500 mt-3" title={`FC-029 risk re-tune deployed ${data.fc029_deploy_date} (call delta band, hard cost-basis floor, and a drawdown pause that has since been removed).`}>
          Since FC-029 ({data.fc029_deploy_date}): {post.count} cycles ·{' '}
          win rate {post.win_rate !== null ? fmtPercent(post.win_rate, 0) : '—'} ·{' '}
          expectancy {fmtCurrency(post.expectancy)} · vs pre:{' '}
          {data.regime_pre_fc029?.count ?? 0} cycles, expectancy {fmtCurrency(data.regime_pre_fc029?.expectancy ?? null)}
        </div>
      )}
    </div>
  );
}
