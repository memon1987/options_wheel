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
export const buildHeadlineKpis = (args: {
  nlv: number | null;
  cash: number | null;
  buyingPower: number | null;
  startingCapital: number | null;    // sum of net deposits (JNLC) since account inception
  grossPremium: number | null;       // sum of every option premium collected
  netRealizedPnl: number | null;     // gross − roll buybacks
  boughtBack: number | null;         // gross − net (paid out to roll)
  daysRunning: number | null;
}): KPI[] => {
  const {
    nlv,
    cash,
    buyingPower,
    startingCapital,
    grossPremium,
    netRealizedPnl,
    boughtBack,
    daysRunning,
  } = args;

  // Bulletproof total return: NLV − sum of net deposits since inception.
  // This is the bank-statement number — what your account actually grew by —
  // and avoids the accounting noise of trying to reconcile realized P&L with
  // share-side cash flow (OPTRD events, capital gains across overlapping lots).
  const totalReturn =
    nlv !== null && startingCapital !== null
      ? nlv - startingCapital
      : null;
  const totalReturnPct =
    nlv !== null && startingCapital !== null && startingCapital > 0
      ? (nlv - startingCapital) / startingCapital
      : null;

  return [
    {
      label: 'Net Liquidation Value',
      value: fmtCurrencyDetail(nlv),
      sub: cash !== null ? `Cash ${fmtCurrency(cash)} · BP ${fmtCurrency(buyingPower)}` : undefined,
    },
    {
      label: 'Total Return',
      value: fmtCurrencyDetail(totalReturn),
      sub:
        startingCapital !== null
          ? `${fmtPercent(totalReturnPct ?? 0)} since inception · started ${fmtCurrency(startingCapital)}`
          : undefined,
      tone: 'pnl',
      rawPnl: totalReturn,
      hint: 'Current NLV minus net deposits since inception. The bank-statement number — what your account actually grew by, free of accounting noise from realized vs unrealized vs share-side cash flow.',
    },
    {
      label: 'Net Realized P&L',
      value: fmtCurrencyDetail(netRealizedPnl),
      sub:
        boughtBack !== null && boughtBack > 0 && grossPremium !== null
          ? `Gross ${fmtCurrency(grossPremium)} − ${fmtCurrency(boughtBack)} bought back`
          : 'Premium kept across all closed positions',
      tone: 'pnl',
      rawPnl: netRealizedPnl,
      hint: 'Sum of realized P&L across every closed option. Equals gross premium kept on assigned/expired/called-away positions, plus (premium − buyback) for early-closed positions. This is "actual cash earned from options."',
    },
    {
      label: 'Days Running',
      value: daysRunning !== null ? `${daysRunning}d` : '—',
      sub: daysRunning !== null && daysRunning > 0 ? `since first trade` : undefined,
      hint: 'Days since the first trade in this account.',
    },
  ];
};
