import { useState } from 'react';
import { useApi } from '../../hooks/useApi';
import type {
  ScorecardRow,
  AccountData,
  AccountBaseline,
  LivePosition,
  PortfolioHistoryPoint,
  PremiumByDayPoint,
  MetricsSummary,
} from '../../types/v2';
import KPICards, { buildHeadlineKpis } from '../../components/v2/KPICards';
import EquityCurve from '../../components/v2/EquityCurve';
import MonthlyPremiumBars from '../../components/v2/MonthlyPremiumBars';
import SymbolScorecard from '../../components/v2/SymbolScorecard';
import ActionPanel from '../../components/v2/ActionPanel';
import { fmtCurrency, fmtRelativeAge } from '../../utils/format';

export default function Overview() {
  const RANGES = [
    { label: '30d', days: 30 },
    { label: '90d', days: 90 },
    { label: '1Y',  days: 365 },
    { label: 'All', days: 3650 },
  ] as const;
  const [range, setRange] = useState<typeof RANGES[number]>(RANGES[2]);
  const days = range.days;

  const { data: scorecard, loading: scorecardLoading } = useApi<ScorecardRow[]>(`/api/v2/scorecard?days=${days}`);
  const { data: account } = useApi<AccountData>('/api/live/account', { refreshInterval: 60_000 });
  const { data: positions } = useApi<LivePosition[]>('/api/live/positions', { refreshInterval: 30_000 });
  const { data: equity } = useApi<PortfolioHistoryPoint[]>(`/api/history/portfolio-history?days=${Math.min(days, 365)}`);
  const { data: premium } = useApi<PremiumByDayPoint[]>(`/api/metrics/premium-by-day?days=${days}`);
  const { data: summary } = useApi<MetricsSummary>(`/api/metrics/summary?days=${days}`);
  const { data: baseline } = useApi<AccountBaseline>('/api/metrics/account-baseline');

  // Derive headline numbers
  const grossPremium = summary?.total_premium ?? null;
  const netRealizedPnl = summary?.net_realized_pnl ?? null;
  const boughtBack = summary?.bought_back ?? null;
  const cash = account?.cash ?? null;
  const buyingPower = account?.buying_power ?? null;
  const nlv = account?.portfolio_value ?? null;

  // (Removed: unrealized-on-shares calc — Total Return now uses NLV − deposits,
  //  which already includes mark-to-market on every open position.)

  // Days running: from first trade time across the scorecard.
  const daysRunning = (() => {
    if (!scorecard || scorecard.length === 0) return null;
    let earliest: number | null = null;
    for (const r of scorecard) {
      if (!r.first_trade_time) continue;
      const t = new Date(r.first_trade_time).getTime();
      if (earliest === null || t < earliest) earliest = t;
    }
    if (earliest === null) return null;
    return Math.floor((Date.now() - earliest) / 86_400_000);
  })();

  // Stress: if every open short PUT assigned at the current underlying price,
  // immediate mark-to-market = (current_price − strike) × 100 × abs(qty).
  // Negative = unrealized loss, since you'd be buying shares above market.
  // Underlying prices come from the scorecard (price_now, daily-bar latest).
  const stressMTM = (() => {
    if (!positions || !scorecard) return null;
    const priceBy: Record<string, number> = {};
    for (const r of scorecard) {
      if (r.price_now !== null) priceBy[r.symbol] = r.price_now;
    }
    let stress = 0;
    let countedPuts = 0;
    for (const p of positions) {
      const symbol = p.symbol ?? '';
      const m = symbol.match(/^([A-Z]{1,6})\d{6}([CP])(\d{8})$/);
      if (!m) continue;
      const [, underlying, type, strikeStr] = m;
      if (type !== 'P') continue; // calls don't carry assignment-cash risk on the user's side
      const strike = parseInt(strikeStr, 10) / 1000;
      const qty = parseFloat(String(p.qty ?? 0));
      const cur = priceBy[underlying];
      if (cur === undefined) continue;
      // If the put is OTM (cur >= strike), assignment is unlikely; contribute 0.
      // If ITM (cur < strike), assigned shares are immediately worth less than paid.
      if (cur < strike) {
        stress += (cur - strike) * 100 * Math.abs(qty);
      }
      countedPuts++;
    }
    return countedPuts > 0 ? stress : null;
  })();

  const kpis = buildHeadlineKpis({
    nlv,
    cash,
    buyingPower,
    startingCapital: baseline?.starting_capital ?? null,
    grossPremium,
    netRealizedPnl,
    boughtBack,
    daysRunning,
  });

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Overview</h1>
          <p className="text-gray-400 mt-1 text-sm">
            Headline P&amp;L, portfolio equity, and per-symbol scorecard.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {scorecardLoading && (
            <span className="text-xs text-gray-400">Loading…</span>
          )}
          <div className="inline-flex rounded-md border border-gray-700 overflow-hidden">
            {RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setRange(r)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  range.label === r.label
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <KPICards kpis={kpis} />

      {stressMTM !== null && stressMTM < 0 && (
        <div className="rounded-lg border border-yellow-700/50 bg-yellow-900/10 px-4 py-3 text-sm text-yellow-200">
          <span className="font-semibold">Stress test:</span>{' '}
          if every open put assigned at current underlying price, mark-to-market loss = {fmtCurrency(stressMTM)}.{' '}
          <span className="text-xs opacity-75 ml-2">
            Sums (current_price − strike) × 100 across in-the-money short puts.
          </span>
        </div>
      )}
      {stressMTM === 0 && (
        <div className="rounded-lg border border-green-700/40 bg-green-900/10 px-4 py-3 text-sm text-green-200">
          <span className="font-semibold">Stress test:</span>{' '}
          all open puts are out-of-the-money; no immediate MTM loss if all assigned today.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EquityCurve data={equity ?? []} />
        <MonthlyPremiumBars data={premium ?? []} />
      </div>

      <SymbolScorecard rows={scorecard ?? []} />

      <ActionPanel positions={positions ?? []} scorecard={scorecard ?? []} />

      <div className="text-xs text-gray-500 text-center pt-2">
        Account data refreshed {fmtRelativeAge(new Date().toISOString())} · v2 preview · FC-018
      </div>
    </div>
  );
}
