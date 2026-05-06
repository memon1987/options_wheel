// FC-022: Replaces the pill grid on the no-symbol /symbol landing page with a
// summary table that gives the user enough at-a-glance info to choose a
// symbol to investigate.

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ScorecardRow } from '../../types/v2';
import { fmtCurrency, fmtDate, fmtNumber, pnlColor, cls } from '../../utils/format';
import { positionState, stateColor } from './positionState';

type SortKey =
  | 'symbol'
  | 'trade_count'
  | 'cycles_completed'
  | 'total_premium'
  | 'total_realized_pnl'
  | 'wheel_minus_bh'
  | 'last_trade_time';

interface SortState { key: SortKey; dir: 'asc' | 'desc' }

interface Props {
  rows: ScorecardRow[];
}

export default function SymbolUniverseTable({ rows }: Props) {
  const [sort, setSort] = useState<SortState>({ key: 'total_realized_pnl', dir: 'desc' });

  const sorted = useMemo(() => {
    const out = [...rows];
    out.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
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

  const toggleSort = (key: SortKey) =>
    setSort((s) => s.key === key
      ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: 'desc' });

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
        <h3 className="text-base font-semibold text-white">Available symbols</h3>
        <p className="text-sm text-gray-400 mt-2">No traded symbols yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-700 flex items-baseline justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Available symbols</h3>
          <p className="text-xs text-gray-400 mt-1">
            Per-symbol summary. Click any row to drill in. All dates ET.
          </p>
        </div>
        <span className="text-xs text-gray-500">{sorted.length} symbols</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50">
            <tr>
              <SortHeader k="symbol" label="Symbol" />
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-left">Position</th>
              <SortHeader k="trade_count" label="Trades" align="right" />
              <SortHeader k="cycles_completed" label="Cycles" align="right" />
              <SortHeader k="total_premium" label="Total Premium" align="right" />
              <SortHeader k="total_realized_pnl" label="Total P&L" align="right" />
              <SortHeader k="wheel_minus_bh" label="vs B&H" align="right" />
              <SortHeader k="last_trade_time" label="Last Activity" />
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-400 text-center" title="Open drilldown">→</th>
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
                    {fmtNumber(r.trade_count)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtNumber(r.cycles_completed)}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(r.total_premium)}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right font-semibold', pnlColor(r.total_realized_pnl))}>
                    {fmtCurrency(r.total_realized_pnl)}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(r.wheel_minus_bh))}>
                    {r.wheel_minus_bh !== null
                      ? fmtCurrency(r.wheel_minus_bh)
                      : <span className="text-gray-500" title="Stock history not yet available">—</span>}
                  </td>
                  <td className="px-3 py-2 text-sm text-gray-300 whitespace-nowrap">
                    {r.last_trade_time ? fmtDate(r.last_trade_time) : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-center">
                    <Link
                      to={`/symbol/${r.symbol}`}
                      className="text-blue-400 hover:text-blue-300"
                      title={`Open ${r.symbol} drilldown`}
                    >
                      ↗
                    </Link>
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
