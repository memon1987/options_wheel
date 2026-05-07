import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';
import type { DecisionQualityRow } from '../../types/v2';
import { fmtCurrency, fmtPercent, pnlColor } from '../../utils/format';

interface Props {
  rows: DecisionQualityRow[];
}

interface Bin {
  label: string;
  range: [number, number];
  count: number;
}

const BINS: Array<Pick<Bin, 'label' | 'range'>> = [
  { label: '<0%', range: [-Infinity, 0] },
  { label: '0-25%', range: [0, 0.25] },
  { label: '25-50%', range: [0.25, 0.5] },
  { label: '50-75%', range: [0.5, 0.75] },
  { label: '75-100%', range: [0.75, 1.0] },
  { label: '100%', range: [1.0, Infinity] },
];

const BIN_COLORS = ['#ef4444', '#f97316', '#fbbf24', '#84cc16', '#22c55e', '#10b981'];

export default function DecisionQuality({ rows }: Props) {
  const bins: Bin[] = useMemo(() => {
    const filled = BINS.map((b) => ({ ...b, count: 0 }));
    for (const r of rows) {
      if (r.capture_ratio === null) continue;
      const cr = r.capture_ratio;
      for (let i = 0; i < filled.length; i++) {
        const [lo, hi] = filled[i].range;
        if (cr >= lo && cr < hi) {
          filled[i].count += 1;
          break;
        }
      }
    }
    return filled;
  }, [rows]);

  const total = bins.reduce((s, b) => s + b.count, 0);
  const counted = rows.filter((r) => r.capture_ratio !== null).length;
  const avgCapture = counted > 0
    ? rows.reduce((s, r) => s + (r.capture_ratio ?? 0), 0) / counted
    : 0;

  // Dollar-weighted aggregates (FC-026). Distinct from avgCapture, which is
  // the trade-weighted mean of per-trade capture ratios.
  //   - received: gross premium taken in across all closed trades
  //   - captured: realized P&L kept after any early-close buybacks
  //   - foregone: premium given back via buy-to-close orders = received − captured
  // Foregone is labeled "(buybacks)" in the UI to disambiguate from the
  // counterfactual "would-have-made" reading, which would require option-chain
  // snapshots (filed as FC-017).
  const premiumReceived = rows.reduce((s, r) => s + (r.premium_total ?? 0), 0);
  const premiumCaptured = rows.reduce((s, r) => s + (r.realized_pnl ?? 0), 0);
  const premiumForegone = premiumReceived - premiumCaptured;
  const captureRatePct = premiumReceived !== 0 ? premiumCaptured / premiumReceived : 0;
  const foregoneRatePct = premiumReceived !== 0 ? premiumForegone / premiumReceived : 0;

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Decision Quality</h3>
        <p className="text-sm text-gray-400 mt-2">No closed trades to evaluate.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="text-base font-semibold text-white">Decision Quality</h3>
        <span className="text-xs text-gray-400">
          avg capture {fmtPercent(avgCapture)} · n={total}
        </span>
      </div>
      <p className="text-xs text-gray-400 mb-3">
        % of max profit captured at close. 100% = held to expiry; 50% = closed at half premium.
      </p>
      <div className="grid grid-cols-3 gap-2 mb-3 text-xs">
        <div className="rounded border border-gray-700 bg-gray-900/30 px-2 py-1.5">
          <div className="uppercase tracking-wide text-gray-500">Received</div>
          <div className="text-sm font-semibold text-gray-200 mt-0.5">{fmtCurrency(premiumReceived)}</div>
        </div>
        <div className="rounded border border-gray-700 bg-gray-900/30 px-2 py-1.5">
          <div className="uppercase tracking-wide text-gray-500">Captured</div>
          <div className={`text-sm font-semibold mt-0.5 ${pnlColor(premiumCaptured)}`}>
            {fmtCurrency(premiumCaptured)}
            <span className="ml-1 text-gray-500 text-xs font-normal">({fmtPercent(captureRatePct)})</span>
          </div>
        </div>
        <div className="rounded border border-gray-700 bg-gray-900/30 px-2 py-1.5">
          <div
            className="uppercase tracking-wide text-gray-500"
            title="Cash spent buying back early-close orders. Distinct from a counterfactual 'what would I have made by holding' (which is FC-017)."
          >
            Foregone (buybacks)
          </div>
          <div className="text-sm font-semibold text-gray-200 mt-0.5">
            {fmtCurrency(premiumForegone)}
            <span className="ml-1 text-gray-500 text-xs font-normal">({fmtPercent(foregoneRatePct)})</span>
          </div>
        </div>
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bins} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="label" tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fill: '#9ca3af', fontSize: 11 }} width={32} />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              formatter={(v: number) => [v, 'Trades']}
            />
            <Bar dataKey="count">
              {bins.map((_, i) => (
                <Cell key={i} fill={BIN_COLORS[i] ?? '#6b7280'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
