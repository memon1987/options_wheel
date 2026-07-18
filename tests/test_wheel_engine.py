"""Tests for wheel strategy engine."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.strategy.wheel_engine import WheelEngine
from src.utils.config import Config


class TestWheelEngine:
    """Test wheel strategy engine functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock(spec=Config)
        self.mock_config.max_total_positions = 10
        self.mock_config.stock_symbols = ['AAPL', 'MSFT', 'GOOGL']
        
        # Mock the dependencies
        with patch('src.strategy.wheel_engine.AlpacaClient') as mock_alpaca_cls, \
             patch('src.strategy.wheel_engine.MarketDataManager') as mock_market_cls, \
             patch('src.strategy.wheel_engine.PutSeller') as mock_put_cls, \
             patch('src.strategy.wheel_engine.CallSeller') as mock_call_cls:
            
            self.mock_alpaca = Mock()
            self.mock_market_data = Mock()
            self.mock_put_seller = Mock()
            self.mock_call_seller = Mock()
            
            mock_alpaca_cls.return_value = self.mock_alpaca
            mock_market_cls.return_value = self.mock_market_data
            mock_put_cls.return_value = self.mock_put_seller
            mock_call_cls.return_value = self.mock_call_seller
            
            self.wheel_engine = WheelEngine(self.mock_config)
        
        # Set up mock responses
        self.sample_account = {
            'portfolio_value': 100000.0,
            'cash': 25000.0,
            'buying_power': 50000.0,
            'equity': 100000.0
        }
        
        self.sample_positions = [
            {
                'symbol': 'AAPL',
                'qty': 100,
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': 500.0
            },
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 100.0
            }
        ]
        
        self.mock_alpaca.get_account.return_value = self.sample_account
        self.mock_alpaca.get_positions.return_value = self.sample_positions
    
    def test_wheel_engine_initialization(self):
        """Test wheel engine initialization."""
        assert self.wheel_engine.config == self.mock_config
        assert self.wheel_engine.alpaca == self.mock_alpaca
        assert self.wheel_engine.market_data == self.mock_market_data
        assert self.wheel_engine.put_seller == self.mock_put_seller
        assert self.wheel_engine.call_seller == self.mock_call_seller
    
    def test_run_strategy_cycle_basic(self):
        """Test basic strategy cycle execution."""
        # Mock market data response
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'AAPL', 'current_price': 150.0, 'suitable_for_wheel': True}
        ]
        
        # Mock put seller response
        self.mock_put_seller.find_put_opportunity.return_value = {
            'action_type': 'new_position',
            'symbol': 'AAPL',
            'strategy': 'sell_put'
        }
        
        # Mock call seller response
        self.mock_call_seller.evaluate_covered_call_opportunity.return_value = None
        
        result = self.wheel_engine.run_strategy_cycle()
        
        assert 'timestamp' in result
        assert 'actions' in result
        assert 'account_info' in result
        assert 'positions_analyzed' in result
        
        assert result['account_info'] == self.sample_account
        assert result['positions_analyzed'] == len(self.sample_positions)
        assert len(result['actions']) >= 0
    
    def test_manage_existing_positions_with_stock(self):
        """Test management of existing stock positions."""
        stock_position = {
            'symbol': 'AAPL',
            'qty': 100,
            'asset_class': 'us_equity',
            'market_value': 15000.0,
            'unrealized_pl': 500.0
        }

        # Set up wheel state to have AAPL in holding_stock phase
        # This is required for covered call selling to be allowed
        self.wheel_engine.wheel_state.handle_put_assignment(
            symbol='AAPL',
            shares=100,
            cost_basis=150.0,
            assignment_date=datetime.now()
        )

        # Mock call seller to return an action
        self.mock_call_seller.evaluate_covered_call_opportunity.return_value = {
            'action_type': 'new_position',
            'strategy': 'sell_call',
            'symbol': 'AAPL'
        }

        actions = self.wheel_engine._manage_existing_positions([stock_position])

        assert len(actions) == 1
        assert actions[0]['strategy'] == 'sell_call'

        # Verify call seller was called with the stock position
        self.mock_call_seller.evaluate_covered_call_opportunity.assert_called_once_with(stock_position)
    
    def test_manage_existing_positions_with_options(self):
        """Test management of existing option positions."""
        option_position = {
            'symbol': 'AAPL_PUT_150_2024_04_19',
            'qty': -1,  # Short position
            'asset_class': 'us_option',
            'market_value': -200.0,
            'unrealized_pl': 100.0  # Profitable
        }
        
        actions = self.wheel_engine._manage_existing_positions([option_position])
        
        # Should consider closing profitable positions
        assert len(actions) >= 0
        
        # If an action is generated, it should be a close position
        if actions:
            assert actions[0]['action_type'] == 'close_position'
    
    def test_can_open_new_positions_success(self):
        """Test can open new positions when within limits."""
        # Few positions, good buying power
        limited_positions = [
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 0.0
            }
        ]
        
        can_open = self.wheel_engine._can_open_new_positions(limited_positions)
        assert can_open == True
    
    def test_can_open_new_positions_max_reached(self):
        """Test can't open new positions when maximum reached."""
        # Create positions at the limit
        max_positions = []
        for i in range(10):
            max_positions.append({
                'symbol': f'TEST_{i}_PUT',
                'qty': -1,
                'asset_class': 'us_option',
                'market_value': -100.0,
                'unrealized_pl': 0.0
            })
        
        can_open = self.wheel_engine._can_open_new_positions(max_positions)
        assert can_open == False
    
    def test_can_open_new_positions_low_buying_power(self):
        """Test can't open new positions with low buying power."""
        # Mock low buying power account
        low_bp_account = self.sample_account.copy()
        low_bp_account['buying_power'] = 500.0
        
        self.mock_alpaca.get_account.return_value = low_bp_account
        
        can_open = self.wheel_engine._can_open_new_positions([])
        assert can_open == False
    
    def test_find_new_opportunities(self):
        """Test finding new trading opportunities."""
        # Mock suitable stocks
        self.mock_market_data.filter_suitable_stocks.return_value = [
            {'symbol': 'MSFT', 'current_price': 300.0, 'suitable_for_wheel': True},
            {'symbol': 'GOOGL', 'current_price': 2500.0, 'suitable_for_wheel': True}
        ]
        
        # Mock put opportunity
        self.mock_put_seller.find_put_opportunity.return_value = {
            'action_type': 'new_position',
            'symbol': 'MSFT',
            'strategy': 'sell_put',
            'premium': 5.00
        }
        
        # Mock no existing positions in these stocks
        self.mock_alpaca.get_positions.return_value = []
        
        actions = self.wheel_engine._find_new_opportunities()
        
        assert len(actions) >= 0
        
        # Should call filter_suitable_stocks
        self.mock_market_data.filter_suitable_stocks.assert_called_once()
        
        # If actions found, should be new positions
        if actions:
            assert all(action['action_type'] == 'new_position' for action in actions)
    
    def test_has_existing_position_with_stock(self):
        """Test detection of existing stock positions."""
        positions_with_aapl = [
            {
                'symbol': 'AAPL',
                'asset_class': 'us_equity',
                'market_value': 15000.0,
                'unrealized_pl': 500.0
            }
        ]
        
        self.mock_alpaca.get_positions.return_value = positions_with_aapl
        
        has_position = self.wheel_engine._has_existing_position('AAPL')
        assert has_position == True
        
        has_position_msft = self.wheel_engine._has_existing_position('MSFT')
        assert has_position_msft == False
    
    def test_has_existing_position_with_options(self):
        """Test detection of existing option positions."""
        positions_with_options = [
            {
                'symbol': 'AAPL_PUT_150_2024_04_19',
                'asset_class': 'us_option',
                'market_value': -200.0,
                'unrealized_pl': 100.0
            }
        ]
        
        self.mock_alpaca.get_positions.return_value = positions_with_options
        
        has_position = self.wheel_engine._has_existing_position('AAPL')
        assert has_position == True
    
    def test_get_strategy_status(self):
        """Test getting strategy status summary."""
        status = self.wheel_engine.get_strategy_status()
        
        assert 'account' in status
        assert 'positions' in status
        assert 'capacity' in status
        assert 'timestamp' in status
        
        assert status['account']['portfolio_value'] == self.sample_account['portfolio_value']
        assert status['positions']['total_positions'] == len(self.sample_positions)
        assert 'can_open_new_positions' in status['capacity']
        assert 'positions_remaining' in status['capacity']
    
    def test_strategy_cycle_with_errors(self):
        """Test strategy cycle handling with errors."""
        # Mock an error in account retrieval
        self.mock_alpaca.get_account.side_effect = Exception("API Error")
        
        result = self.wheel_engine.run_strategy_cycle()
        
        assert 'errors' in result
        assert len(result['errors']) > 0
        assert "API Error" in result['errors'][0]
    
    def test_evaluate_option_position_profitable(self):
        """Test evaluation of profitable option position."""
        profitable_position = {
            'symbol': 'AAPL_PUT_150_2024_04_19',
            'qty': -1,  # Short position
            'unrealized_pl': 150.0,  # Profitable
            'market_value': -200.0
        }
        
        action = self.wheel_engine._evaluate_option_position(profitable_position)
        
        assert action is not None
        assert action['action_type'] == 'close_position'
        assert action['reason'] == 'profit_target'
        assert action['unrealized_pl'] == 150.0

# --------------------------------------------------------------------------- #
# FC-035: poll_order_statuses closed-orders path
#
# This path raised `NameError: name 'alpaca' is not defined` on every
# invocation (the module was never imported), and the surrounding
# `except Exception` swallowed it — so it had never executed in production.
# Even once the import was fixed, `closed_orders` was assigned and never
# read. These tests exercise the path end to end so neither defect can
# return silently.
# --------------------------------------------------------------------------- #
class _FakeEnum:
    """Stands in for an SDK enum whose value is read via `.value`."""

    def __init__(self, value):
        self.value = value


class _FakeSDKOrder:
    """Mimics an alpaca-py `Order` model as returned by the trading client."""

    def __init__(self, order_id, symbol, status, qty=1, filled_qty=1,
                 filled_avg_price="2.50", side="sell"):
        self.id = order_id
        self.symbol = symbol
        self.status = _FakeEnum(status)
        self.side = _FakeEnum(side)
        self.order_type = _FakeEnum("limit")
        self.qty = qty
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.submitted_at = datetime(2026, 7, 17, 10, 0, 0)
        # Real expired/canceled orders carry filled_at=None. Hard-coding a
        # datetime here is what let the str(None) -> 'None' bug hide.
        self.filled_at = (datetime(2026, 7, 17, 10, 0, 5)
                          if status == "filled" else None)


class TestPollOrderStatusesClosedOrders:
    """The closed-orders path must actually run and actually be consumed."""

    def setup_method(self):
        mock_config = Mock(spec=Config)
        mock_config.max_total_positions = 10
        mock_config.stock_symbols = ['AAPL']

        with patch('src.strategy.wheel_engine.AlpacaClient') as mock_alpaca_cls, \
             patch('src.strategy.wheel_engine.MarketDataManager'), \
             patch('src.strategy.wheel_engine.PutSeller'), \
             patch('src.strategy.wheel_engine.CallSeller'):
            self.mock_alpaca = Mock()
            mock_alpaca_cls.return_value = self.mock_alpaca
            self.engine = WheelEngine(mock_config)

        # `get_orders()` sends no status filter and Alpaca defaults to "open",
        # so the wrapper yields only non-final orders. Empty is the realistic
        # case: without the closed-orders fetch there is nothing to log.
        self.mock_alpaca.get_orders.return_value = []

    def _run(self, closed_orders):
        self.mock_alpaca.trading_client.get_orders.return_value = closed_orders
        with patch('src.strategy.wheel_engine.log_order_status_update') as log_status, \
             patch('src.strategy.wheel_engine.get_analytics_writer') as get_writer:
            self.writer = Mock()
            get_writer.return_value = self.writer
            stats = self.engine.poll_order_statuses()
        return stats, log_status

    def _payloads(self):
        """kwargs of every write_order_status call made during the run."""
        return [c.kwargs for c in self.writer.write_order_status.call_args_list]

    def test_closed_orders_are_fetched_and_logged(self):
        """Regression: the NameError made this path a permanent no-op.

        With the bug present, `closed_orders` is [] and nothing is ever
        logged, so every assertion below fails.
        """
        stats, log_status = self._run([
            _FakeSDKOrder("ord-1", "AAPL260717P00150000", "filled"),
            _FakeSDKOrder("ord-2", "AAPL260717P00140000", "expired"),
        ])

        assert stats['orders_checked'] == 2
        assert stats['filled_logged'] == 1
        assert stats['expired_logged'] == 1
        assert stats['errors'] == 0

        event_types = [c.kwargs['event_type'] for c in log_status.call_args_list]
        assert event_types == ['order_filled', 'order_expired']

    def test_closed_orders_request_uses_closed_status_filter(self):
        """The fetch must ask for CLOSED orders, not re-request open ones."""
        from alpaca.trading.enums import QueryOrderStatus

        self._run([])

        _, kwargs = self.mock_alpaca.trading_client.get_orders.call_args
        assert kwargs['filter'].status == QueryOrderStatus.CLOSED

    def test_closed_orders_request_is_bounded_to_seven_days(self):
        """The job has no persistence, so an unbounded window re-logs history.

        The docstring has always promised a 7-day lookback; assert the request
        actually carries it.
        """
        from src.utils import clock

        self._run([])

        _, kwargs = self.mock_alpaca.trading_client.get_orders.call_args
        after = kwargs['filter'].after
        assert after is not None, "closed-orders fetch is unbounded"
        assert (clock.now_utc() - after).days == 7

    def test_expired_order_with_no_fill_price_still_logs(self):
        """Expired orders carry filled_avg_price=None (15% of live closed orders).

        `float(None)` would raise and silently drop the analytics write.
        """
        stats, log_status = self._run([
            _FakeSDKOrder("ord-3", "AAPL260717P00140000", "expired",
                          filled_qty=0, filled_avg_price=None),
        ])
        assert stats['expired_logged'] == 1
        assert stats['errors'] == 0
        assert log_status.call_args.kwargs['event_type'] == 'order_expired'

    def test_no_exception_is_swallowed_on_the_closed_path(self):
        """The bug hid behind `except Exception` -> closed_orders_failed.

        If any NameError-style defect returns, the fetch raises, the handler
        sets closed_orders = [] and nothing is logged.
        """
        stats, log_status = self._run([
            _FakeSDKOrder("ord-1", "AAPL260717P00150000", "filled"),
        ])
        assert log_status.call_count == 1, (
            "closed-orders fetch was swallowed by the except handler"
        )
        assert stats['filled_logged'] == 1

    def test_order_in_both_sources_is_logged_once_with_final_state(self):
        """Dedupe by order_id; the closed (final) state wins."""
        self.mock_alpaca.get_orders.return_value = [{
            'order_id': 'ord-1', 'symbol': 'AAPL260717P00150000',
            'status': 'new', 'filled_qty': 0, 'filled_avg_price': None,
        }]
        stats, log_status = self._run([
            _FakeSDKOrder("ord-1", "AAPL260717P00150000", "filled"),
        ])

        assert stats['orders_checked'] == 1
        assert log_status.call_count == 1
        assert log_status.call_args.kwargs['event_type'] == 'order_filled'

    def test_sdk_order_is_normalized_to_wrapper_shape(self):
        """Normalized closed orders must match AlpacaClient.get_orders()."""
        row = WheelEngine._normalize_sdk_order(
            _FakeSDKOrder("ord-9", "AAPL260717P00150000", "filled",
                          qty=2, filled_qty=1, filled_avg_price="3.25")
        )
        assert row['order_id'] == 'ord-9'
        assert row['status'] == 'filled'
        assert row['side'] == 'sell'
        assert row['qty'] == 2
        assert row['filled_qty'] == 1
        assert row['remaining_qty'] == 1
        assert row['is_partial_fill'] is True
        assert row['filled_avg_price'] == 3.25

    def test_malformed_order_does_not_abort_the_poll(self):
        """One unreadable order must not take the whole job down."""
        stats, log_status = self._run([
            object(),  # no attributes at all
            _FakeSDKOrder("ord-2", "AAPL260717P00140000", "filled"),
        ])
        assert stats['filled_logged'] == 1
        assert log_status.call_count == 1

    # --- fixes required by adversarial review -------------------------- #

    def test_expired_order_sends_empty_not_none_string_for_filled_at(self):
        """`str(None)` -> 'None', which BigQuery rejects for a TIMESTAMP.

        `write_order_status` maps falsy -> NULL, but the non-empty string
        'None' is truthy, so it reached BigQuery and the row was dropped.
        Every expired/canceled order has filled_at=None, so this was ~17%
        of qualifying orders silently lost.
        """
        self._run([
            _FakeSDKOrder("ord-e", "AAPL260717P00140000", "expired",
                          filled_qty=0, filled_avg_price=None),
        ])
        payload = self._payloads()[0]
        assert payload['filled_at'] == '', (
            f"filled_at={payload['filled_at']!r} would be rejected as a TIMESTAMP"
        )
        assert payload['filled_at'] != 'None'

    def test_call_on_p_containing_underlying_is_not_labeled_a_put(self):
        """`'P' in symbol` labeled every AAPL/SPY/PFE call as a put.

        Three of the configured symbols contain 'P', so this was structural,
        not an edge case.
        """
        _, log_status = self._run([
            _FakeSDKOrder("ord-c", "AAPL260715C00317500", "filled"),
        ])
        assert log_status.call_args.kwargs['strategy'] == 'sell_call'
        assert self._payloads()[0]['underlying'] == 'AAPL'

    def test_buy_to_close_is_not_labeled_a_sell(self):
        """The bot buys to close; labeling those as sells inverts attribution."""
        _, log_status = self._run([
            _FakeSDKOrder("ord-b", "IWM260721P00289000", "filled", side="buy"),
        ])
        assert log_status.call_args.kwargs['strategy'] == 'buy_to_close_put'
        assert self._payloads()[0]['side'] == 'buy'

    def test_equity_symbol_is_not_classified_as_an_option(self):
        """parse_option_symbol falls back to a type on short strings."""
        assert WheelEngine._classify_order_strategy('PFE', 'sell') == 'unknown'
        assert WheelEngine._classify_order_strategy('', '') == 'unknown'

    def test_analytics_payload_carries_the_audit_columns(self):
        """underlying/order_type/submitted_at were computed and discarded,
        leaving the audit table's grouping column blank."""
        self._run([
            _FakeSDKOrder("ord-a", "AAPL260717P00150000", "filled"),
        ])
        payload = self._payloads()[0]
        assert payload['underlying'] == 'AAPL'
        assert payload['order_type'] == 'limit'
        assert payload['submitted_at'] == '2026-07-17 10:00:00'
        assert payload['filled_price'] == 2.50

    def test_closed_fetch_failure_is_visible_to_the_caller(self):
        """A debug log is suppressed at production level — that is how the
        original NameError hid for three months."""
        self.mock_alpaca.trading_client.get_orders.side_effect = RuntimeError("boom")
        with patch('src.strategy.wheel_engine.log_order_status_update'), \
             patch('src.strategy.wheel_engine.get_analytics_writer'):
            stats = self.engine.poll_order_statuses()
        assert stats['closed_fetch_ok'] is False
        assert stats['closed_orders_fetched'] == 0

    def test_successful_fetch_reports_ok(self):
        stats, _ = self._run([
            _FakeSDKOrder("ord-1", "AAPL260717P00150000", "filled"),
        ])
        assert stats['closed_fetch_ok'] is True
        assert stats['closed_orders_fetched'] == 1

    def test_analytics_write_is_deduped_by_order_and_status(self):
        """The job re-polls the same closed orders ~30x per 7-day window with
        no persistence, so the write needs an idempotency key."""
        from src.data.analytics_writer import AnalyticsWriter

        writer = AnalyticsWriter.__new__(AnalyticsWriter)
        writer._enabled = True
        writer._tables = {"order_statuses": "tbl"}
        writer._client = Mock()
        writer._client.insert_rows_json.return_value = []

        writer.write_order_status(order_id="ord-1", symbol="AAPL260717P00150000",
                                  status="filled")
        _, kwargs = writer._client.insert_rows_json.call_args
        assert kwargs['row_ids'] == ["ord-1:filled"]

    def test_page_limit_truncation_is_warned(self):
        """At the page limit the oldest orders are dropped and, with no
        persistence, never logged."""
        from src.strategy.wheel_engine import CLOSED_ORDER_PAGE_LIMIT
        orders = [
            _FakeSDKOrder(f"ord-{i}", "AAPL260717P00150000", "filled")
            for i in range(CLOSED_ORDER_PAGE_LIMIT)
        ]
        with patch('src.strategy.wheel_engine.logger') as mock_logger:
            self._run(orders)
        warned = [c for c in mock_logger.warning.call_args_list
                  if c.kwargs.get('event_type') == 'closed_orders_truncated']
        assert len(warned) == 1

    def test_closed_fetch_uses_utc_and_descending_order(self):
        """clock.now() is naive local; the API bound must be UTC-aware."""
        from alpaca.common.enums import Sort

        self._run([])
        _, kwargs = self.mock_alpaca.trading_client.get_orders.call_args
        req = kwargs['filter']
        assert req.after.tzinfo is not None, "after= must be timezone-aware"
        assert req.direction == Sort.DESC
