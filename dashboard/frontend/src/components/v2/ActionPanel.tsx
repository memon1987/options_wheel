import type { LivePosition, ScorecardRow } from '../../types/v2';
import { fmtCurrency, fmtPercent, parseOcc, cls } from '../../utils/format';

interface Props {
  positions: LivePosition[];
  scorecard?: ScorecardRow[]; // for current_price lookup per underlying
}

interface Annotated {
  pos: LivePosition;
  underlying: string;
  optionType: 'P' | 'C' | null;
  strike: number | null;
  expiration: string | null;
  daysToExpiry: number | null;
  strikeCushion: number | null;      // signed OTM cushion: positive = OTM, negative = ITM
  captureRatio: number | null;       // % of max profit currently captured (options only)
  basisPerShare: number | null;      // stock rows: avg cost per share
  pnlPct: number | null;             // unrealized / entry cost-or-credit
  badges: string[];
}

const annotate = (positions: LivePosition[], scorecard: ScorecardRow[] | undefined): Annotated[] => {
  const today = new Date();
  const priceBySymbol = new Map<string, number>();
  for (const r of scorecard ?? []) {
    if (r.price_now !== null) priceBySymbol.set(r.symbol, r.price_now);
  }

  return positions.map((pos) => {
    const occ = parseOcc(pos.symbol);
    let dte: number | null = null;
    if (occ.expiration) {
      // Options stop trading 4pm ET. 21:00Z covers EST exactly and overshoots
      // EDT by one hour — never undercounts DTE (16:00Z was noon ET and did).
      const exp = new Date(occ.expiration + 'T21:00:00Z');
      dte = Math.max(0, Math.ceil((exp.getTime() - today.getTime()) / 86_400_000));
    }

    const underlyingPrice = priceBySymbol.get(occ.underlying) ?? null;
    const strike = occ.strike;
    // Signed cushion to the strike: positive = still OTM by that fraction,
    // negative = ITM. Direction depends on option type.
    const strikeCushion =
      strike !== null && underlyingPrice !== null && underlyingPrice > 0 && occ.optionType !== null
        ? occ.optionType === 'P'
          ? (underlyingPrice - strike) / underlyingPrice
          : (strike - underlyingPrice) / underlyingPrice
        : null;

    // % of max profit captured for a SHORT option:
    // max profit = original premium received. current "remaining" = current
    // option market value (cost to close). captured = (premium − cost_to_close) / premium.
    // We have cost_basis (negative when short) representing initial credit, and
    // market_value (negative) representing current cost-to-close.
    // Only meaningful for option rows — stock rows show basis instead.
    const credit = Math.abs(parseFloat(String(pos.cost_basis ?? 0)));
    const cost = Math.abs(parseFloat(String(pos.market_value ?? 0)));
    const captureRatio = occ.optionType !== null && credit > 0 ? (credit - cost) / credit : null;

    const qty = Math.abs(parseFloat(String(pos.qty ?? 0)));
    const basisPerShare = occ.optionType === null && qty > 0 ? credit / qty : null;

    // Unrealized % against entry credit (short options) / entry cost (stock),
    // NOT current market value — a short option decayed to near zero would
    // otherwise show absurd percentages.
    const upl = parseFloat(String(pos.unrealized_pl ?? 0));
    const pnlPct = credit > 0 ? upl / credit : null;

    const badges: string[] = [];
    if (dte !== null && dte <= 7) badges.push('≤7 DTE');
    if (strikeCushion !== null && strikeCushion < 0) badges.push('ITM');
    else if (strikeCushion !== null && strikeCushion < 0.05) badges.push('Near strike');
    if (captureRatio !== null && captureRatio >= 0.5) badges.push('≥50% captured');

    return {
      pos,
      underlying: occ.underlying,
      optionType: occ.optionType,
      strike,
      expiration: occ.expiration,
      daysToExpiry: dte,
      strikeCushion,
      captureRatio,
      basisPerShare,
      pnlPct,
      badges,
    };
  });
};

const Badge = ({ children, color }: { children: React.ReactNode; color: string }) => (
  <span className={cls('px-2 py-0.5 text-xs font-medium rounded', color)}>{children}</span>
);

export default function ActionPanel({ positions, scorecard }: Props) {
  const annotated = annotate(positions ?? [], scorecard);
  // Sort by DTE ascending (most urgent first); positions without expiry last.
  annotated.sort((a, b) => {
    if (a.daysToExpiry === null && b.daysToExpiry === null) return 0;
    if (a.daysToExpiry === null) return 1;
    if (b.daysToExpiry === null) return -1;
    return a.daysToExpiry - b.daysToExpiry;
  });

  if (annotated.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Open Positions</h3>
        <p className="text-sm text-gray-400 mt-2">No open positions.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-700">
        <h3 className="text-base font-semibold text-white">Open Positions</h3>
        <p className="text-xs text-gray-400 mt-1">Sorted by days to expiry</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50">
            <tr>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Symbol</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Type</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Strike</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">DTE</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Signed cushion to the strike as % of underlying price. Positive = out of the money by that much; negative = in the money. Underlying price is the last daily close.">Cushion</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400" title="Options: % of max profit captured if closed now = (premium − current cost to close) / premium. Stock rows: cost basis per share.">% Captured / Basis</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Mkt Value</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Unrealized</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Flags</th>
            </tr>
          </thead>
          <tbody>
            {annotated.map(({ pos, underlying, optionType, strike, daysToExpiry, strikeCushion, captureRatio, basisPerShare, pnlPct, badges }) => {
              const mv = parseFloat(String(pos.market_value ?? 0));
              const upl = parseFloat(String(pos.unrealized_pl ?? 0));
              return (
                <tr key={pos.symbol} className="border-t border-gray-700/50">
                  <td className="px-3 py-2 text-sm font-mono text-blue-300">
                    {underlying || pos.symbol}
                  </td>
                  <td className="px-3 py-2 text-sm">
                    {optionType === 'P' ? (
                      <span className="text-green-300">Put</span>
                    ) : optionType === 'C' ? (
                      <span className="text-purple-300">Call</span>
                    ) : (
                      <span className="text-gray-300">Stock</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {strike !== null ? `$${strike.toFixed(2)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {daysToExpiry !== null ? `${daysToExpiry}d` : '—'}
                  </td>
                  <td className={cls(
                    'px-3 py-2 text-sm text-right',
                    strikeCushion !== null && strikeCushion < 0 ? 'text-red-300'
                      : strikeCushion !== null && strikeCushion < 0.05 ? 'text-yellow-300' : 'text-gray-200'
                  )}>
                    {strikeCushion !== null
                      ? `${strikeCushion >= 0 ? '+' : ''}${fmtPercent(strikeCushion, 1)}`
                      : <span className="text-gray-500">—</span>}
                  </td>
                  <td className={cls(
                    'px-3 py-2 text-sm text-right',
                    captureRatio !== null && captureRatio >= 0.5 ? 'text-green-300' : 'text-gray-200'
                  )}>
                    {captureRatio !== null
                      ? fmtPercent(captureRatio, 0)
                      : basisPerShare !== null
                        ? <span title="Cost basis per share">{`$${basisPerShare.toFixed(2)}/sh`}</span>
                        : <span className="text-gray-500">—</span>}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(mv)}
                  </td>
                  <td className={cls(
                    'px-3 py-2 text-sm text-right',
                    upl > 0 ? 'text-green-400' : upl < 0 ? 'text-red-400' : 'text-gray-300'
                  )}>
                    {fmtCurrency(upl)}{pnlPct !== null && <span className="text-xs opacity-75"> ({fmtPercent(pnlPct)})</span>}
                  </td>
                  <td className="px-3 py-2 text-sm">
                    <div className="flex gap-1 flex-wrap">
                      {badges.map((b) => {
                        let color = 'bg-gray-700 text-gray-300';
                        if (b.includes('DTE')) color = 'bg-yellow-900/40 text-yellow-300';
                        else if (b === 'ITM') color = 'bg-red-900/40 text-red-300';
                        else if (b === 'Near strike') color = 'bg-orange-900/40 text-orange-300';
                        else if (b.includes('captured')) color = 'bg-green-900/40 text-green-300';
                        return <Badge key={b} color={color}>{b}</Badge>;
                      })}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
