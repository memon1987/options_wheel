"""Tests for call selling module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.call_seller import CallSeller
from src.utils.config import Config


class TestCallSellerEvaluateOpportunity:
    """Test CallSeller.evaluate_covered_call_opportunity."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.mock_config.min_call_premium = 0.30

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

        # Default stock metrics
        self.mock_market_data.get_stock_metrics.return_value = {
            'current_price': 175.0,
        }

    def test_find_suitable_covered_calls(self):
        """Test finding suitable covered call opportunities."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,  # $160/share
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'annual_return': 0.54,
            }
        ]

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is not None
        assert result['strategy'] == 'sell_call'
        assert result['symbol'] == 'AAPL'
        assert result['strike_price'] == 185.0
        assert result['contracts'] == 1
        # Verify cost basis was used for filtering
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AAPL', min_strike_price=160.0
        )

    def test_strike_vs_cost_basis_filtering(self):
        """Test that find_suitable_calls is called with cost basis as min strike."""
        stock_position = {
            'symbol': 'MSFT',
            'qty': 200,
            'cost_basis': 60000.0,  # $300/share
            'market_value': 62000.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = []

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is None
        # Cost basis per share = 60000 / 200 = 300
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'MSFT', min_strike_price=300.0
        )

    def test_insufficient_shares(self):
        """Test returns None when fewer than 100 shares owned."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 50,
            'cost_basis': 8000.0,
            'market_value': 8750.0,
        }

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_no_suitable_calls_found(self):
        """Test returns None when no suitable calls exist."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = []

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)
        assert result is None

    def test_multiple_round_lots(self):
        """Test correct contract count for multiple round lots."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 300,
            'cost_basis': 48000.0,  # $160/share
            'market_value': 52500.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = [
            {
                'symbol': 'AAPL250117C00185000',
                'strike_price': 185.0,
                'expiration_date': '2025-01-17',
                'dte': 7,
                'delta': 0.15,
                'mid_price': 1.80,
                'annual_return': 0.54,
            }
        ]

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)

        assert result is not None
        assert result['contracts'] == 3  # 300 shares / 100 = 3 contracts

    def test_api_error_returns_none(self):
        """Test returns None on API error."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,
            'market_value': 17500.0,
        }

        self.mock_market_data.find_suitable_calls.side_effect = Exception("API Error")

        result = self.call_seller.evaluate_covered_call_opportunity(stock_position)
        assert result is None


class TestCallSellerExecuteSale:
    """Test CallSeller.execute_call_sale."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_execute_call_sale_success(self):
        """Test successful call sale execution."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-789',
            'status': 'new',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
            'dte': 7,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is True
        assert result['order_id'] == 'order-789'
        assert result['strategy'] == 'sell_call'

    def test_execute_call_sale_blocks_below_cost_basis(self):
        """Test that selling calls below cost basis is blocked."""
        opportunity = {
            'option_symbol': 'AAPL250117C00150000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 3.00,
            'strike_price': 150.0,  # Below cost basis per share
            'stock_cost_basis': 16000.0,  # $160/share for 100 shares
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'strike_below_cost_basis'
        # Order should NOT have been placed
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_execute_call_sale_allows_above_cost_basis(self):
        """Test that selling calls above cost basis proceeds."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': True,
            'order_id': 'order-abc',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,  # Above cost basis per share of $160
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
            'dte': 7,
        }

        result = self.call_seller.execute_call_sale(opportunity)
        assert result['success'] is True

    def test_execute_call_sale_order_failure(self):
        """Test handling of order placement failure."""
        self.mock_alpaca.place_option_order.return_value = {
            'success': False,
            'error_type': 'order_rejected',
            'error_message': 'Market closed',
        }

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'order_rejected'

    def test_execute_call_sale_exception(self):
        """Test handling of unexpected exception."""
        self.mock_alpaca.place_option_order.side_effect = Exception("Connection lost")

        opportunity = {
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'contracts': 1,
            'premium': 1.80,
            'strike_price': 185.0,
            'stock_cost_basis': 16000.0,
            'shares_covered': 100,
        }

        result = self.call_seller.execute_call_sale(opportunity)

        assert result['success'] is False
        assert result['error'] == 'execution_exception'


class TestCallSellerEarlyClose:
    """Test CallSeller.should_close_call_early."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.use_call_stop_loss = True
        self.mock_config.call_stop_loss_percent = 0.50
        self.mock_config.stop_loss_multiplier = 1.5
        self.mock_config.use_dynamic_profit_target = False
        self.mock_config.profit_taking_static_target = 0.50

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def test_should_close_at_profit_target(self):
        """Test closing when profit target is reached."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': 120.0,
            'market_value': -200.0,  # 120/200 = 0.60 > 0.50
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is True

    def test_should_not_close_below_profit_target(self):
        """Test not closing below profit target."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': 50.0,
            'market_value': -200.0,  # 50/200 = 0.25 < 0.50
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is False

    def test_stop_loss_triggered(self):
        """Test stop loss triggers for large losses."""
        # stop_loss_threshold = 0.50 * 1.5 = 0.75
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': -200.0,
            'market_value': -200.0,  # loss_pct = 200/200 = 1.0 > 0.75
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is True

    def test_delta_stop_loss_triggered(self):
        """Test delta-based stop loss when option goes ITM."""
        position = {
            'symbol': 'AAPL250117C00185000',
            'unrealized_pl': -50.0,
            'market_value': -300.0,  # loss_pct = 50/300 = 0.167 < 0.75
        }
        current_option_data = {'delta': 0.7}  # > 0.5, likely ITM

        result = self.call_seller.should_close_call_early(position, current_option_data)
        assert result is True

    def test_exception_returns_false(self):
        """Test that exceptions are handled gracefully."""
        position = {
            'symbol': 'AAPL250117C00185000',
            # Missing required keys to trigger exception
        }

        result = self.call_seller.should_close_call_early(position)
        assert result is False


class TestCallSellerCostBasisFloorFC029:
    """FC-029 (R2 + R3): cost-basis floor source order + drawdown pause.

    The bot must source the per-share cost basis from (in order):
      1. wheel_state.symbol_states[symbol]['stock_cost_basis']
         — populated at OPASN time from the put strike
      2. BQ lookup of the most recent OPASN-put strike for the symbol
         — handles silent assignments and cold starts
      3. Alpaca's reported cost_basis — last-resort fallback

    See docs/plans/fc-029.md and
    docs/investigations/cost-basis-floor-validation-2026-05-08.md.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.mock_config.min_call_premium = 0.30
        self.mock_config.call_drawdown_pause_threshold = 0.05

        # Patch BQ at the import site so no real network call is attempted.
        # Each test re-patches with the specific behavior it needs.
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 230.0}

    def _make_seller(self, wheel_state=None):
        # Stock quote returns near-cost (no drawdown) by default.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 247.0, 'ask': 248.0}
        return CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config,
                          wheel_state_manager=wheel_state)

    def _amzn_position(self):
        # Alpaca returns cost_basis=0 for assigned positions in paper trading
        # — this is the bug FC-029 R2 works around.
        return {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 0.0, 'market_value': 24700.0}

    def _candidate_call(self, strike: float, delta: float = 0.20):
        return {
            'symbol': f'AMZN260515C{int(strike * 1000):08d}',
            'strike_price': strike,
            'expiration_date': '2026-05-15',
            'dte': 7,
            'delta': delta,
            'mid_price': 1.50,
            'annual_return': 0.30,
        }

    def test_cost_basis_floor_uses_wheel_state(self):
        """FC-029 R2 source 1: wheel_state's stock_cost_basis is the floor.

        Even when Alpaca returns cost_basis=0 (paper-engine quirk), the floor
        must be the OPASN-put strike from wheel_state.
        """
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        seller = self._make_seller(wheel_state=wheel_state)

        # Call with strike >= cost basis is offered; floor passed correctly.
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        # Critical: find_suitable_calls received the wheel_state floor (247.5),
        # NOT the Alpaca cost_basis/100 = 0.
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )

    def test_cost_basis_floor_falls_back_to_bq_when_state_empty(self):
        """FC-029 R2 source 2: BQ lookup recovers OPASN-put strike, then backfills wheel_state.

        Uses a stateful mock so the backfill via ``set_stock_cost_basis`` is
        actually observed by the second ``get_position_summary`` call inside
        ``_calculate_call_position`` (which means the BQ lookup runs once, not
        twice — proving the backfill optimization works).
        """
        # Stateful wheel_state mock: get_position_summary reflects the latest
        # value written by set_stock_cost_basis.
        wheel_state = Mock()
        cb_state = {'stock_cost_basis': 0.0}
        wheel_state.get_position_summary.side_effect = lambda _s: dict(cb_state)
        wheel_state.set_stock_cost_basis.side_effect = lambda _s, cb: cb_state.update(stock_cost_basis=cb)

        seller = self._make_seller(wheel_state=wheel_state)
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        with patch.object(seller, '_lookup_last_opasn_put_strike', return_value=247.5) as mock_bq:
            result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        # BQ lookup ran exactly once (second resolve hits the wheel_state cache).
        mock_bq.assert_called_once_with('AMZN')
        # Floor was 247.5 from BQ.
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )
        # Backfilled wheel_state for fast-path on subsequent calls.
        wheel_state.set_stock_cost_basis.assert_called_once_with('AMZN', 247.5)

    def test_cost_basis_floor_falls_back_to_alpaca_for_manual_buys(self):
        """FC-029 R2 source 3: Alpaca's value is correct for non-wheel positions."""
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 0}
        seller = self._make_seller(wheel_state=wheel_state)
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(255.0)]

        # Alpaca returns a real cost basis (manual buy at $250/share).
        manual_buy_position = {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 25000.0, 'market_value': 25500.0}
        # No fresh near-cost quote: drawdown check uses 250 cb, mock current 248 → 0.8% drawdown < 5% → skip pause.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 247.0, 'ask': 249.0}

        with patch.object(seller, '_lookup_last_opasn_put_strike', return_value=0.0):
            result = seller.evaluate_covered_call_opportunity(manual_buy_position)

        assert result is not None
        # 25000 / 100 = 250.0 from Alpaca fallback.
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=250.0
        )

    def test_drawdown_pause_skips_when_underwater(self):
        """FC-029 R3: drawdown pause when shares > 5% below cost basis."""
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        seller = self._make_seller(wheel_state=wheel_state)

        # AMZN at $230 vs cost $247.5 → 7.07% drawdown > 5% threshold → skip.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 229.5, 'ask': 230.5}

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None
        # Critically: no call evaluation/sale was attempted.
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_drawdown_pause_does_not_skip_when_at_cost(self):
        """Drawdown pause should NOT fire when stock is within threshold of cost."""
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        seller = self._make_seller(wheel_state=wheel_state)

        # AMZN at $245 vs cost $247.5 → 1% drawdown < 5% threshold → don't skip.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 244.5, 'ask': 245.5}
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )

    def test_amzn_cycle_1_failure_mode_now_blocked(self):
        """End-to-end regression: AMZN cycle 1 (Nov 2025) loss scenario.

        Setup: shares assigned at $247.5, current price has dropped to $230
        (7% drawdown — below FC-029 threshold). Available calls in Alpaca's
        chain include strikes from $230 to $260.

        Pre-FC-029 outcome: bot wrote $230C (delta ~0.50, just OTM at the
        spot price), getting called away below cost.

        Post-FC-029 outcome: drawdown pause fires; no call written; bot waits
        for either a price recovery or for cycle to roll without share-side
        loss.
        """
        wheel_state = Mock()
        wheel_state.get_position_summary.return_value = {'stock_cost_basis': 247.5}
        seller = self._make_seller(wheel_state=wheel_state)

        # AMZN at $230 = 7.07% below cost basis $247.5.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 229.5, 'ask': 230.5}
        # Even if calls are available, drawdown pause should prevent evaluation.
        self.mock_market_data.find_suitable_calls.return_value = [
            self._candidate_call(232.5, delta=0.45),  # below cost — would have been the trap
            self._candidate_call(250.0, delta=0.18),
        ]

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None, "Drawdown pause must block call writes when stock is well below cost basis"
        self.mock_market_data.find_suitable_calls.assert_not_called()
