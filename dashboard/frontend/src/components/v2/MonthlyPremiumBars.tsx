import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine } from 'recharts';
import type { MonthlyCashflow } from '../../types/v2';
import { fmtCurrency } from '../../utils/format';

interface Props {
  data: MonthlyCashflow[];
}

const fmtMonth = (m: string): string => {
  const [y, mm] = m.split('-');
  if (!y || !mm) return m;
  const d = new Date(parseInt(y, 10), parseInt(mm, 10) - 1, 1);
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
};

// FC-031: NET option cash flow by month (premiums received − buyback costs
// in the month the cash moved). Gross premium is revenue, not profit — the
// old gross bars overstated income in heavy-roll months. Gross shown in the
// tooltip for context.
export default function MonthlyPremiumBars({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Net Option Cash Flow</h3>
        <p className="text-sm text-gray-400 mt-2">No option cash-flow history yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white mb-1">Net Option Cash Flow</h3>
      <p className="text-xs text-gray-400 mb-3" title="Premiums received minus buy-to-close costs, by the month the cash moved. Gross premium (shown in tooltip) is revenue, not profit.">
        Put / call split · net of buybacks, by calendar month
      </p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="month"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={fmtMonth}
            />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(n) => fmtCurrency(n, { compact: true })}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload || payload.length === 0) return null;
                const row = payload[0].payload as MonthlyCashflow;
                return (
                  <div className="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-xs text-gray-200">
                    <div className="font-semibold">{fmtMonth(label as string)}</div>
                    <div>Net: {fmtCurrency(row.net_option_cashflow)}</div>
                    <div>Put net: {fmtCurrency(row.put_net_cashflow)} · Call net: {fmtCurrency(row.call_net_cashflow)}</div>
                    <div className="text-gray-400">
                      Gross {fmtCurrency(row.gross_premium)} − buybacks {fmtCurrency(row.buyback_cost)}
                    </div>
                  </div>
                );
              }}
            />
            <Legend
              wrapperStyle={{ color: '#9ca3af' }}
              formatter={(v) => (v === 'put_net_cashflow' ? 'Put (net)' : 'Call (net)')}
            />
            <ReferenceLine y={0} stroke="#6b7280" />
            <Bar dataKey="put_net_cashflow" stackId="net" fill="#60a5fa" />
            <Bar dataKey="call_net_cashflow" stackId="net" fill="#a78bfa" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
