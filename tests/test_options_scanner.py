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
