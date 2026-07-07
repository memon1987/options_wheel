import type { FilteringStat } from '../../types/v2';
import { fmtNumber, fmtPercent, cls } from '../../utils/format';

interface Props {
  rows: FilteringStat[];       // selected window
  baselineRows: FilteringStat[]; // trailing window for pass-rate baseline
  windowLabel: string;
}

interface StageAgg {
  stage: string;
  order: number;
  passed: number;
  blocked: number;
}

const stageOrder = (stage: string): number => {
  const m = stage.match(/(\d+)/);
  return m ? parseInt(m[1], 10) : 99;
};

const aggregate = (rows: FilteringStat[]): Map<string, StageAgg> => {
  const map = new Map<string, StageAgg>();
  for (const r of rows) {
    const key = r.stage ?? 'unknown';
    const agg = map.get(key) ?? { stage: key, order: stageOrder(key), passed: 0, blocked: 0 };
    agg.passed += r.passed ?? 0;
    agg.blocked += r.blocked ?? 0;
    map.set(key, agg);
  }
  return map;
};

// FC-031: the decision funnel — candidates entering each gate stage and the
// pass/block split, ordered by pipeline stage. A healthy bot has a stable
// funnel shape; config bugs, dead data feeds, and regime changes all show up
// as shape breaks vs the trailing baseline.
export default function DecisionFunnel({ rows, baselineRows, windowLabel }: Props) {
  const stages = Array.from(aggregate(rows).values()).sort((a, b) => a.order - b.order);
  const baseline = aggregate(baselineRows);

  if (stages.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Decision Funnel</h3>
        <p className="text-sm text-gray-400 mt-2">No filtering events in this window.</p>
      </div>
    );
  }

  const maxTotal = Math.max(...stages.map((s) => s.passed + s.blocked), 1);

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold text-white">Decision Funnel</h3>
        <span className="text-xs text-gray-500">{windowLabel} · Δ vs trailing 30d pass rate</span>
      </div>
      <div className="mt-3 space-y-1.5">
        {stages.map((s) => {
          const total = s.passed + s.blocked;
          const passRate = total > 0 ? s.passed / total : null;
          const base = baseline.get(s.stage);
          const baseTotal = base ? base.passed + base.blocked : 0;
          const basePassRate = base && baseTotal > 0 ? base.passed / baseTotal : null;
          const delta = passRate !== null && basePassRate !== null ? passRate - basePassRate : null;
          const fullBlock = total > 0 && s.passed === 0;
          return (
            <div key={s.stage} className="flex items-center gap-2 text-xs">
              <div className="w-28 shrink-0 font-mono text-gray-300 truncate" title={s.stage}>{s.stage}</div>
              <div className="flex-1 h-4 bg-gray-900/60 rounded overflow-hidden flex" title={`${fmtNumber(s.passed)} passed · ${fmtNumber(s.blocked)} blocked`}>
                <div className="bg-green-700/70 h-full" style={{ width: `${(s.passed / maxTotal) * 100}%` }} />
                <div className="bg-red-800/70 h-full" style={{ width: `${(s.blocked / maxTotal) * 100}%` }} />
              </div>
              <div className={cls('w-16 text-right', fullBlock ? 'text-red-400 font-semibold' : 'text-gray-300')}>
                {passRate !== null ? fmtPercent(passRate, 0) : '—'}
              </div>
              <div className={cls(
                'w-14 text-right',
                delta === null ? 'text-gray-600'
                  : delta < -0.15 ? 'text-yellow-400'
                  : 'text-gray-500'
              )} title="Pass rate vs the trailing baseline — a large negative delta means this gate suddenly blocks much more than usual">
                {delta !== null ? `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(0)}pp` : ''}
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-gray-500 mt-3">
        Green = passed, red = blocked, bar width ∝ candidates entering the stage.
        100% block on a stage that normally passes is the classic silent-failure signature.
      </p>
    </div>
  );
}
