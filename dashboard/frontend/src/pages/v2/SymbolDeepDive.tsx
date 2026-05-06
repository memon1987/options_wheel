import { useParams, Link, useNavigate } from 'react-router-dom';
import { useApi } from '../../hooks/useApi';
import type {
  AcbTimelineRow,
  DecisionQualityRow,
  VsBuyAndHold,
  ScorecardRow,
  PhaseTiming,
} from '../../types/v2';
import AcbWalkChart from '../../components/v2/AcbWalkChart';
import DecisionQuality from '../../components/v2/DecisionQuality';
import CycleTable from '../../components/v2/CycleTable';
import TradeLog from '../../components/v2/TradeLog';
import VsBuyAndHoldCard from '../../components/v2/VsBuyAndHoldCard';
import PhaseTimingBar from '../../components/v2/PhaseTimingBar';
import SymbolUniverseTable from '../../components/v2/SymbolUniverseTable';
import { fmtCurrency, fmtCurrencyDetail, fmtNumber, pnlColor } from '../../utils/format';

interface CycleRow {
  timestamp: string;
  symbol: string;
  put_date: string | null;
  put_strike: number | null;
  put_premium: number | null;
  assignment_date: string | null;
  call_date: string | null;
  call_strike: number | null;
  call_premium: number | null;
  calls_in_cycle: number | null;
  cycle_call_gross_premium: number | null;
  cycle_call_net_realized: number | null;
  capital_gain: number | null;
  total_premium: number | null;
  total_return: number | null;
  duration_days: number | null;
  shares: number | null;
}

export default function SymbolDeepDive() {
  const { underlying } = useParams<{ underlying?: string }>();
  const navigate = useNavigate();
  const symbol = (underlying ?? '').toUpperCase();

  const skip = !symbol;

  const { data: acb } = useApi<AcbTimelineRow[]>(skip ? null : `/api/v2/symbol/${symbol}/acb-timeline?days=730`);
  const { data: decision } = useApi<DecisionQualityRow[]>(skip ? null : `/api/v2/symbol/${symbol}/decision-quality?days=365`);
  const { data: vsBh } = useApi<VsBuyAndHold>(skip ? null : `/api/v2/symbol/${symbol}/vs-buy-and-hold`);
  const { data: cycles } = useApi<CycleRow[]>(skip ? null : `/api/v2/symbol/${symbol}/cycles?days=730`);
  const { data: phase } = useApi<PhaseTiming>(skip ? null : `/api/v2/symbol/${symbol}/phase-timing?days=730`);
  const { data: scorecard } = useApi<ScorecardRow[]>('/api/v2/scorecard?days=365');
  const { data: account } = useApi<{ paper_trading?: boolean }>('/api/live/account', { refreshInterval: 60_000 });
  const isPaperTrading = account?.paper_trading ?? true;

  // Symbol-summary header data is the matching scorecard row.
  const summary = scorecard?.find((r) => r.symbol === symbol) ?? null;

  // The v2/cycles endpoint already filters by underlying — use as-is.
  const symbolCycles = cycles ?? [];

  // Symbol picker — uses scorecard for the canonical universe.
  const universe = (scorecard ?? []).map((r) => r.symbol).sort();

  if (skip) {
    return (
      <div className="space-y-6">
        <header>
          <h1 className="text-2xl font-bold text-white">By Symbol</h1>
          <p className="text-gray-400 mt-1 text-sm">
            Pick a symbol to drill down. Sort to find the highest-P&L or most-active names.
          </p>
        </header>
        <SymbolUniverseTable rows={scorecard ?? []} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white font-mono">{symbol}</h1>
          {summary && (
            <p className="text-gray-400 mt-1 text-sm">
              {summary.cycles_completed} cycles · {summary.trade_count} trades ·
              {' '}premium {fmtCurrency(summary.total_premium)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/overview"
            className="text-sm px-3 py-1.5 rounded border border-gray-600 text-gray-300 hover:bg-gray-700"
          >
            ← Overview
          </Link>
          <select
            className="text-sm px-2 py-1.5 rounded border border-gray-600 bg-gray-800 text-gray-200"
            value={symbol}
            onChange={(e) => navigate(`/symbol/${e.target.value}`)}
          >
            {universe.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        </div>
      </header>

      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-3">
            <div className="text-xs uppercase tracking-wide text-gray-400">Total Premium</div>
            <div className="text-lg font-semibold text-white mt-1">{fmtCurrencyDetail(summary.total_premium)}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              put {fmtCurrency(summary.put_premium)} · call {fmtCurrency(summary.call_premium)}
            </div>
          </div>
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-3">
            <div className="text-xs uppercase tracking-wide text-gray-400">Realized P&amp;L</div>
            <div className={`text-lg font-semibold mt-1 ${pnlColor(summary.realized_pnl)}`}>
              {fmtCurrencyDetail(summary.realized_pnl)}
            </div>
          </div>
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-3">
            <div className="text-xs uppercase tracking-wide text-gray-400">Cycles Completed</div>
            <div className="text-lg font-semibold text-white mt-1">{fmtNumber(summary.cycles_completed)}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              avg {summary.avg_cycle_days !== null ? `${Math.round(summary.avg_cycle_days)}d` : '—'} per cycle
            </div>
          </div>
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-3">
            <div className="text-xs uppercase tracking-wide text-gray-400">Outcomes</div>
            <div className="text-sm text-gray-200 mt-1">
              {fmtNumber(summary.put_assignment_count)} assigned ·{' '}
              {fmtNumber(summary.called_away_count)} called
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              {fmtNumber(summary.early_close_count)} early closes ·{' '}
              {fmtNumber(summary.expiration_count)} expired
            </div>
          </div>
        </div>
      )}

      <AcbWalkChart data={acb ?? []} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DecisionQuality rows={decision ?? []} />
        <VsBuyAndHoldCard data={vsBh ?? null} />
      </div>

      <PhaseTimingBar data={phase ?? null} />

      <CycleTable rows={symbolCycles} />

      <TradeLog events={acb ?? []} paperTrading={isPaperTrading} />
    </div>
  );
}
