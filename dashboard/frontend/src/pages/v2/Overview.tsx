import { useApi } from '../../hooks/useApi';
import type {
  ScorecardRow,
  AccountData,
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
  const { data: scorecard, loading: scorecardLoading } = useApi<ScorecardRow[]>('/api/v2/scorecard?days=365');
  const { data: account } = useApi<AccountData>('/api/live/account', { refreshInterval: 60_000 });
  const { data: positions } = useApi<LivePosition[]>('/api/live/positions', { refreshInterval: 30_000 });
  const { data: equity } = useApi<PortfolioHistoryPoint[]>('/api/history/portfolio-history?days=180');
  const { data: premium } = useApi<PremiumByDayPoint[]>('/api/metrics/premium-by-day?days=365');
  const { data: summary } = useApi<MetricsSummary>('/api/metrics/summary?days=365');

  // Derive headline numbers
  const grossPremium = summary?.total_premium ?? null;
  const netRealizedPnl = summary?.net_realized_pnl ?? null;
  const boughtBack = summary?.bought_back ?? null;
  const cash = account?.cash ?? null;
  const buyingPower = account?.buying_power ?? null;
  const nlv = account?.portfolio_value ?? null;

  // Unrealized P&L on currently-assigned shares: sum of unrealized_pl on
  // positions where asset_class is stock (i.e., side != short option).
  const unrealizedOnShares = (() => {
    if (!positions) return null;
    let sum = 0;
    let counted = 0;
    for (const p of positions) {
      const symbol = p.symbol ?? '';
      // Crude: option symbols match the OCC pattern (>=15 chars, has digits).
      const isOption = symbol.length >= 15 && /\d/.test(symbol);
      if (isOption) continue;
      sum += parseFloat(String(p.unrealized_pl ?? 0));
      counted++;
    }
    return counted > 0 ? sum : 0;
  })();

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

  // Stress: if every short put assigned at strike, mark-to-market loss = sum
  // of (strike - current_price) × 100 × qty for each short put.
  const stressMTM = (() => {
    if (!positions) return null;
    let stress = 0;
    for (const p of positions) {
      const symbol = p.symbol ?? '';
      const isOption = symbol.length >= 15 && /\d/.test(symbol);
      if (!isOption) continue;
      // Just sum the absolute unrealized loss to avoid pulling current
      // option chain. Underestimates true stress; flagged in the tooltip.
      const upl = parseFloat(String(p.unrealized_pl ?? 0));
      if (upl < 0) stress += upl;
    }
    return stress;
  })();

  const kpis = buildHeadlineKpis({
    nlv,
    cash,
    buyingPower,
    grossPremium,
    netRealizedPnl,
    boughtBack,
    unrealizedOnShares,
    daysRunning,
  });

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Overview</h1>
          <p className="text-gray-400 mt-1 text-sm">
            Headline P&amp;L, portfolio equity, and per-symbol scorecard.
          </p>
        </div>
        {scorecardLoading && (
          <span className="text-xs text-gray-400">Loading…</span>
        )}
      </header>

      <KPICards kpis={kpis} />

      {stressMTM !== null && stressMTM < 0 && (
        <div className="rounded-lg border border-yellow-700/50 bg-yellow-900/10 px-4 py-3 text-sm text-yellow-200">
          <span className="font-semibold">Open option exposure:</span>{' '}
          {fmtCurrency(stressMTM)} unrealized loss across open option positions.{' '}
          <span className="text-xs opacity-75 ml-2">
            (Approximate — does not include re-pricing assigned shares to strike.)
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EquityCurve data={equity ?? []} />
        <MonthlyPremiumBars data={premium ?? []} />
      </div>

      <SymbolScorecard rows={scorecard ?? []} />

      <ActionPanel positions={positions ?? []} />

      <div className="text-xs text-gray-500 text-center pt-2">
        Account data refreshed {fmtRelativeAge(new Date().toISOString())} · v2 preview · FC-018
      </div>
    </div>
  );
}
