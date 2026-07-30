"""Tests for the execution engine module."""

import copy
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.execution_engine import DROP_REASONS, ExecutionEngine
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


class TestCommittedSharesCheck:
    """FC-052: the oversell guard must count only real short CALLS.

    It previously did `'C' in opt_sym` over a hand-rolled underlying, so a
    short PUT on any ticker containing a "C" counted as a committed call —
    over-reporting committed shares and starving the call side. Fifth instance
    of the OCC-substring family (FC-041/043/045/048).
    """

    def _engine_with(self, positions):
        alpaca = Mock()
        alpaca.get_positions.return_value = positions
        return ExecutionEngine(alpaca, Mock(spec=Config)), alpaca

    def _run_call(self, engine, call_seller):
        return engine.execute_batch(
            [{"symbol": "CVX", "option_symbol": "CVX250117C00160000",
              "strategy": "sell_call", "contracts": 1, "premium": 1.0,
              "strike_price": 160, "shares_covered": 100,
              "stock_cost_basis": 150.0}],
            Mock(spec=PutSeller), call_seller=call_seller)

    def test_a_short_put_on_a_c_ticker_does_not_consume_call_capacity(self):
        """The bug: CVX...P... contains 'C', so it counted as a committed call."""
        call_seller = Mock(spec=CallSeller)
        call_seller.execute_call_sale.return_value = {"success": True, "order_id": "c1"}
        engine, _ = self._engine_with([
            {"symbol": "CVX", "qty": "100", "asset_class": "us_equity", "side": "long"},
            # A short PUT on the same underlying. Not a call; must not commit shares.
            {"symbol": "CVX250117P00140000", "qty": "-1", "asset_class": "us_option"},
        ])

        self._run_call(engine, call_seller)

        call_seller.execute_call_sale.assert_called_once(), (
            "a short PUT consumed the shares backing a legitimate covered call"
        )

    def test_a_real_short_call_still_consumes_capacity(self):
        """The guard must keep working: don't over-correct into overselling."""
        call_seller = Mock(spec=CallSeller)
        call_seller.execute_call_sale.return_value = {"success": True, "order_id": "c1"}
        engine, _ = self._engine_with([
            {"symbol": "CVX", "qty": "100", "asset_class": "us_equity", "side": "long"},
            # 100 shares already backing a short CALL -> nothing available.
            {"symbol": "CVX250117C00170000", "qty": "-1", "asset_class": "us_option"},
        ])

        self._run_call(engine, call_seller)

        call_seller.execute_call_sale.assert_not_called()


# ======================================================================
# FC-038: two-pool execution selection
#
# Covered calls were charged strike x 100 of cash collateral they never
# needed -- at BOTH the sizing stage (put_seller._calculate_position_size's
# buying-power cap) and the selection stage. One call could therefore exhaust
# the cash budget for the whole batch, and AAPL went four trading days without
# a covered call while its calls were the top-scored opportunities in every
# scan. See docs/investigations/covered-call-starvation-2026-07-18.md.
# ======================================================================

FIXTURES = Path(__file__).parent / "fixtures"

# Buying power logged by the production /run cycle being replayed.
GOLDEN_BP = 67142.50


def _drop_events(mock_logger):
    """Every `selection_dropped` payload emitted on a mocked engine logger."""
    return [c.kwargs for c in mock_logger.info.call_args_list
            if c.kwargs.get("event_type") == "selection_dropped"]


def _select_events(mock_logger):
    return [c.kwargs for c in mock_logger.info.call_args_list
            if c.kwargs.get("event_type") == "opportunity_selected"]


def _call(symbol, strike, *, expiry="260724", premium=1.0, score=None, **extra):
    opp = {
        "symbol": symbol,
        "option_symbol": f"{symbol}{expiry}C{int(strike * 1000):08d}",
        "type": "call",
        "strike_price": float(strike),
        "premium": premium,
    }
    if score is not None:
        opp["attractiveness_score"] = score
    opp.update(extra)
    return opp


def _put(symbol, strike, *, expiry="260724", premium=1.0, **extra):
    opp = {
        "symbol": symbol,
        "option_symbol": f"{symbol}{expiry}P{int(strike * 1000):08d}",
        "type": "put",
        "strike_price": float(strike),
        "premium": premium,
    }
    opp.update(extra)
    return opp


def _equity(symbol, qty):
    return {"symbol": symbol, "qty": str(qty), "asset_class": "us_equity",
            "side": "long"}


def _short_option(option_symbol, qty=-1):
    return {"symbol": option_symbol, "qty": str(qty), "asset_class": "us_option",
            "side": "short"}


class TestAvailableSharesHelper:
    """The committed-shares arithmetic, extracted from execute_batch (FC-038).

    Pinned as its own unit because three call sites now share it: call sizing,
    batch selection, and the execution-time oversell guard. A regression here
    either starves the call side or sells naked.
    """

    def setup_method(self):
        self.engine = ExecutionEngine(Mock(), Mock(spec=Config))

    def test_no_position_means_nothing_available(self):
        assert self.engine._available_shares("AAPL", []) == (0, 0, 0)

    def test_owned_shares_are_available(self):
        assert self.engine._available_shares("AAPL", [_equity("AAPL", 100)]) == (100, 100, 0)
        assert self.engine._available_shares("AAPL", [_equity("AAPL", 200)]) == (200, 200, 0)

    def test_a_short_call_commits_the_shares_backing_it(self):
        positions = [_equity("AAPL", 100), _short_option("AAPL260724C00340000")]

        assert self.engine._available_shares("AAPL", positions) == (0, 100, 100)

    def test_partial_commitment_leaves_the_remainder_available(self):
        positions = [_equity("AAPL", 300), _short_option("AAPL260724C00340000", qty=-2)]

        assert self.engine._available_shares("AAPL", positions) == (100, 300, 200)

    def test_a_short_put_never_commits_shares(self):
        """FC-052 parity: `'C' in symbol` counted CVX puts as committed calls."""
        positions = [_equity("CVX", 100), _short_option("CVX260724P00140000")]

        assert self.engine._available_shares("CVX", positions) == (100, 100, 0)

    def test_a_long_call_does_not_commit_shares(self):
        """Only SHORT calls are covered by shares; a long call is an asset."""
        positions = [_equity("AAPL", 100),
                     {"symbol": "AAPL260724C00340000", "qty": "1",
                      "asset_class": "us_option", "side": "long"}]

        assert self.engine._available_shares("AAPL", positions) == (100, 100, 0)

    def test_another_underlyings_call_does_not_commit_these_shares(self):
        positions = [_equity("AAPL", 100), _equity("GOOGL", 100),
                     _short_option("GOOGL260724C00370000")]

        assert self.engine._available_shares("AAPL", positions) == (100, 100, 0)

    def test_malformed_position_cannot_inflate_availability(self):
        positions = [_equity("AAPL", 100),
                     {"symbol": "AAPL", "qty": "not-a-number",
                      "asset_class": "us_equity"}]

        available, _, _ = self.engine._available_shares("AAPL", positions)
        assert available == 100

    def test_missing_underlying_is_zero_not_a_crash(self):
        assert self.engine._available_shares(None, [_equity("AAPL", 100)]) == (0, 0, 0)

    def test_snapshot_fetch_failure_fails_closed(self):
        """No positions data must mean "sell nothing", never "sell naked"."""
        alpaca = Mock()
        alpaca.get_positions.side_effect = RuntimeError("Alpaca 503")
        engine = ExecutionEngine(alpaca, Mock(spec=Config))

        assert engine._available_shares("AAPL", engine._positions_snapshot()) == (0, 0, 0)


class TestSharesBasedCallSizing:
    """rank_opportunities sizes calls from shares, never from buying power.

    THE SIZING-STAGE BUG: every opportunity went through
    put_seller._calculate_position_size, whose cap is
    `buying_power // (strike * 100)`. On 2026-07-14, runs with BP $621 and
    $383 dropped *every* opportunity here -- including three AAPL calls backed
    by 100 idle shares that needed no cash at all.
    """

    def setup_method(self):
        self.alpaca = Mock()
        self.engine = ExecutionEngine(self.alpaca, Mock(spec=Config))
        self.engine.logger = Mock()
        self.put_seller = Mock(spec=PutSeller)
        self.put_seller._calculate_position_size.return_value = {"contracts": 1}

    def _rank(self, opps, positions, bp=0.0):
        self.alpaca.get_positions.return_value = positions
        return self.engine.rank_opportunities(opps, self.put_seller, bp)

    def test_call_is_sized_at_zero_buying_power(self):
        """THE FC-038 REGRESSION. Fails on the old code: BP $0 drops the call."""
        ranked = self._rank([_call("AAPL", 337.5)], [_equity("AAPL", 100)], bp=0.0)

        assert len(ranked) == 1
        assert ranked[0]["opportunity"]["contracts"] == 1
        assert ranked[0]["collateral"] == 0, "a covered call reserves no cash"
        self.put_seller._calculate_position_size.assert_not_called()

    def test_two_hundred_shares_size_two_contracts(self):
        ranked = self._rank([_call("AAPL", 337.5)], [_equity("AAPL", 200)])

        assert ranked[0]["opportunity"]["contracts"] == 2
        assert ranked[0]["premium"] == pytest.approx(1.0 * 100 * 2)

    def test_no_shares_drops_the_call_with_a_reason(self):
        ranked = self._rank([_call("AAPL", 337.5)], [])

        assert ranked == []
        drops = _drop_events(self.engine.logger)
        assert len(drops) == 1
        assert drops[0]["reason"] == "insufficient_available_shares"
        assert drops[0]["symbol"] == "AAPL"
        assert drops[0]["stage"] == "ranking"

    def test_fully_committed_shares_drop_the_call_with_a_reason(self):
        """The wasted-slot case: 100 owned, 100 already backing a short call."""
        ranked = self._rank(
            [_call("AAPL", 345)],
            [_equity("AAPL", 100), _short_option("AAPL260724C00340000")],
        )

        assert ranked == []
        drops = _drop_events(self.engine.logger)
        assert drops[0]["reason"] == "insufficient_available_shares"
        assert drops[0]["owned_shares"] == 100
        assert drops[0]["committed_to_calls"] == 100

    def test_odd_lot_below_one_contract_is_dropped(self):
        ranked = self._rank([_call("AAPL", 337.5)], [_equity("AAPL", 99)])

        assert ranked == []

    def test_puts_are_still_sized_by_the_put_seller(self):
        """Non-goal guard: put sizing must not change at all."""
        ranked = self._rank([_put("MSFT", 375.0, premium=2.56)], [], bp=GOLDEN_BP)

        self.put_seller._calculate_position_size.assert_called_once()
        assert self.put_seller._calculate_position_size.call_args.kwargs[
            "override_buying_power"] == GOLDEN_BP
        assert ranked[0]["collateral"] == 37500.0

    def test_put_sizing_failure_is_logged_not_silent(self):
        self.put_seller._calculate_position_size.return_value = None

        ranked = self._rank([_put("MSFT", 375.0)], [], bp=100.0)

        assert ranked == []
        assert _drop_events(self.engine.logger)[0]["reason"] == "sizing_failed"

    def test_call_type_is_taken_from_the_occ_symbol_not_the_dict_key(self):
        """Same routing rule execute_batch uses (FC-048): the contract wins."""
        mislabelled = _call("AAPL", 337.5)
        mislabelled["type"] = "put"          # producer lied

        ranked = self._rank([mislabelled], [_equity("AAPL", 100)], bp=0.0)

        assert len(ranked) == 1
        self.put_seller._calculate_position_size.assert_not_called()

    def test_positions_are_not_fetched_for_an_all_put_batch(self):
        """Puts need no share data; don't spend an API call every cycle."""
        self._rank([_put("MSFT", 375.0)], [], bp=GOLDEN_BP)

        self.alpaca.get_positions.assert_not_called()


class TestTwoPoolSelection:
    """select_batch runs two budgets: shares for calls, cash for puts.

    THE SELECTION-STAGE BUG: `collateral = strike * 100 * contracts` was
    charged against buying power for calls too. On 2026-07-17 a single GOOGL
    call charged $37,000 of phantom collateral and pushed all three AAPL calls
    out of a $67,142.50 budget.
    """

    def setup_method(self):
        self.alpaca = Mock()
        self.engine = ExecutionEngine(self.alpaca, Mock(spec=Config))
        self.engine.logger = Mock()

    def _select(self, items, bp, positions=None):
        self.alpaca.get_positions.return_value = positions or []
        return self.engine.select_batch(items, bp)

    @staticmethod
    def _item(opp, collateral=0.0, premium=100.0, roi=0.0):
        return {"opportunity": opp, "collateral": collateral, "premium": premium,
                "roi": roi, "type": opp.get("type", "put")}

    def test_call_is_selected_at_zero_buying_power(self):
        """THE FC-038 REGRESSION: a covered call needs no cash."""
        opp = _call("AAPL", 337.5, contracts=1)

        selected, remaining = self._select(
            [self._item(opp)], 0.0, [_equity("AAPL", 100)])

        assert [o["option_symbol"] for o in selected] == [opp["option_symbol"]]
        assert remaining == 0.0, "a call must not consume buying power"

    def test_a_call_does_not_crowd_out_a_put(self):
        """The 2026-07-17 reproduction, in miniature."""
        call = _call("GOOGL", 370.0, contracts=1)
        put = _put("IWM", 289.0, premium=0.68, contracts=1)

        selected, remaining = self._select(
            [self._item(call), self._item(put, collateral=28900.0, roi=0.0024)],
            30000.0, [_equity("GOOGL", 100)])

        assert [o["symbol"] for o in selected] == ["GOOGL", "IWM"], (
            "the call charged phantom collateral and starved the put again")
        assert remaining == pytest.approx(1100.0)

    def test_share_committed_underlying_is_dropped_at_selection(self):
        """The wasted-slot bug: this used to surface only at execution time."""
        opp = _call("GOOGL", 370.0, contracts=1)

        selected, _ = self._select(
            [self._item(opp)], 100000.0,
            [_equity("GOOGL", 100), _short_option("GOOGL260724C00365000")])

        assert selected == []
        drops = _drop_events(self.engine.logger)
        assert drops[0]["reason"] == "insufficient_available_shares"
        assert drops[0]["stage"] == "selection"

    def test_the_share_ledger_bounds_contract_count(self):
        """200 shares back two contracts, not three."""
        selected, _ = self._select(
            [self._item(_call("AAPL", 337.5, contracts=2))], 0.0,
            [_equity("AAPL", 200)])
        assert len(selected) == 1

        self.engine.logger = Mock()
        selected, _ = self._select(
            [self._item(_call("AAPL", 337.5, contracts=3))], 0.0,
            [_equity("AAPL", 200)])
        assert selected == []
        assert _drop_events(self.engine.logger)[0][
            "reason"] == "insufficient_available_shares"

    def test_puts_are_still_gated_by_buying_power(self):
        """Non-goal guard: the cash budget is unchanged for puts."""
        cheap = _put("IWM", 289.0, contracts=1)
        dear = _put("MSFT", 375.0, contracts=1)

        selected, remaining = self._select(
            [self._item(cheap, collateral=28900.0, roi=0.0024),
             self._item(dear, collateral=37500.0, roi=0.0068)],
            30000.0)

        assert [o["symbol"] for o in selected] == ["IWM"]
        assert remaining == pytest.approx(1100.0)
        assert [d["reason"] for d in _drop_events(self.engine.logger)] == [
            "insufficient_buying_power"]

    def test_dedup_is_global_across_both_pools(self):
        """One position per underlying, whichever pool it comes from."""
        selected, _ = self._select(
            [self._item(_call("AAPL", 337.5, contracts=1)),
             self._item(_put("AAPL", 300.0, contracts=1), collateral=30000.0, roi=0.01)],
            100000.0, [_equity("AAPL", 100)])

        assert len(selected) == 1
        assert selected[0]["type"] == "call"
        assert [d["reason"] for d in _drop_events(self.engine.logger)] == [
            "duplicate_underlying"]

    def test_calls_rank_by_attractiveness_score_not_roi(self):
        """Naive roi = premium/collateral is 0 for calls and sorts them last."""
        low = _call("AAPL", 337.5, score=70.0, contracts=1)
        high = _call("GOOGL", 370.0, score=90.0, contracts=1)

        selected, _ = self._select(
            [self._item(low), self._item(high)], 0.0,
            [_equity("AAPL", 100), _equity("GOOGL", 100)])

        assert [o["symbol"] for o in selected] == ["GOOGL", "AAPL"]

    def test_call_ranking_falls_back_to_premium_yield_without_a_score(self):
        thin = _call("AAPL", 340.0, premium=0.50, contracts=1)
        rich = _call("GOOGL", 340.0, premium=3.00, contracts=1)

        selected, _ = self._select(
            [self._item(thin), self._item(rich)], 0.0,
            [_equity("AAPL", 100), _equity("GOOGL", 100)])

        assert [o["symbol"] for o in selected] == ["GOOGL", "AAPL"]

    def test_calls_are_selected_before_puts(self):
        selected, _ = self._select(
            [self._item(_put("MSFT", 375.0, contracts=1), collateral=37500.0, roi=0.0068),
             self._item(_call("AAPL", 337.5, contracts=1))],
            100000.0, [_equity("AAPL", 100)])

        assert [o["symbol"] for o in selected] == ["AAPL", "MSFT"]

    def test_every_dropped_opportunity_carries_a_reason(self):
        items = [
            self._item(_call("AAPL", 337.5, contracts=1)),          # selected
            self._item(_call("AAPL", 340.0, contracts=1)),          # duplicate
            self._item(_call("NVDA", 220.0, contracts=1)),          # no shares
            self._item(_put("MSFT", 375.0, contracts=1), collateral=37500.0, roi=0.0068),
            self._item(_put("IWM", 289.0, contracts=1), collateral=28900.0, roi=0.0024),
        ]

        selected, _ = self._select(items, 40000.0, [_equity("AAPL", 100)])

        assert [o["symbol"] for o in selected] == ["AAPL", "MSFT"]
        assert sorted(d["reason"] for d in _drop_events(self.engine.logger)) == [
            "duplicate_underlying",
            "insufficient_available_shares",
            "insufficient_buying_power",
        ]

    def test_batch_summary_reports_drop_counts(self):
        self._select(
            [self._item(_call("NVDA", 220.0, contracts=1)),
             self._item(_put("MSFT", 375.0, contracts=1), collateral=37500.0)],
            100.0)

        summary = next(c.kwargs for c in self.engine.logger.info.call_args_list
                       if c.kwargs.get("event_type") == "batch_selection_completed")
        assert summary["dropped_count"] == 2
        assert summary["dropped_insufficient_available_shares"] == 1
        assert summary["dropped_insufficient_buying_power"] == 1
        assert summary["calls_selected"] == 0 and summary["puts_selected"] == 0


class TestGoldenReplay20260717:
    """Replay of the archived scan that produced the outage.

    Fixture: gs://options-wheel-opportunities/opportunities/2026-07-17/14-00.json
    -- 12 opportunities, six calls and six puts, copied verbatim. Its own
    `execution_results` record what the buggy pipeline did with $67,142.50 of
    buying power: GOOGL 370C (charged $37,000 of phantom collateral) plus
    IWM 289P, and nothing else. AAPL's calls were the two top-scored items in
    the batch (87.24 / 87.19) and were dropped.

    Portfolio value is set so the 35% per-position cap is never the binding
    constraint; buying power is the variable under test, at its production value.
    """

    def setup_method(self):
        with open(FIXTURES / "scan_2026-07-17_14-00.json") as f:
            self.blob = json.load(f)
        self.opportunities = copy.deepcopy(self.blob["opportunities"])

        self.alpaca = Mock()
        self.alpaca.get_account.return_value = {
            "portfolio_value": "120000.0",
            "buying_power": str(GOLDEN_BP),
            "options_buying_power": str(GOLDEN_BP),
        }
        self.config = Mock(spec=Config)
        self.config.max_position_size = 0.35        # config/settings.yaml
        self.engine = ExecutionEngine(self.alpaca, self.config)
        self.engine.logger = Mock()
        # A real PutSeller: the put path stays pinned to production sizing.
        self.put_seller = PutSeller(self.alpaca, Mock(), self.config)

    def _run(self, positions, bp=GOLDEN_BP):
        self.alpaca.get_positions.return_value = positions
        ranked = self.engine.rank_opportunities(self.opportunities, self.put_seller, bp)
        return self.engine.select_batch(ranked, bp)

    def test_the_fixture_is_the_incident(self):
        """Guard the fixture: a silent edit would hollow out this whole class."""
        assert self.blob["opportunity_count"] == 12
        assert len(self.opportunities) == 12

        executed = [r["opportunity"]["option_symbol"]
                    for r in self.blob["execution_results"]]
        assert executed == ["GOOGL260724C00370000", "IWM260721P00289000"], (
            "the fixture no longer records the buggy outcome it exists to document")

        top = max(self.opportunities, key=lambda o: o["attractiveness_score"])
        assert top["option_symbol"] == "AAPL260720C00337500"

    def test_aapls_top_call_is_selected(self):
        """The point of FC-038: AAPL was starved for four trading days."""
        selected, _ = self._run([_equity("AAPL", 100), _equity("GOOGL", 100)])

        assert "AAPL260720C00337500" in [o["option_symbol"] for o in selected]

    def test_the_puts_that_actually_fit_are_still_selected(self):
        """Calls must not displace the cash pool -- they consume none of it."""
        selected, remaining = self._run([_equity("AAPL", 100), _equity("GOOGL", 100)])

        symbols = [o["option_symbol"] for o in selected]
        assert "MSFT260724P00375000" in symbols
        assert "IWM260721P00289000" in symbols
        # 67,142.50 - 37,500 (MSFT 375) - 28,900 (IWM 289)
        assert remaining == pytest.approx(742.50)

    def test_one_position_per_underlying_across_twelve_opportunities(self):
        selected, _ = self._run([_equity("AAPL", 100), _equity("GOOGL", 100)])

        underlyings = [o["symbol"] for o in selected]
        assert sorted(underlyings) == ["AAPL", "GOOGL", "IWM", "MSFT"]

        googl = [o for o in selected if o["symbol"] == "GOOGL"]
        assert len(googl) == 1
        assert googl[0]["option_symbol"] == "GOOGL260722C00370000", (
            "GOOGL's one slot should go to its best-scored call")

    def test_nothing_is_dropped_without_a_reason(self):
        selected, _ = self._run([_equity("AAPL", 100), _equity("GOOGL", 100)])

        drops = _drop_events(self.engine.logger)
        selected_symbols = {o["option_symbol"] for o in selected}
        dropped_symbols = {d["option_symbol"] for d in drops}
        all_symbols = {o["option_symbol"] for o in self.opportunities}

        assert selected_symbols | dropped_symbols == all_symbols
        assert not selected_symbols & dropped_symbols
        assert all(d["reason"] in DROP_REASONS for d in drops)
        assert len(_select_events(self.engine.logger)) == len(selected)

    def test_committed_googl_shares_no_longer_burn_a_slot(self):
        """7/15-7/16: GOOGL was re-selected every cycle and never executable."""
        selected, _ = self._run([
            _equity("AAPL", 100),
            _equity("GOOGL", 100),
            _short_option("GOOGL260724C00370000"),   # the fill from this cycle
        ])

        assert "GOOGL" not in [o["symbol"] for o in selected]
        googl_drops = [d for d in _drop_events(self.engine.logger)
                       if d["symbol"] == "GOOGL"]
        assert len(googl_drops) == 3
        assert {d["reason"] for d in googl_drops} == {"insufficient_available_shares"}
        assert "AAPL260720C00337500" in [o["option_symbol"] for o in selected]

    def test_calls_survive_the_cash_drought_that_killed_them_on_0714(self):
        """BP $621 dropped every opportunity at the sizing stage on 2026-07-14."""
        selected, remaining = self._run(
            [_equity("AAPL", 100), _equity("GOOGL", 100)], bp=621.0)

        assert [o["option_symbol"] for o in selected] == [
            "AAPL260720C00337500", "GOOGL260722C00370000"]
        assert remaining == 621.0

        put_drops = [d for d in _drop_events(self.engine.logger)
                     if d["opportunity_type"] == "put"]
        assert len(put_drops) == 6
        assert {d["reason"] for d in put_drops} == {"sizing_failed"}
