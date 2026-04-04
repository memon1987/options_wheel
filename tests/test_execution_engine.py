"""Tests for the execution engine module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.execution_engine import ExecutionEngine
from src.strategy.put_seller import PutSeller
from src.utils.config import Config


class TestFilterDuplicateOpportunities:
    """Test ExecutionEngine.filter_duplicate_opportunities."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_config = Mock(spec=Config)
        self.engine = ExecutionEngine(self.mock_alpaca, self.mock_config)

    def test_removes_existing_positions(self):
        """Test that opportunities matching existing positions are removed."""
        opportunities = [
            {'option_symbol': 'AAPL250117P00170000', 'symbol': 'AAPL'},
            {'option_symbol': 'MSFT250117P00380000', 'symbol': 'MSFT'},
            {'option_symbol': 'GOOGL250117P00150000', 'symbol': 'GOOGL'},
        ]
        existing_positions = [
            {'symbol': 'AAPL250117P00170000'},
            {'symbol': 'GOOGL250117P00150000'},
        ]

        filtered, count = self.engine.filter_duplicate_opportunities(
            opportunities, existing_positions
        )

        assert len(filtered) == 1
        assert filtered[0]['symbol'] == 'MSFT'
        assert count == 2

    def test_keeps_all_when_no_existing_positions(self):
        """Test all opportunities kept when no existing positions."""
        opportunities = [
            {'option_symbol': 'AAPL250117P00170000', 'symbol': 'AAPL'},
            {'option_symbol': 'MSFT250117P00380000', 'symbol': 'MSFT'},
        ]

        filtered, count = self.engine.filter_duplicate_opportunities(
            opportunities, []
        )

        assert len(filtered) == 2
        assert count == 0

    def test_empty_opportunities(self):
        """Test with empty opportunity list."""
        filtered, count = self.engine.filter_duplicate_opportunities([], [])

        assert filtered == []
        assert count == 0

    def test_all_duplicates(self):
        """Test when all opportunities are duplicates."""
        opportunities = [
            {'option_symbol': 'AAPL250117P00170000', 'symbol': 'AAPL'},
        ]
        existing_positions = [
            {'symbol': 'AAPL250117P00170000'},
        ]

        filtered, count = self.engine.filter_duplicate_opportunities(
            opportunities, existing_positions
        )

        assert filtered == []
        assert count == 1


class TestRankOpportunities:
    """Test ExecutionEngine.rank_opportunities."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_position_size = 0.10
        self.engine = ExecutionEngine(self.mock_alpaca, self.mock_config)

        self.mock_put_seller = Mock(spec=PutSeller)

    def test_sorts_by_roi_descending(self):
        """Test that opportunities are sorted by ROI highest first."""
        opportunities = [
            {'symbol': 'AAPL', 'strike_price': 170.0, 'premium': 2.50, 'option_symbol': 'A'},
            {'symbol': 'MSFT', 'strike_price': 380.0, 'premium': 5.00, 'option_symbol': 'B'},
        ]

        # AAPL: collateral=17000, premium=250, roi=250/17000=0.0147
        # MSFT: collateral=38000, premium=500, roi=500/38000=0.0132
        self.mock_put_seller._calculate_position_size.return_value = {
            'contracts': 1,
        }

        ranked = self.engine.rank_opportunities(
            opportunities, self.mock_put_seller, 50000.0
        )

        assert len(ranked) == 2
        assert ranked[0]['roi'] >= ranked[1]['roi']

    def test_skips_opportunities_that_fail_sizing(self):
        """Test that opportunities failing position sizing are excluded."""
        opportunities = [
            {'symbol': 'AAPL', 'strike_price': 170.0, 'premium': 2.50, 'option_symbol': 'A'},
            {'symbol': 'MSFT', 'strike_price': 380.0, 'premium': 5.00, 'option_symbol': 'B'},
        ]

        # First succeeds, second fails sizing
        self.mock_put_seller._calculate_position_size.side_effect = [
            {'contracts': 1},
            None,
        ]

        ranked = self.engine.rank_opportunities(
            opportunities, self.mock_put_seller, 50000.0
        )

        assert len(ranked) == 1
        assert ranked[0]['opportunity']['symbol'] == 'AAPL'

    def test_empty_opportunities(self):
        """Test with empty opportunity list."""
        ranked = self.engine.rank_opportunities(
            [], self.mock_put_seller, 50000.0
        )
        assert ranked == []

    def test_adds_mid_price_from_premium(self):
        """Test that premium is copied to mid_price for position sizing."""
        opportunities = [
            {'symbol': 'AAPL', 'strike_price': 100.0, 'premium': 1.50, 'option_symbol': 'A'},
        ]

        self.mock_put_seller._calculate_position_size.return_value = {
            'contracts': 1,
        }

        ranked = self.engine.rank_opportunities(
            opportunities, self.mock_put_seller, 50000.0
        )

        assert len(ranked) == 1
        # Verify mid_price was set on the opportunity
        assert opportunities[0]['mid_price'] == 1.50


class TestSelectBatch:
    """Test ExecutionEngine.select_batch."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_config = Mock(spec=Config)
        self.engine = ExecutionEngine(self.mock_alpaca, self.mock_config)

    def test_respects_buying_power_limit(self):
        """Test that batch selection stops when buying power exhausted."""
        ranked = [
            {
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'A'},
                'collateral': 17000.0,
                'premium': 250.0,
                'roi': 0.015,
            },
            {
                'opportunity': {'symbol': 'MSFT', 'option_symbol': 'B'},
                'collateral': 38000.0,
                'premium': 500.0,
                'roi': 0.013,
            },
        ]

        # Only 20000 buying power - can afford AAPL but not MSFT
        selected, remaining_bp = self.engine.select_batch(ranked, 20000.0)

        assert len(selected) == 1
        assert selected[0]['symbol'] == 'AAPL'
        assert remaining_bp == 3000.0  # 20000 - 17000

    def test_enforces_one_position_per_underlying(self):
        """Test that only one position per underlying is selected."""
        ranked = [
            {
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'A1'},
                'collateral': 17000.0,
                'premium': 300.0,
                'roi': 0.018,
            },
            {
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'A2'},
                'collateral': 16000.0,
                'premium': 250.0,
                'roi': 0.016,
            },
            {
                'opportunity': {'symbol': 'MSFT', 'option_symbol': 'B1'},
                'collateral': 38000.0,
                'premium': 500.0,
                'roi': 0.013,
            },
        ]

        selected, remaining_bp = self.engine.select_batch(ranked, 100000.0)

        # Should pick first AAPL and MSFT, skip second AAPL
        assert len(selected) == 2
        symbols = [s['symbol'] for s in selected]
        assert symbols.count('AAPL') == 1
        assert 'MSFT' in symbols

    def test_empty_ranked_list(self):
        """Test with no ranked opportunities."""
        selected, remaining_bp = self.engine.select_batch([], 50000.0)

        assert selected == []
        assert remaining_bp == 50000.0

    def test_no_affordable_opportunities(self):
        """Test when no opportunities fit within buying power."""
        ranked = [
            {
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'A'},
                'collateral': 17000.0,
                'premium': 250.0,
                'roi': 0.015,
            },
        ]

        selected, remaining_bp = self.engine.select_batch(ranked, 5000.0)

        assert selected == []
        assert remaining_bp == 5000.0

    def test_selects_multiple_underlyings(self):
        """Test selecting opportunities across different underlyings."""
        ranked = [
            {
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'A'},
                'collateral': 10000.0,
                'premium': 200.0,
                'roi': 0.020,
            },
            {
                'opportunity': {'symbol': 'MSFT', 'option_symbol': 'B'},
                'collateral': 10000.0,
                'premium': 180.0,
                'roi': 0.018,
            },
            {
                'opportunity': {'symbol': 'GOOGL', 'option_symbol': 'C'},
                'collateral': 10000.0,
                'premium': 150.0,
                'roi': 0.015,
            },
        ]

        selected, remaining_bp = self.engine.select_batch(ranked, 25000.0)

        assert len(selected) == 2  # Can afford 2 out of 3
        assert remaining_bp == 5000.0


class TestExecuteBatch:
    """Test ExecutionEngine.execute_batch."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_config = Mock(spec=Config)
        self.engine = ExecutionEngine(self.mock_alpaca, self.mock_config)

        self.mock_put_seller = Mock(spec=PutSeller)

    def test_successful_batch_execution(self):
        """Test executing a batch of orders successfully."""
        self.mock_put_seller.execute_put_sale.return_value = {
            'success': True,
            'order_id': 'order-123',
        }

        opportunities = [
            {'symbol': 'AAPL', 'option_symbol': 'A', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'B', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
        ]

        results, trades_count = self.engine.execute_batch(
            opportunities, self.mock_put_seller
        )

        assert len(results) == 2
        assert trades_count == 2
        assert all(r['success'] for r in results)

    def test_handles_order_failure_gracefully(self):
        """Test that one order failure does not stop the batch."""
        self.mock_put_seller.execute_put_sale.side_effect = [
            {'success': True, 'order_id': 'order-1'},
            {'success': False, 'message': 'Insufficient margin'},
            {'success': True, 'order_id': 'order-3'},
        ]

        opportunities = [
            {'symbol': 'AAPL', 'option_symbol': 'A', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'B', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
            {'symbol': 'GOOGL', 'option_symbol': 'C', 'contracts': 1, 'premium': 3.0, 'strike_price': 150},
        ]

        results, trades_count = self.engine.execute_batch(
            opportunities, self.mock_put_seller
        )

        assert len(results) == 3
        assert trades_count == 2  # 2 out of 3 succeeded
        assert results[0]['success'] is True
        assert results[1]['success'] is False
        assert results[2]['success'] is True

    def test_handles_exception_during_execution(self):
        """Test that exceptions during order execution are caught."""
        self.mock_put_seller.execute_put_sale.side_effect = [
            {'success': True, 'order_id': 'order-1'},
            Exception("Network timeout"),
        ]

        opportunities = [
            {'symbol': 'AAPL', 'option_symbol': 'A', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'B', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
        ]

        results, trades_count = self.engine.execute_batch(
            opportunities, self.mock_put_seller
        )

        assert len(results) == 2
        assert trades_count == 1
        assert results[0]['success'] is True
        assert results[1]['success'] is False
        assert 'Network timeout' in results[1]['result']['message']

    def test_empty_batch(self):
        """Test executing an empty batch."""
        results, trades_count = self.engine.execute_batch(
            [], self.mock_put_seller
        )

        assert results == []
        assert trades_count == 0
        self.mock_put_seller.execute_put_sale.assert_not_called()

    def test_all_orders_fail(self):
        """Test batch where all orders fail."""
        self.mock_put_seller.execute_put_sale.return_value = {
            'success': False,
            'message': 'Market closed',
        }

        opportunities = [
            {'symbol': 'AAPL', 'option_symbol': 'A', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'B', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
        ]

        results, trades_count = self.engine.execute_batch(
            opportunities, self.mock_put_seller
        )

        assert len(results) == 2
        assert trades_count == 0
        assert all(not r['success'] for r in results)

    def test_passes_skip_buying_power_check_false(self):
        """Test that execute_batch calls put_seller with skip_buying_power_check=False."""
        self.mock_put_seller.execute_put_sale.return_value = {
            'success': True,
            'order_id': 'order-1',
        }

        opportunities = [
            {'symbol': 'AAPL', 'option_symbol': 'A', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
        ]

        self.engine.execute_batch(opportunities, self.mock_put_seller)

        self.mock_put_seller.execute_put_sale.assert_called_once_with(
            opportunities[0], skip_buying_power_check=False
        )
