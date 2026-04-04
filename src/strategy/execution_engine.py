"""Execution engine for batch order selection and trade execution.

Extracts business logic from the Flask server layer (cloud_run_server.py /run endpoint)
into independently testable methods:
  - Idempotency checks (filtering opportunities where positions already exist)
  - Buying power tracking
  - ROI-based opportunity ranking
  - Batch order selection
  - Sequential order execution
"""

from typing import Dict, List, Any, Optional, Set, Tuple
import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..data.trade_journal import TradeJournal
from ..utils.config import Config
from ..utils.logging_events import log_system_event, log_error_event
from .put_seller import PutSeller
from .call_seller import CallSeller

logger = structlog.get_logger(__name__)

# Module-level set tracking option symbols that failed with non-retryable errors today.
# This prevents the same rejected opportunity from being retried every /run cycle.
# Cleared on service restart (daily Cloud Run cold start).
_failed_symbols: Set[str] = set()


def get_failed_symbols() -> Set[str]:
    """Return the current set of failed (non-retryable) option symbols."""
    return _failed_symbols


def clear_failed_symbols() -> None:
    """Clear the failed symbols set (e.g., at start of new trading day)."""
    _failed_symbols.clear()


class ExecutionEngine:
    """Handles batch opportunity selection and trade execution.

    Encapsulates the business logic previously inlined in the ``/run``
    endpoint of ``cloud_run_server.py``.
    """

    def __init__(self, alpaca_client: AlpacaClient, config: Config,
                 log: Optional[Any] = None,
                 trade_journal: Optional[TradeJournal] = None):
        """Initialize the execution engine.

        Args:
            alpaca_client: Alpaca API client instance.
            config: Application configuration.
            log: Optional structlog logger (falls back to module logger).
            trade_journal: Optional TradeJournal for persistent trade recording.
        """
        self.alpaca_client = alpaca_client
        self.config = config
        self.logger = log or logger
        self.trade_journal = trade_journal or TradeJournal()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_duplicate_opportunities(
        self,
        opportunities: List[Dict[str, Any]],
        existing_positions: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Remove opportunities where a position already exists (idempotency).

        Args:
            opportunities: Raw opportunities from the opportunity store.
            existing_positions: Current option positions from Alpaca.

        Returns:
            A tuple of (filtered_opportunities, filtered_count).
        """
        existing_symbols: Set[str] = {
            pos.get('symbol') for pos in existing_positions if pos.get('symbol')
        }

        original_count = len(opportunities)
        filtered = [
            opp for opp in opportunities
            if opp.get('option_symbol') not in existing_symbols
        ]

        filtered_count = original_count - len(filtered)
        if filtered_count > 0:
            self.logger.warning(
                "Idempotency check: filtered out opportunities with existing positions",
                event_category="system",
                event_type="idempotency_filter_applied",
                original_count=original_count,
                filtered_count=filtered_count,
                remaining_count=len(filtered),
            )

        return filtered, filtered_count

    def filter_failed_opportunities(
        self,
        opportunities: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Remove opportunities whose option symbol previously failed with a non-retryable error.

        Args:
            opportunities: Opportunities to filter.

        Returns:
            A tuple of (filtered_opportunities, filtered_count).
        """
        if not _failed_symbols:
            return opportunities, 0

        original_count = len(opportunities)
        filtered = [
            opp for opp in opportunities
            if opp.get('option_symbol') not in _failed_symbols
        ]

        filtered_count = original_count - len(filtered)
        if filtered_count > 0:
            self.logger.warning(
                "Filtered out previously failed (non-retryable) opportunities",
                event_category="system",
                event_type="non_retryable_filter_applied",
                original_count=original_count,
                filtered_count=filtered_count,
                remaining_count=len(filtered),
                failed_symbols=list(_failed_symbols),
            )

        return filtered, filtered_count

    def rank_opportunities(
        self,
        opportunities: List[Dict[str, Any]],
        put_seller: PutSeller,
        available_buying_power: float,
    ) -> List[Dict[str, Any]]:
        """Calculate ROI for each opportunity and return sorted list.

        Each entry in the returned list is a dict with keys:
        ``opportunity``, ``collateral``, ``premium``, ``roi``.

        Args:
            opportunities: Opportunities to rank.
            put_seller: PutSeller instance (used for position sizing).
            available_buying_power: Current buying power for sizing.

        Returns:
            List of metric dicts sorted by ROI descending.
        """
        opportunities_with_metrics: List[Dict[str, Any]] = []

        for opp in opportunities:
            # Transform scanner format to position sizing format
            if 'premium' in opp and 'mid_price' not in opp:
                opp['mid_price'] = opp['premium']

            # Calculate position size
            position_size = put_seller._calculate_position_size(
                opp, override_buying_power=available_buying_power
            )
            if not position_size:
                continue

            opp['contracts'] = position_size['contracts']
            collateral = opp['strike_price'] * 100 * opp['contracts']
            premium_collected = opp['premium'] * 100 * opp['contracts']
            roi = premium_collected / collateral if collateral > 0 else 0

            opportunities_with_metrics.append({
                'opportunity': opp,
                'collateral': collateral,
                'premium': premium_collected,
                'roi': roi,
            })

        # Sort by ROI (highest first)
        opportunities_with_metrics.sort(key=lambda x: x['roi'], reverse=True)
        return opportunities_with_metrics

    def select_batch(
        self,
        ranked_opportunities: List[Dict[str, Any]],
        available_buying_power: float,
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Greedily select opportunities that fit within buying power.

        Only one position per underlying stock is allowed (risk management rule).

        Args:
            ranked_opportunities: Opportunities sorted by ROI (from ``rank_opportunities``).
            available_buying_power: Starting buying power.

        Returns:
            A tuple of (selected_opportunities, remaining_buying_power).
        """
        selected: List[Dict[str, Any]] = []
        selected_underlyings: Set[str] = set()
        remaining_bp = available_buying_power

        for item in ranked_opportunities:
            underlying = item['opportunity'].get('symbol')

            # Skip if we already have a position for this underlying
            if underlying in selected_underlyings:
                self.logger.info(
                    "Skipping duplicate underlying in batch selection",
                    event_category="filtering",
                    event_type="duplicate_underlying_skipped",
                    symbol=underlying,
                    collateral=item['collateral'],
                    premium=item['premium'],
                    roi=f"{item['roi']:.4f}",
                    reason="already_selected_for_execution",
                )
                continue

            if item['collateral'] <= remaining_bp:
                selected.append(item['opportunity'])
                selected_underlyings.add(underlying)
                remaining_bp -= item['collateral']
                self.logger.info(
                    "Selected opportunity for batch execution",
                    event_category="system",
                    event_type="opportunity_selected_for_execution",
                    symbol=underlying,
                    collateral=item['collateral'],
                    premium=item['premium'],
                    roi=f"{item['roi']:.4f}",
                    remaining_bp=remaining_bp,
                )

        self.logger.info(
            "Batch order selection complete",
            event_category="system",
            event_type="batch_selection_completed",
            total_opportunities=len(ranked_opportunities),
            selected_count=len(selected),
            initial_bp=available_buying_power,
            bp_to_use=available_buying_power - remaining_bp,
        )

        return selected, remaining_bp

    def execute_batch(
        self,
        selected_opportunities: List[Dict[str, Any]],
        put_seller: PutSeller,
        call_seller: Optional[CallSeller] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Execute orders sequentially with real-time buying power validation.

        Routes put opportunities to put_seller and call opportunities to
        call_seller.  Call opportunities are rejected if call_seller is not
        provided or if the account does not own sufficient shares (naked call
        prevention).

        Args:
            selected_opportunities: Opportunities chosen by ``select_batch``.
            put_seller: PutSeller instance for put order execution.
            call_seller: Optional CallSeller instance for covered call execution.

        Returns:
            A tuple of (execution_results, trades_executed_count).
        """
        self.logger.info(
            "Executing batch orders sequentially",
            event_category="system",
            event_type="batch_orders_executing",
            order_count=len(selected_opportunities),
        )

        execution_results: List[Dict[str, Any]] = []
        trades_executed = 0

        for opp in selected_opportunities:
            try:
                opp_type = opp.get('type', 'put')

                if opp_type == 'call':
                    # --- Covered call path ---
                    if call_seller is None:
                        self.logger.warning(
                            "Call opportunity skipped — no call_seller provided",
                            event_category="trade",
                            event_type="call_skipped_no_seller",
                            symbol=opp.get('symbol'),
                            option_symbol=opp.get('option_symbol'),
                        )
                        execution_results.append({
                            'opportunity': opp,
                            'result': {'success': False, 'message': 'No call seller available'},
                            'success': False,
                        })
                        continue

                    # Verify share ownership before executing covered call
                    underlying = opp.get('symbol')
                    contracts = opp.get('contracts', 1)
                    required_shares = contracts * 100

                    try:
                        positions = self.alpaca_client.get_positions()
                        stock_pos = next(
                            (p for p in positions
                             if p.get('symbol') == underlying
                             and p.get('asset_class') == 'us_equity'),
                            None,
                        )
                        owned_shares = int(float(stock_pos['qty'])) if stock_pos else 0
                    except Exception:
                        owned_shares = 0

                    if owned_shares < required_shares:
                        self.logger.warning(
                            "Naked call prevented — insufficient shares",
                            event_category="risk",
                            event_type="naked_call_blocked",
                            symbol=underlying,
                            option_symbol=opp.get('option_symbol'),
                            required_shares=required_shares,
                            owned_shares=owned_shares,
                        )
                        # Do NOT add to _failed_symbols — share ownership is transient.
                        # The account could acquire shares before the next /run cycle
                        # (e.g., put assignment), at which point this call becomes valid.
                        execution_results.append({
                            'opportunity': opp,
                            'result': {'success': False, 'message': f'Naked call blocked: own {owned_shares} shares, need {required_shares}'},
                            'success': False,
                        })
                        continue

                    result = call_seller.execute_call_sale(opp)
                else:
                    # --- Put path (default) ---
                    result = put_seller.execute_put_sale(opp, skip_buying_power_check=False)

                execution_data = {
                    'opportunity': opp,
                    'result': result,
                    'success': result and result.get('success', False),
                }
                execution_results.append(execution_data)

                if execution_data['success']:
                    trades_executed += 1

                    # Convert UUID to string if present
                    order_id = result.get('order_id')
                    if order_id is not None:
                        order_id = str(order_id)

                    log_system_event(
                        self.logger,
                        event_type="trade_executed",
                        status="success",
                        symbol=opp.get('symbol'),
                        option_symbol=opp.get('option_symbol'),
                        contracts=opp.get('contracts'),
                        premium=opp.get('premium'),
                        strike_price=opp.get('strike_price'),
                        order_id=order_id,
                    )

                    # Persist trade to BigQuery journal
                    self.trade_journal.record_trade({
                        **opp,
                        "order_id": order_id,
                        "client_order_id": str(result.get("client_order_id")) if result.get("client_order_id") else None,
                        "status": "submitted",
                        "fill_price": result.get("fill_price"),
                        "limit_price": result.get("limit_price"),
                    })
                else:
                    error_message = result.get('message', '') or result.get('error_message', 'Unknown error')
                    is_non_retryable = result.get('non_retryable', False)

                    # Track non-retryable failures so they are skipped in future cycles
                    if is_non_retryable:
                        option_sym = opp.get('option_symbol')
                        if option_sym:
                            _failed_symbols.add(option_sym)
                            self.logger.warning(
                                "Marking opportunity as non-retryable failure",
                                event_category="system",
                                event_type="opportunity_marked_non_retryable",
                                option_symbol=option_sym,
                                error_type=result.get('error_type', 'unknown'),
                                error_message=error_message,
                            )

                    log_error_event(
                        self.logger,
                        error_type="trade_execution_failed",
                        error_message=error_message,
                        component="execution_engine",
                        recoverable=not is_non_retryable,
                        symbol=opp.get('symbol'),
                        option_symbol=opp.get('option_symbol'),
                    )
            except Exception as e:
                self.logger.error(
                    "Exception during order execution",
                    event_category="error",
                    event_type="order_execution_exception",
                    symbol=opp.get('symbol'),
                    error=str(e),
                )
                execution_results.append({
                    'opportunity': opp,
                    'result': {'success': False, 'message': str(e)},
                    'success': False,
                })

        return execution_results, trades_executed
