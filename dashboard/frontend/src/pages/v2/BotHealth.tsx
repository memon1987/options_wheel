import { useApi } from '../../hooks/useApi';
import type {
  IngestHealth,
  FilteringStat,
  ErrorEvent,
  DailySummary,
} from '../../types/v2';
import IngestHealthCard from '../../components/v2/IngestHealthCard';
import GateHitsHeatmap from '../../components/v2/GateHitsHeatmap';
import { fmtDateTime, fmtNumber, cls } from '../../utils/format';

export default function BotHealth() {
  const { data: ingest } = useApi<IngestHealth>('/api/v2/bot-health/ingest', { refreshInterval: 60_000 });
  const { data: filtering } = useApi<FilteringStat[]>('/api/history/filtering?days=14');
  const { data: errors } = useApi<ErrorEvent[]>('/api/history/errors?days=7');
  const { data: daily } = useApi<DailySummary[]>('/api/history/daily-summary?days=14');

  // Aggregate error frequency by error_type for the summary table.
  const errorByType: Array<[string, number]> = (() => {
    const counts = new Map<string, number>();
    for (const e of errors ?? []) {
      const k = e.error_type || e.event_type || 'unknown';
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10);
  })();

  const recentDaily = (daily ?? []).slice(0, 7);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Bot Health</h1>
        <p className="text-gray-400 mt-1 text-sm">
          Operational view — what the bot has been doing and where it&apos;s been blocked.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1">
          <IngestHealthCard data={ingest ?? null} />
        </div>

        <div className="lg:col-span-2 rounded-lg border border-gray-700 bg-gray-800 p-5">
          <h3 className="text-base font-semibold text-white">Scan Cadence</h3>
          <p className="text-xs text-gray-400 mt-1 mb-3">Daily summary (last 7)</p>
          {recentDaily.length === 0 ? (
            <p className="text-sm text-gray-400">No execution data.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-gray-400">
                <tr>
                  <th className="text-left py-1">Date</th>
                  <th className="text-right py-1">Scans</th>
                  <th className="text-right py-1">Opps</th>
                  <th className="text-right py-1">Trades</th>
                  <th className="text-right py-1">Errors</th>
                  <th className="text-right py-1">Avg sec</th>
                </tr>
              </thead>
              <tbody>
                {recentDaily.map((d) => {
                  const noScans = d.total_scans === 0;
                  return (
                    <tr key={d.date_et} className="border-t border-gray-700/50">
                      <td className="py-1.5 text-gray-300">{d.date_et}</td>
                      <td className={cls('py-1.5 text-right', noScans ? 'text-yellow-400' : 'text-gray-200')}>
                        {fmtNumber(d.total_scans)}
                      </td>
                      <td className="py-1.5 text-right text-gray-200">{fmtNumber(d.total_opportunities)}</td>
                      <td className="py-1.5 text-right text-gray-200">{fmtNumber(d.total_executions)}</td>
                      <td className={cls(
                        'py-1.5 text-right',
                        (d.total_errors ?? 0) > 0 ? 'text-red-400' : 'text-gray-200'
                      )}>
                        {fmtNumber(d.total_errors)}
                      </td>
                      <td className="py-1.5 text-right text-gray-200">
                        {d.avg_scan_duration_sec?.toFixed(1) ?? '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <GateHitsHeatmap rows={filtering ?? []} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
          <h3 className="text-base font-semibold text-white">Error Frequency (7d)</h3>
          {errorByType.length === 0 ? (
            <p className="text-sm text-gray-400 mt-2">No errors in the last 7 days.</p>
          ) : (
            <table className="w-full mt-3 text-sm">
              <tbody>
                {errorByType.map(([type, count]) => (
                  <tr key={type} className="border-t border-gray-700/50 first:border-t-0">
                    <td className="py-1.5 text-gray-300 font-mono text-xs">{type}</td>
                    <td className="py-1.5 text-right text-gray-200">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
          <h3 className="text-base font-semibold text-white">Recent Errors</h3>
          {(errors ?? []).length === 0 ? (
            <p className="text-sm text-gray-400 mt-2">No recent errors.</p>
          ) : (
            <ul className="mt-3 space-y-2 max-h-64 overflow-y-auto">
              {(errors ?? []).slice(0, 20).map((e, i) => (
                <li key={`${e.timestamp}-${i}`} className="text-xs">
                  <div className="flex items-baseline justify-between">
                    <span className="font-mono text-gray-300">{e.error_type || e.event_type}</span>
                    <span className="text-gray-500">{fmtDateTime(e.timestamp)}</span>
                  </div>
                  {e.error_message && (
                    <div className="text-gray-400 mt-0.5 truncate" title={e.error_message}>
                      {e.error_message}
                    </div>
                  )}
                  {e.symbol && (
                    <div className="text-gray-500 mt-0.5">
                      {e.symbol} · {e.component ?? ''}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
