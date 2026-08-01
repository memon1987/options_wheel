import { useState } from 'react';
import { useApi } from '../../hooks/useApi';
import type {
  IngestHealth,
  FilteringStat,
  ErrorEvent,
  DailySummary,
  BotAnomaly,
  UncoveredSymbols,
} from '../../types/v2';
import IngestHealthCard from '../../components/v2/IngestHealthCard';
import GateHitsHeatmap from '../../components/v2/GateHitsHeatmap';
import DecisionFunnel from '../../components/v2/DecisionFunnel';
import AnomalyFlags from '../../components/v2/AnomalyFlags';
import UncoveredPositionsCard from '../../components/v2/DrawdownPauseCard';
import { fmtDateTime, fmtNumber, fmtPercent, cls } from '../../utils/format';

export default function BotHealth() {
  const WINDOWS = [
    { label: '1d', days: 1 },
    { label: '7d', days: 7 },
    { label: '30d', days: 30 },
  ] as const;
  const [funnelWindow, setFunnelWindow] = useState<typeof WINDOWS[number]>(WINDOWS[1]);

  const { data: ingest } = useApi<IngestHealth>('/api/v2/bot-health/ingest', { refreshInterval: 60_000 });
  const { data: filtering } = useApi<FilteringStat[]>(`/api/history/filtering?days=${funnelWindow.days}`);
  // Skip the baseline fetch when the selected window IS 30d — it would be a
  // byte-identical query (review E5).
  const { data: filteringBaseline } = useApi<FilteringStat[]>(
    funnelWindow.days === 30 ? null : '/api/history/filtering?days=30');
  const baseline = funnelWindow.days === 30 ? filtering : filteringBaseline;
  const { data: errors } = useApi<ErrorEvent[]>('/api/history/errors?days=7');
  const { data: daily } = useApi<DailySummary[]>('/api/history/daily-summary?days=30');
  const { data: anomalies } = useApi<BotAnomaly[]>('/api/v2/bot-health/anomalies', { refreshInterval: 300_000 });
  const { data: uncovered } = useApi<UncoveredSymbols>('/api/v2/bot-health/drawdown-pauses', { refreshInterval: 300_000 });

  // Explicit client-side ordering — never assume API order (FC-031).
  const dailySorted = [...(daily ?? [])].sort((a, b) => (b.date_et ?? '').localeCompare(a.date_et ?? ''));
  const recentDaily = dailySorted.slice(0, 7);

  // Run reliability: share of days (with any scans scheduled) that completed
  // without errors, over the 30d window.
  const activeDays = dailySorted.filter((d) => (d.total_scans ?? 0) > 0);
  const cleanDays = activeDays.filter((d) => (d.total_errors ?? 0) === 0);
  const reliability = activeDays.length > 0 ? cleanDays.length / activeDays.length : null;

  const errorsSorted = [...(errors ?? [])].sort((a, b) => (b.timestamp ?? '').localeCompare(a.timestamp ?? ''));
  const errorByType: Array<[string, number]> = (() => {
    const counts = new Map<string, number>();
    for (const e of errorsSorted) {
      const k = e.error_type || e.event_type || 'unknown';
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10);
  })();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Bot Health</h1>
        <p className="text-gray-400 mt-1 text-sm">
          Is the algo doing what it should — and if not, where is it blocked?
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AnomalyFlags data={anomalies ?? null} />
        <UncoveredPositionsCard data={uncovered ?? null} />
      </div>

      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-sm text-gray-300">
          <span title="Days with ≥1 scan and zero errors / days with ≥1 scan, trailing 30 days.">
            Run reliability (30d):{' '}
            <span className={cls('font-semibold', reliability !== null && reliability < 0.95 ? 'text-yellow-300' : 'text-green-300')}>
              {reliability !== null ? fmtPercent(reliability, 0) : '—'}
            </span>
            {activeDays.length > 0 && <span className="text-xs text-gray-500"> ({cleanDays.length}/{activeDays.length} clean days)</span>}
          </span>
        </div>
        <div className="inline-flex rounded-md border border-gray-700 overflow-hidden">
          {WINDOWS.map((w) => (
            <button
              key={w.label}
              onClick={() => setFunnelWindow(w)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                funnelWindow.label === w.label
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <DecisionFunnel
        rows={filtering ?? []}
        baselineRows={baseline ?? []}
        windowLabel={funnelWindow.label}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1">
          <IngestHealthCard data={ingest ?? null} />
        </div>

        <div className="lg:col-span-2 rounded-lg border border-gray-700 bg-gray-800 p-5">
          <h3 className="text-base font-semibold text-white">Scan Cadence</h3>
          <p className="text-xs text-gray-400 mt-1 mb-3">Daily summary (last 7 active days)</p>
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
          {errorsSorted.length === 0 ? (
            <p className="text-sm text-gray-400 mt-2">No recent errors.</p>
          ) : (
            <ul className="mt-3 space-y-2 max-h-64 overflow-y-auto">
              {errorsSorted.slice(0, 20).map((e, i) => (
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
