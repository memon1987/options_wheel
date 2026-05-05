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
  totalPremium: number | null;
  unrealizedOnShares: number | null;
  netPnl: number | null;
  daysRunning: number | null;
}): KPI[] => {
  const {
    nlv,
    cash,
    buyingPower,
    totalPremium,
    unrealizedOnShares,
    netPnl,
    daysRunning,
  } = args;

  return [
    {
      label: 'Net Liquidation Value',
      value: fmtCurrencyDetail(nlv),
      sub: cash !== null ? `Cash ${fmtCurrency(cash)} · BP ${fmtCurrency(buyingPower)}` : undefined,
    },
    {
      label: 'Net P&L',
      value: fmtCurrencyDetail(netPnl),
      sub: 'Premium − unrealized on shares',
      tone: 'pnl',
      rawPnl: netPnl,
      hint: 'Total premium collected minus unrealized P&L on currently-assigned shares. The "honest" P&L number.',
    },
    {
      label: 'Total Premium',
      value: fmtCurrencyDetail(totalPremium),
      sub:
        unrealizedOnShares !== null && unrealizedOnShares !== 0
          ? `Unreal on shares ${fmtCurrency(unrealizedOnShares)}`
          : 'No assigned shares',
      hint: 'Cumulative premium collected. Always read alongside unrealized P&L on assigned shares.',
    },
    {
      label: 'Days Running',
      value: daysRunning !== null ? `${daysRunning}d` : '—',
      sub: daysRunning !== null && daysRunning > 0 ? `~${fmtPercent(365 / daysRunning - 1)} extrapolation hint` : undefined,
      hint: 'Days since the first trade in this account.',
    },
  ];
};
