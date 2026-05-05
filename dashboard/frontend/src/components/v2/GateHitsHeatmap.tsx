import { useMemo } from 'react';
import type { FilteringStat } from '../../types/v2';
import { cls } from '../../utils/format';

interface Props {
  rows: FilteringStat[];
}

interface AggBucket {
  date: string;
  stage: string;
  total: number;
  blocked: number;
}

export default function GateHitsHeatmap({ rows }: Props) {
  const { dates, stages, byKey, maxBlocked } = useMemo(() => {
    const buckets = new Map<string, AggBucket>();
    for (const r of rows) {
      const date = r.date_et;
      const stage = r.stage;
      if (!date || !stage) continue;
      const key = `${date}|${stage}`;
      const existing = buckets.get(key) ?? { date, stage, total: 0, blocked: 0 };
      existing.total += r.total_events ?? 0;
      existing.blocked += r.blocked ?? 0;
      buckets.set(key, existing);
    }
    const dateSet = new Set<string>();
    const stageSet = new Set<string>();
    for (const b of buckets.values()) {
      dateSet.add(b.date);
      stageSet.add(b.stage);
    }
    const dates = Array.from(dateSet).sort();
    const stages = Array.from(stageSet).sort();
    let maxBlocked = 0;
    for (const b of buckets.values()) {
      if (b.blocked > maxBlocked) maxBlocked = b.blocked;
    }
    const byKey: Record<string, AggBucket> = {};
    for (const b of buckets.values()) byKey[`${b.date}|${b.stage}`] = b;
    return { dates, stages, byKey, maxBlocked };
  }, [rows]);

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Gate Hits</h3>
        <p className="text-sm text-gray-400 mt-2">No filtering events recorded in this window.</p>
      </div>
    );
  }

  const intensity = (n: number): string => {
    if (n === 0) return 'bg-gray-900';
    if (maxBlocked === 0) return 'bg-gray-900';
    const ratio = n / maxBlocked;
    if (ratio < 0.1) return 'bg-blue-900/30';
    if (ratio < 0.25) return 'bg-blue-800/50';
    if (ratio < 0.5) return 'bg-blue-700/70';
    if (ratio < 0.75) return 'bg-blue-600';
    return 'bg-blue-500';
  };

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Gate Hits</h3>
      <p className="text-xs text-gray-400 mt-1 mb-3">
        Blocked events per filtering stage per day. Darker = more rejections.
      </p>
      <div className="overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="px-2 py-1 text-left text-gray-400 font-semibold">Stage</th>
              {dates.map((d) => (
                <th key={d} className="px-1 py-1 text-center text-gray-400 font-semibold whitespace-nowrap">
                  {d.slice(5)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stages.map((stage) => (
              <tr key={stage}>
                <td className="px-2 py-1 text-gray-300 font-mono whitespace-nowrap">{stage}</td>
                {dates.map((d) => {
                  const cell = byKey[`${d}|${stage}`];
                  const blocked = cell?.blocked ?? 0;
                  return (
                    <td key={d} className="p-0.5">
                      <div
                        className={cls(
                          'w-7 h-7 rounded text-center flex items-center justify-center',
                          intensity(blocked),
                          blocked > 0 ? 'text-white' : 'text-gray-600'
                        )}
                        title={`${stage} on ${d}: ${blocked} blocked of ${cell?.total ?? 0} total`}
                      >
                        {blocked > 0 ? blocked : ''}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
