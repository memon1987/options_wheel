import { fmtCurrency, fmtCurrencyDetail, fmtPercent, pnlColor } from '../../utils/format';

interface KPI {
  label: string;
  value: string;
  sub?: string;
  tone?: 'neutral' | 'pnl';
  rawPnl?: number | null;
  hint?: string;
}

interface Props {
  kpis: KPI[];
}

export default function KPICards({ kpis }: Props) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {kpis.map((k) => (
        <div
          key={k.label}
          className="rounded-lg border border-gray-700 bg-gray-800 p-4"
          title={k.hint}
        >
          <div className="text-xs uppercase tracking-wide text-gray-400">{k.label}</div>
          <div
            className={`text-xl font-semibold mt-1 ${
              k.tone === 'pnl' ? pnlColor(k.rawPnl ?? null) : 'text-white'
            }`}
          >
            {k.value}
          </div>
          {k.sub && <div className="text-xs text-gray-400 mt-1">{k.sub}</div>}
        </div>
      ))}
    </div>
  );
}

// Helpers used by Overview to build the KPI list from raw API data.
// FC-031: Total P&L keeps the tile (the bank-statement number); XIRR/TWR are
// sub-lines with the single-deposit caveat spelled out; max drawdown replaces
// the retired CAGR tile; Days Running counts from the first DEPOSIT.
export const buildHeadlineKpis = (args: {
  nlv: number | null;
  cash: number | null;
  buyingPower: number | null;
  startingCapital: number | null;    // sum of net deposits (JNLC) since account inception
  realizedCashPnl: number | null;    // reconciliation: closed net cash P&L
  openValue: number | null;          // reconciliation: open premium + live MV − share cash… (see Overview)
  xirr: number | null;
  twrCumulative: number | null;
  singleDeposit: boolean;
  maxDrawdown: number | null;        // fraction ≤ 0
  maxDrawdownDollars: number | null;
  currentDrawdown: number | null;
  daysRunning: number | null;        // since first deposit
  nlvSource: string | null;
}): KPI[] => {
  const {
    nlv, cash, buyingPower, startingCapital,
    realizedCashPnl, openValue,
    xirr, twrCumulative, singleDeposit,
    maxDrawdown, maxDrawdownDollars, currentDrawdown,
    daysRunning, nlvSource,
  } = args;

  // Total P&L: NLV − net deposits. The bank-statement number — what the
  // account actually grew by, marked to market by the broker.
  const totalPnl =
    nlv !== null && startingCapital !== null ? nlv - startingCapital : null;
  const totalPnlPct =
    nlv !== null && startingCapital !== null && startingCapital > 0
      ? (nlv - startingCapital) / startingCapital
      : null;

  const xirrLabel = singleDeposit ? 'annualized (single deposit)' : 'XIRR (money-weighted)';

  return [
    {
      label: 'Net Liquidation Value',
      value: fmtCurrencyDetail(nlv),
      sub: cash !== null ? `Cash ${fmtCurrency(cash)} · BP ${fmtCurrency(buyingPower)}` : undefined,
      hint: nlvSource ? `NLV source: ${nlvSource}` : undefined,
    },
    {
      label: 'Total P&L',
      value: fmtCurrencyDetail(totalPnl),
      sub: (() => {
        const parts: string[] = [];
        if (totalPnlPct !== null) parts.push(`${fmtPercent(totalPnlPct)} on deposits`);
        if (realizedCashPnl !== null && openValue !== null) {
          parts.push(`${fmtCurrency(realizedCashPnl)} realized cash · ${fmtCurrency(openValue)} open value`);
        }
        return parts.join(' · ') || undefined;
      })(),
      tone: 'pnl',
      rawPnl: totalPnl,
      hint: 'NLV minus net deposits since inception — the bank-statement number. The split shows closed net-cash P&L (options + share cash) vs the value currently sitting in open positions. Convention: share acquisition cost is expensed in cash P&L, so open value is full market value, never (price − basis) × shares.',
    },
    {
      label: 'Max Drawdown',
      value: maxDrawdown !== null ? fmtPercent(maxDrawdown) : '—',
      sub: (() => {
        const parts: string[] = [];
        if (maxDrawdownDollars !== null) parts.push(`${fmtCurrency(maxDrawdownDollars)}`);
        if (currentDrawdown !== null) parts.push(`now ${fmtPercent(currentDrawdown)} from peak`);
        return parts.join(' · ') || undefined;
      })(),
      tone: 'pnl',
      rawPnl: maxDrawdown,
      hint: 'Largest peak-to-trough decline of the flow-adjusted equity curve (a deposit can neither mask nor create a drawdown). Close-to-close daily data — intraday drawdowns can be deeper.',
    },
    {
      label: 'Return',
      value: xirr !== null ? fmtPercent(xirr) : '—',
      sub: (() => {
        const parts: string[] = [xirrLabel];
        if (twrCumulative !== null) parts.push(`TWR ${fmtPercent(twrCumulative)} cumulative`);
        if (daysRunning !== null) parts.push(`${daysRunning}d since first deposit`);
        return parts.join(' · ');
      })(),
      hint: singleDeposit
        ? 'With a single deposit ever, XIRR is algebraically the annualized return since inception — nothing is money-weighted until a second cash flow exists. Extrapolated from a short track record; treat with the same skepticism as any annualized figure under 12 months.'
        : 'XIRR: the money-weighted annual rate your actual dollars earned, including deposit timing. TWR: time-weighted return, the number to compare against benchmarks.',
    },
  ];
};
