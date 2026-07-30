"""FC-050: shared cost-basis floor resolution.

The resolver is the FC-029 chain moved out of ``CallSeller`` so the scanner can
use the same number. These tests pin the chain's contract at its new home, and
pin the opportunity-shape helper that made the execute-time floor real.
"""

import pytest
from unittest.mock import Mock, patch

from src.strategy.cost_basis import (
    CostBasisResolver,
    SOURCE_ALPACA,
    SOURCE_BIGQUERY,
    SOURCE_UNRESOLVED,
    SOURCE_WHEEL_STATE,
    opportunity_floor_per_share,
)
from src.utils.config import Config


def _position(cost_basis=0.0, symbol='AMZN', qty=100):
    return {'symbol': symbol, 'qty': qty, 'cost_basis': cost_basis,
            'asset_class': 'us_equity', 'side': 'long'}


class TestCostBasisResolverSourceOrder:
    """FC-029 R2 source order: wheel_state → BigQuery OPASN → Alpaca."""

    def _resolver(self, wheel_state=None, allow_bigquery=True):
        return CostBasisResolver(Mock(), Mock(spec=Config),
                                 wheel_state=wheel_state,
                                 allow_bigquery=allow_bigquery)

    def test_wheel_state_wins_over_every_other_source(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        resolver = self._resolver(wheel_state=wheel_state)

        with patch.object(resolver, '_lookup_last_opasn_put_strike',
                          return_value=300.0) as mock_bq:
            # Alpaca would say $250/share; wheel_state must still win.
            basis, source = resolver.resolve_with_source('AMZN', _position(25000.0), 100)

        assert (basis, source) == (247.5, SOURCE_WHEEL_STATE)
        mock_bq.assert_not_called()

    def test_bigquery_is_used_when_wheel_state_is_empty(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 0}
        resolver = self._resolver(wheel_state=wheel_state)

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=247.5):
            # Alpaca reports 0 for a freshly assigned position (FC-029).
            basis, source = resolver.resolve_with_source('AMZN', _position(0.0), 100)

        assert (basis, source) == (247.5, SOURCE_BIGQUERY)

    def test_a_bigquery_hit_is_backfilled_into_wheel_state(self):
        """The back-fill is what makes the second resolve in a cycle free."""
        wheel_state = Mock()
        cb_state = {'stock_cost_basis': 0.0}
        wheel_state.get_position_summary.side_effect = lambda _s: dict(cb_state)
        wheel_state.set_stock_cost_basis.side_effect = (
            lambda _s, cb: cb_state.update(stock_cost_basis=cb))
        resolver = self._resolver(wheel_state=wheel_state)

        with patch.object(resolver, '_lookup_last_opasn_put_strike',
                          return_value=247.5) as mock_bq:
            first = resolver.resolve_with_source('AMZN', _position(0.0), 100)
            second = resolver.resolve_with_source('AMZN', _position(0.0), 100)

        wheel_state.set_stock_cost_basis.assert_called_once_with('AMZN', 247.5)
        mock_bq.assert_called_once_with('AMZN')
        assert first == (247.5, SOURCE_BIGQUERY)
        assert second == (247.5, SOURCE_WHEEL_STATE)

    def test_a_failed_backfill_does_not_lose_the_resolved_basis(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 0}
        wheel_state.set_stock_cost_basis.side_effect = Exception("GCS down")
        resolver = self._resolver(wheel_state=wheel_state)

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=247.5):
            assert resolver.resolve('AMZN', _position(0.0), 100) == 247.5

    def test_a_failed_wheel_state_read_falls_through_to_bigquery(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.side_effect = Exception("state unreadable")
        resolver = self._resolver(wheel_state=wheel_state)

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=247.5):
            assert resolver.resolve_with_source('AMZN', _position(0.0), 100) == (
                247.5, SOURCE_BIGQUERY)

    def test_alpaca_is_the_last_resort_for_manual_buys(self):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=0.0):
            basis, source = resolver.resolve_with_source('AMZN', _position(25000.0), 100)

        assert (basis, source) == (250.0, SOURCE_ALPACA)

    def test_nothing_resolves_reports_unresolved_not_a_floor(self):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=0.0):
            basis, source = resolver.resolve_with_source('AMZN', _position(0.0), 100)

        assert basis == 0.0
        assert source == SOURCE_UNRESOLVED

    def test_a_malformed_alpaca_cost_basis_resolves_to_no_floor(self):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_last_opasn_put_strike', return_value=0.0):
            basis, source = resolver.resolve_with_source(
                'AMZN', _position('not-a-number'), 100)

        assert (basis, source) == (0.0, SOURCE_UNRESOLVED)

    def test_resolve_returns_only_the_number(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        assert self._resolver(wheel_state=wheel_state).resolve(
            'AMZN', _position(0.0), 100) == 247.5


class TestCostBasisResolverBigQueryGate:
    """A backtest must never reach production trade history."""

    @pytest.mark.real_bq_lookup
    def test_allow_bigquery_false_never_builds_a_client(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=False)

        with patch('google.cloud.bigquery.Client') as mock_client:
            assert resolver._lookup_last_opasn_put_strike('AMZN') == 0.0

        mock_client.assert_not_called()

    @pytest.mark.real_bq_lookup
    def test_a_bigquery_failure_returns_no_floor_rather_than_raising(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)

        with patch('google.cloud.bigquery.Client',
                   side_effect=Exception("no creds in test env")):
            assert resolver._lookup_last_opasn_put_strike('AMZN') == 0.0

    @pytest.mark.real_bq_lookup
    def test_the_bigquery_client_is_constructed_once_and_cached(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)
        job = Mock()
        job.result.return_value = []

        with patch('google.cloud.bigquery.Client') as mock_client:
            mock_client.return_value.query.return_value = job
            resolver._lookup_last_opasn_put_strike('AMZN')
            resolver._lookup_last_opasn_put_strike('AMZN')

        assert mock_client.call_count == 1


class TestOpportunityFloorPerShare:
    """FC-050: one helper that understands both opportunity shapes."""

    def test_scanner_shape_uses_cost_basis_per_share(self):
        assert opportunity_floor_per_share({
            'cost_basis_per_share': 303.50, 'max_contracts': 2,
        }) == 303.50

    def test_wheel_engine_shape_divides_the_total_by_shares_covered(self):
        assert opportunity_floor_per_share({
            'stock_cost_basis': 16000.0, 'shares_covered': 100, 'contracts': 1,
        }) == 160.0

    def test_multi_contract_without_shares_covered_divides_by_contracts_times_100(self):
        """FC-038 made multi-contract calls reachable; a bare 100 would
        understate the floor by the contract count."""
        assert opportunity_floor_per_share({
            'stock_cost_basis': 32000.0, 'contracts': 2,
        }) == 160.0

    def test_scanner_shape_wins_when_both_are_present(self):
        assert opportunity_floor_per_share({
            'cost_basis_per_share': 303.50,
            'stock_cost_basis': 16000.0, 'shares_covered': 100,
        }) == 303.50

    @pytest.mark.parametrize("opportunity", [
        {},
        {'cost_basis_per_share': 0},
        {'cost_basis_per_share': None},
        {'stock_cost_basis': 16000.0},                       # no share count at all
        {'stock_cost_basis': 16000.0, 'contracts': 0},
        {'stock_cost_basis': 0, 'shares_covered': 100},
        {'cost_basis_per_share': 'oops'},
    ])
    def test_an_underivable_floor_is_zero_not_a_guess(self, opportunity):
        assert opportunity_floor_per_share(opportunity) == 0.0


class TestCallSellerDelegationIsBehaviourPreserving:
    """The seller's methods are wrappers now; the chain must still be reachable
    (and interceptable) through them — the hermeticity guard depends on it."""

    def _seller(self, wheel_state=None, allow_bigquery=True):
        from src.strategy.call_seller import CallSeller
        return CallSeller(Mock(), Mock(), Mock(spec=Config),
                          wheel_state_manager=wheel_state,
                          allow_bigquery_cost_basis=allow_bigquery)

    def test_patching_the_seller_wrapper_intercepts_the_chain(self):
        seller = self._seller()

        with patch.object(seller, '_lookup_last_opasn_put_strike', return_value=247.5):
            assert seller._resolve_cost_basis_floor('AMZN', _position(0.0), 100) == 247.5

    def test_the_wrapper_forwards_the_backtest_bigquery_gate(self):
        assert self._seller(allow_bigquery=False)._lookup_last_opasn_put_strike('AMZN') == 0.0

    def test_the_seller_resolves_through_its_wheel_state(self):
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}

        assert self._seller(wheel_state=wheel_state)._resolve_cost_basis_floor(
            'AMZN', _position(0.0), 100) == 247.5
