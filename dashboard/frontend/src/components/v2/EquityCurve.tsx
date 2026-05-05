import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import type { PortfolioHistoryPoint } from '../../types/v2';
import { fmtCurrency, fmtDateShort } from '../../utils/format';

interface Props {
  data: PortfolioHistoryPoint[];
}

export default function EquityCurve({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Equity Curve</h3>
        <p className="text-sm text-gray-400 mt-2">No equity history yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white mb-4">Equity Curve</h3>
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
              tickFormatter={(n) => fmtCurrency(n, { compact: true })}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              labelFormatter={(label) => fmtDateShort(label as string)}
              formatter={(value: number) => fmtCurrency(value)}
            />
            <Line
              type="monotone"
              dataKey="portfolio_value"
              stroke="#60a5fa"
              strokeWidth={2}
              dot={false}
              name="Portfolio value"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
