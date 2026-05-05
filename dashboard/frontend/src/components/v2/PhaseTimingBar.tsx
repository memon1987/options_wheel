import type { PhaseTiming } from '../../types/v2';
import { cls } from '../../utils/format';

interface Props {
  data: PhaseTiming | null;
}

const PHASES: Array<{
  key: keyof Pick<PhaseTiming, 'cash_waiting' | 'short_put' | 'long_stock' | 'covered'>;
  label: string;
  bg: string;
  text: string;
  hint: string;
}> = [
  { key: 'cash_waiting', label: 'Cash waiting',  bg: 'bg-gray-600',     text: 'text-gray-200',
    hint: 'No open puts, no shares held. Capital is parked.' },
  { key: 'short_put',    label: 'Short put',     bg: 'bg-green-700',    text: 'text-green-100',
    hint: 'Open put(s) sold, no shares yet. Premium-collection mode.' },
  { key: 'long_stock',   label: 'Long stock',    bg: 'bg-blue-700',     text: 'text-blue-100',
    hint: 'Holding shares from assignment, no covered call yet.' },
  { key: 'covered',      label: 'Covered call',  bg: 'bg-purple-700',   text: 'text-purple-100',
    hint: 'Holding shares + open call. The income-generating phase of the wheel.' },
];

export default function PhaseTimingBar({ data }: Props) {
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Phase Timing</h3>
        <p className="text-sm text-gray-400 mt-2">No timing data available.</p>
      </div>
    );
  }

  const total = PHASES.reduce((s, p) => s + (data[p.key] ?? 0), 0);

  if (total <= 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Phase Timing</h3>
        <p className="text-sm text-gray-400 mt-2">No tracked time for this symbol yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-base font-semibold text-white">Phase Timing</h3>
          <p className="text-xs text-gray-400 mt-1">
            Days spent in each wheel phase. Diagnoses capital drag (long Cash) and over-exposure (long Long Stock without a Covered Call).
          </p>
        </div>
        <span className="text-xs text-gray-400">
          current: <span className="font-medium text-white">{data.current_phase.replace('_', ' ')}</span>
        </span>
      </div>

      <div className="flex h-8 rounded-md overflow-hidden border border-gray-700">
        {PHASES.map(({ key, bg }) => {
          const days = data[key] ?? 0;
          const pct = (days / total) * 100;
          if (pct < 0.1) return null;
          return (
            <div
              key={key}
              className={cls(bg, 'flex items-center justify-center transition-all')}
              style={{ width: `${pct}%` }}
              title={`${key}: ${days.toFixed(1)} days (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
        {PHASES.map(({ key, label, bg, text, hint }) => {
          const days = data[key] ?? 0;
          const pct = total > 0 ? (days / total) * 100 : 0;
          return (
            <div key={key} className="border border-gray-700 rounded p-3" title={hint}>
              <div className="flex items-center gap-2">
                <span className={cls('w-3 h-3 rounded', bg)} />
                <span className={cls('text-xs uppercase tracking-wide font-semibold', text)}>{label}</span>
              </div>
              <div className="text-lg font-semibold text-white mt-1">{days.toFixed(1)}d</div>
              <div className="text-xs text-gray-400">{pct.toFixed(1)}% of tracked</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
