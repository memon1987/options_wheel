import type { BotAnomaly } from '../../types/v2';
import { cls } from '../../utils/format';

interface Props {
  data: BotAnomaly[] | null;
}

// FC-031: anomaly flags computed on the SPY-bar trading calendar —
// independent of the scheduler, so a totally dead scheduler still lights up.
export default function AnomalyFlags({ data }: Props) {
  const flags = data ?? [];

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Anomaly Flags</h3>
      {flags.length === 0 ? (
        <p className="text-sm text-green-300 mt-2">✓ No anomalies detected.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {flags.map((f, i) => (
            <li key={`${f.code}-${i}`} className="flex items-start gap-2 text-sm">
              <span
                className={cls(
                  'px-1.5 py-0.5 rounded text-xs font-semibold uppercase shrink-0',
                  f.severity === 'critical'
                    ? 'bg-red-900/50 text-red-300'
                    : 'bg-yellow-900/50 text-yellow-300'
                )}
              >
                {f.severity}
              </span>
              <div>
                <div className="text-gray-200">{f.message}</div>
                <div className="text-xs text-gray-500 font-mono">
                  {f.code}
                  {f.since && <> · since {f.since}</>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-gray-500 mt-3">
        Trading calendar from SPY bars (independent of the bot&apos;s own scheduler).
      </p>
    </div>
  );
}
