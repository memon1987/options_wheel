import type { Reconciliation } from '../../types/v2';
import { fmtCurrency, fmtCurrencyDetail } from '../../utils/format';

interface Props {
  data: Reconciliation | null;
}

// FC-031: broker-vs-ledger reconciliation surfaced on every Overview load.
// Identity: NLV − deposits = realized cash P&L + open option premium + fees
// + live market value. Residual ≈ 0 unless the BQ ledger disagrees with the
// broker — missed activities or paper-engine anomalies.
export default function ReconciliationBanner({ data }: Props) {
  if (!data || data.status === 'unknown') return null;

  if (data.status === 'ok') {
    return (
      <div className="text-xs text-gray-500 text-center">
        Books reconcile to the broker · residual {fmtCurrency(data.residual)}
        {data.known_gaps.length > 0 && (
          <span title={data.known_gaps.map((g) => `${g.symbol}: ${fmtCurrency(g.amount)} (${g.reason})`).join('\n')}>
            {' '}(known gaps {fmtCurrency(data.known_gaps.reduce((s, g) => s + g.amount, 0))})
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-yellow-700/50 bg-yellow-900/10 px-4 py-3 text-sm text-yellow-200">
      <div className="font-semibold">Reconciliation warning — ledger vs broker drift</div>
      <div className="text-xs mt-1 space-y-0.5">
        <div>
          NLV {fmtCurrencyDetail(data.nlv)} − deposits {fmtCurrency(data.deposits)} ={' '}
          {fmtCurrencyDetail(data.nlv !== null ? data.nlv - data.deposits : null)} account growth
        </div>
        <div>
          Ledger: realized cash {fmtCurrency(data.realized_cash_pnl)} + open premium{' '}
          {fmtCurrency(data.open_option_premium)} + fees {fmtCurrency(data.fees)} + live positions{' '}
          {fmtCurrency(data.live_market_value)}
        </div>
        <div className="font-semibold">
          Residual {fmtCurrencyDetail(data.residual)} · net of known gaps{' '}
          {fmtCurrencyDetail(data.residual_net_of_known_gaps)}
        </div>
        {data.share_count_mismatches.length > 0 && (
          <div>
            Share-count mismatches (view vs broker):{' '}
            {data.share_count_mismatches
              .map((m) => `${m.symbol} ${m.view_shares} vs ${m.live_shares}`)
              .join(' · ')}
          </div>
        )}
      </div>
    </div>
  );
}
