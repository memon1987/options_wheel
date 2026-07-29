"""Tests for the execution engine module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.execution_engine import ExecutionEngine
from src.strategy.put_seller import PutSeller
from src.strategy.call_seller import CallSeller
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
            {'symbol': 'AAPL', 'strike_price': 170.0, 'premium': 2.50, 'option_symbol': 'AAPL250117P00170000'},
            {'symbol': 'MSFT', 'strike_price': 380.0, 'premium': 5.00, 'option_symbol': 'MSFT250117P00380000'},
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
            {'symbol': 'AAPL', 'strike_price': 170.0, 'premium': 2.50, 'option_symbol': 'AAPL250117P00170000'},
            {'symbol': 'MSFT', 'strike_price': 380.0, 'premium': 5.00, 'option_symbol': 'MSFT250117P00380000'},
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
            {'symbol': 'AAPL', 'strike_price': 100.0, 'premium': 1.50, 'option_symbol': 'AAPL250117P00170000'},
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
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000'},
                'collateral': 17000.0,
                'premium': 250.0,
                'roi': 0.015,
            },
            {
                'opportunity': {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000'},
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
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000'},
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
                'opportunity': {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000'},
                'collateral': 10000.0,
                'premium': 200.0,
                'roi': 0.020,
            },
            {
                'opportunity': {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000'},
                'collateral': 10000.0,
                'premium': 180.0,
                'roi': 0.018,
            },
            {
                'opportunity': {'symbol': 'GOOGL', 'option_symbol': 'GOOGL250117P00150000'},
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
            {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
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
            {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
            {'symbol': 'GOOGL', 'option_symbol': 'GOOGL250117P00150000', 'contracts': 1, 'premium': 3.0, 'strike_price': 150},
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
            {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
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
            {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
            {'symbol': 'MSFT', 'option_symbol': 'MSFT250117P00380000', 'contracts': 1, 'premium': 5.0, 'strike_price': 380},
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
            {'symbol': 'AAPL', 'option_symbol': 'AAPL250117P00170000', 'contracts': 1, 'premium': 2.5, 'strike_price': 170},
        ]

        self.engine.execute_batch(opportunities, self.mock_put_seller)

        self.mock_put_seller.execute_put_sale.assert_called_once_with(
            opportunities[0], skip_buying_power_check=False
        )


PUT_SYM = "AAPL250117P00170000"
CALL_SYM = "AAPL250117C00190000"


class TestExecuteBatchRouting:
    """FC-048: routing is derived from the OCC symbol, not from a dict key.

    The bug: `opp.get('type', 'put')`. Only the scanner sets 'type'; the sellers
    set 'strategy'. So every seller-produced covered call defaulted to "put",
    went to put_seller, and was rejected — which is why every backtest modelled
    a put-only wheel while looking healthy.
    """

    def setup_method(self):
        from src.strategy.execution_engine import clear_failed_symbols
        clear_failed_symbols()      # module-global; must not leak between tests
        self.alpaca = Mock()
        # Enough shares for the covered-call path's availability check.
        self.alpaca.get_positions.return_value = [
            {"symbol": "AAPL", "qty": "500", "asset_class": "us_equity", "side": "long"}
        ]
        self.engine = ExecutionEngine(self.alpaca, Mock(spec=Config))
        self.put_seller = Mock(spec=PutSeller)
        self.call_seller = Mock(spec=CallSeller)
        self.put_seller.execute_put_sale.return_value = {"success": True, "order_id": "p1"}
        self.call_seller.execute_call_sale.return_value = {"success": True, "order_id": "c1"}

    def _run(self, opp):
        return self.engine.execute_batch([opp], self.put_seller, call_seller=self.call_seller)

    def test_seller_shaped_call_without_type_key_routes_to_call(self):
        """THE FC-048 REGRESSION. Fails on the old code: defaults to 'put'."""
        self._run({"symbol": "AAPL", "option_symbol": CALL_SYM, "strategy": "sell_call",
                   "contracts": 1, "premium": 1.0, "strike_price": 190,
                   "shares_covered": 100, "stock_cost_basis": 150.0})

        self.call_seller.execute_call_sale.assert_called_once()
        self.put_seller.execute_put_sale.assert_not_called()

    def test_scanner_shaped_call_still_routes_to_call(self):
        """Production /run executes scanner-shaped dicts — must not change."""
        self._run({"symbol": "AAPL", "option_symbol": CALL_SYM, "type": "call",
                   "contracts": 1, "premium": 1.0, "strike_price": 190,
                   "shares_covered": 100, "stock_cost_basis": 150.0})

        self.call_seller.execute_call_sale.assert_called_once()
        self.put_seller.execute_put_sale.assert_not_called()

    def test_scanner_shaped_put_routes_to_put_with_bp_check(self):
        self._run({"symbol": "AAPL", "option_symbol": PUT_SYM, "type": "put",
                   "contracts": 1, "premium": 2.5, "strike_price": 170})

        self.put_seller.execute_put_sale.assert_called_once()
        assert self.put_seller.execute_put_sale.call_args.kwargs[
            "skip_buying_power_check"] is False
        self.call_seller.execute_call_sale.assert_not_called()

    def test_seller_shaped_put_routes_to_put(self):
        self._run({"symbol": "AAPL", "option_symbol": PUT_SYM, "strategy": "sell_put",
                   "contracts": 1, "premium": 2.5, "strike_price": 170})

        self.put_seller.execute_put_sale.assert_called_once()
        self.call_seller.execute_call_sale.assert_not_called()

    def test_unroutable_symbol_fails_loud_and_trades_nothing(self):
        """The silent-default class: a missing/garbage symbol must NOT trade.

        The bare-ticker cases are the sharp ones. parse_option_symbol's
        heuristic resolves 'AAPL' -> "put" and 'NOT_AN_OCC' -> "call"; routing
        on that would send a non-contract to a seller, and place_option_order
        on a bare ticker is a plain EQUITY order. Adjusted roots ('1AAPL...')
        are refused too — their deliverable is not 100 shares.
        """
        for bad in ({"symbol": "AAPL", "contracts": 1},                       # no option_symbol
                    {"symbol": "AAPL", "option_symbol": "", "contracts": 1},
                    {"symbol": "AAPL", "option_symbol": "NOT_AN_OCC", "contracts": 1},
                    {"symbol": "AAPL", "option_symbol": "AAPL", "contracts": 1},
                    {"symbol": "SPY", "option_symbol": "SPY", "contracts": 1},
                    {"symbol": "AAPL", "option_symbol": "1AAPL250117C00190000",
                     "contracts": 1}):
            self.put_seller.reset_mock(); self.call_seller.reset_mock()
            results, count = self._run(bad)

            assert count == 0
            assert results[0]["success"] is False
            assert results[0]["result"]["error_type"] == "unroutable_opportunity"
            assert results[0]["result"]["non_retryable"] is True
            self.put_seller.execute_put_sale.assert_not_called()
            self.call_seller.execute_call_sale.assert_not_called()

    def test_unroutable_opportunity_suppresses_the_retry_storm(self):
        """Plan D1 promised non_retryable feeds _failed_symbols; it must."""
        from src.strategy.execution_engine import (
            clear_failed_symbols, get_failed_symbols)

        clear_failed_symbols()
        try:
            self._run({"symbol": "AAPL", "option_symbol": "NOT_AN_OCC", "contracts": 1})
            # Keyed on the contract, not the underlying: blacklisting "AAPL"
            # would suppress every future legitimate AAPL contract.
            assert "NOT_AN_OCC" in get_failed_symbols()
            assert "AAPL" not in get_failed_symbols()
        finally:
            clear_failed_symbols()

    def test_one_unroutable_opportunity_does_not_kill_the_batch(self):
        results, count = self.engine.execute_batch(
            [{"symbol": "AAPL", "option_symbol": "", "contracts": 1},
             {"symbol": "AAPL", "option_symbol": PUT_SYM, "strategy": "sell_put",
              "contracts": 1, "premium": 2.5, "strike_price": 170}],
            self.put_seller, call_seller=self.call_seller)

        assert len(results) == 2 and count == 1
        self.put_seller.execute_put_sale.assert_called_once()

    def test_contradictory_type_key_loses_to_the_occ_symbol(self):
        """The contract is what place_option_order actually trades."""
        self.engine.logger = Mock()
        self._run({"symbol": "AAPL", "option_symbol": CALL_SYM, "type": "put",
                   "contracts": 1, "premium": 1.0, "strike_price": 190,
                   "shares_covered": 100, "stock_cost_basis": 150.0})

        self.call_seller.execute_call_sale.assert_called_once()
        self.put_seller.execute_put_sale.assert_not_called()
        assert any(
            c.kwargs.get("event_type") == "opportunity_type_mismatch"
            for c in self.engine.logger.warning.call_args_list
        ), "the type/symbol contradiction must be logged, not silently resolved"


class TestProducerVocabulary:
    """Both producers must set both keys (FC-048 D2).

    Not load-bearing after the router change, but the sellers setting only
    'strategy' while the scanner set only 'type' is the asymmetry that caused
    the misroute. Asserted against the real emitted dicts, not the source text.
    """

    def test_call_seller_opportunity_declares_its_type(self):
        """Assert the REAL emitted dict, not the source text.

        The first version of this test stubbed the seller so loosely that
        _resolve_cost_basis_floor found nothing, evaluate_covered_call_opportunity
        returned None, and the test skipped on every run — coverage that never
        executed. Patch the floor so the builder actually reaches its return.
        """
        from src.strategy.call_seller import CallSeller as CS

        seller = CS.__new__(CS)          # builder-only; no __init__ wiring
        seller.config = Mock(spec=Config)
        seller.config.call_drawdown_pause_threshold = 0.05
        seller.market_data = Mock()
        seller.alpaca = Mock()
        # Spot above the 150 basis so the FC-029 drawdown pause does not fire.
        seller.alpaca.get_stock_quote.return_value = {"bid": 160.0, "ask": 160.10}
        seller.wheel_state = None
        seller.market_data.find_suitable_calls.return_value = [{
            "symbol": "AAPL250117C00190000", "strike_price": 190.0,
            "expiration_date": "2025-01-17", "dte": 7, "delta": 0.20,
            "mid_price": 1.10, "annual_return": 0.3,
        }]

        with patch.object(CS, "_resolve_cost_basis_floor", return_value=150.0), \
             patch.object(CS, "_calculate_call_position",
                          return_value={"contracts": 1, "shares_covered": 100,
                                        "max_profit": 110.0,
                                        "current_stock_price": 160.05,
                                        "total_return_if_called": 0.07}):
            opp = seller.evaluate_covered_call_opportunity(
                {"symbol": "AAPL", "qty": "100", "avg_entry_price": "150.0"})

        assert opp is not None, (
            "builder returned None — the stub is too loose again; this test "
            "must ASSERT, never skip"
        )
        assert opp["type"] == "call"
        assert opp["strategy"] == "sell_call"

    def test_both_sellers_declare_type_in_their_opportunity_shape(self):
        """Belt-and-braces contract check that survives a constant refactor."""
        import re as _re
        from pathlib import Path as _P

        for f, want in (("src/strategy/call_seller.py", "'type': 'call'"),
                        ("src/strategy/put_seller.py", "'type': 'put'")):
            body = _P(f).read_text()
            assert want in body, f"{f} no longer declares {want}"
