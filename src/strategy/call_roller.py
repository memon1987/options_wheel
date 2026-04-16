"""Covered call rolling engine for Friday EOW rolls.

Plan: docs/plans/fc-006.md

Buys-to-close expiring ITM short calls and sells-to-open new calls at higher
strikes for next week. Uses percentage-based debit tolerance, 2-roll max per
position, and reuses the existing find_suitable_calls framework.
"""

import time
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple

import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..api.earnings_calendar import EarningsCalendarService
from ..risk.risk_manager import RiskManager
from ..utils.config import Config
from ..utils.option_symbols import parse_option_symbol
from ..utils.logging_events import log_trade_event, log_error_event, log_position_update
from .wheel_state_manager import WheelStateManager

logger = structlog.get_logger(__name__)


class CallRoller:
    """Friday EOW call rolling engine.

    Evaluates short call positions for rolling when the underlying has
    rallied through the strike. Executes sequential BTC -> STO with
    percentage-based debit tolerance.
    """

    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager,
                 config: Config, wheel_state: WheelStateManager,
                 risk_manager: RiskManager,
                 earnings_calendar: Optional[EarningsCalendarService] = None):
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        self.wheel_state = wheel_state
        self.risk_manager = risk_manager
        self.earnings_calendar = earnings_calendar

    def should_roll(self, short_call_position: Dict[str, Any],
                    stock_position: Dict[str, Any],
                    current_stock_price: float) -> Tuple[bool, str]:
        """Check all trigger gates for rolling a short call.

        Returns:
            (should_roll, reason_code) — reason_code explains the decision.
        """
        option_symbol = short_call_position.get('symbol', '')
        parsed = parse_option_symbol(option_symbol)
        underlying = parsed.get('underlying', '')
        current_strike = parsed.get('strike_price', 0)
        dte = parsed.get('dte', 999)

        # Gate: DTE must be <= max_current_dte
        if dte > self.config.rolling_max_current_dte:
            return False, f"dte_too_high ({dte} > {self.config.rolling_max_current_dte})"

        # Gate: Stock price / strike >= ITM trigger ratio
        if current_strike <= 0:
            return False, "invalid_strike"
        ratio = current_stock_price / current_strike
        if ratio < self.config.rolling_itm_trigger_ratio:
            return False, f"not_itm_enough (ratio={ratio:.4f} < {self.config.rolling_itm_trigger_ratio})"

        # Gate: Max rolls per position
        roll_count = self.wheel_state.get_roll_count(underlying)
        if roll_count >= self.config.rolling_max_rolls_per_position:
            return False, f"max_rolls_reached ({roll_count} >= {self.config.rolling_max_rolls_per_position})"

        # Gate: Earnings blackout
        if self.earnings_calendar:
            if self.earnings_calendar.is_earnings_within_n_days(
                    underlying, self.config.rolling_earnings_blackout_days):
                return False, "earnings_blackout"

        return True, "eligible"

    def evaluate_roll_opportunity(self, short_call_position: Dict[str, Any],
                                  stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate whether a short call should be rolled and find a target.

        Returns:
            Roll opportunity dict with both legs described, or None if no roll.
        """
        option_symbol = short_call_position.get('symbol', '')
        parsed = parse_option_symbol(option_symbol)
        underlying = parsed.get('underlying', '')
        current_strike = parsed.get('strike_price', 0)
        contracts = abs(int(float(short_call_position.get('qty', 0))))

        # Get current stock price
        quote = self.alpaca.get_stock_quote(underlying)
        if not quote:
            return None
        current_stock_price = float(quote.get('last_price', 0) or quote.get('ask_price', 0))
        if current_stock_price <= 0:
            return None

        # Get earnings proximity for log enrichment
        earnings_info = {}
        if self.earnings_calendar:
            earnings_info = self.earnings_calendar.get_earnings_proximity(underlying)

        # Check trigger gates
        should, reason = self.should_roll(short_call_position, stock_position,
                                          current_stock_price)
        if not should:
            log_trade_event(
                logger, event_type="call_roll_skipped",
                symbol=option_symbol, underlying=underlying,
                strategy="roll_call", success=False,
                skip_reason=reason, gate_failed=reason,
                current_strike=current_strike,
                stock_price=current_stock_price,
                **earnings_info,
            )
            return None

        # Get cost basis for strike selection floor
        shares = int(float(stock_position.get('qty', 0)))
        total_cost = float(stock_position.get('cost_basis', 0))
        cost_basis_per_share = total_cost / shares if shares > 0 else 0

        # Find replacement calls — min strike is max(cost_basis, current_strike + 0.01)
        min_strike = max(cost_basis_per_share, current_strike + 0.01)
        suitable_calls = self.market_data.find_suitable_calls(underlying,
                                                               min_strike_price=min_strike)
        if not suitable_calls:
            log_trade_event(
                logger, event_type="call_roll_skipped",
                symbol=option_symbol, underlying=underlying,
                strategy="roll_call", success=False,
                skip_reason="no_suitable_replacement",
                current_strike=current_strike,
                **earnings_info,
            )
            return None

        # Get original premium for debit tolerance
        active_details = self.wheel_state.get_active_call_details(underlying)
        original_premium = active_details['premium_per_contract'] if active_details else 0

        # Get current ask for BTC pricing
        btc_quote = self.alpaca.get_option_quote(option_symbol)
        btc_ask = float(btc_quote.get('ask_price', 0)) if btc_quote else 0
        if btc_ask <= 0:
            return None

        # Try candidates in order (sorted by return_score)
        max_attempts = self.config.rolling_fallback_strike_attempts + 1
        for candidate in suitable_calls[:max_attempts]:
            new_strike = candidate.get('strike_price', 0)
            new_bid = candidate.get('bid', 0)

            # Validate via risk manager
            valid, val_reason = self.risk_manager.validate_roll(
                candidate, current_strike, cost_basis_per_share)
            if not valid:
                continue

            # Compute economics
            economics = self._compute_net_roll_economics(
                original_premium, btc_ask, new_bid, contracts)

            # Check debit tolerance
            notional = current_strike * 100 * contracts
            if not self._check_debit_tolerance(
                    economics['net_debit'], original_premium, notional):
                log_trade_event(
                    logger, event_type="call_roll_blocked_debit",
                    symbol=option_symbol, underlying=underlying,
                    strategy="roll_call", success=False,
                    net_debit=economics['net_debit'],
                    max_allowed_premium_pct=self.config.rolling_max_debit_pct_of_premium,
                    pct_of_premium=economics['debit_pct_of_premium'],
                    **earnings_info,
                )
                continue

            # Found a viable opportunity
            opportunity = {
                'underlying': underlying,
                'old_option_symbol': option_symbol,
                'new_option_symbol': candidate['symbol'],
                'old_strike': current_strike,
                'new_strike': new_strike,
                'contracts': contracts,
                'btc_ask': btc_ask,
                'new_bid': new_bid,
                'original_premium': original_premium,
                'stock_price': current_stock_price,
                'cost_basis_per_share': cost_basis_per_share,
                'economics': economics,
                'earnings_info': earnings_info,
                'candidate': candidate,
            }

            log_trade_event(
                logger, event_type="call_roll_evaluated",
                symbol=option_symbol, underlying=underlying,
                strategy="roll_call", success=True,
                current_strike=current_strike,
                target_strike=new_strike,
                btc_ask=btc_ask, stc_bid=new_bid,
                net_debit=economics['net_debit'],
                net_debit_pct=economics['debit_pct_of_premium'],
                contracts=contracts,
                **earnings_info,
            )
            return opportunity

        log_trade_event(
            logger, event_type="call_roll_skipped",
            symbol=option_symbol, underlying=underlying,
            strategy="roll_call", success=False,
            skip_reason="no_candidate_passed_economics",
            current_strike=current_strike,
            **earnings_info,
        )
        return None

    def execute_roll(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a two-leg roll: buy-to-close then sell-to-open.

        Returns:
            Result dict with success status, order IDs, and fill details.
        """
        underlying = opportunity['underlying']
        old_symbol = opportunity['old_option_symbol']
        new_symbol = opportunity['new_option_symbol']
        contracts = opportunity['contracts']
        btc_ask = opportunity['btc_ask']
        new_bid = opportunity['new_bid']
        earnings_info = opportunity.get('earnings_info', {})

        # === LEG 1: Buy-to-close ===
        btc_limit = round(btc_ask * (1 + self.config.rolling_btc_limit_over_ask_pct), 2)

        log_trade_event(
            logger, event_type="call_roll_btc_placed",
            symbol=old_symbol, underlying=underlying,
            strategy="roll_call", success=True,
            current_strike=opportunity['old_strike'],
            contracts=contracts, limit_price=btc_limit,
        )

        btc_result = self.alpaca.place_option_order(
            symbol=old_symbol, qty=contracts,
            side='buy', order_type='limit', limit_price=btc_limit)

        if not btc_result or not btc_result.get('success', False):
            error_msg = btc_result.get('error_message', 'BTC order rejected') if btc_result else 'No result'
            log_error_event(
                logger, error_type="call_roll_btc_unfilled",
                error_message=error_msg, component="call_roller",
                recoverable=True, symbol=old_symbol, underlying=underlying,
            )
            return {'success': False, 'reason': 'btc_rejected', 'error': error_msg}

        btc_order_id = btc_result.get('order_id', '')

        # Poll for BTC fill
        btc_fill = self._poll_order_fill(btc_order_id)
        if not btc_fill or btc_fill.get('status') not in ('filled', 'partially_filled'):
            log_error_event(
                logger, error_type="call_roll_btc_unfilled",
                error_message=f"BTC order {btc_order_id} did not fill within timeout",
                component="call_roller", recoverable=True,
                symbol=old_symbol, underlying=underlying,
                order_id=btc_order_id,
            )
            return {'success': False, 'reason': 'btc_unfilled', 'order_id': btc_order_id}

        btc_filled_price = btc_fill.get('filled_avg_price', btc_limit)
        btc_filled_qty = btc_fill.get('filled_qty', contracts)

        log_trade_event(
            logger, event_type="call_roll_btc_filled",
            symbol=old_symbol, underlying=underlying,
            strategy="roll_call", success=True,
            order_id=btc_order_id,
            filled_qty=btc_filled_qty,
            filled_price=btc_filled_price,
        )

        # === LEG 2: Sell-to-open ===
        stc_fill_result = self._attempt_stc(
            new_symbol, underlying, contracts, new_bid, opportunity, earnings_info)

        if stc_fill_result and stc_fill_result.get('success'):
            stc_order_id = stc_fill_result['order_id']
            stc_filled_qty = stc_fill_result['filled_qty']
            stc_filled_price = stc_fill_result['filled_price']

            # Calculate actual net premium
            btc_total = btc_filled_price * btc_filled_qty * 100
            stc_total = stc_filled_price * stc_filled_qty * 100
            net_premium = stc_total - btc_total

            # Handle partial fill
            if stc_filled_qty < contracts:
                log_trade_event(
                    logger, event_type="call_roll_partial_fill",
                    symbol=new_symbol, underlying=underlying,
                    strategy="roll_call", success=True,
                    requested_qty=contracts,
                    filled_qty=stc_filled_qty,
                    unfilled_qty=contracts - stc_filled_qty,
                )

            # Update state
            self.wheel_state.remove_position(underlying, 'call', btc_filled_qty, 'rolled')
            self.wheel_state.add_call_position(
                underlying, stc_filled_qty, stc_filled_price, datetime.now())
            self.wheel_state.set_active_call_details(
                underlying, new_symbol, stc_filled_price,
                opportunity['new_strike'], stc_filled_qty,
                datetime.now().strftime('%Y-%m-%d'))
            self.wheel_state.record_call_roll(
                underlying, old_symbol, new_symbol, stc_filled_qty,
                net_premium, btc_total, stc_total,
                opportunity['old_strike'], opportunity['new_strike'],
                datetime.now().strftime('%Y-%m-%d'))

            log_position_update(
                logger, event_type="call_roll_completed",
                symbol=underlying,
                position_status="rolled",
                old_strike=opportunity['old_strike'],
                new_strike=opportunity['new_strike'],
                net_premium=round(net_premium, 2),
                contracts=stc_filled_qty,
                roll_count=self.wheel_state.get_roll_count(underlying),
                btc_order_id=btc_order_id,
                stc_order_id=stc_order_id,
                **earnings_info,
            )

            return {
                'success': True,
                'underlying': underlying,
                'old_strike': opportunity['old_strike'],
                'new_strike': opportunity['new_strike'],
                'contracts': stc_filled_qty,
                'net_premium': round(net_premium, 2),
                'btc_order_id': btc_order_id,
                'stc_order_id': stc_order_id,
            }
        else:
            # STO failed after BTC succeeded — naked exposure
            log_error_event(
                logger, error_type="call_roll_naked_exposure",
                error_message="STO failed after BTC succeeded — shares uncovered",
                component="call_roller", recoverable=False,
                symbol=new_symbol, underlying=underlying,
                btc_order_id=btc_order_id,
            )
            # Still update state for the BTC side
            self.wheel_state.remove_position(underlying, 'call', btc_filled_qty, 'rolled_btc_only')
            return {
                'success': False,
                'reason': 'stc_failed_naked_exposure',
                'btc_order_id': btc_order_id,
                'underlying': underlying,
            }

    def _attempt_stc(self, new_symbol: str, underlying: str, contracts: int,
                     new_bid: float, opportunity: Dict, earnings_info: Dict) -> Optional[Dict]:
        """Attempt STO with retry at flat bid then fallback strikes."""
        # First attempt: aggressive pricing
        stc_limit = round(new_bid * (1 - self.config.rolling_stc_limit_under_bid_pct), 2)
        result = self._place_and_poll_stc(new_symbol, underlying, contracts, stc_limit)
        if result and result.get('success'):
            return result

        # Retry at flat bid
        result = self._place_and_poll_stc(new_symbol, underlying, contracts, round(new_bid, 2))
        if result and result.get('success'):
            return result

        # Try fallback strikes from the candidate list
        min_strike = max(opportunity['cost_basis_per_share'],
                         opportunity['old_strike'] + 0.01)
        fallback_calls = self.market_data.find_suitable_calls(
            underlying, min_strike_price=min_strike)

        for fallback in fallback_calls[1:self.config.rolling_fallback_strike_attempts + 1]:
            fb_symbol = fallback['symbol']
            fb_bid = fallback.get('bid', 0)
            if fb_bid <= 0:
                continue
            fb_limit = round(fb_bid * (1 - self.config.rolling_stc_limit_under_bid_pct), 2)
            result = self._place_and_poll_stc(fb_symbol, underlying, contracts, fb_limit)
            if result and result.get('success'):
                return result

        return None

    def _place_and_poll_stc(self, symbol: str, underlying: str,
                            contracts: int, limit_price: float) -> Optional[Dict]:
        """Place STO order and poll for fill."""
        log_trade_event(
            logger, event_type="call_roll_stc_placed",
            symbol=symbol, underlying=underlying,
            strategy="roll_call", success=True,
            contracts=contracts, limit_price=limit_price,
        )

        result = self.alpaca.place_option_order(
            symbol=symbol, qty=contracts,
            side='sell', order_type='limit', limit_price=limit_price)

        if not result or not result.get('success', False):
            return None

        order_id = result.get('order_id', '')
        fill = self._poll_order_fill(order_id)

        if not fill:
            return None

        status = fill.get('status', '')
        filled_qty = fill.get('filled_qty', 0)

        if filled_qty > 0:
            log_trade_event(
                logger, event_type="call_roll_stc_filled",
                symbol=symbol, underlying=underlying,
                strategy="roll_call", success=True,
                order_id=order_id,
                filled_qty=filled_qty,
                filled_price=fill.get('filled_avg_price', limit_price),
            )
            return {
                'success': True,
                'order_id': order_id,
                'filled_qty': filled_qty,
                'filled_price': fill.get('filled_avg_price', limit_price),
                'symbol': symbol,
            }

        log_error_event(
            logger, error_type="call_roll_stc_unfilled",
            error_message=f"STO order {order_id} status={status}",
            component="call_roller", recoverable=True,
            symbol=symbol, underlying=underlying,
            order_id=order_id,
        )
        return None

    def _poll_order_fill(self, order_id: str) -> Optional[Dict]:
        """Poll order status until terminal state or timeout."""
        timeout = self.config.rolling_btc_fill_timeout_seconds
        poll_interval = 5
        elapsed = 0

        while elapsed < timeout:
            try:
                order = self.alpaca.get_order_by_id(order_id)
                status = order.get('status', '')
                if status in ('filled', 'partially_filled', 'expired', 'canceled'):
                    return order
            except Exception:
                pass
            time.sleep(poll_interval)
            elapsed += poll_interval

        return None

    def _compute_net_roll_economics(self, original_premium: float,
                                     btc_ask: float, new_bid: float,
                                     contracts: int) -> Dict[str, Any]:
        """Compute net credit/debit for the roll using conservative pricing."""
        btc_cost_per = btc_ask  # paying ask to close
        stc_credit_per = new_bid  # receiving bid to open
        net_per_contract = stc_credit_per - btc_cost_per  # positive = credit
        net_debit = -net_per_contract if net_per_contract < 0 else 0
        net_credit = net_per_contract if net_per_contract > 0 else 0

        debit_pct_of_premium = (net_debit / original_premium * 100) if original_premium > 0 else 999

        return {
            'btc_cost_per': btc_cost_per,
            'stc_credit_per': stc_credit_per,
            'net_per_contract': net_per_contract,
            'net_debit': net_debit,
            'net_credit': net_credit,
            'total_net': net_per_contract * contracts * 100,
            'debit_pct_of_premium': round(debit_pct_of_premium, 2),
        }

    def _check_debit_tolerance(self, net_debit: float, original_premium: float,
                                notional_value: float) -> bool:
        """Check if net debit is within tolerance bounds."""
        if net_debit <= 0:
            return True  # credit roll — always ok

        # Primary gate: debit as % of original premium
        max_debit_premium = original_premium * self.config.rolling_max_debit_pct_of_premium
        if net_debit > max_debit_premium:
            return False

        # Backstop: debit as % of notional
        max_debit_notional = notional_value * self.config.rolling_max_debit_pct_of_notional
        if net_debit > max_debit_notional:
            return False

        return True
