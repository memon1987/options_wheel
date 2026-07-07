import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts';
import type { EquityCurvePoint } from '../../types/v2';
import { fmtDateShort } from '../../utils/format';

interface Props {
  data: EquityCurvePoint[];
}

// FC-031: TWR-indexed account curve vs SPY price index, both base 100 at
// window start. TWR strips deposit jumps out of the account line, so the two
// curves sit on the same capital-time base — the only honest comparison.
export default function EquityCurve({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Equity Curve vs Benchmark</h3>
        <p className="text-sm text-gray-400 mt-2">No equity history yet.</p>
      </div>
    );
  }

  const hasBenchmark = data.some((p) => p.benchmark !== null && p.benchmark !== undefined);

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Equity Curve vs Benchmark</h3>
      <p className="text-xs text-gray-500 mt-1 mb-3">
        Time-weighted index, base 100 (deposits stripped out).{' '}
        {hasBenchmark ? (
          <span title="SPY closes only — no dividend reinvestment, which understates buy-and-hold by roughly 1.2%/yr. The paper account also credits 0% on idle cash where a live account would earn T-bill yield on put collateral; both biases run against the benchmark being flattering.">
            SPY price-only (no dividends) ⓘ
          </span>
        ) : (
          'SPY benchmark pending backfill (POST /ingest-stock-history).'
        )}
      </p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="date"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={fmtDateShort}
              minTickGap={24}
            />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(n) => `${n}`}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              labelFormatter={(label) => fmtDateShort(label as string)}
              formatter={(value: number, name: string) => [value?.toFixed(1), name]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              type="monotone"
              dataKey="wheel"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={false}
              connectNulls
              name="Wheel (TWR)"
            />
            {hasBenchmark && (
              <Line
                type="monotone"
                dataKey="benchmark"
                stroke="#9ca3af"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                connectNulls
                name="SPY (price)"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
