import type { AcbTimelineRow } from '../../types/v2';
import { fmtCurrency, fmtDate, fmtNumber, pnlColor, cls } from '../../utils/format';

interface Props {
  events: AcbTimelineRow[];
  paperTrading?: boolean;
}

const eventBadge = (label: string): { text: string; classes: string } => {
  switch (label) {
    case 'put_sold':       return { text: 'Put sold',       classes: 'bg-green-900/40 text-green-300' };
    case 'call_sold':      return { text: 'Call sold',      classes: 'bg-purple-900/40 text-purple-300' };
    case 'option_closed':  return { text: 'Closed',         classes: 'bg-gray-700 text-gray-300' };
    case 'put_assigned':   return { text: 'Assigned',       classes: 'bg-yellow-900/40 text-yellow-300' };
    case 'called_away':    return { text: 'Called away',    classes: 'bg-orange-900/40 text-orange-300' };
    case 'expired':        return { text: 'Expired',        classes: 'bg-blue-900/40 text-blue-300' };
    default:               return { text: label,            classes: 'bg-gray-700 text-gray-400' };
  }
};

// Build the Alpaca order detail link for an event row. Synthetic FC-021
// rows have order_ids prefixed `synthetic-` and shouldn't link out.
const alpacaOrderLink = (orderId: string | null, paperTrading: boolean): string | null => {
  if (!orderId || orderId.startsWith('synthetic-')) return null;
  const base = paperTrading
    ? 'https://app.alpaca.markets/paper/dashboard/orders'
    : 'https://app.alpaca.markets/live/dashboard/orders';
  return `${base}/${orderId}`;
};

export default function TradeLog({ events, paperTrading = true }: Props) {
  if (!events || events.length === 0) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Trade Log</h3>
        <p className="text-sm text-gray-400 mt-2">No events recorded for this symbol.</p>
      </div>
    );
  }

  // Newest first.
  const sorted = [...events].sort((a, b) =>
    (b.event_time ?? '').localeCompare(a.event_time ?? '')
  );

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-700 flex items-baseline justify-between">
        <div>
          <h3 className="text-base font-semibold text-white">Trade Log</h3>
          <p className="text-xs text-gray-400 mt-1">
            Every event for this symbol, newest first (all dates ET). Includes opens, closes, assignments, and expirations.
          </p>
        </div>
        <span className="text-xs text-gray-500">{sorted.length} events</span>
      </div>
      <div className="overflow-x-auto max-h-[32rem] overflow-y-auto">
        <table className="w-full">
          <thead className="bg-gray-900/50 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Date</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Event</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Type</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Strike</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Expiry</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Qty</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Premium</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-gray-400">Realized</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-left text-gray-400">Outcome</th>
              <th className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-center text-gray-400" title="Open this order in Alpaca">↗</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((e) => {
              const badge = eventBadge(e.event_label);
              const isOpen = e.activity_type === 'FILL' && (e.side === 'sell_short' || e.side === 'sell');
              const isClose = e.activity_type === 'FILL' && (e.side === 'buy_to_close' || e.side === 'buy');

              return (
                <tr key={e.event_time + (e.activity_type ?? '')} className="border-t border-gray-700/50">
                  <td className="px-3 py-2 text-sm text-gray-200 whitespace-nowrap">
                    {fmtDate(e.event_date)}
                  </td>
                  <td className="px-3 py-2 text-sm">
                    <span className={cls('px-2 py-0.5 text-xs font-medium rounded', badge.classes)}>
                      {badge.text}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-sm">
                    {e.option_type === 'put' ? (
                      <span className="text-green-300">Put</span>
                    ) : e.option_type === 'call' ? (
                      <span className="text-purple-300">Call</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {e.strike_price !== null ? (
                      <div>
                        <div>${e.strike_price.toFixed(2)}</div>
                        {e.occ_symbol && (
                          <div
                            className="font-mono text-[10px] text-gray-500 mt-0.5"
                            title="OCC contract symbol"
                          >
                            {e.occ_symbol}
                          </div>
                        )}
                      </div>
                    ) : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-gray-300 whitespace-nowrap">
                    {e.expiration ? fmtDate(e.expiration) : <span className="text-gray-500">—</span>}
                  </td>
                  <td className="px-3 py-2 text-sm text-right text-gray-200">
                    {fmtNumber(e.qty)}
                  </td>
                  <td className={cls(
                    'px-3 py-2 text-sm text-right',
                    isOpen ? 'text-gray-200' : isClose ? 'text-gray-500' : 'text-gray-400'
                  )}>
                    {isOpen
                      ? fmtCurrency(e.premium_total)
                      : isClose
                        ? <span title="Cost paid to buy back this position">({fmtCurrency(e.premium_total)})</span>
                        : '—'}
                  </td>
                  <td className={cls('px-3 py-2 text-sm text-right', pnlColor(e.realized_pnl))}>
                    {e.realized_pnl !== null ? fmtCurrency(e.realized_pnl) : '—'}
                  </td>
                  <td className="px-3 py-2 text-sm text-gray-300">
                    {e.outcome ? (
                      <span className="font-mono text-xs">{e.outcome}</span>
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-sm text-center">
                    {(() => {
                      const url = alpacaOrderLink(e.order_id, paperTrading);
                      return url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-400 hover:text-blue-300"
                          title={`Open order ${e.order_id} in Alpaca`}
                        >
                          ↗
                        </a>
                      ) : (
                        <span className="text-gray-600" title={
                          e.order_id?.startsWith('synthetic-')
                            ? 'Synthetic FC-021 row — no Alpaca order to link to'
                            : 'No order id recorded for this event'
                        }>—</span>
                      );
                    })()}
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
