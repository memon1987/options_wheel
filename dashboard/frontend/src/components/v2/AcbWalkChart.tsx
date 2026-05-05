import { ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot, Legend } from 'recharts';
import type { AcbTimelineRow } from '../../types/v2';
import { fmtCurrencyDetail, fmtDate } from '../../utils/format';

interface Props {
  data: AcbTimelineRow[];
}

const labelColor = (label: string): string => {
  switch (label) {
    case 'put_sold': return '#34d399';
    case 'call_sold': return '#a78bfa';
    case 'option_closed': return '#9ca3af';
    case 'put_assigned': return '#fbbf24';
    case 'called_away': return '#fb923c';
    case 'expired': return '#60a5fa';
    default: return '#6b7280';
  }
};

const eventLegendItems: Array<{ label: string; color: string }> = [
  { label: 'put sold', color: '#34d399' },
  { label: 'call sold', color: '#a78bfa' },
  { label: 'closed', color: '#9ca3af' },
  { label: 'assigned', color: '#fbbf24' },
  { label: 'called away', color: '#fb923c' },
  { label: 'expired', color: '#60a5fa' },
];

export default function AcbWalkChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">ACB Walk</h3>
        <p className="text-sm text-gray-400 mt-2">No events recorded for this symbol.</p>
      </div>
    );
  }

  const series = data.map((r) => ({
    ...r,
    x: r.event_time,
    cumulative_premium: r.cumulative_net_premium,
    acb: r.acb_per_share,
  }));

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-base font-semibold text-white">ACB Walk</h3>
          <p className="text-xs text-gray-400 mt-1">
            Adjusted cost basis per share over time. Annotated by event.
          </p>
        </div>
        <div className="hidden md:flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {eventLegendItems.map(({ label, color }) => (
            <span key={label} className="inline-flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full" style={{ background: color }}></span>
              <span className="text-gray-400">{label}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={series} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="x"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(v) => fmtDate(v).slice(-9)}
              minTickGap={40}
            />
            <YAxis
              yAxisId="acb"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(n) => `$${n}`}
              width={60}
            />
            <YAxis
              yAxisId="prem"
              orientation="right"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(n) => `$${n}`}
              width={60}
            />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', color: '#f3f4f6' }}
              labelFormatter={(v) => fmtDate(v as string)}
              formatter={(value: number, name: string) => [fmtCurrencyDetail(value), name]}
            />
            <Legend wrapperStyle={{ color: '#9ca3af' }} />
            <Line
              yAxisId="acb"
              type="stepAfter"
              dataKey="acb"
              stroke="#fbbf24"
              strokeWidth={2}
              connectNulls
              dot={false}
              name="ACB / share"
            />
            <Line
              yAxisId="prem"
              type="monotone"
              dataKey="cumulative_premium"
              stroke="#60a5fa"
              strokeWidth={1.5}
              dot={false}
              name="Cumulative premium"
              strokeDasharray="3 3"
            />
            {series.map((s, i) => (
              <ReferenceDot
                key={`${s.x}-${i}`}
                yAxisId="acb"
                x={s.x}
                y={s.acb ?? 0}
                r={3}
                fill={labelColor(s.event_label)}
                stroke="none"
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
