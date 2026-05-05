import { useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';
import type { DecisionQualityRow } from '../../types/v2';
import { fmtPercent } from '../../utils/format';

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
