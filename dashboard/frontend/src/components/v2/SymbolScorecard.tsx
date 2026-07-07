import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { ScorecardRow } from '../../types/v2';
import { fmtCurrency, fmtNumber, fmtPercent, pnlColor, cls } from '../../utils/format';
import { positionState, stateColor } from './positionState';

interface Props {
  rows: ScorecardRow[];
}

type SortKey =
  | 'symbol'
  | 'trade_count'
  | 'cycles_completed'
  | 'total_premium'
  | 'realized_pnl'
  | 'share_side_pnl'
  | 'total_realized_pnl'
  | 'wheel_mtm_pnl'
  | 'wheel_minus_bh';

interface SortState {
  key: SortKey;
  dir: 'asc' | 'desc';
}

export default function SymbolScorecard({ rows }: Props) {
  const [sort, setSort] = useState<SortState>({ key: 'wheel_mtm_pnl', dir: 'desc' });

  const sorted = useMemo(() => {
    const out = [...rows];
    out.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      // Strings (symbol) sort lexically; numbers sort numerically with nulls last.
      if (typeof av === 'string' || typeof bv === 'string') {
        const as = (av as string) ?? '';
        const bs = (bv as string) ?? '';
        return sort.dir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as);
      }
      const an = av === null || av === undefined ? -Infinity : (av as number);
      const bn = bv === null || bv === undefined ? -Infinity : (bv as number);
      return sort.dir === 'asc' ? an - bn : bn - an;
    });
    return out;
  }, [rows, sort]);

  const toggleSort = (key: SortKey) => {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'desc' }
    );
  };

  const SortHeader = ({ k, label, align = 'left' }: { k: SortKey; label: string; align?: 'left' | 'right' }) => (
    <th
      className={cls(
        'px-3 py-2 text-xs font-semibold uppercase tracking-wide cursor-pointer select-none text-gray-400 hover:text-white',
        align === 'right' ? 'text-right' : 'text-left'
      )}
      onClick={() => toggleSort(k)}
    >
      {label}
      {sort.key === k && <span className="ml-1 text-blue-400">{sort.dir === 'asc' ? '↑' : '↓'}</span>}
    </th>
  );

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Per-Symbol Scorecard</h3>
        <p className="text-sm text-gray-400 mt-2">No traded symbols in this window.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-700 flex items-baseline justify-between">
        <h3 className="text-base font-semibold text-white">Per-Symbol Scorecard</h3>
        <span className="text-xs text-gray-400">click a row → drilldown</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50">
            <tr>
              <SortHeader k="symbol" label="Symbol" />
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-left">State</th>
              <SortHeader k="cycles_completed" label="Cycles" align="right" />
              <SortHeader k="trade_count" label="Trades" align="right" />
              <SortHeader k="total_premium" label="Gross Prem" align="right" />
              <SortHeader k="realized_pnl" label="Option P&L" align="right" />
              <SortHeader k="share_side_pnl" label="Share P&L" align="right" />
              <SortHeader k="total_realized_pnl" label="Cash P&L" align="right" />
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-right" title="Cost of the currently-open share lot (FIFO over OPTRD events). Display only — this cost is already expensed inside Cash P&L.">Basis/sh</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-right" title="Effective breakeven per share: (share cost − net premiums) / shares. A covered-call strike decision input — never summed into P&L.">Breakeven/sh</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-right" title="Most recent daily-bar close for the underlying — can lag live prices">Price</th>
              <SortHeader k="wheel_mtm_pnl" label="MTM P&L" align="right" />
              <SortHeader k="wheel_minus_bh" label="vs B&H" align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const state = positionState(r);
              return (
                <tr
                  key={r.symbol}
                  className="border-t border-gray-700/50 hover:bg-gray-700/30"
                >
                  <td className="px-3 py-2">
                    <Link
                      to={`/symbol/${r.symbol}`}
                      className="font-mono text-sm font-semibold text-blue-300 hover:text-blue-200"
                    >
                      {r.symbol}
                    </Link>
                  </td>
                  <td className={cls('px-3 py-2 text-sm', stateColor(state))}>{state}</td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtNumber(r.cycles_completed)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtNumber(r.trade_count)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(r.total_premium)}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.realized_pnl))}>
                    {fmtCurrency(r.realized_pnl)}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.share_side_pnl))}>
                    {r.share_side_pnl !== null && r.share_side_pnl !== 0
                      ? <span title="Sum of OPTRD net cash flow on share movements (assignments and called-aways) for this symbol">{fmtCurrency(r.share_side_pnl)}</span>
                      : <span className="text-gray-500">—</span>}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.total_realized_pnl))}>
                    <span title="Net CASH P&L: option premiums net of buybacks + all OPTRD share cash (including the acquisition cost of shares still held). See MTM P&L for the marked-to-market total.">
                      {fmtCurrency(r.total_realized_pnl)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {r.open_lot_basis_per_share !== null && (r.open_lot_shares ?? 0) > 0
                      ? <span title={`FIFO open-lot cost. Acquired ${r.open_lot_acquired_at?.slice(0, 10) ?? '—'}`}>{`$${r.open_lot_basis_per_share.toFixed(2)}`}</span>
                      : <span className="text-gray-500">—</span>}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {r.current_shares !== null && r.current_shares > 0 && r.current_acb_per_share !== null
                      ? <span title={r.price_now !== null ? `Distance to breakeven: ${(((r.price_now - r.current_acb_per_share) / r.current_acb_per_share) * 100).toFixed(1)}%` : undefined}>
                          {`$${r.current_acb_per_share.toFixed(2)}`}
                        </span>
                      : <span className="text-gray-500">—</span>}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {r.price_now !== null
                      ? <span title={r.price_now_date ? `Close of ${r.price_now_date}` : undefined}>{`$${r.price_now.toFixed(2)}`}</span>
                      : <span className="text-gray-500">—</span>}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right font-semibold', pnlColor(r.wheel_mtm_pnl ?? r.total_realized_pnl))}>
                    {r.wheel_mtm_pnl !== null ? (
                      <span title="Marked-to-market P&L: net cash P&L + full market value of held shares (their cost is already expensed in cash P&L — using (price − basis) × shares here would double-count). Open option marks excluded.">
                        {fmtCurrency(r.wheel_mtm_pnl)}
                      </span>
                    ) : (
                      <span title="No price data yet for held shares — showing net cash P&L">{fmtCurrency(r.total_realized_pnl)}</span>
                    )}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.wheel_minus_bh))}>
                    {r.wheel_minus_bh !== null ? (
                      <span title="Wheel MTM P&L minus synthetic buy-and-hold of the first put's collateral, both marked to the same close. B&H is a perfect-foresight reference — every symbol assumes its full collateral deployed for the whole period.">
                        {fmtCurrency(r.wheel_minus_bh)}
                      </span>
                    ) : (
                      <span className="text-gray-500" title="Stock history not yet available">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="px-5 py-2 border-t border-gray-700 text-xs text-gray-500 flex justify-between gap-4 flex-wrap">
        <span>
          {(() => {
            // FC-031: denominator counts only symbols WITH a comparison —
            // null rows (missing bars) used to deflate the beat rate.
            const comparable = sorted.filter((r) => r.wheel_minus_bh !== null);
            if (comparable.length === 0) return 'No buy-and-hold comparisons available yet.';
            const beat = comparable.filter((r) => (r.wheel_minus_bh ?? 0) > 0).length;
            const dateStamp = sorted.find((r) => r.price_now_date)?.price_now_date;
            return (
              <>
                {fmtPercent(beat / comparable.length)} of {comparable.length} comparable symbols beat buy-and-hold.
                {dateStamp && <span className="ml-2">Prices as of {dateStamp}.</span>}
              </>
            );
          })()}
        </span>
        <span className="text-right">
          <span title="Sum of every option premium collected when sold (gross of buybacks) — revenue, not profit">Gross Prem</span> ·{' '}
          <span title="Option-side realized P&L net of roll buybacks">Option P&L</span> ·{' '}
          <span title="Stock-side cash flow from OPTRD (assignment / called-away) — includes acquisition cost of shares still held">Share P&L</span> ·{' '}
          <span title="Net cash P&L = Option + Share cash. Σ Cash P&L + open premium + fees + live market value ≈ NLV − deposits (see reconciliation line)">Cash P&L</span> ·{' '}
          <span title="Cash P&L + market value of held shares — the marked-to-market total">MTM P&L</span>
        </span>
      </div>
    </div>
  );
}
