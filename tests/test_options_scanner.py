"""Tests for options scanner module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.data.options_scanner import OptionsScanner
from src.utils.config import Config


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
        # Should filter by cost basis
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0
        )

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
    on, and the execute-time floor in call_seller is dead (FC-050, the
    `stock_cost_basis` key mismatch). Alpaca returns `cost_basis` 0 for
    freshly assigned positions (FC-029), so a basis of 0 must mean "no calls",
    never "calls at any strike".
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

    def _position(self, cost_basis):
        return {'symbol': 'AAPL', 'qty': '100', 'cost_basis': cost_basis,
                'asset_class': 'us_equity', 'side': 'long'}

    @pytest.mark.parametrize("cost_basis", ['0', '0.0', 0, None, ''])
    def test_unresolved_cost_basis_emits_nothing(self, cost_basis):
        self.mock_alpaca.get_positions.return_value = [self._position(cost_basis)]

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
        assert skips[0]["cost_basis"] == 0.0

    def test_a_valid_cost_basis_still_produces_opportunities(self):
        """The guard must not cost us the calls we are entitled to sell."""
        self.mock_alpaca.get_positions.return_value = [self._position('16000.0')]

        results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert results[0]['symbol'] == 'AAPL'
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0)

    def test_one_bad_position_does_not_suppress_a_good_one(self):
        self.mock_alpaca.get_positions.return_value = [
            self._position('0'),
            {'symbol': 'MSFT', 'qty': '100', 'cost_basis': '38000.0',
             'asset_class': 'us_equity', 'side': 'long'},
        ]

        results = self.scanner.scan_for_call_opportunities()

        assert [r['symbol'] for r in results] == ['MSFT']


class TestCallScanResolvesCostBasisViaTheFC029Chain:
    """FC-050: the scanner's floor comes from the shared resolution chain.

    Alpaca reports ``cost_basis = 0`` for freshly assigned positions — exactly
    the moment the wheel next writes a call. Before FC-050 the scanner read
    that field directly, so the symbol was skipped (FC-038) even though the
    assigning put's strike was sitting in BigQuery.
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
        # An assigned position: shares held, broker cost basis lost.
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '0',
            'asset_class': 'us_equity', 'side': 'long',
        }]

    def _with_opasn_strike(self, strike):
        """Inject the BigQuery source explicitly (the suite stubs the real one)."""
        return patch.object(self.scanner.cost_basis_resolver,
                            '_lookup_last_opasn_put_strike', return_value=strike)

    def test_a_bigquery_resolved_basis_produces_opportunities(self):
        with self._with_opasn_strike(303.50):
            results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        # The chain's number filtered the chain scan...
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=303.50)
        # ...and is the same number carried on the opportunity, which is what
        # call_seller now enforces at execution.
        assert results[0]['cost_basis_per_share'] == 303.50
        assert results[0]['assignment_above_cost_basis'] is True
        # (320 - 303.50) * 100 + 1.80 * 100 = 1830.0
        assert results[0]['total_return_if_assigned'] == pytest.approx(1830.0)

    def test_a_fallback_source_is_logged_for_provenance(self):
        with self._with_opasn_strike(303.50):
            with patch('src.data.options_scanner.logger') as mock_logger:
                self.scanner.scan_for_call_opportunities()

        events = [c.kwargs for c in mock_logger.info.call_args_list
                  if c.kwargs.get("event_type") == "cost_basis_resolved_via_fallback"]
        assert len(events) == 1
        assert events[0]["symbol"] == "AAPL"
        assert events[0]["source"] == "bigquery"
        assert events[0]["resolved_basis"] == 303.50
        # Alpaca had nothing to say here, so there is nothing to compare.
        assert events[0]["alpaca_cost_basis_per_share"] == 0.0
        assert events[0]["basis_delta"] is None

    def test_a_bigquery_broker_divergence_is_visible_in_the_event(self):
        """This event fires on every scan while wheel-state persistence is dead
        (FC-039), so the broker comparison is what makes it signal rather than
        noise: BQ and Alpaca disagreeing means one of them is wrong."""
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '29000.0',   # $290/share
            'asset_class': 'us_equity', 'side': 'long',
        }]

        with self._with_opasn_strike(303.50):
            with patch('src.data.options_scanner.logger') as mock_logger:
                self.scanner.scan_for_call_opportunities()

        events = [c.kwargs for c in mock_logger.info.call_args_list
                  if c.kwargs.get("event_type") == "cost_basis_resolved_via_fallback"]
        assert len(events) == 1
        assert events[0]["source"] == "bigquery"
        assert events[0]["resolved_basis"] == 303.50
        assert events[0]["alpaca_cost_basis_per_share"] == 290.0
        assert events[0]["basis_delta"] == pytest.approx(13.50)

    def test_an_alpaca_sourced_basis_logs_no_fallback_event(self):
        self.mock_alpaca.get_positions.return_value = [{
            'symbol': 'AAPL', 'qty': '100', 'cost_basis': '30350.0',
            'asset_class': 'us_equity', 'side': 'long',
        }]

        with self._with_opasn_strike(0.0):
            with patch('src.data.options_scanner.logger') as mock_logger:
                results = self.scanner.scan_for_call_opportunities()

        assert len(results) == 1
        assert not [c for c in mock_logger.info.call_args_list
                    if c.kwargs.get("event_type") == "cost_basis_resolved_via_fallback"]

    def test_nothing_resolves_still_emits_no_opportunities(self):
        """FC-038's fail-closed skip survives, now on the resolved value."""
        with self._with_opasn_strike(0.0):
            results = self.scanner.scan_for_call_opportunities()

        assert results == []
        self.mock_market_data.find_suitable_calls.assert_not_called()


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
