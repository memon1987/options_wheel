"""Tests for options scanner module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.data.options_scanner import OptionsScanner
from src.utils.config import Config

# Sentinel for "the key is not present at all", which is a distinct failure
# from "the key is present and empty" once the floor is a single broker field.
_ABSENT = object()


class TestOptionsScannerPutScan:
    """Test OptionsScanner.scan_for_put_opportunities."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.stock_symbols = ['AAPL', 'MSFT', 'GOOGL']
        self.mock_config.put_target_dte = 7
        self.mock_config.call_target_dte = 7

        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data, self.mock_config)

        # No existing positions by default
        self.mock_alpaca.get_positions.return_value = []

    def test_scan_finds_put_opportunities(self):
        """Test scanning returns scored put opportunities."""
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'AAPL', 'current_price': 175.0},
            {'symbol': 'MSFT', 'current_price': 400.0},
        ]

        self.mock_market_data.find_suitable_puts.side_effect = [
            [
                {
                    'symbol': 'AAPL250117P00170000',
                    'strike_price': 170.0,
                    'expiration_date': '2025-01-17',
                    'dte': 7,
                    'delta': -0.15,
                    'mid_price': 2.50,
                    'bid': 2.45,
                    'ask': 2.55,
                    'volume': 1500,
                    'open_interest': 5000,
                    'implied_volatility': 0.25,
                }
            ],
            [
                {
                    'symbol': 'MSFT250117P00380000',
                    'strike_price': 380.0,
                    'expiration_date': '2025-01-17',
                    'dte': 7,
                    'delta': -0.12,
                    'mid_price': 3.00,
                    'bid': 2.90,
                    'ask': 3.10,
                    'volume': 2000,
                    'open_interest': 8000,
                    'implied_volatility': 0.22,
                }
            ],
        ]

        results = self.scanner.scan_for_put_opportunities(max_results=10)

        assert len(results) == 2
        # Each result should have an attractiveness score
        for opp in results:
            assert 'attractiveness_score' in opp
            assert opp['attractiveness_score'] >= 0
            assert opp['type'] == 'put'
        # Should be sorted by attractiveness_score descending
        assert results[0]['attractiveness_score'] >= results[1]['attractiveness_score']

    def test_scan_filters_existing_positions(self):
        """Test that stocks with existing positions are skipped."""
        self.mock_alpaca.get_positions.return_value = [
            {'symbol': 'AAPL', 'asset_class': 'us_equity'},
        ]

        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'AAPL', 'current_price': 175.0},
            {'symbol': 'MSFT', 'current_price': 400.0},
        ]

        self.mock_market_data.find_suitable_puts.return_value = [
            {
                'symbol': 'MSFT250117P00380000',
                'strike_price': 380.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': -0.12,
                'mid_price': 3.00,
                'bid': 2.90,
                'ask': 3.10,
                'volume': 2000,
                'open_interest': 8000,
                'implied_volatility': 0.22,
            }
        ]

        results = self.scanner.scan_for_put_opportunities()

        # Only MSFT should appear (AAPL has existing position)
        assert len(results) == 1
        assert results[0]['symbol'] == 'MSFT'

    def test_scan_handles_empty_suitable_stocks(self):
        """Test handling when no stocks are suitable."""
        self.mock_market_data.filter_suitable_stocks.return_value = []

        results = self.scanner.scan_for_put_opportunities()
        assert results == []

    def test_scan_handles_no_puts_found(self):
        """Test handling when suitable stocks have no puts."""
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'AAPL', 'current_price': 175.0},
        ]
        self.mock_market_data.find_suitable_puts.return_value = []

        results = self.scanner.scan_for_put_opportunities()
        assert results == []

    def test_scan_handles_api_error(self):
        """Test graceful handling of API errors returns empty list."""
        self.mock_market_data.filter_suitable_stocks.side_effect = Exception("API down")

        results = self.scanner.scan_for_put_opportunities()
        assert results == []

    def test_scan_respects_max_results(self):
        """Test that max_results limits output."""
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': f'SYM{i}', 'current_price': 100.0}
            for i in range(5)
        ]

        self.mock_market_data.find_suitable_puts.return_value = [
            {
                'symbol': f'SYM250117P00090000',
                'strike_price': 90.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': -0.15,
                'mid_price': 1.50,
                'bid': 1.45,
                'ask': 1.55,
                'volume': 1000,
                'open_interest': 3000,
                'implied_volatility': 0.20,
            }
        ]

        results = self.scanner.scan_for_put_opportunities(max_results=2)
        assert len(results) <= 2


class TestOptionsScannerScoring:
    """Test opportunity scoring and ranking logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.put_target_dte = 7
        self.mock_config.call_target_dte = 7

        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_put_attractiveness_score_range(self):
        """Test put attractiveness score is between 0 and 100."""
        score = self.scanner._calculate_put_attractiveness_score(
            annual_return=15.0,
            delta=0.15,
            otm_percentage=8.0,
            liquidity_score=50.0,
            dte=5,
        )

        assert 0 <= score <= 100

    def test_put_score_higher_for_better_return(self):
        """Test that higher annual return gives higher score."""
        score_low = self.scanner._calculate_put_attractiveness_score(
            annual_return=5.0, delta=0.15, otm_percentage=8.0,
            liquidity_score=50.0, dte=5,
        )
        score_high = self.scanner._calculate_put_attractiveness_score(
            annual_return=20.0, delta=0.15, otm_percentage=8.0,
            liquidity_score=50.0, dte=5,
        )

        assert score_high > score_low

    def test_put_score_prefers_target_delta(self):
        """Test that delta near 0.20 scores higher than extremes."""
        score_ideal = self.scanner._calculate_put_attractiveness_score(
            annual_return=10.0, delta=0.20, otm_percentage=8.0,
            liquidity_score=50.0, dte=5,
        )
        score_extreme = self.scanner._calculate_put_attractiveness_score(
            annual_return=10.0, delta=0.50, otm_percentage=8.0,
            liquidity_score=50.0, dte=5,
        )

        assert score_ideal > score_extreme

    def test_call_attractiveness_score_above_cost_basis_bonus(self):
        """Test that calls above cost basis get a bonus."""
        score_above = self.scanner._calculate_call_attractiveness_score(
            annual_return=10.0, delta=0.15, otm_percentage=5.0,
            liquidity_score=50.0, dte=5, above_cost_basis=True,
        )
        score_below = self.scanner._calculate_call_attractiveness_score(
            annual_return=10.0, delta=0.15, otm_percentage=5.0,
            liquidity_score=50.0, dte=5, above_cost_basis=False,
        )

        assert score_above > score_below

    def test_put_score_zero_for_bad_dte(self):
        """Test that DTE exceeding target gets zero DTE component."""
        score_good = self.scanner._calculate_put_attractiveness_score(
            annual_return=10.0, delta=0.15, otm_percentage=8.0,
            liquidity_score=50.0, dte=5,  # Within target
        )
        score_bad = self.scanner._calculate_put_attractiveness_score(
            annual_return=10.0, delta=0.15, otm_percentage=8.0,
            liquidity_score=50.0, dte=30,  # Way past target of 7
        )

        assert score_good > score_bad

    def test_call_score_range(self):
        """Test call attractiveness score is between 0 and 100."""
        score = self.scanner._calculate_call_attractiveness_score(
            annual_return=10.0, delta=0.15, otm_percentage=5.0,
            liquidity_score=50.0, dte=5, above_cost_basis=True,
        )

        assert 0 <= score <= 100


class TestOptionsScannerCallScan:
    """Test OptionsScanner.scan_for_call_opportunities."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7

        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_scan_call_opportunities_with_stock_positions(self):
        """Test scanning for calls when stock positions exist."""
        self.mock_alpaca.get_positions.return_value = [
            {
                'symbol': 'AAPL',
                'qty': '100',
                'cost_basis': '16000.0',
                'avg_entry_price': '160.0',
                'asset_class': 'us_equity',
                'side': 'long',
            }
        ]

        self.mock_market_data.get_stock_metrics.return_value = {
            'current_price': 175.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'bid': 1.75,
                'ask': 1.85,
                'volume': 2000,
                'open_interest': 8000,
                'implied_volatility': 0.22,
            }
        ]

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['type'] == 'call'
        assert results[0]['symbol'] == 'AAPL'
        assert results[0]['max_contracts'] == 1
        # Should filter by cost basis
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0
        )

    def test_multiple_round_lots_size_to_every_lot(self):
        """FC-068 migration of the engine path's `test_multiple_round_lots`.

        A 300-share position must offer 3 contracts, not 1. The deleted
        `_calculate_call_position` pinned this; nothing on the scanner path
        did — `test_scan_call_opportunities_with_stock_positions` only ever
        used 100 shares, so a `max_contracts = 1` regression would have been
        invisible after the deletion.
        """
        self.mock_alpaca.get_positions.return_value = [
            {
                'symbol': 'AAPL',
                'qty': '300',
                'cost_basis': '48000.0',
                'avg_entry_price': '160.0',
                'asset_class': 'us_equity',
                'side': 'long',
            }
        ]
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 175.0}
        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'bid': 1.75,
                'ask': 1.85,
                'volume': 2000,
                'open_interest': 8000,
                'implied_volatility': 0.22,
            }
        ]

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['shares_owned'] == 300
        assert results[0]['max_contracts'] == 3
        # Premium income must scale with the lots, not with a bare 100.
        assert results[0]['premium_income'] == pytest.approx(1.80 * 100 * 3)

    def test_scan_call_skips_insufficient_shares(self):
        """Test that positions with < 100 shares are skipped."""
        self.mock_alpaca.get_positions.return_value = [
            {
                'symbol': 'AAPL',
                'qty': '50',
                'cost_basis': '8000.0',
                'asset_class': 'us_equity',
                'side': 'long',
            }
        ]

        results = self.scanner.scan_for_call_opportunities()
        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_scan_call_handles_empty_positions(self):
        """Test handling when no stock positions exist."""
        self.mock_alpaca.get_positions.return_value = []

        results = self.scanner.scan_for_call_opportunities()
        assert results == []


class TestCallScanFailsClosedOnUnresolvedCostBasis:
    """An unresolved cost basis must emit NO call opportunities (FC-038 review).

    This floor is the operative below-basis protection on the live path:
    `find_suitable_calls` only warns when `min_strike_price <= 0` and carries
    on. FC-065 makes the floor Alpaca's `avg_entry_price`, so the failure this
    guards is the broker reporting nothing usable for that field — FC-029
    observed exactly that (`cost_basis = 0`) on assigned paper positions, and
    the whole floor now rests on one field of the same payload.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 175.0}
        self.mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'AAPL250117C00185000', 'strike_price': 185.0,
            'expiration_date': '2025-01-17', 'dte': 7, 'delta': 0.15,
            'mid_price': 1.80, 'bid': 1.75, 'ask': 1.85, 'volume': 2000,
            'open_interest': 8000, 'implied_volatility': 0.22,
        }]

    def _position(self, avg_entry_price, cost_basis='16000.0'):
        position = {'symbol': 'AAPL', 'qty': '100', 'cost_basis': cost_basis,
                    'asset_class': 'us_equity', 'side': 'long'}
        if avg_entry_price is not _ABSENT:
            position['avg_entry_price'] = avg_entry_price
        return position

    # 'nonsense' added by FC-068: it is the third parametrization of the
    # engine-path test this one replaces
    # (`test_no_cost_basis_floor_resolved_blocks_call_write[0.0/None/nonsense]`),
    # and an unparseable string is a distinct failure from a zero or an absent
    # field — it reaches float() rather than the falsy checks.
    @pytest.mark.parametrize("avg_entry_price",
                             ['0', '0.0', 0, None, '', 'nonsense', _ABSENT])
    def test_unresolved_cost_basis_emits_nothing(self, avg_entry_price):
        self.mock_alpaca.get_positions.return_value = [
            self._position(avg_entry_price)]

        with patch('src.data.options_scanner.logger') as mock_logger:
            results = self.scanner.scan_for_call_opportunities()

        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called(), (
            "an unprotected chain scan was run with a zero floor")
        skips = [c.kwargs for c in mock_logger.warning.call_args_list
                 if c.kwargs.get("event_type") == "call_scan_skipped_cost_basis_unresolved"]
        assert len(skips) == 1
        assert skips[0]["event_category"] == "trade"
        assert skips[0]["symbol"] == "AAPL"
        assert skips[0]["shares"] == 100
        assert skips[0]["avg_entry_price"] == 0.0

    def test_a_positive_cost_basis_does_not_rescue_a_missing_avg_entry_price(self):
        """FC-065 fail-closed: ``cost_basis`` is not a second floor source. The
        derivation lives in the client wrapper; a position dict arriving here
        without the field means the plumbing is broken, and writing calls
        against a guessed floor is the outcome this guard exists to prevent."""
        self.mock_alpaca.get_positions.return_value = [
            self._position(_ABSENT, cost_basis='16000.0')]

        results = self.scanner.scan_for_call_opportunities()

        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_a_valid_cost_basis_still_produces_opportunities(self):
        """The guard must not cost us the calls we are entitled to sell."""
        self.mock_alpaca.get_positions.return_value = [self._position('160.0')]

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['symbol'] == 'AAPL'
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0)

    def test_one_bad_position_does_not_suppress_a_good_one(self):
        self.mock_alpaca.get_positions.return_value = [
            self._position('0'),
            {'symbol': 'MSFT', 'qty': '100', 'cost_basis': '38000.0',
             'avg_entry_price': '380.0', 'asset_class': 'us_equity',
             'side': 'long'},
        ]

        results = self.scanner.scan_for_call_opportunities()

        assert [r['symbol'] for r in results] == ['MSFT']


class TestCallScanFloorIsTheBrokerBasisCrossCheckedAgainstBigQuery:
    """FC-065 Phase 1: the scanner's floor is Alpaca's ``avg_entry_price``, and
    BigQuery runs inline per held symbol per scan as a divergence cross-check
    that can veto it.

    This inverts FC-050, where a BigQuery-resolved OPASN strike *set* the floor
    and the broker was the last resort.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 310.0}
        self.mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'AAPL260821C00320000', 'strike_price': 320.0,
            'expiration_date': '2026-08-21', 'dte': 7, 'delta': 0.20,
            'mid_price': 1.80, 'bid': 1.75, 'ask': 1.85, 'volume': 2000,
            'open_interest': 8000, 'implied_volatility': 0.22,
        }]
        # An assigned AAPL lot: assigning put struck 305.00, sold for $1.50, so
        # the broker reports the premium-netted 303.50.
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '30350.0',
            'avg_entry_price': '303.50', 'asset_class': 'us_equity',
            'side': 'long',
        }]

    def _with_reconstruction(self, expected, shares=100):
        """Inject the cross-check's BigQuery answer (the suite stubs the real
        chokepoint out, so a test that wants one supplies it explicitly)."""
        return patch.object(
            self.scanner.cost_basis_resolver, '_lookup_assignment_basis',
            return_value={'expected_basis_per_share': expected,
                          'reconstructed_shares': shares, 'lots': []})

    def test_the_broker_basis_filters_the_chain_and_rides_the_opportunity(self):
        with self._with_reconstruction(303.50):
            results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        # The broker's number filtered the chain scan...
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=303.50)
        # ...and is the same number carried on the opportunity, which is what
        # call_seller enforces at execution.
        assert results[0]['cost_basis_per_share'] == 303.50
        assert results[0]['assignment_above_cost_basis'] is True
        # (320 - 303.50) * 100 + 1.80 * 100 = 1830.0
        assert results[0]['total_return_if_assigned'] == pytest.approx(1830.0)

    def test_a_divergent_cross_check_skips_the_symbol(self):
        """Fails if the cross-check is reverted to warn-only: the assertion is
        that no chain scan ran and no opportunity was emitted, not that a
        warning was written."""
        with self._with_reconstruction(290.00):
            with patch('src.data.options_scanner.logger') as mock_logger:
                results = self.scanner.scan_for_call_opportunities()

        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called()

        skips = [c.kwargs for c in mock_logger.warning.call_args_list
                 if c.kwargs.get("event_type") == "call_scan_skipped_cost_basis_divergent"]
        assert len(skips) == 1
        assert skips[0]["event_category"] == "trade"
        assert skips[0]["symbol"] == "AAPL"
        assert skips[0]["broker_basis"] == 303.50
        assert skips[0]["expected_basis"] == 290.00
        assert skips[0]["basis_delta"] == pytest.approx(13.50)
        assert skips[0]["reason"] == "basis_mismatch"

    def test_a_share_count_mismatch_skips_the_symbol(self):
        with self._with_reconstruction(303.50, shares=200):
            with patch('src.data.options_scanner.logger') as mock_logger:
                results = self.scanner.scan_for_call_opportunities()

        assert results == []
        skips = [c.kwargs for c in mock_logger.warning.call_args_list
                 if c.kwargs.get("event_type") == "call_scan_skipped_cost_basis_divergent"]
        assert skips[0]["reason"] == "share_count_mismatch"
        assert skips[0]["reconstructed_shares"] == 200

    def test_an_agreeing_cross_check_is_logged_with_its_verdict(self):
        with self._with_reconstruction(303.45):
            with patch('src.data.options_scanner.logger') as mock_logger:
                results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        events = [c.kwargs for c in mock_logger.info.call_args_list
                  if c.kwargs.get("event_type") == "cost_basis_cross_check"]
        assert len(events) == 1
        assert events[0]["symbol"] == "AAPL"
        assert events[0]["source"] == "alpaca"
        assert events[0]["resolved_basis"] == 303.50
        assert events[0]["status"] == "ok"
        assert events[0]["expected_basis"] == 303.45

    def test_an_unavailable_cross_check_is_logged_but_keeps_the_floor(self):
        """No assignment history (a manual buy, or BigQuery down) means no
        comparison — which must not be mistaken for an all-clear, hence the
        event carries the status either way."""
        with patch('src.data.options_scanner.logger') as mock_logger:
            results = self.scanner.scan_for_call_opportunities()  # suite stub → None

        assert len(results) == 1
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=303.50)
        events = [c.kwargs for c in mock_logger.info.call_args_list
                  if c.kwargs.get("event_type") == "cost_basis_cross_check"]
        assert len(events) == 1
        assert events[0]["status"] == "unavailable"
        assert events[0]["reason"] == "no_assignment_history"
        assert events[0]["resolved_basis"] == 303.50

    def test_nothing_resolves_still_emits_no_opportunities(self):
        """FC-038's fail-closed skip survives, now on the broker field."""
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '0',
            'avg_entry_price': '0', 'asset_class': 'us_equity', 'side': 'long',
        }]

        results = self.scanner.scan_for_call_opportunities()

        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called()


class TestAtFloorStrikesAreFlaggedTheWayTheGatesTreatThem:
    """FC-065 Phase 2: ``assignment_above_cost_basis`` is ``strike >= floor``.

    Every floor gate rejects only ``strike < floor`` — ``market_data``'s chain
    filter, ``call_seller``'s execute-time check
    (``test_a_strike_exactly_at_basis_is_allowed``), and
    ``risk_manager.validate_roll``
    (``test_a_strike_exactly_at_the_floor_is_allowed``). So an at-floor call is
    admitted and sold, and GOOGL's 370C was. Under strict ``>`` the flag read
    ``False`` on exactly those writes: a warning that gated nothing and
    contradicted what the bot had just done.

    At-floor is the decided policy, not an edge case to close — called away at
    cost keeps both premiums and gives up no capital.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 372.0}
        # GOOGL's real shape: floor 368.34, and the only candidate is struck
        # exactly there.
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'GOOGL', 'qty': '100', 'cost_basis': '36834.0',
            'avg_entry_price': '368.34', 'asset_class': 'us_equity',
            'side': 'long',
        }]

    def _chain(self, strike):
        self.mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'GOOGL260821C%08d' % int(strike * 1000),
            'strike_price': strike, 'expiration_date': '2026-08-21', 'dte': 7,
            'delta': 0.20, 'mid_price': 2.10, 'bid': 2.05, 'ask': 2.15,
            'volume': 1500, 'open_interest': 6000, 'implied_volatility': 0.24,
        }]

    def test_a_strike_exactly_at_the_floor_is_flagged_above_the_basis(self):
        """The mutation target. Reverted to strict ``>`` this asserts False on
        a write the gates admit and the bot executes."""
        self._chain(368.34)

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['strike_price'] == 368.34
        assert results[0]['cost_basis_per_share'] == 368.34
        assert results[0]['assignment_above_cost_basis'] is True

    def test_the_floor_was_handed_to_the_chain_gate_that_admitted_it(self):
        """The other half of the reconciliation: the same number that produced
        the flag is the ``min_strike_price`` the chain scan filtered on, and
        that filter rejects only ``strike < min_strike_price``."""
        self._chain(368.34)

        self.scanner.scan_for_call_opportunities()

        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'GOOGL', min_strike_price=368.34)

    def test_a_strike_above_the_floor_is_still_flagged_above(self):
        self._chain(375.00)

        results = self.scanner.scan_for_call_opportunities()

        assert results[0]['assignment_above_cost_basis'] is True

    def test_a_strike_below_the_floor_is_still_flagged_below(self):
        """``>=`` loosened the boundary by one point, not the predicate. A
        below-floor strike — which the chain gate would never return, so this
        pins the flag itself — still reads False."""
        self._chain(360.00)

        results = self.scanner.scan_for_call_opportunities()

        assert results[0]['assignment_above_cost_basis'] is False


class TestAtFloorStrikesAreScoredTheWayTheyAreFlagged:
    """FC-071: the ``above_cost_basis`` scoring input is the same ``>=``
    comparison as the flag, so gate, flag, and score all agree that at-floor
    is good.

    FC-065 Phase 2 moved the flag to ``>=`` but deliberately left the scoring
    input on strict ``>`` for an operator decision. The result was an at-floor
    candidate that was *flagged* at-or-above basis while being *scored* as
    below-basis — 5 points instead of 15, a 10-point swing in a 0-100 score
    that ranks a genuinely profitable write below its peers. The operator
    decided to align (2026-08-02).

    Exact equality is near measure-zero on premium-netted floors against
    $2.50 strike grids, so this is consistency hygiene rather than a shift on
    today's book. These tests pin the boundary semantics: they fail on any
    ``>`` vs ``>=`` divergence between the flag and the scoring input.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 372.0}
        # Same GOOGL shape as the flag tests above: floor 368.34.
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'GOOGL', 'qty': '100', 'cost_basis': '36834.0',
            'avg_entry_price': '368.34', 'asset_class': 'us_equity',
            'side': 'long',
        }]

    def _chain(self, strike):
        self.mock_market_data.find_suitable_calls.return_value = [{
            # round(), not int(): the OCC strike field is in thousandths and
            # strike * 1000 can land a hair below the integer in float, which
            # int() would truncate down by a tenth of a cent.
            'symbol': 'GOOGL260821C%08d' % round(strike * 1000),
            'strike_price': strike, 'expiration_date': '2026-08-21', 'dte': 7,
            'delta': 0.20, 'mid_price': 2.10, 'bid': 2.05, 'ask': 2.15,
            'volume': 1500, 'open_interest': 6000, 'implied_volatility': 0.24,
        }]

    def _score_with(self, opportunity, above_cost_basis):
        """Re-score an emitted opportunity from its own published components,
        varying only the basis input. Reading the components back off the dict
        keeps this independent of the scan's internal arithmetic."""
        return self.scanner._calculate_call_attractiveness_score(
            opportunity['annual_premium_return_percent'],
            opportunity['delta'],
            opportunity['otm_percentage'],
            opportunity['liquidity_score'],
            opportunity['dte'],
            above_cost_basis,
        )

    def test_a_strike_exactly_at_the_floor_earns_the_above_basis_bonus(self):
        """The mutation target. Reverted to strict ``>``, the at-floor
        opportunity carries the 5-point below-basis consolation instead of the
        15-point bonus and this fails on both assertions."""
        self._chain(368.34)

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        opportunity = results[0]
        assert opportunity['strike_price'] == 368.34
        assert opportunity['cost_basis_per_share'] == 368.34

        with_bonus = self._score_with(opportunity, True)
        without_bonus = self._score_with(opportunity, False)
        # This pins the current 15-vs-5 spread at 10 points. It is a pin, not
        # a derivation: if FC-073 retunes the basis weights this assert must
        # be updated deliberately — which is the intended prompt to re-confirm
        # that at-floor still ranks with the above-basis cohort.
        assert with_bonus - without_bonus == pytest.approx(10)
        # The emitted score is the with-bonus one, not the consolation.
        assert opportunity['attractiveness_score'] == pytest.approx(with_bonus)
        assert opportunity['attractiveness_score'] != pytest.approx(without_bonus)

    def test_an_at_floor_strike_scores_the_same_as_one_cent_above(self):
        """The boundary is no longer a scoring cliff: a penny of extra capital
        gain must not be worth 10 points of rank."""
        self._chain(368.34)
        at_floor = self.scanner.scan_for_call_opportunities()[0]

        self._chain(368.35)
        above_floor = self.scanner.scan_for_call_opportunities()[0]

        assert above_floor['assignment_above_cost_basis'] is True
        # Both sides of the boundary now collect the same 15-point bonus, so
        # the residual gap is only the OTM/return effect of the extra cent.
        assert abs(above_floor['attractiveness_score']
                   - at_floor['attractiveness_score']) < 1

    @pytest.mark.parametrize('strike', [360.00, 368.34, 368.35, 375.00])
    def test_the_flag_and_the_scoring_input_are_the_same_value(self, strike):
        """FC-071's real contract: one comparison feeds both surfaces. This
        fails on any semantic divergence (``>`` vs ``>=``) at the boundary —
        the drift FC-071 closed. It does not, and cannot, catch a
        semantics-preserving refactor that merely re-derives one side from an
        equivalent comparison; the single-source shape in the scanner is what
        guards against that. Below-floor is included because the parameter
        contract survives even though the chain gate would never return such
        a strike."""
        self._chain(strike)
        recorded = {}
        real_score = self.scanner._calculate_call_attractiveness_score

        def spy(*args, **kwargs):
            # ``above_cost_basis`` is the 6th positional parameter.
            recorded['above_cost_basis'] = (
                kwargs['above_cost_basis'] if 'above_cost_basis' in kwargs
                else args[5]
            )
            return real_score(*args, **kwargs)

        self.scanner._calculate_call_attractiveness_score = spy

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert 'above_cost_basis' in recorded, 'scoring was never invoked'
        assert recorded['above_cost_basis'] is (strike >= 368.34)
        assert recorded['above_cost_basis'] is results[0]['assignment_above_cost_basis']


class TestCallScanFailsClosedOnAnUnusableQuote:
    """FC-065 (folded in from the removed Phase 3): a failed stock quote used
    to fail OPEN — the opportunity was emitted anyway, with every price-derived
    metric computed against a current price of 0."""

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        self.mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'AAPL260821C00320000', 'strike_price': 320.0,
            'expiration_date': '2026-08-21', 'dte': 7, 'delta': 0.20,
            'mid_price': 1.80, 'bid': 1.75, 'ask': 1.85, 'volume': 2000,
            'open_interest': 8000, 'implied_volatility': 0.22,
        }]
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '30350.0',
            'avg_entry_price': '303.50', 'asset_class': 'us_equity',
            'side': 'long',
        }]

    @pytest.mark.parametrize("metrics", [
        {},                                # no metrics at all
        {'current_price': 0},              # quote came back empty
        {'current_price': None},
        {'current_price': 'n/a'},          # malformed
        None,                              # get_stock_metrics returned nothing
    ])
    def test_an_unusable_quote_emits_no_opportunity(self, metrics):
        self.mock_market_data.get_stock_metrics.return_value = metrics

        with patch('src.data.options_scanner.logger') as mock_logger:
            results = self.scanner.scan_for_call_opportunities()

        assert results == []
        skips = [c.kwargs for c in mock_logger.warning.call_args_list
                 if c.kwargs.get("event_type") == "call_scan_skipped_quote_unavailable"]
        assert len(skips) == 1
        assert skips[0]["symbol"] == "AAPL"

    def test_a_usable_quote_still_produces_the_opportunity(self):
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 310.0}

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['current_stock_price'] == 310.0


class TestOptionsScannerScanAll:
    """Test OptionsScanner.scan_all_opportunities."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.stock_symbols = ['AAPL']
        self.mock_config.put_target_dte = 7
        self.mock_config.call_target_dte = 7

        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data, self.mock_config)
        self.mock_alpaca.get_positions.return_value = []

    def test_scan_all_returns_both_types(self):
        """Test that scan_all returns both puts and calls keys."""
        self.mock_market_data.filter_suitable_stocks.return_value = []

        result = self.scanner.scan_all_opportunities()

        assert 'puts' in result
        assert 'calls' in result
        assert 'scan_timestamp' in result
        assert 'total_opportunities' in result

    def test_scan_all_handles_exception(self):
        """Test graceful error handling in scan_all."""
        self.mock_market_data.filter_suitable_stocks.side_effect = Exception("Timeout")

        result = self.scanner.scan_all_opportunities()

        # The inner scan catches its own error and returns [],
        # so scan_all should still succeed
        assert 'puts' in result
        assert result['puts'] == []


class TestScanStageDecisionRecords:
    """FC-065 Phase 4: every held symbol gets a decision, every cycle.

    Before this, an underwater symbol produced *silence* — NVDA has ended
    every scan since 2026-07-30 at `stage_8_complete_not_found` with nothing
    downstream saying so. The acceptance test for this phase is that the
    silence becomes a labelled row.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7

        self.scanner = OptionsScanner(self.mock_alpaca, self.mock_market_data,
                                      self.mock_config)
        # Deterministic label: the hermeticity fixture already forces the
        # BigQuery chokepoint to "no comparison"; tests that care inject one.
        self.scanner.uncovered_days_resolver._lookup_uncovered_days = (
            lambda symbols: {s: 9 for s in symbols})
        self.mock_market_data.last_call_rejection_stats = {}
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 199.0}

    # -- helpers ---------------------------------------------------- #

    @staticmethod
    def _nvda(qty=100, avg_entry_price='218.43', market_value='19900.0'):
        return {
            'symbol': 'NVDA', 'qty': str(qty), 'cost_basis': '21843.0',
            'avg_entry_price': avg_entry_price, 'market_value': market_value,
            'asset_class': 'us_equity', 'side': 'long',
        }

    def _rows(self, run_id="20260803T140000Z-abcdef12", **kw):
        captured = []
        with patch('src.data.decision_record.DecisionRecorder.flush',
                   autospec=True,
                   side_effect=lambda self, **_: captured.extend(self.rows)):
            self.scanner.scan_for_call_opportunities(run_id=run_id, **kw)
        return captured

    # -- the acceptance test ---------------------------------------- #

    def test_the_nothing_happened_case_produces_a_labelled_row(self):
        """NVDA's silent exclusion becomes a row — the phase's acceptance test."""
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = []
        self.mock_market_data.last_call_rejection_stats = {
            'NVDA': {'below_cost_basis': 41, 'delta_out_of_range': 0,
                     'premium_too_low': 2, 'total_rejected': 43},
        }

        rows = self._rows()

        assert len(rows) == 1
        row = rows[0]
        assert row['symbol'] == 'NVDA'
        assert row['outcome'] == 'no_candidates'
        assert row['reason'] == 'no_qualifying_strikes'
        assert row['candidates'] == 0
        assert row['cost_basis_per_share'] == 218.43
        # Both legibility labels present and meaningful.
        assert row['underwater_pct'] == pytest.approx(-0.088953, abs=1e-6)
        assert row['uncovered_days'] == 9
        # The chain breakdown rides along as a REPEATED record, and the
        # meaningless roll-up is not one of its entries.
        assert row['reason_counts'] == [
            {'reason': 'below_cost_basis', 'count': 41},
            {'reason': 'premium_too_low', 'count': 2},
        ]

    def test_under_100_shares_is_recorded_not_just_skipped(self):
        self.mock_alpaca.get_positions.return_value = [
            self._nvda(qty=50, market_value='9950.0')]

        rows = self._rows()

        assert [(r['outcome'], r['reason']) for r in rows] == [
            ('not_eligible', 'insufficient_shares')]
        assert rows[0]['shares'] == 50

    def test_an_unresolved_floor_is_recorded_as_blocked(self):
        self.mock_alpaca.get_positions.return_value = [
            self._nvda(avg_entry_price='0')]

        rows = self._rows()

        assert [(r['outcome'], r['reason']) for r in rows] == [
            ('blocked', 'floor_unresolved')]

    def test_a_divergent_cross_check_is_recorded_as_blocked(self):
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.scanner.cost_basis_resolver._lookup_assignment_basis = (
            lambda symbol, shares_held: {
                'expected_basis_per_share': 300.0, 'reconstructed_shares': 100})

        rows = self._rows()

        assert [(r['outcome'], r['reason']) for r in rows] == [
            ('blocked', 'floor_divergent')]

    @staticmethod
    def _chain():
        return [{
            'symbol': 'NVDA260807C00230000', 'strike_price': 230.0,
            'expiration_date': '2026-08-07', 'dte': 7, 'delta': 0.18,
            'mid_price': 1.20, 'bid': 1.15, 'ask': 1.25,
            'volume': 900, 'open_interest': 3000, 'implied_volatility': 0.4,
        }]

    def test_a_symbol_with_candidates_is_deferred_to_the_run_stage(self):
        """Its terminal verdict is `sold`/`dropped`, which only /run knows."""
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = self._chain()

        rows = self._rows()

        assert rows == []

    def test_candidates_carry_the_scan_labels_into_the_run_stage(self):
        """BLOCKER: without this every /run row had a NULL uncovered_days.

        /run is a separate stateless request with no positions snapshot and no
        BigQuery lookup, so the labels have to ride the blob exactly as
        `run_id` does.
        """
        from src.data.decision_record import decision_labels

        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = self._chain()

        opportunities = self.scanner.scan_for_call_opportunities(run_id="R1")

        assert len(opportunities) == 1
        labels = decision_labels(opportunities[0])
        assert labels['uncovered_days'] == 9
        assert labels['shares'] == 100
        assert labels['current_price'] == pytest.approx(199.0)
        assert labels['underwater'] == pytest.approx(-0.088953, abs=1e-6)

    def test_a_covered_symbol_with_candidates_stamps_zero_days(self):
        """The path the old covered-symbol test did NOT exercise.

        A covered symbol has candidates far more often than not, so it is
        terminated by /run — and a NULL there is what mailed the operator a
        CHECK_FAILED every trading day.
        """
        from src.data.decision_record import decision_labels

        self.mock_alpaca.get_positions.return_value = [
            self._nvda(),
            {'symbol': 'NVDA260807C00230000', 'qty': '-1',
             'asset_class': 'us_option', 'side': 'short', 'market_value': '-120.0'},
        ]
        self.mock_market_data.find_suitable_calls.return_value = self._chain()
        self.scanner.uncovered_days_resolver._lookup_uncovered_days = (
            lambda symbols: (_ for _ in ()).throw(
                AssertionError("must not query for a covered symbol")))

        opportunities = self.scanner.scan_for_call_opportunities(run_id="R1")

        assert decision_labels(opportunities[0])['uncovered_days'] == 0

    def test_a_builder_failure_is_not_filed_as_a_bad_quote(self):
        """A closed vocabulary that misfiles is worse than one more value."""
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = self._chain()
        # Quote is fine; the builder swallowed its own exception and returned
        # None, which is exactly what its `except` clause does in production.
        self.scanner._create_call_opportunity = lambda *a, **k: None

        rows = self._rows()

        assert [(r['outcome'], r['reason']) for r in rows] == [
            ('no_candidates', 'opportunity_build_failed')]

    def test_a_dead_quote_records_no_candidates_rather_than_vanishing(self):
        # The chain HAD qualifying strikes; opportunity construction failed
        # closed on an unusable quote (Phase 1). That must not be silence.
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = [{
            'symbol': 'NVDA260807C00230000', 'strike_price': 230.0,
            'expiration_date': '2026-08-07', 'dte': 7, 'delta': 0.18,
            'mid_price': 1.20, 'bid': 1.15, 'ask': 1.25,
            'volume': 900, 'open_interest': 3000, 'implied_volatility': 0.4,
        }]
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 0}

        rows = self._rows()

        assert [(r['outcome'], r['reason']) for r in rows] == [
            ('no_candidates', 'quote_unavailable')]

    def test_every_held_symbol_gets_exactly_one_row(self):
        self.mock_alpaca.get_positions.return_value = [
            self._nvda(),
            {'symbol': 'AAPL', 'qty': '100', 'cost_basis': '30350.0',
             'avg_entry_price': '303.50', 'market_value': '31000.0',
             'asset_class': 'us_equity', 'side': 'long'},
            {'symbol': 'F', 'qty': '40', 'cost_basis': '400.0',
             'avg_entry_price': '10.0', 'market_value': '440.0',
             'asset_class': 'us_equity', 'side': 'long'},
        ]
        self.mock_market_data.find_suitable_calls.return_value = []

        rows = self._rows()

        assert sorted(r['symbol'] for r in rows) == ['AAPL', 'F', 'NVDA']
        assert len({r['dedup_key'] for r in rows}) == 3

    def test_all_rows_carry_the_run_id_they_were_given(self):
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = []

        rows = self._rows(run_id="20260803T150000Z-99887766")

        assert rows[0]['run_id'] == "20260803T150000Z-99887766"
        assert rows[0]['dedup_key'] == "20260803T150000Z-99887766|NVDA|scan"
        assert rows[0]['stage'] == 'scan'
        assert rows[0]['endpoint'] == '/scan'

    def test_a_covered_symbol_reports_zero_uncovered_days(self):
        # An open short call on the underlying means covered TODAY, answered
        # from the positions snapshot without a BigQuery round trip.
        self.mock_alpaca.get_positions.return_value = [
            self._nvda(),
            {'symbol': 'NVDA260807C00230000', 'qty': '-1',
             'asset_class': 'us_option', 'side': 'short', 'market_value': '-120.0'},
        ]
        self.mock_market_data.find_suitable_calls.return_value = []
        self.scanner.uncovered_days_resolver._lookup_uncovered_days = (
            lambda symbols: (_ for _ in ()).throw(
                AssertionError("must not query for a covered symbol")))

        rows = self._rows()

        assert rows[0]['uncovered_days'] == 0

    def test_an_underivable_uncovered_days_is_null_not_zero(self):
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = []
        self.scanner.uncovered_days_resolver._lookup_uncovered_days = (
            lambda symbols: None)

        rows = self._rows()

        assert rows[0]['uncovered_days'] is None

    def test_records_survive_a_scan_that_dies_partway(self):
        # A cycle that crashed is exactly the cycle worth investigating; the
        # rows it did produce must not die with it.
        self.mock_alpaca.get_positions.return_value = [
            self._nvda(qty=50, market_value='9950.0'), self._nvda()]
        self.mock_market_data.find_suitable_calls.side_effect = Exception("chain down")

        rows = self._rows()

        assert [r['symbol'] for r in rows] == ['NVDA']
        assert rows[0]['outcome'] == 'not_eligible'

    def test_a_chain_exception_emits_no_opportunity(self):
        """FC-068 migration of `test_api_error_returns_none`.

        The test above pins that the *records* survive a mid-scan exception.
        The deleted engine-path test pinned the other half — that the scan
        emits nothing rather than a half-built opportunity — and nothing on
        the scanner path asserted it.
        """
        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.side_effect = Exception("chain down")

        assert self.scanner.scan_for_call_opportunities() == []

    def test_a_scan_without_a_run_id_still_records_under_a_minted_one(self):
        from src.data.decision_record import is_run_id

        self.mock_alpaca.get_positions.return_value = [self._nvda()]
        self.mock_market_data.find_suitable_calls.return_value = []

        captured = []
        with patch('src.data.decision_record.DecisionRecorder.flush',
                   autospec=True,
                   side_effect=lambda self, **_: captured.extend(self.rows)):
            self.scanner.scan_for_call_opportunities()

        assert len(captured) == 1
        assert is_run_id(captured[0]['run_id'])
