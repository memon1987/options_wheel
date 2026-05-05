import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import type { ScorecardRow } from '../../types/v2';
import { fmtCurrency, fmtNumber, fmtPercent, pnlColor, cls } from '../../utils/format';

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
  | 'wheel_minus_bh';

interface SortState {
  key: SortKey;
  dir: 'asc' | 'desc';
}

const positionState = (row: ScorecardRow): string => {
  const shares = row.current_shares ?? 0;
  const open = row.open_count ?? 0;
  if (shares > 0) return open > 0 ? 'Long + Short Call' : 'Long Stock';
  if (open > 0) return 'Short Put';
  return 'Cash';
};

const stateColor = (state: string): string => {
  switch (state) {
    case 'Long + Short Call': return 'text-purple-300';
    case 'Long Stock': return 'text-blue-300';
    case 'Short Put': return 'text-green-300';
    default: return 'text-gray-400';
  }
};

export default function SymbolScorecard({ rows }: Props) {
  const [sort, setSort] = useState<SortState>({ key: 'total_premium', dir: 'desc' });

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
              <SortHeader k="total_realized_pnl" label="Total P&L" align="right" />
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
                      to={`/v2/symbol/${r.symbol}`}
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
                  <td className={cls('px-3 py-2 text-sm text-right font-semibold', pnlColor(r.total_realized_pnl))}>
                    <span title="Option-side realized P&L plus stock-side realized P&L from share movements. This number plus unrealized on open positions = your account growth.">
                      {fmtCurrency(r.total_realized_pnl)}
                    </span>
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.wheel_minus_bh))}>
                    {r.wheel_minus_bh !== null ? (
                      <span title="Wheel total return minus synthetic buy-and-hold of same dollar amount">
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
          {fmtPercent(sorted.filter((r) => r.wheel_minus_bh !== null && r.wheel_minus_bh > 0).length / Math.max(sorted.length, 1))} of symbols beat buy-and-hold this period.
        </span>
        <span className="text-right">
          <span title="Sum of every option premium collected when sold (gross of buybacks)">Gross Prem</span> ·{' '}
          <span title="Option-side realized P&L net of roll buybacks">Option P&L</span> ·{' '}
          <span title="Stock-side cash flow from OPTRD (assignment / called-away) — captures real lot economics">Share P&L</span> ·{' '}
          <span title="Option P&L + Share P&L. Sum of this column across symbols ≈ headline Total Return (minus unrealized + fees)">Total P&L</span>
        </span>
      </div>
    </div>
  );
}
