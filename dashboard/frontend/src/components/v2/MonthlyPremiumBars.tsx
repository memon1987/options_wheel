import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts';
import type { PremiumByDayPoint } from '../../types/v2';
import { fmtCurrency } from '../../utils/format';

interface Props {
  data: PremiumByDayPoint[];
}

interface MonthBucket {
  month: string;
  put_premium: number;
  call_premium: number;
}

const aggregateByMonth = (data: PremiumByDayPoint[]): MonthBucket[] => {
  const map = new Map<string, MonthBucket>();
  for (const row of data) {
    const month = (row.date ?? '').slice(0, 7);
    if (!month) continue;
    const existing = map.get(month) ?? { month, put_premium: 0, call_premium: 0 };
    existing.put_premium += row.put_premium ?? 0;
    existing.call_premium += row.call_premium ?? 0;
    map.set(month, existing);
  }
  return Array.from(map.values()).sort((a, b) => a.month.localeCompare(b.month));
};

const fmtMonth = (m: string): string => {
  const [y, mm] = m.split('-');
  if (!y || !mm) return m;
  const d = new Date(parseInt(y, 10), parseInt(mm, 10) - 1, 1);
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
};

export default function MonthlyPremiumBars({ data }: Props) {
  const monthly = aggregateByMonth(data);

  if (monthly.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Monthly Premium</h3>
        <p className="text-sm text-gray-400 mt-2">No premium history yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white mb-1">Monthly Premium</h3>
      <p className="text-xs text-gray-400 mb-3">Put / call split by calendar month</p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={monthly} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
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
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              labelFormatter={(m) => fmtMonth(m as string)}
              formatter={(value: number, name: string) => [fmtCurrency(value), name === 'put_premium' ? 'Put' : 'Call']}
            />
            <Legend
              wrapperStyle={{ color: '#9ca3af' }}
              formatter={(v) => (v === 'put_premium' ? 'Put premium' : 'Call premium')}
            />
            <Bar dataKey="put_premium" stackId="prem" fill="#60a5fa" />
            <Bar dataKey="call_premium" stackId="prem" fill="#a78bfa" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
