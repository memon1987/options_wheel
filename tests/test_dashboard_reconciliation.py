"""FC-031: falsifiable reconciliation-identity tests.

Reconstructs NLV from a synthetic activity stream and asserts
`get_reconciliation` composes the identity correctly:

    NLV − deposits = closed net cash P&L + open-option premium + fees
                     + live market value (stocks + options, signed)

This is the test the adversarial review demanded (F1/F15): a broken
convention (e.g. double-subtracting held-share cost) produces a non-zero
residual here, where a tautological "invariant" could not fail.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard" / "backend"))


def _service(scorecard_sums, view_shares, deposits=100_000.0, fees=-2.0):
    """BigQueryService with all BQ I/O stubbed."""
    from services.bigquery import BigQueryService

    svc = BigQueryService.__new__(BigQueryService)
    svc.dataset = "test.options_wheel"

    def fake_run_query(query):
        if "SUM(COALESCE(total_realized_pnl" in query:
            return [scorecard_sums]
        if "SELECT underlying, current_shares" in query:
            return view_shares
        raise AssertionError(f"unexpected query: {query[:80]}")

    svc._run_query = fake_run_query
    svc.get_account_baseline = lambda: {"starting_capital": deposits, "source": "test"}
    svc.get_fees_total = lambda: fees
    return svc


# Synthetic stream: $100k deposit; put sold for $300 then assigned
# (OPTRD −$25,000 for 100sh @ $250, put realized_pnl = +$300); covered call
# open with $200 premium; $2 of fees.
#   cash = 100,000 + 300 − 25,000 + 200 − 2 = 75,498
#   MV   = 100sh @ $255 = 25,500 ; short call mark −150
#   NLV  = 75,498 + 25,500 − 150 = 100,848
SCORECARD = {"realized_cash": 300.0 - 25_000.0, "open_premium": 200.0}
VIEW_SHARES = [{"underlying": "XYZ", "current_shares": 100.0}]
LIVE = [
    {"symbol": "XYZ", "qty": "100", "market_value": "25500"},
    {"symbol": "XYZ260117C00260000", "qty": "-1", "market_value": "-150"},
]
NLV = 100_848.0


class TestIdentity:
    def test_residual_zero_on_consistent_stream(self):
        svc = _service(SCORECARD, VIEW_SHARES)
        rec = svc.get_reconciliation(NLV, LIVE)
        assert rec["residual"] == pytest.approx(0.0, abs=1e-6)
        # AMD's known gap is in the payload, so net-of-known-gaps is +1594,
        # above the $500 floor — with the documented gap absent from live
        # mismatches, status must be WARN (stale allowance), not ok.
        assert rec["status"] == "warn"

    def test_missing_share_cash_breaks_identity(self):
        # Drop the OPTRD outflow from the ledger (ingest gap): the residual
        # must expose the full $25,000, and status must warn.
        broken = {"realized_cash": 300.0, "open_premium": 200.0}
        svc = _service(broken, VIEW_SHARES)
        rec = svc.get_reconciliation(NLV, LIVE)
        assert rec["residual"] == pytest.approx(-25_000.0, abs=1e-6)
        assert rec["status"] == "warn"

    def test_double_subtracted_basis_is_caught(self):
        # The exact F1 bug: treating (price − basis) × shares as the
        # unrealized add-back after the cash ledger already expensed the
        # basis. That understates the ledger side by basis × shares and the
        # residual exposes it.
        f1_bug = {
            "realized_cash": (300.0 - 25_000.0) + (255.0 - 250.0) * 100 - 25_500.0,
            "open_premium": 200.0,
        }
        svc = _service(f1_bug, VIEW_SHARES)
        rec = svc.get_reconciliation(NLV, LIVE)
        assert abs(rec["residual"]) == pytest.approx(25_000.0, abs=1e-6)
        assert rec["status"] == "warn"

    def test_share_count_mismatch_detected(self):
        # View says 100 shares, broker says 0 (the AMD anomaly shape).
        svc = _service(SCORECARD, [{"underlying": "AMD", "current_shares": 100.0}])
        rec = svc.get_reconciliation(NLV, LIVE)
        symbols = {m["symbol"] for m in rec["share_count_mismatches"]}
        assert "AMD" in symbols          # view-only shares
        assert "XYZ" in symbols          # live-only shares

    def test_no_live_data_is_unknown_not_ok(self):
        svc = _service(SCORECARD, VIEW_SHARES)
        rec = svc.get_reconciliation(None, None)
        assert rec["residual"] is None
        assert rec["status"] == "unknown"
