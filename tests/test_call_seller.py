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
        # FC-029: drawdown pause threshold needs to be a real number, not a
        # Mock (which would fail the `drawdown_pct >= threshold` comparison).
        self.mock_config.call_drawdown_pause_threshold = 0.05

        self.call_seller = CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)
        # Unit isolation: the suite's autouse hermeticity fixture stubs the
        # resolver's single BigQuery chokepoint
        # (`CostBasisResolver._lookup_assignment_basis`) to "no comparison
        # available", so these tests resolve against the position's own
        # `avg_entry_price` and never reach live production history. With
        # ambient GCP credentials (Cloud Build, dev machines with ADC) an
        # unstubbed lookup would read real AAPL assignments and the
        # cross-check would fail these fixtures closed as divergent (FC-065).

        # Default stock metrics
        self.mock_market_data.get_stock_metrics.return_value = {
            'current_price': 175.0,
        }
        # FC-029: default a usable quote so the drawdown-pause check doesn't
        # defer in legacy tests that didn't anticipate the quote requirement.
        # Cost basis is below stock price → drawdown_pct is negative (gain),
        # so the pause won't fire — tests proceed to call evaluation.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 174.5, 'ask': 175.5}

    def test_find_suitable_covered_calls(self):
        """Test finding suitable covered call opportunities."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'cost_basis': 16000.0,  # $160/share
            'avg_entry_price': 160.0,
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
            'avg_entry_price': 300.0,
            'market_value': 62000.0,
        }

        self.mock_market_data.find_suitable_calls.return_value = []
        # FC-029: provide a quote near cost basis so drawdown pause doesn't
        # fire (would block call evaluation). The test's intent is to verify
        # the cost-basis floor is passed; need to clear the pause path first.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 299.5, 'ask': 300.5}

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
            'avg_entry_price': 160.0,
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
            'avg_entry_price': 160.0,
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
            'avg_entry_price': 160.0,
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
            'avg_entry_price': 160.0,
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
        # Unit isolation: the suite's autouse hermeticity fixture stubs the
        # resolver's single BigQuery chokepoint
        # (`CostBasisResolver._lookup_assignment_basis`) to "no comparison
        # available", so these tests resolve against the position's own
        # `avg_entry_price` and never reach live production history. With
        # ambient GCP credentials (Cloud Build, dev machines with ADC) an
        # unstubbed lookup would read real AAPL assignments and the
        # cross-check would fail these fixtures closed as divergent (FC-065).

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
        # Unit isolation: the suite's autouse hermeticity fixture stubs the
        # resolver's single BigQuery chokepoint
        # (`CostBasisResolver._lookup_assignment_basis`) to "no comparison
        # available", so these tests resolve against the position's own
        # `avg_entry_price` and never reach live production history. With
        # ambient GCP credentials (Cloud Build, dev machines with ADC) an
        # unstubbed lookup would read real AAPL assignments and the
        # cross-check would fail these fixtures closed as divergent (FC-065).

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


class TestCallSellerCostBasisFloorFC065:
    """FC-065 (floor) + FC-029 R3 (drawdown pause, engine path only).

    The per-share floor is Alpaca's ``avg_entry_price`` for the equity
    position, vetoed by the BigQuery divergence cross-check. There is no
    wheel_state source and no BigQuery floor source any more — the inversion
    these tests were rewritten for.

    See docs/plans/fc-065.md §Phase 1.
    """

    def setup_method(self):
        self.mock_alpaca = Mock()
        self.mock_market_data = Mock()
        self.mock_config = Mock(spec=Config)
        self.mock_config.call_target_dte = 7
        self.mock_config.min_call_premium = 0.30
        self.mock_config.call_drawdown_pause_threshold = 0.05

        # The suite's autouse fixture stubs the resolver's BigQuery chokepoint,
        # so no real network call is attempted. Tests that want a cross-check
        # answer inject one explicitly.
        self.mock_market_data.get_stock_metrics.return_value = {'current_price': 230.0}

    def _make_seller(self):
        # Stock quote returns near-cost (no drawdown) by default.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 247.0, 'ask': 248.0}
        return CallSeller(self.mock_alpaca, self.mock_market_data, self.mock_config)

    def _amzn_position(self, avg_entry_price=247.5):
        # An assigned lot: the broker reports the premium-netted entry price,
        # and cost_basis agrees with it (qty * avg_entry_price).
        return {'symbol': 'AMZN', 'qty': 100,
                'cost_basis': avg_entry_price * 100,
                'avg_entry_price': avg_entry_price,
                'market_value': 24700.0}

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

    def test_cost_basis_floor_is_the_brokers_avg_entry_price(self):
        """FC-065: one field, broker-authoritative, no chain to walk."""
        seller = self._make_seller()

        # Call with strike >= cost basis is offered; floor passed correctly.
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )

    def test_a_divergent_cross_check_blocks_the_call_write(self):
        """The execute path fails closed on divergence too — one floor, one
        implementation, no path that fails open. Fails if the cross-check is
        reverted to warn-only."""
        seller = self._make_seller()
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        with patch.object(seller._cost_basis_resolver, '_lookup_assignment_basis',
                          return_value={'expected_basis_per_share': 210.0,
                                        'reconstructed_shares': 100, 'lots': []}):
            result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_an_agreeing_cross_check_leaves_the_floor_alone(self):
        """The veto must not cost us the calls we are entitled to sell."""
        seller = self._make_seller()
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        with patch.object(seller._cost_basis_resolver, '_lookup_assignment_basis',
                          return_value={'expected_basis_per_share': 247.45,
                                        'reconstructed_shares': 100, 'lots': []}):
            result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )

    def test_the_floor_works_for_a_manually_bought_position(self):
        """A non-wheel position has no assignment history, so the cross-check
        reports 'no comparison' and the broker's entry price stands."""
        seller = self._make_seller()
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(255.0)]

        # Manual buy at $250/share.
        manual_buy_position = {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 25000.0,
                               'avg_entry_price': 250.0, 'market_value': 25500.0}
        # No fresh near-cost quote: drawdown check uses 250 cb, mock current 248 → 0.8% drawdown < 5% → skip pause.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 247.0, 'ask': 249.0}

        result = seller.evaluate_covered_call_opportunity(manual_buy_position)

        assert result is not None
        # 25000 / 100 = 250.0 from Alpaca fallback.
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=250.0
        )

    def test_drawdown_pause_skips_when_underwater(self):
        """FC-029 R3: drawdown pause when shares > 5% below cost basis."""
        seller = self._make_seller()

        # AMZN at $230 vs cost $247.5 → 7.07% drawdown > 5% threshold → skip.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 229.5, 'ask': 230.5}

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None
        # Critically: no call evaluation/sale was attempted.
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_drawdown_pause_does_not_skip_when_at_cost(self):
        """Drawdown pause should NOT fire when stock is within threshold of cost."""
        seller = self._make_seller()

        # AMZN at $245 vs cost $247.5 → 1% drawdown < 5% threshold → don't skip.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 244.5, 'ask': 245.5}
        self.mock_market_data.find_suitable_calls.return_value = [self._candidate_call(250.0)]

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is not None
        self.mock_market_data.find_suitable_calls.assert_called_once_with(
            'AMZN', min_strike_price=247.5
        )

    def test_drawdown_pause_at_exact_threshold_boundary(self):
        """FC-029 R3: pause uses ``>=`` semantics, so exactly 5.00% triggers.

        Concern from peer review (concern #1) — get the boundary nailed.
        """
        seller = self._make_seller()

        # 5.00% exact: cost $100, current $95 → drawdown_pct = 0.05 ≥ 0.05 → pause.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 94.5, 'ask': 95.5}
        position = {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 10000.0,
                    'avg_entry_price': 100.0, 'market_value': 9500.0}

        result = seller.evaluate_covered_call_opportunity(position)

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_drawdown_pause_quote_fetch_failure_defers(self):
        """FC-029 review HIGH 2: bad quote → defer call write, don't fail-open.

        When the quote fetch raises, we must NOT proceed without the drawdown
        protection. Defer to the next monitor cycle (re-evaluates in ~5 min).
        """
        seller = self._make_seller()

        self.mock_alpaca.get_stock_quote.side_effect = Exception("network blip")

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None
        # Critical: no call evaluation/sale was attempted.
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_drawdown_pause_one_sided_quote_defers(self):
        """FC-029 review HIGH 2: one-sided quote (bid OR ask = 0) → defer.

        Pre-fix this was treated as "missing → proceed without pause check"
        (fail-open). The pause IS the protection; failing open means LESS
        protection precisely on noisy quotes (premarket, illiquid intraday,
        halts) — exactly the regimes the pause exists for. Now defers.
        """
        seller = self._make_seller()

        # Malformed quote (one side zero). Pre-FC-029-review proceeded; now defers.
        self.mock_alpaca.get_stock_quote.return_value = {'bid': 230.0, 'ask': 0}

        result = seller.evaluate_covered_call_opportunity(self._amzn_position())

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    @pytest.mark.parametrize("avg_entry_price", [0.0, None, 'nonsense'])
    def test_no_cost_basis_floor_resolved_blocks_call_write(self, avg_entry_price):
        """FC-029 review MEDIUM 6, carried forward to FC-065's single source:
        shares held but the broker reports no usable ``avg_entry_price`` means
        no floor, and no floor means no call — a structured-error block, not a
        write at any strike.

        FC-029 (2026-05-08) observed exactly this on assigned paper positions
        (``cost_basis = 0``). It was not reproducible in July 2026, but the
        whole floor now rests on one field of that payload, so a regression to
        zero must halt writing rather than write unprotected.
        """
        seller = self._make_seller()
        ghost_position = {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 0.0,
                          'avg_entry_price': avg_entry_price,
                          'market_value': 24700.0}

        result = seller.evaluate_covered_call_opportunity(ghost_position)

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

    def test_a_position_without_the_broker_field_at_all_blocks_the_write(self):
        """The plumbing failure the plan review caught: a caller handing the
        seller a position dict that never carried ``avg_entry_price``."""
        seller = self._make_seller()

        result = seller.evaluate_covered_call_opportunity(
            {'symbol': 'AMZN', 'qty': 100, 'cost_basis': 24750.0,
             'market_value': 24700.0})

        assert result is None
        self.mock_market_data.find_suitable_calls.assert_not_called()

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
        seller = self._make_seller()

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


class TestWrongSellerGuard:
    """FC-048: call_seller must refuse a PUT routed to it.

    put_seller has had the mirror of this guard since FC-021; the call side did
    not. That asymmetry is the same one that let the covered-call misroute hide
    — the put side rejected loudly, the call side had nothing to reject with.
    """

    def _seller(self):
        from src.strategy.call_seller import CallSeller
        s = CallSeller.__new__(CallSeller)      # builder-only; no __init__ wiring
        s.config = Mock(spec=Config)
        s.alpaca = Mock()
        s.market_data = Mock()
        return s

    def test_a_put_routed_to_the_call_seller_is_rejected(self):
        result = self._seller().execute_call_sale({
            'option_symbol': 'AAPL250117P00170000',   # a PUT
            'symbol': 'AAPL', 'strike_price': 170.0, 'contracts': 1,
        })

        assert result['success'] is False
        assert result['error_type'] == 'wrong_seller'
        assert result['non_retryable'] is True
        # And it never reached the broker.
        self.__dict__.setdefault('_', None)

    def test_a_call_is_not_rejected_by_the_guard(self):
        """The guard must not block legitimate calls."""
        seller = self._seller()
        result = seller.execute_call_sale({
            'option_symbol': 'AAPL250117C00190000',   # a CALL
            'symbol': 'AAPL', 'strike_price': 190.0, 'contracts': 1,
        })
        # It may fail later for other reasons, but never as wrong_seller.
        if result is not None:
            assert result.get('error_type') != 'wrong_seller'


class TestExecuteTimeCostBasisFloorFC050:
    """FC-050: the execute-time below-basis floor on the path production runs.

    ``execute_call_sale`` used to read only ``stock_cost_basis`` /
    ``shares_covered`` — keys that only the wheel-engine path sets. Every
    opportunity production actually executes comes from the scanner and carries
    ``cost_basis_per_share`` / ``max_contracts`` instead, so the guard silently
    never ran. The below-basis tests here fail against pre-FC-050 code.
    """

    def _seller(self):
        self.mock_alpaca = Mock()
        return CallSeller(self.mock_alpaca, Mock(), Mock(spec=Config))

    def _scanner_opportunity(self, strike, cost_basis_per_share=303.50):
        """The shape OptionsScanner._create_call_opportunity emits."""
        return {
            'type': 'call',
            'symbol': 'AAPL',
            'option_symbol': f'AAPL260821C{int(strike * 1000):08d}',
            'strike_price': strike,
            'premium': 1.80,
            'dte': 7,
            'shares_owned': 100,
            'max_contracts': 1,
            'contracts': 1,
            'cost_basis_per_share': cost_basis_per_share,
        }

    def test_a_scanner_opportunity_below_basis_is_blocked(self):
        """THE regression: $290 strike on shares that cost $303.50."""
        seller = self._seller()

        result = seller.execute_call_sale(self._scanner_opportunity(290.0))

        assert result['success'] is False
        assert result['error'] == 'strike_below_cost_basis'
        assert '303.50' in result['message']
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_a_scanner_opportunity_above_basis_still_trades(self):
        """The restored guard must not cost us the calls we may write."""
        seller = self._seller()
        self.mock_alpaca.place_option_order.return_value = {
            'success': True, 'order_id': 'order-fc050',
        }

        result = seller.execute_call_sale(self._scanner_opportunity(310.0))

        assert result['success'] is True
        self.mock_alpaca.place_option_order.assert_called_once()

    def test_a_strike_exactly_at_basis_is_allowed(self):
        """Called away at cost is flat on the shares plus the premium — the
        guard blocks losses, not break-even."""
        seller = self._seller()
        self.mock_alpaca.place_option_order.return_value = {
            'success': True, 'order_id': 'order-flat',
        }

        result = seller.execute_call_sale(self._scanner_opportunity(303.50))

        assert result['success'] is True

    def test_a_multi_contract_wheel_engine_opportunity_divides_by_contracts(self):
        """FC-038 made multi-contract covered calls reachable. A total basis of
        $32,000 over 2 contracts is $160/share — dividing by a bare 100 would
        read $320 and block a perfectly good $170 strike."""
        seller = self._seller()
        self.mock_alpaca.place_option_order.return_value = {
            'success': True, 'order_id': 'order-multi',
        }

        result = seller.execute_call_sale({
            'option_symbol': 'AAPL250117C00170000',
            'symbol': 'AAPL',
            'strike_price': 170.0,
            'premium': 1.80,
            'contracts': 2,
            'stock_cost_basis': 32000.0,   # 200 shares at $160
            'dte': 7,
        })

        assert result['success'] is True

    def test_a_multi_contract_opportunity_below_the_true_basis_is_blocked(self):
        seller = self._seller()

        result = seller.execute_call_sale({
            'option_symbol': 'AAPL250117C00150000',
            'symbol': 'AAPL',
            'strike_price': 150.0,
            'premium': 3.00,
            'contracts': 2,
            'stock_cost_basis': 32000.0,   # $160/share, not $320
            'dte': 7,
        })

        assert result['success'] is False
        assert result['error'] == 'strike_below_cost_basis'
        assert '160.00' in result['message']
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_an_opportunity_with_no_resolvable_floor_is_blocked(self):
        """Fail closed: post-FC-050 both producers carry a floor, so none means
        a malformed opportunity — never 'skip the check and trade'."""
        seller = self._seller()

        result = seller.execute_call_sale({
            'option_symbol': 'AAPL250117C00185000',
            'symbol': 'AAPL',
            'strike_price': 185.0,
            'premium': 1.80,
            'contracts': 1,
        })

        assert result['success'] is False
        assert result['error_type'] == 'cost_basis_floor_unresolved_at_execution'
        assert result['non_retryable'] is False
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_a_zero_cost_basis_per_share_is_blocked_not_ignored(self):
        """Alpaca reports 0 for freshly assigned positions (FC-029)."""
        seller = self._seller()

        result = seller.execute_call_sale(
            self._scanner_opportunity(310.0, cost_basis_per_share=0.0))

        assert result['success'] is False
        assert result['error_type'] == 'cost_basis_floor_unresolved_at_execution'
        self.mock_alpaca.place_option_order.assert_not_called()

    def test_a_misrouted_put_is_still_rejected_before_the_floor_check(self):
        """The FC-045/FC-048 guard stays ahead of the floor: a put must be
        rejected as wrong_seller, not as an unresolved floor."""
        seller = self._seller()

        result = seller.execute_call_sale({
            'option_symbol': 'AAPL250117P00170000',
            'symbol': 'AAPL',
            'strike_price': 170.0,
            'contracts': 1,
        })

        assert result['error_type'] == 'wrong_seller'
        assert result['non_retryable'] is True
        self.mock_alpaca.place_option_order.assert_not_called()
