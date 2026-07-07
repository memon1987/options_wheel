import { useState } from 'react';
import { useApi } from '../../hooks/useApi';
import type {
  ScorecardRow,
  AccountData,
  AccountBaseline,
  LivePosition,
  EquityCurvePoint,
  MonthlyCashflow,
  PortfolioReturns,
  Reconciliation,
  CycleStats,
  OptionTradeStats,
} from '../../types/v2';
import KPICards, { buildHeadlineKpis } from '../../components/v2/KPICards';
import EquityCurve from '../../components/v2/EquityCurve';
import MonthlyPremiumBars from '../../components/v2/MonthlyPremiumBars';
import SymbolScorecard from '../../components/v2/SymbolScorecard';
import ActionPanel from '../../components/v2/ActionPanel';
import ReconciliationBanner from '../../components/v2/ReconciliationBanner';
import CycleStatsCard from '../../components/v2/CycleStatsCard';
import OptionStatsCard from '../../components/v2/OptionStatsCard';
import { fmtCurrency, fmtPercent, parseOcc } from '../../utils/format';

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
  const { data: equityCurve } = useApi<EquityCurvePoint[]>(`/api/v2/portfolio/equity-curve?days=${days}`);
  const { data: monthly } = useApi<MonthlyCashflow[]>('/api/v2/monthly-cashflow?months=24');
  const { data: baseline } = useApi<AccountBaseline>('/api/metrics/account-baseline');
  const { data: returns } = useApi<PortfolioReturns>('/api/v2/portfolio/returns');
  const { data: reconciliation } = useApi<Reconciliation>('/api/v2/reconciliation', { refreshInterval: 120_000 });
  const { data: cycleStats } = useApi<CycleStats>(`/api/v2/cycle-stats?days=${days}`);
  const { data: putStats } = useApi<OptionTradeStats>(`/api/v2/put-stats?days=${days}`);
  const { data: callStats } = useApi<OptionTradeStats>(`/api/v2/call-stats?days=${days}`);

  const nlv = account?.portfolio_value ?? null;
  const startingCapital = baseline?.starting_capital ?? null;
  const realizedCash = reconciliation?.realized_cash_pnl ?? null;
  // Open value split comes from the reconciliation payload's OWN nlv so the
  // realized/open components stay self-consistent — mixing the 60s-polled
  // account NLV with the 120s-polled ledger sums made the split incoherent
  // for up to two minutes after a fill (review AL4).
  const openValue =
    reconciliation?.nlv != null && realizedCash !== null
      ? reconciliation.nlv - reconciliation.deposits - realizedCash
      : null;

  // Stress + deployment stats from live positions. Underlying prices come
  // from the scorecard (latest daily-bar close) — stamped below.
  const priceBy: Record<string, number> = {};
  for (const r of scorecard ?? []) {
    if (r.price_now !== null) priceBy[r.symbol] = r.price_now;
  }
  const priceDate = (scorecard ?? []).find((r) => r.price_now_date)?.price_now_date ?? null;

  let stress = 0;
  let countedPuts = 0;
  let putCollateral = 0;
  let stockMV = 0;
  const exposureBySymbol: Record<string, number> = {};
  for (const p of positions ?? []) {
    const occ = parseOcc(p.symbol ?? '');
    const qty = Math.abs(parseFloat(String(p.qty ?? 0)));
    if (occ.optionType === 'P' && occ.strike !== null) {
      const notional = occ.strike * 100 * qty;
      putCollateral += notional;
      exposureBySymbol[occ.underlying] = (exposureBySymbol[occ.underlying] ?? 0) + notional;
      const cur = priceBy[occ.underlying];
      // Only puts we can actually price count toward the stress figure — an
      // unpriced put must not let the green "all OTM" banner show.
      if (cur !== undefined) {
        countedPuts++;
        if (cur < occ.strike) {
          stress += (cur - occ.strike) * 100 * qty;
        }
      }
    } else if (occ.optionType === null && !/\d/.test(p.symbol ?? '')) {
      const mv = parseFloat(String(p.market_value ?? 0));
      stockMV += mv;
      exposureBySymbol[p.symbol] = (exposureBySymbol[p.symbol] ?? 0) + mv;
    }
  }
  const stressMTM = countedPuts > 0 ? stress : null;
  const notionalIfAssigned = putCollateral + stockMV;
  const deployedPct = nlv !== null && nlv > 0 ? notionalIfAssigned / nlv : null;
  const topExposure = Object.entries(exposureBySymbol).sort((a, b) => b[1] - a[1])[0] ?? null;

  const kpis = buildHeadlineKpis({
    nlv,
    cash: account?.cash ?? null,
    buyingPower: account?.buying_power ?? null,
    startingCapital,
    realizedCashPnl: realizedCash,
    openValue,
    xirr: returns?.xirr ?? null,
    twrCumulative: returns?.twr_cumulative ?? null,
    singleDeposit: returns?.single_deposit ?? true,
    maxDrawdown: returns?.max_drawdown ?? null,
    maxDrawdownDollars: returns?.max_drawdown_dollars ?? null,
    currentDrawdown: returns?.current_drawdown ?? null,
    daysRunning: returns?.days_since_first_deposit ?? null,
    nlvSource: returns?.nlv_source ?? null,
  });

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Overview</h1>
          <p className="text-gray-400 mt-1 text-sm">
            Headline P&amp;L, benchmark comparison, and per-symbol scorecard.
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

      {reconciliation?.status === 'warn' && <ReconciliationBanner data={reconciliation} />}

      <KPICards kpis={kpis} />

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-400 px-1">
        <span title="Put collateral at strike notional + market value of held shares, over NLV. Short-option marks are netted inside NLV (the denominator), not the numerator — the ratio can drift above the broker's buying-power view.">
          Capital deployed:{' '}
          <span className={deployedPct !== null && deployedPct > 1 ? 'text-red-300 font-semibold' : 'text-gray-200'}>
            {deployedPct !== null ? fmtPercent(deployedPct, 0) : '—'}
          </span>
          {deployedPct !== null && deployedPct > 1 && ' ⚠ over-committed'}
        </span>
        <span title="Σ open put strike notionals + held share value — what the account would hold if every put assigned.">
          Notional if assigned: <span className="text-gray-200">{fmtCurrency(notionalIfAssigned)}</span>
        </span>
        {topExposure && nlv !== null && nlv > 0 && (
          <span title="Largest single-symbol exposure (put notional + share value) as % of NLV.">
            Largest exposure: <span className="text-gray-200">{topExposure[0]} {fmtPercent(topExposure[1] / nlv, 0)}</span>
          </span>
        )}
        {priceDate && <span>Underlying prices as of {priceDate} close.</span>}
      </div>

      {stressMTM !== null && stressMTM < 0 && (
        <div className="rounded-lg border border-yellow-700/50 bg-yellow-900/10 px-4 py-3 text-sm text-yellow-200">
          <span className="font-semibold">Stress test:</span>{' '}
          if every open put assigned at the last close, mark-to-market loss = {fmtCurrency(stressMTM)}.{' '}
          <span className="text-xs opacity-75 ml-2">
            Sums (close − strike) × 100 across in-the-money short puts{priceDate ? ` · prices as of ${priceDate}` : ''}.
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
        <EquityCurve data={equityCurve ?? []} />
        <MonthlyPremiumBars data={monthly ?? []} />
      </div>

      <CycleStatsCard data={cycleStats ?? null} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OptionStatsCard data={putStats ?? null} optionType="put" />
        <OptionStatsCard data={callStats ?? null} optionType="call" />
      </div>

      <SymbolScorecard rows={scorecard ?? []} />

      <ActionPanel positions={positions ?? []} scorecard={scorecard ?? []} />

      {reconciliation?.status === 'ok' && <ReconciliationBanner data={reconciliation} />}
    </div>
  );
}
