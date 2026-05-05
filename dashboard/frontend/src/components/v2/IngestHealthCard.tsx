import type { IngestHealth } from '../../types/v2';
import { fmtDateTime, fmtRelativeAge, cls } from '../../utils/format';

interface Props {
  data: IngestHealth | null;
}

const labels: Record<keyof IngestHealth, string> = {
  trades_from_activities: 'Activities (FC-012)',
  equity_history_from_alpaca: 'Portfolio history (FC-012)',
  stock_history_from_alpaca: 'Stock bars (FC-018)',
};

const isStale = (ts: string | null): boolean => {
  if (!ts) return true;
  const ageMs = Date.now() - new Date(ts).getTime();
  return ageMs > 26 * 3600 * 1000;
};

export default function IngestHealthCard({ data }: Props) {
  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Ingest Health</h3>
      <p className="text-xs text-gray-400 mt-1 mb-3">
        Last successful run of each Alpaca-sourced ingestor. Stale ({'>'}26h) means a scheduler may have failed.
      </p>
      <table className="w-full">
        <tbody>
          {(Object.keys(labels) as Array<keyof IngestHealth>).map((k) => {
            const ts = data?.[k] ?? null;
            const stale = isStale(ts);
            return (
              <tr key={k} className="border-t border-gray-700/50 first:border-t-0">
                <td className="py-2 text-sm text-gray-300">{labels[k]}</td>
                <td className="py-2 text-sm text-right">
                  <span className={cls(stale ? 'text-yellow-400' : 'text-green-400')}>
                    {fmtRelativeAge(ts)}
                  </span>
                  <div className="text-xs text-gray-500 mt-0.5">{ts ? fmtDateTime(ts) : 'never'}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
