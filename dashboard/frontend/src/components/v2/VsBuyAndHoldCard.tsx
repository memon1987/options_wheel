import type { VsBuyAndHold } from '../../types/v2';
import { fmtCurrency, fmtCurrencyDetail, fmtDate, pnlColor } from '../../utils/format';

interface Props {
  data: VsBuyAndHold | null;
}

// FC-031: symmetric comparison — the wheel side is marked-to-market
// (net cash P&L + market value of held shares) just like the B&H side.
// The pre-FC-031 version compared realized-only wheel to MTM B&H.
export default function VsBuyAndHoldCard({ data }: Props) {
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Wheel vs Buy-and-Hold</h3>
        <p className="text-sm text-gray-400 mt-2">No comparison available.</p>
      </div>
    );
  }

  const wheelMtm = data.wheel_mtm_pnl ?? data.total_realized_pnl;
  const bhTotal = data.bh_dollar_pnl;
  const delta = data.wheel_minus_bh;
  const holdingShares = (data.current_shares ?? 0) > 0;

  const ready =
    data.first_trade_date != null && data.price_at_start != null &&
    data.price_now != null && data.bh_dollar_pnl != null;

  // Flag a late backfill silently re-basing the comparison (review F18).
  const lateBaseline =
    data.price_at_start_date != null && data.first_trade_date != null &&
    data.price_at_start_date > data.first_trade_date &&
    (new Date(data.price_at_start_date).getTime() - new Date(data.first_trade_date).getTime()) > 5 * 86_400_000;

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Wheel vs Buy-and-Hold</h3>
      <p className="text-xs text-gray-400 mt-1">
        Wheel MTM P&L for {data.underlying} vs holding the first put&apos;s collateral in stock
        from {fmtDate(data.first_trade_date)} to {data.price_now_date ?? 'today'}.{' '}
        <span title="Perfect-foresight reference: assumes this symbol's full collateral was deployed in it for the entire period — the account could not do that for every symbol simultaneously.">
          B&amp;H is a perfect-foresight reference ⓘ
        </span>
      </p>

      {!ready ? (
        <p className="text-sm text-gray-400 mt-4">
          Stock-history backfill not yet complete for this symbol. Comparison populates after the next
          /ingest-stock-history run.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 mt-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Wheel (MTM)</div>
              <div className={`text-lg font-semibold mt-1 ${pnlColor(wheelMtm)}`}>
                {fmtCurrencyDetail(wheelMtm)}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                cash {fmtCurrency(data.total_realized_pnl)}
                {holdingShares && data.price_now !== null && (
                  <> + shares {fmtCurrency((data.current_shares ?? 0) * data.price_now)}</>
                )}
                {holdingShares && (
                  <span title="Open short-option marks are not included in this figure — check live positions for the current option liability.">
                    {' '}· excl. open option marks
                  </span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Buy-and-Hold</div>
              <div className={`text-lg font-semibold mt-1 ${pnlColor(bhTotal)}`}>
                {fmtCurrencyDetail(bhTotal)}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {data.price_at_start !== null && data.price_now !== null && (
                  <>${data.price_at_start?.toFixed(2)} → ${data.price_now?.toFixed(2)} <span title="Buy-and-hold figure is price-only and does not reinvest dividends — it understates B&H for dividend payers.">(price only)</span></>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-400">Δ Wheel − B&amp;H</div>
              <div className={`text-lg font-semibold mt-1 ${pnlColor(delta)}`}>
                {fmtCurrencyDetail(delta)}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {delta !== null && delta > 0 ? 'wheel beat buy-and-hold' : delta !== null && delta < 0 ? 'wheel lagged' : ''}
              </div>
            </div>
          </div>
          {lateBaseline && (
            <p className="text-xs text-yellow-500 mt-3">
              ⚠ B&amp;H baseline uses the {data.price_at_start_date} close — bar history starts after the
              first trade ({data.first_trade_date}), so the comparison window is shortened.
            </p>
          )}
        </>
      )}
    </div>
  );
}
