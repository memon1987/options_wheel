import type { VsBuyAndHold } from '../../types/v2';
import { fmtCurrency, fmtCurrencyDetail, fmtDate, pnlColor } from '../../utils/format';

interface Props {
  data: VsBuyAndHold | null;
}

export default function VsBuyAndHoldCard({ data }: Props) {
  if (!data) {
    return (
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
        <h3 className="text-base font-semibold text-white">Wheel vs Buy-and-Hold</h3>
        <p className="text-sm text-gray-400 mt-2">No comparison available.</p>
      </div>
    );
  }

  const wheelTotal = data.total_realized_pnl ?? 0;
  const bhTotal = data.bh_dollar_pnl;
  const delta = data.wheel_minus_bh;

  const ready =
    data.first_trade_date && data.price_at_start && data.price_now &&
    data.bh_dollar_pnl !== null;

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-800 p-5">
      <h3 className="text-base font-semibold text-white">Wheel vs Buy-and-Hold</h3>
      <p className="text-xs text-gray-400 mt-1">
        Wheel return for {data.underlying} vs holding the same dollar amount of stock
        from {fmtDate(data.first_trade_date)} to today.
      </p>

      {!ready ? (
        <p className="text-sm text-gray-400 mt-4">
          Stock-history backfill not yet complete for this symbol. Comparison populates after the next
          /ingest-stock-history run.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-3 mt-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-400">Wheel</div>
            <div className={`text-lg font-semibold mt-1 ${pnlColor(wheelTotal)}`}>
              {fmtCurrencyDetail(wheelTotal)}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              option {fmtCurrency(data.realized_pnl)} + share {fmtCurrency(data.share_side_pnl)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-wide text-gray-400">Buy-and-Hold</div>
            <div className={`text-lg font-semibold mt-1 ${pnlColor(bhTotal)}`}>
              {fmtCurrencyDetail(bhTotal)}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {data.price_at_start !== null && data.price_now !== null && (
                <>${data.price_at_start?.toFixed(2)} → ${data.price_now?.toFixed(2)} <span title="Buy-and-hold figure is price-only and does not reinvest dividends.">(price only)</span></>
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
      )}
    </div>
  );
}
