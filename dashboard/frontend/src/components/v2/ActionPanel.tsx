import type { LivePosition } from '../../types/v2';
import { fmtCurrency, fmtPercent, parseOcc, cls } from '../../utils/format';

interface Props {
  positions: LivePosition[];
}

interface Annotated {
  pos: LivePosition;
  underlying: string;
  optionType: 'P' | 'C' | null;
  strike: number | null;
  expiration: string | null;
  daysToExpiry: number | null;
  badges: string[];
}

const annotate = (positions: LivePosition[]): Annotated[] => {
  const today = new Date();
  return positions.map((pos) => {
    const occ = parseOcc(pos.symbol);
    let dte: number | null = null;
    if (occ.expiration) {
      const exp = new Date(occ.expiration + 'T16:00:00Z');
      dte = Math.max(0, Math.ceil((exp.getTime() - today.getTime()) / 86_400_000));
    }
    const badges: string[] = [];
    if (dte !== null && dte <= 7) badges.push('≤7 DTE');
    return {
      pos,
      underlying: occ.underlying,
      optionType: occ.optionType,
      strike: occ.strike,
      expiration: occ.expiration,
      daysToExpiry: dte,
      badges,
    };
  });
};

const Badge = ({ children, color }: { children: React.ReactNode; color: string }) => (
  <span className={cls('px-2 py-0.5 text-xs font-medium rounded', color)}>{children}</span>
);

export default function ActionPanel({ positions }: Props) {
  const annotated = annotate(positions ?? []);
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
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Mkt Value</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Unrealized</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Flags</th>
            </tr>
          </thead>
          <tbody>
            {annotated.map(({ pos, underlying, optionType, strike, daysToExpiry, badges }) => {
              const mv = parseFloat(String(pos.market_value ?? 0));
              const upl = parseFloat(String(pos.unrealized_pl ?? 0));
              const pnlPct = mv !== 0 ? upl / Math.abs(mv) : 0;
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
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtCurrency(mv)}
                  </td>
                  <td className={cls(
                    'px-3 py-2 text-sm text-right',
                    upl > 0 ? 'text-green-400' : upl < 0 ? 'text-red-400' : 'text-gray-300'
                  )}>
                    {fmtCurrency(upl)} <span className="text-xs opacity-75">({fmtPercent(pnlPct)})</span>
                  </td>
                  <td className="px-3 py-2 text-sm">
                    <div className="flex gap-1 flex-wrap">
                      {badges.map((b) => (
                        <Badge
                          key={b}
                          color={b.includes('DTE') ? 'bg-yellow-900/40 text-yellow-300' : 'bg-gray-700 text-gray-300'}
                        >
                          {b}
                        </Badge>
                      ))}
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
