"""FC-065 Phase 1: the inverted cost-basis floor.

FC-050 moved the FC-029 chain (wheel_state → BigQuery OPASN strike → Alpaca)
out of ``CallSeller`` so the scanner could share it. FC-065 **inverts** it:
Alpaca's ``avg_entry_price`` is the primary and only floor source, BigQuery is
an inline divergence cross-check that can veto the broker's number but never
supply one, and ``wheel_state`` is gone from the chain entirely.

The precedence tests here are the deliberate inversions of FC-050's
``test_a_bigquery_hit_beats_a_positive_alpaca_basis`` and
``test_wheel_state_beats_a_positive_alpaca_basis_too`` — rewritten to pin the
new order rather than deleted, and mutation-tested against it.
"""

import pytest
from unittest.mock import Mock, patch

from src.strategy.cost_basis import (
    CROSS_CHECK_DIVERGENT,
    CROSS_CHECK_OK,
    CROSS_CHECK_UNAVAILABLE,
    CostBasisResolver,
    SOURCE_ALPACA,
    SOURCE_DIVERGENT,
    SOURCE_UNRESOLVED,
    opportunity_floor_per_share,
    reconstruct_expected_basis,
)
from src.utils.config import Config


def _position(avg_entry_price=0.0, cost_basis=0.0, symbol='AMZN', qty=100):
    position = {'symbol': symbol, 'qty': qty, 'cost_basis': cost_basis,
                'asset_class': 'us_equity', 'side': 'long'}
    if avg_entry_price is not None:
        position['avg_entry_price'] = avg_entry_price
    return position


def _assignment(strike, premium, shares=100, occ='AMZN260612P00247500'):
    return {'occ_symbol': occ, 'strike_price': strike, 'shares': shares,
            'put_premium': premium}


class TestTheFloorIsTheBrokersAvgEntryPrice:
    """FC-065: one field, broker-authoritative, operator-verifiable."""

    def _resolver(self, allow_bigquery=True):
        return CostBasisResolver(Mock(), Mock(spec=Config),
                                 allow_bigquery=allow_bigquery)

    def test_alpaca_avg_entry_price_is_the_floor(self):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis', return_value=None):
            basis, source = resolver.resolve_with_source(
                'AAPL', _position(avg_entry_price=303.50, cost_basis=30350.0), 100)

        assert (basis, source) == (303.50, SOURCE_ALPACA)

    def test_the_broker_beats_a_bigquery_derived_value(self):
        """The inversion of FC-050's ``test_a_bigquery_hit_beats_a_positive_
        alpaca_basis``. BigQuery no longer competes to set the floor: when the
        two agree within tolerance the broker's number is what is used, and
        when they disagree BigQuery's answer is still not adopted — the symbol
        is skipped instead (see the divergence tests below)."""
        resolver = self._resolver()

        # BQ reconstructs 303.49; Alpaca says 303.50. Inside tolerance.
        with patch.object(resolver, '_lookup_assignment_basis', return_value={
                'expected_basis_per_share': 303.49, 'reconstructed_shares': 100,
                'lots': []}):
            detail = resolver.resolve_detailed(
                'AAPL', _position(avg_entry_price=303.50), 100)

        assert (detail['basis'], detail['source']) == (303.50, SOURCE_ALPACA)
        assert detail['cross_check']['status'] == CROSS_CHECK_OK

    def test_wheel_state_is_not_consulted_at_all(self):
        """The inversion of FC-050's ``test_wheel_state_beats_a_positive_alpaca_
        basis_too``. ``wheel_state`` has never been populated in production
        (``STATE_STORAGE_BUCKET`` unset since inception) and is now gone from
        the resolver's constructor as well as from its chain."""
        with pytest.raises(TypeError):
            CostBasisResolver(Mock(), Mock(spec=Config), wheel_state=Mock())

        resolver = self._resolver()
        assert not hasattr(resolver, 'wheel_state')

    def test_a_multi_lot_position_uses_the_brokers_weighted_average(self):
        """Alpaca already averages across lots — the exact semantic wanted, and
        why FC-064's bespoke lot arithmetic dissolved."""
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis', return_value=None):
            basis, source = resolver.resolve_with_source(
                'AAPL', _position(avg_entry_price=304.25, qty=200), 200)

        assert (basis, source) == (304.25, SOURCE_ALPACA)

    def test_resolve_returns_only_the_number(self):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis', return_value=None):
            assert resolver.resolve('AMZN', _position(261.20), 100) == 261.20


class TestFailClosedOnAMissingBrokerBasis:
    """A regression to FC-029's reported ``cost_basis = 0`` behaviour must halt
    writing, not write unprotected. Every one of these fails if the guard is
    reverted to "resolve anyway"."""

    def _resolver(self):
        return CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)

    @pytest.mark.parametrize("position", [
        _position(avg_entry_price=0.0),                       # broker reports 0
        _position(avg_entry_price=None),                      # field absent
        _position(avg_entry_price='not-a-number'),            # malformed
        _position(avg_entry_price=-5.0),                      # nonsensical
        {},                                                   # unreadable
    ])
    def test_no_usable_broker_basis_yields_no_floor(self, position):
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis') as mock_bq:
            basis, source = resolver.resolve_with_source('AMZN', position, 100)

        assert (basis, source) == (0.0, SOURCE_UNRESOLVED)
        # No point cross-checking a number that does not exist.
        mock_bq.assert_not_called()

    def test_a_positive_cost_basis_does_not_rescue_a_missing_avg_entry_price(self):
        """Deliberately strict: the derivation ``cost_basis / qty`` belongs to
        the client wrapper (``AlpacaClient.get_positions``). A position dict
        arriving here without the field is a plumbing defect, and failing
        closed is the right response to a plumbing defect."""
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis', return_value=None):
            basis, source = resolver.resolve_with_source(
                'AMZN', _position(avg_entry_price=None, cost_basis=26120.0), 100)

        assert (basis, source) == (0.0, SOURCE_UNRESOLVED)


class TestTheDivergenceCrossCheckHasTeeth:
    """Not warn-only — both plan reviewers rejected warn-only. The dangerous
    case is *presence with a wrong value* (a mis-adjusted split, a partial
    disposal), which fail-closed-on-zero cannot catch."""

    def _resolver(self):
        return CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)

    def _with_reconstruction(self, resolver, expected, shares=100):
        return patch.object(resolver, '_lookup_assignment_basis', return_value={
            'expected_basis_per_share': expected,
            'reconstructed_shares': shares,
            'lots': [],
        })

    def test_a_divergent_basis_fails_closed(self):
        """Fails if the cross-check is reverted to warn-only."""
        resolver = self._resolver()

        # Broker says 303.50; history says the shares cost 261.20 net of
        # premium. One of the two is wrong about what these shares cost.
        with self._with_reconstruction(resolver, 261.20):
            detail = resolver.resolve_detailed(
                'AAPL', _position(avg_entry_price=303.50), 100)

        assert detail['basis'] == 0.0
        assert detail['source'] == SOURCE_DIVERGENT
        assert detail['broker_basis'] == 303.50
        assert detail['cross_check']['status'] == CROSS_CHECK_DIVERGENT
        assert detail['cross_check']['reason'] == 'basis_mismatch'
        assert detail['cross_check']['expected_basis'] == 261.20

    def test_a_split_shaped_divergence_fails_closed(self):
        """The motivating case: a 4:1 split adjusted on one side only. Neither
        value is zero, so fail-closed-on-zero is blind to it."""
        resolver = self._resolver()

        with self._with_reconstruction(resolver, 303.50):
            basis, source = resolver.resolve_with_source(
                'AAPL', _position(avg_entry_price=75.875), 100)

        assert (basis, source) == (0.0, SOURCE_DIVERGENT)

    def test_a_share_count_mismatch_is_treated_as_divergence(self):
        """Plan: reconstructed shares != Alpaca qty → divergence. The lots we
        would be pricing are not the lots we hold."""
        resolver = self._resolver()

        with self._with_reconstruction(resolver, 303.50, shares=100):
            detail = resolver.resolve_detailed(
                'AAPL', _position(avg_entry_price=303.50, qty=200), 200)

        assert detail['basis'] == 0.0
        assert detail['source'] == SOURCE_DIVERGENT
        assert detail['cross_check']['reason'] == 'share_count_mismatch'

    # Tolerance = max($0.10, 0.1% of basis); 0.1% of 303.50 is $0.3035, so the
    # relative bound is the binding one here. The table straddles it.
    @pytest.mark.parametrize("expected,verdict", [
        (303.50, SOURCE_ALPACA),      # exact
        (303.80, SOURCE_ALPACA),      # +0.30, inside 0.3035
        (303.20, SOURCE_ALPACA),      # -0.30, inside 0.3035
        (303.85, SOURCE_DIVERGENT),   # +0.35, outside
        (303.15, SOURCE_DIVERGENT),   # -0.35, outside
    ])
    def test_the_tolerance_is_max_ten_cents_or_a_tenth_of_a_percent(
            self, expected, verdict):
        resolver = self._resolver()

        with self._with_reconstruction(resolver, expected):
            _, source = resolver.resolve_with_source(
                'AAPL', _position(avg_entry_price=303.50), 100)

        assert source == verdict

    def test_a_cheap_stock_uses_the_ten_cent_floor_not_the_percentage(self):
        resolver = self._resolver()

        # 0.1% of $25 is $0.025 — far tighter than a penny-rounding artefact
        # deserves, so the absolute floor takes over.
        with self._with_reconstruction(resolver, 25.06):
            _, source = resolver.resolve_with_source(
                'F', _position(avg_entry_price=25.00), 100)

        assert source == SOURCE_ALPACA

    def test_an_underivable_premium_keeps_the_floor_rather_than_failing_closed(self):
        """Plan: 'if underivable, no comparison is possible — log that, keep
        the floor, fail closed only on zero/missing/divergent.'"""
        resolver = self._resolver()

        with self._with_reconstruction(resolver, None):
            detail = resolver.resolve_detailed(
                'AAPL', _position(avg_entry_price=303.50), 100)

        assert (detail['basis'], detail['source']) == (303.50, SOURCE_ALPACA)
        assert detail['cross_check']['status'] == CROSS_CHECK_UNAVAILABLE
        assert detail['cross_check']['reason'] == 'premium_underivable'

    def test_no_assignment_history_keeps_the_floor(self):
        """A manually bought position has no OPASN rows at all."""
        resolver = self._resolver()

        with patch.object(resolver, '_lookup_assignment_basis', return_value=None):
            detail = resolver.resolve_detailed(
                'SPY', _position(avg_entry_price=610.00), 100)

        assert (detail['basis'], detail['source']) == (610.00, SOURCE_ALPACA)
        assert detail['cross_check']['reason'] == 'no_assignment_history'

    def test_the_cross_check_is_skipped_when_bigquery_is_gated_off(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config),
                                     allow_bigquery=False)

        detail = resolver.resolve_detailed(
            'AAPL', _position(avg_entry_price=303.50), 100)

        assert (detail['basis'], detail['source']) == (303.50, SOURCE_ALPACA)
        assert detail['cross_check'] == {'status': CROSS_CHECK_UNAVAILABLE,
                                         'reason': 'bigquery_disabled'}


class TestExpectedBasisReconstruction:
    """The derivation, in isolation: expected avg_entry = strike − premium,
    weighted across the lots that make up the currently-held quantity."""

    def test_a_single_lot_nets_the_put_premium_off_the_strike(self):
        result = reconstruct_expected_basis([_assignment(305.00, 1.50)], 100)

        assert result['expected_basis_per_share'] == pytest.approx(303.50)
        assert result['reconstructed_shares'] == 100

    def test_multiple_lots_are_weighted_by_shares(self):
        rows = [
            _assignment(310.00, 2.00, shares=100),   # 308.00
            _assignment(300.00, 1.00, shares=200),   # 299.00
        ]

        result = reconstruct_expected_basis(rows, 300)

        # (308*100 + 299*200) / 300
        assert result['expected_basis_per_share'] == pytest.approx(302.0)
        assert result['reconstructed_shares'] == 300

    def test_rows_are_consumed_newest_first_and_truncated_at_the_held_quantity(self):
        """After a partial call-away, FIFO disposal leaves the newest lot."""
        rows = [
            _assignment(310.00, 2.00, shares=100),   # newest
            _assignment(300.00, 1.00, shares=100),   # older, already sold
        ]

        result = reconstruct_expected_basis(rows, 100)

        assert result['expected_basis_per_share'] == pytest.approx(308.0)
        assert result['reconstructed_shares'] == 100

    def test_a_partial_lot_is_pro_rated(self):
        rows = [_assignment(310.00, 2.00, shares=200)]

        result = reconstruct_expected_basis(rows, 100)

        assert result['reconstructed_shares'] == 100
        assert result['expected_basis_per_share'] == pytest.approx(308.0)

    def test_insufficient_history_reports_the_shortfall_rather_than_guessing(self):
        """This is what surfaces as ``share_count_mismatch`` — 100 shares of
        assignment history against 200 held means something else moved them."""
        result = reconstruct_expected_basis([_assignment(305.00, 1.50)], 200)

        assert result['reconstructed_shares'] == 100
        assert result['expected_basis_per_share'] == pytest.approx(303.50)

    def test_a_missing_premium_makes_the_whole_comparison_underivable(self):
        rows = [
            _assignment(310.00, None, shares=100),
            _assignment(300.00, 1.00, shares=100),
        ]

        result = reconstruct_expected_basis(rows, 200)

        assert result['expected_basis_per_share'] is None
        # Share reconstruction still completes, so a genuine quantity mismatch
        # is not masked by the missing price.
        assert result['reconstructed_shares'] == 200

    @pytest.mark.parametrize("rows,shares_held", [
        ([], 100),
        ([_assignment(0, 1.50)], 100),
        ([_assignment(305.00, 1.50, shares=0)], 100),
        ([_assignment('bad', 1.50)], 100),
        ([_assignment(305.00, 1.50)], 0),
    ])
    def test_nothing_reconstructable_returns_none(self, rows, shares_held):
        assert reconstruct_expected_basis(rows, shares_held) is None


class TestTheBigQueryChokepoint:
    """One method, patched by the suite's hermeticity guard. A second door
    would let a unit test reach production trade history."""

    def test_the_hermeticity_guard_covers_every_resolver_instance(self):
        """The autouse conftest fixture patches the class, so a resolver built
        inside a test — by the scanner, the roller, or directly — cannot reach
        BigQuery. If this method is ever renamed, this test fails.

        Every construction site belongs here. A new one that is not listed is
        still covered (the patch is on the class), but listing it is what keeps
        this test an inventory rather than a spot check — and an entry left
        here after its site is deleted is the same rot in the other direction,
        which is why CallSeller's *absence* is asserted below rather than just
        dropped (FC-068).
        """
        assert CostBasisResolver(Mock(), Mock(spec=Config))._lookup_assignment_basis(
            'AAPL', 100) is None

        from src.data.options_scanner import OptionsScanner
        scanner = OptionsScanner(Mock(), Mock(), Mock(spec=Config))
        assert scanner.cost_basis_resolver._lookup_assignment_basis('AAPL', 100) is None

        # FC-065 Phase 2: the roller resolves its strike floor here too.
        from src.strategy.call_roller import CallRoller
        roller = CallRoller(Mock(), Mock(), Mock(spec=Config), Mock(), Mock())
        assert roller.cost_basis_resolver._lookup_assignment_basis('AAPL', 100) is None

        # FC-068 dropped the CallSeller leg: `execute_call_sale` reads its
        # floor off the opportunity (`opportunity_floor_per_share`) and the
        # class owns no resolver any more. The census must track the real
        # instance list — a stale entry here is a test asserting a
        # construction site that no longer exists, which is how an inventory
        # rots into a spot check.
        from src.strategy.call_seller import CallSeller
        assert not hasattr(CallSeller(Mock(), Mock(), Mock(spec=Config)),
                           '_cost_basis_resolver')

    @pytest.mark.real_bq_lookup
    def test_allow_bigquery_false_never_builds_a_client(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=False)

        with patch('google.cloud.bigquery.Client') as mock_client:
            assert resolver._lookup_assignment_basis('AMZN', 100) is None

        mock_client.assert_not_called()

    @pytest.mark.real_bq_lookup
    def test_a_bigquery_failure_returns_no_comparison_rather_than_raising(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)

        with patch('google.cloud.bigquery.Client',
                   side_effect=Exception("no creds in test env")):
            assert resolver._lookup_assignment_basis('AMZN', 100) is None

    @pytest.mark.real_bq_lookup
    def test_the_bigquery_client_is_constructed_once_and_cached(self):
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)
        job = Mock()
        job.result.return_value = []

        with patch('google.cloud.bigquery.Client') as mock_client:
            mock_client.return_value.query.return_value = job
            resolver._lookup_assignment_basis('AMZN', 100)
            resolver._lookup_assignment_basis('AMZN', 100)

        assert mock_client.call_count == 1

    @pytest.mark.real_bq_lookup
    def test_the_query_reconstructs_the_basis_from_returned_rows(self):
        """End-to-end through the chokepoint with the BQ client mocked at the
        SDK boundary, so the row → reconstruction wiring is covered."""
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)
        row = {'occ_symbol': 'AAPL260612P00305000', 'strike_price': 305.0,
               'shares': 100.0, 'put_premium': 1.50}
        job = Mock()
        job.result.return_value = [_FakeRow(row)]

        with patch('google.cloud.bigquery.Client') as mock_client:
            mock_client.return_value.query.return_value = job
            result = resolver._lookup_assignment_basis('AAPL', 100)

        assert result['expected_basis_per_share'] == pytest.approx(303.50)
        assert result['reconstructed_shares'] == 100

    @pytest.mark.real_bq_lookup
    def test_the_query_carries_no_lookback_bound(self):
        """FC-065 removed the 90-day window with the floor path it protected.
        As a cross-check, aged-out history degrades to 'no comparison', so a
        window would only reintroduce the dated cliff (AAPL 2026-09-11)."""
        resolver = CostBasisResolver(Mock(), Mock(spec=Config), allow_bigquery=True)
        job = Mock()
        job.result.return_value = []

        with patch('google.cloud.bigquery.Client') as mock_client:
            mock_client.return_value.query.return_value = job
            resolver._lookup_assignment_basis('AAPL', 100)

        query = mock_client.return_value.query.call_args[0][0]
        assert 'TIMESTAMP_SUB' not in query
        assert 'lookback' not in query.lower()


class _FakeRow(dict):
    """Minimal stand-in for a ``bigquery.table.Row`` (supports ``.get``)."""


class TestQualifyingStrikeSetIsUnchangedByTheInversion:
    """FC-065's acceptance test: the floor number moves by one put premium, but
    the *set of tradeable strikes* it admits does not.

    Verified against the four live lots as of 2026-07-31 (old floor = assigning
    put strike, new floor = Alpaca ``avg_entry_price``), on the $2.50 strike
    grids these underlyings trade. Asserting the strike set rather than the
    floor is the point: the floor is expected to change.
    """

    # symbol → (old floor = OPASN strike, new floor = avg_entry_price)
    LIVE_LOTS = {
        'AAPL': (305.00, 303.50),
        'AMZN': (262.50, 261.20),
        'GOOGL': (370.00, 368.34),
        'NVDA': (220.00, 218.43),
    }

    @staticmethod
    def _grid(centre, increment=2.50, span=12):
        """A $2.50 strike grid straddling the floor, as the chains quote."""
        base = round(centre / increment) * increment
        return [round(base + i * increment, 2)
                for i in range(-span, span + 1)]

    @staticmethod
    def _qualifying(strikes, floor):
        """``market_data.find_suitable_calls``' cost-basis gate: a strike is
        rejected when ``strike < min_strike_price`` — at-floor is allowed."""
        return {s for s in strikes if not (floor > 0 and s < floor)}

    @pytest.mark.parametrize("symbol", sorted(LIVE_LOTS))
    def test_the_qualifying_strike_set_is_identical_before_and_after(self, symbol):
        old_floor, new_floor = self.LIVE_LOTS[symbol]
        strikes = self._grid(old_floor)

        before = self._qualifying(strikes, old_floor)
        after = self._qualifying(strikes, new_floor)

        assert before == after, (
            f"{symbol}: floor moved {old_floor} → {new_floor} and admitted "
            f"{sorted(after - before)} that the old floor rejected")

    @pytest.mark.parametrize("symbol", sorted(LIVE_LOTS))
    def test_the_gap_is_smaller_than_the_strike_increment(self, symbol):
        """Why the sets are identical: premium-netting moves the floor by less
        than one strike increment on a $2.50 grid. This is the predicate that
        would break on a $1-grid underlying such as IWM — permitted per the
        operator's OQ-1 decision, deliberately not gated in code."""
        old_floor, new_floor = self.LIVE_LOTS[symbol]

        assert 0 < old_floor - new_floor < 2.50

    def test_a_dollar_grid_underlying_would_admit_an_in_gap_strike(self):
        """OQ-1, recorded as a test rather than as a guard: on IWM's $1 grid a
        normal put premium opens a real gap. This documents the accepted
        exception — it must NOT be read as a defect to fix, and no audit
        machinery exists for it by operator decision (2026-07-31)."""
        old_floor, new_floor = 287.50, 286.45      # IWM260803P00287500 @ $1.05
        strikes = [round(285.0 + i, 2) for i in range(0, 6)]

        before = self._qualifying(strikes, old_floor)
        after = self._qualifying(strikes, new_floor)

        assert after - before == {287.0}


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
