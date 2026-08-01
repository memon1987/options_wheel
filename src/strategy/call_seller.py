"""Call selling module for options wheel strategy."""

from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from ..utils import clock
from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..utils.config import Config
from ..utils.logging_events import log_trade_event, log_error_event, log_position_update
from ..utils.option_symbols import parse_option_symbol
from .cost_basis import CostBasisResolver, opportunity_floor_per_share

logger = structlog.get_logger(__name__)


class CallSeller:
    """Handles covered call selling for the wheel strategy."""
    
    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager,
                 config: Config, wheel_state_manager=None,
                 allow_bigquery_cost_basis: bool = True):
        """Initialize call seller.

        Args:
            alpaca_client: Alpaca API client
            market_data: Market data manager
            config: Configuration instance
            wheel_state_manager: Optional WheelStateManager for tracking active call details
            allow_bigquery_cost_basis: whether the cost-basis divergence
                cross-check may query BigQuery. A backtest passes False: the
                cross-check would otherwise read *production* trade history —
                against CURRENT_TIMESTAMP() — mixing real assignments into a
                simulated run. With it off the cross-check is "unavailable",
                which keeps the simulated broker's floor (FC-065).
        """
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        self.wheel_state = wheel_state_manager
        # Construction-time snapshot, kept for assertions only: the resolver below
        # took its own copy, so mutating this attribute afterwards changes nothing.
        self.allow_bigquery_cost_basis = allow_bigquery_cost_basis
        self._entry_times: Dict[str, datetime] = {}  # symbol → entry time for hold period
        # FC-050: the floor resolution lives in cost_basis.py so the scanner
        # shares it. FC-065: it resolves from Alpaca's avg_entry_price and
        # cross-checks against BigQuery, so there is no wheel_state source and
        # no injected lookup any more — the resolver's own
        # ``_lookup_assignment_basis`` is the single BigQuery chokepoint, and
        # the test suite's hermeticity guard patches it on the class.
        self._cost_basis_resolver = CostBasisResolver(
            alpaca_client,
            config,
            allow_bigquery=allow_bigquery_cost_basis,
        )
        
    def evaluate_covered_call_opportunity(self, stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate covered call opportunity for an assigned stock position.
        
        Args:
            stock_position: Stock position from assignment
            
        Returns:
            Call opportunity details or None
        """
        try:
            symbol = stock_position['symbol']
            shares_owned = int(float(stock_position['qty']))
            
            # Only sell calls if we own shares in round lots (100 shares per contract)
            if shares_owned < 100:
                logger.info("Insufficient shares for covered calls",
                           event_category="trade",
                           event_type="insufficient_shares_for_calls",
                           symbol=symbol,
                           shares=shares_owned)
                return None

            logger.info("Evaluating covered call opportunity",
                       event_category="trade",
                       event_type="call_opportunity_evaluation",
                       symbol=symbol,
                       shares=shares_owned)

            # FC-065: cost basis = Alpaca's avg_entry_price for the equity
            # position, vetoed by the BigQuery divergence cross-check. Zero
            # means the broker field was missing/zero or the cross-check
            # disagreed — both are "no floor", both block the write below.
            stock_cost_basis = self._resolve_cost_basis_floor(
                symbol, stock_position, shares_owned
            )

            # FC-029 review fix (MEDIUM 6): when shares are held but no source
            # resolved a cost basis, we have no floor — this is unsafe. Block
            # the call write entirely with a structured error rather than
            # writing at any strike. Operator intervention required.
            if stock_cost_basis <= 0:
                log_error_event(
                    logger,
                    error_type="cost_basis_floor_unresolved",
                    error_message=(
                        f"No cost-basis floor resolved for {symbol} (Alpaca "
                        f"avg_entry_price missing/zero, or the BigQuery "
                        f"cross-check found it divergent). Holding "
                        f"{shares_owned} shares with no protection. Blocking call write."
                    ),
                    component="call_seller",
                    recoverable=True,
                    symbol=symbol,
                    shares=shares_owned,
                )
                return None

            # FC-029 (R3): drawdown pause — when shares are deeply underwater
            # every delta-range strike is at-or-below cost basis. Make this an
            # explicit, observable decision instead of relying on the (now
            # working) cost-basis filter to silently return no candidates.
            try:
                quote = self.alpaca.get_stock_quote(symbol) or {}
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                # Defensive: a malformed quote with one side zero would yield
                # a wildly-wrong mid (e.g. bid=$10, ask=$0 → mid=$5).
                current_price = (bid + ask) / 2 if (bid > 0 and ask > 0) else 0
            except Exception:
                current_price = 0

            # FC-029 review fix (HIGH 2): no usable quote → defer to next cycle
            # rather than writing without drawdown protection. The pause IS the
            # protection; failing open means LESS protection precisely when
            # quotes are noisy (premarket, illiquid intraday, halts) — exactly
            # the regimes the pause exists for. Monitor cycle re-evaluates in
            # ~5 min; cost of deferring is negligible.
            if current_price <= 0:
                logger.info("Covered call deferred: quote unavailable",
                           event_category="trade",
                           event_type="covered_call_quote_missing",
                           symbol=symbol,
                           cost_basis=stock_cost_basis)
                return None

            drawdown_pct = (stock_cost_basis - current_price) / stock_cost_basis
            threshold = self.config.call_drawdown_pause_threshold
            if drawdown_pct >= threshold:
                logger.info("Covered call skipped: drawdown pause",
                           event_category="trade",
                           event_type="covered_call_drawdown_pause",
                           symbol=symbol,
                           cost_basis=stock_cost_basis,
                           current_price=current_price,
                           drawdown_pct=round(drawdown_pct, 4),
                           threshold_pct=threshold)
                return None

            # Get suitable calls for this stock (with cost basis protection)
            suitable_calls = self.market_data.find_suitable_calls(symbol, min_strike_price=stock_cost_basis)
            
            if not suitable_calls:
                logger.info("No suitable calls found",
                           event_category="trade",
                           event_type="no_suitable_calls",
                           symbol=symbol)
                return None
            
            # Select the best call (first in sorted list)
            best_call = suitable_calls[0]
            
            # Calculate position details
            position_details = self._calculate_call_position(best_call, shares_owned, stock_position)
            
            if not position_details:
                logger.info("Call position validation failed",
                           event_category="trade",
                           event_type="call_position_validation_failed",
                           symbol=symbol)
                return None
            
            # Create opportunity
            opportunity = {
                'action_type': 'new_position',
                'strategy': 'sell_call',
                # FC-048: the router keys off the OCC symbol, so this is
                # documentation/telemetry rather than load-bearing -- but the
                # sellers previously set only 'strategy' while the scanner set
                # only 'type', and that vocabulary split is what caused the
                # covered-call misroute. Both producers now speak both.
                'type': 'call',
                'symbol': symbol,
                'option_symbol': best_call['symbol'],
                'strike_price': best_call['strike_price'],
                'expiration_date': best_call['expiration_date'],
                'dte': best_call['dte'],
                'delta': best_call.get('delta', 0),
                'premium': best_call['mid_price'],
                'annual_return': best_call.get('annual_return', 0),
                'contracts': position_details['contracts'],
                'shares_covered': position_details['shares_covered'],
                'max_profit': position_details['max_profit'],
                # FC-029 (R2): canonical floor (per-share × shares_covered).
                # Used by the defensive check in execute_call_sale.
                'stock_cost_basis': stock_cost_basis * position_details['shares_covered'],
                'current_stock_price': position_details['current_stock_price'],
                'total_return_if_called': position_details['total_return_if_called'],
                'timestamp': clock.now().isoformat()
            }
            
            logger.info("Covered call opportunity identified",
                       event_category="trade",
                       event_type="call_opportunity_found",
                       symbol=symbol,
                       strike=best_call['strike_price'],
                       premium=best_call['mid_price'],
                       dte=best_call['dte'],
                       contracts=position_details['contracts'])
            
            return opportunity
            
        except Exception as e:
            logger.error("Failed to evaluate covered call opportunity",
                        event_category="error",
                        event_type="call_opportunity_error",
                        symbol=stock_position.get('symbol', 'unknown'),
                        error=str(e))
            return None
    
    def _calculate_call_position(self, call_option: Dict[str, Any], shares_owned: int, 
                                stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Calculate covered call position details.
        
        Args:
            call_option: Call option details
            shares_owned: Number of shares owned
            stock_position: Stock position details
            
        Returns:
            Position details or None if invalid
        """
        try:
            # Calculate number of contracts we can sell (1 contract = 100 shares)
            max_contracts = shares_owned // 100
            
            # Conservative approach - sell calls on all round lots
            contracts = max_contracts
            
            if contracts <= 0:
                return None
            
            shares_covered = contracts * 100
            strike_price = call_option['strike_price']
            premium_per_contract = call_option['mid_price']
            
            # Get current stock price
            symbol = stock_position['symbol']
            stock_metrics = self.market_data.get_stock_metrics(symbol)
            current_price = stock_metrics.get('current_price', 0)
            
            # Calculate returns
            premium_income = contracts * premium_per_contract * 100
            # FC-029 (R2): same canonical-source resolution as the entry path.
            stock_cost_basis = self._resolve_cost_basis_floor(
                symbol, stock_position, shares_owned
            )
            
            # If called away, calculate total return
            if current_price > 0:
                capital_gain_per_share = strike_price - stock_cost_basis
                total_capital_gain = capital_gain_per_share * shares_covered
                total_return_if_called = premium_income + total_capital_gain
                
                # Return as percentage
                total_cost_basis = stock_cost_basis * shares_covered
                if total_cost_basis > 0:
                    return_percentage = (total_return_if_called / total_cost_basis) * 100
                else:
                    return_percentage = 0
            else:
                total_return_if_called = premium_income
                return_percentage = 0
            
            return {
                'contracts': contracts,
                'shares_covered': shares_covered,
                'max_profit': premium_income,
                'current_stock_price': current_price,
                'total_return_if_called': total_return_if_called,
                'return_percentage': return_percentage,
                'premium_per_contract': premium_per_contract
            }
            
        except Exception as e:
            logger.error("Failed to calculate call position",
                        event_category="error",
                        event_type="call_position_calculation_error",
                        error=str(e))
            return None
    
    def execute_call_sale(self, opportunity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute a covered call trade.

        Args:
            opportunity: Call opportunity details

        Returns:
            Trade execution result
        """
        try:
            # SAFETY (FC-048): Reject put options that were incorrectly routed
            # here. Mirrors put_seller.execute_put_sale's guard -- the put side
            # has had this protection since FC-021 and the call side did not,
            # which is the same asymmetry that let the misroute go unnoticed.
            option_symbol = opportunity.get('option_symbol', '')
            parsed = parse_option_symbol(option_symbol)
            if parsed.get('option_type') == 'put':
                logger.warning("Put option incorrectly routed to call_seller - rejecting",
                              event_category="risk",
                              event_type="put_rejected_by_call_seller",
                              symbol=option_symbol,
                              underlying=parsed.get('underlying'))
                return {
                    'success': False,
                    'error_type': 'wrong_seller',
                    'message': f'Put option {option_symbol} cannot be executed by call_seller',
                    'non_retryable': True
                }

            # DEFENSIVE: Final validation before execution - prevent guaranteed losses.
            # FC-050: the floor is read through opportunity_floor_per_share, which
            # understands both producers' shapes. Reading only the wheel-engine keys
            # meant this check never fired on scanner-produced opportunities — the
            # only kind production executes.
            strike_price = opportunity.get('strike_price', 0)
            cost_basis_per_share = opportunity_floor_per_share(opportunity)

            # FC-050: no resolvable floor is a blocking condition, not a reason to
            # skip the check. Post-FC-050 every scanner opportunity carries a
            # positive cost_basis_per_share and the wheel engine always sets
            # stock_cost_basis, so this means a malformed opportunity — the exact
            # case that must not reach the broker. Mirrors the FC-029
            # cost_basis_floor_unresolved block on the evaluation path.
            if cost_basis_per_share <= 0:
                log_error_event(
                    logger,
                    error_type="cost_basis_floor_unresolved_at_execution",
                    error_message=(
                        f"No cost-basis floor on opportunity for "
                        f"{opportunity.get('option_symbol', 'unknown')} "
                        f"({opportunity.get('symbol', 'unknown')}) - blocking call write"
                    ),
                    component="call_seller",
                    recoverable=True,
                    symbol=opportunity.get('symbol', ''),
                    option_symbol=opportunity.get('option_symbol', ''),
                    strike_price=strike_price,
                )
                return {
                    'success': False,
                    'error_type': 'cost_basis_floor_unresolved_at_execution',
                    'message': (
                        f"No cost-basis floor on opportunity for "
                        f"{opportunity.get('option_symbol', 'unknown')} - call not written"
                    ),
                    'non_retryable': False
                }

            # A missing/zero strike also lands here rather than skipping the
            # check: with a real floor in hand, "no strike" is malformed input,
            # not a reason to trade unprotected.
            if strike_price < cost_basis_per_share:
                log_error_event(
                    logger,
                    error_type="call_below_cost_basis_blocked",
                    error_message=f"Strike ${strike_price} below cost basis ${cost_basis_per_share:.2f}/share - guaranteed loss prevented",
                    component="call_seller",
                    recoverable=True,
                    symbol=opportunity.get('symbol', ''),
                    option_symbol=opportunity.get('option_symbol', ''),
                    strike_price=strike_price,
                    cost_basis_per_share=cost_basis_per_share,
                    loss_per_share=cost_basis_per_share - strike_price
                )
                return {
                    'success': False,
                    'error': 'strike_below_cost_basis',
                    'message': f'Strike ${strike_price} below cost basis ${cost_basis_per_share:.2f}/share'
                }

            option_symbol = opportunity['option_symbol']
            contracts = opportunity['contracts']
            premium = opportunity['premium']
            
            # Calculate limit price (slightly below mid to improve fill probability)
            limit_price = round(premium * 0.95, 2)  # 5% below mid price
            
            logger.info("Executing covered call sale",
                       event_category="trade",
                       event_type="call_sale_executing",
                       symbol=option_symbol,
                       contracts=contracts,
                       limit_price=limit_price)
            
            # Place the sell order
            order_result = self.alpaca.place_option_order(
                symbol=option_symbol,
                qty=contracts,
                side='sell',
                order_type='limit',
                limit_price=limit_price
            )

            # Handle order result (success or structured error)
            if order_result and order_result.get('success', True):
                result = {
                    'success': True,
                    'order_id': order_result.get('order_id'),
                    'symbol': option_symbol,
                    'contracts': contracts,
                    'limit_price': limit_price,
                    'strategy': 'sell_call',
                    'timestamp': clock.now().isoformat()
                }

                # Enhanced logging for BigQuery analytics
                log_trade_event(
                    logger,
                    event_type="call_sale_executed",
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strategy="sell_call",
                    success=True,
                    strike_price=opportunity.get('strike_price', 0),
                    premium=premium,
                    contracts=contracts,
                    limit_price=limit_price,
                    order_id=order_result.get('order_id'),
                    shares_covered=opportunity.get('shares_covered', 0),
                    stock_cost_basis=opportunity.get('stock_cost_basis', 0),
                    total_return_if_called=opportunity.get('total_return_if_called', 0),
                    dte=opportunity.get('dte', 0)
                )

                # Track active call details for rolling engine (FC-006)
                if self.wheel_state:
                    underlying = opportunity.get('symbol', '')
                    if underlying:
                        self.wheel_state.set_active_call_details(
                            symbol=underlying,
                            option_symbol=option_symbol,
                            premium=premium,
                            strike=opportunity.get('strike_price', 0),
                            contracts=contracts,
                            sell_date=clock.now().strftime('%Y-%m-%d'),
                        )

                # Track entry time for hold period (min_hold_hours)
                self._entry_times[option_symbol] = clock.now()

                return result
            else:
                # Order failed - return structured error
                error_type = order_result.get('error_type', 'unknown') if order_result else 'unknown'
                error_msg = order_result.get('error_message', 'Unknown error') if order_result else 'No result returned'

                # Enhanced error logging
                log_error_event(
                    logger,
                    error_type=error_type,
                    error_message=error_msg,
                    component="call_seller",
                    recoverable=True,
                    symbol=option_symbol,
                    underlying=opportunity.get('symbol', ''),
                    strike_price=opportunity.get('strike_price', 0),
                    contracts=contracts,
                    limit_price=limit_price
                )

                # Return structured error dict instead of None for consistent return type
                return {
                    'success': False,
                    'error': error_type,
                    'message': error_msg,
                    'symbol': option_symbol,
                    'strategy': 'sell_call',
                    'timestamp': clock.now().isoformat()
                }

        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="execution_exception",
                error_message=str(e),
                component="call_seller",
                recoverable=False,
                symbol=opportunity.get('option_symbol', ''),
                underlying=opportunity.get('symbol', '')
            )
            # Return structured error dict instead of None for consistent return type
            return {
                'success': False,
                'error': 'execution_exception',
                'message': str(e),
                'symbol': opportunity.get('option_symbol', ''),
                'strategy': 'sell_call',
                'timestamp': clock.now().isoformat()
            }
    
    def _resolve_cost_basis_floor(
        self, symbol: str, stock_position: Dict[str, Any], shares_owned: int
    ) -> float:
        """Resolve the per-share cost basis for covered-call strike floor.

        FC-050: delegates to the shared :class:`CostBasisResolver`, which the
        scanner uses too. Kept as a method so callers and tests that patch this
        entry point keep working.

        FC-065: the resolved value is Alpaca's ``avg_entry_price`` for the
        equity position, and it is 0 whenever the broker field is missing or
        the BigQuery divergence cross-check vetoed it. Both cases mean "no
        floor", and the caller must fail closed.

        Args:
            symbol: Underlying ticker (e.g. ``"AMD"``).
            stock_position: Alpaca position dict (carries ``avg_entry_price``).
            shares_owned: Current share count, used to bound the cross-check's
                lot reconstruction.

        Returns:
            Per-share cost basis, or 0 if there is no usable floor.
        """
        return self._cost_basis_resolver.resolve(symbol, stock_position, shares_owned)

    def _parse_dte_from_option_symbol(self, option_symbol: str) -> int:
        """
        Extract DTE (Days to Expiration) from option symbol.

        Option symbol format: AMD251031C00350000
                              ^^^YYMMDD = 251031 = 2025-10-31

        Args:
            option_symbol: Option symbol string

        Returns:
            Days to expiration (0-N), or 7 as fallback if parse fails
        """
        try:
            import re
            from datetime import datetime, timezone

            # Extract date portion (6 digits after ticker, before P/C)
            match = re.search(r'(\d{6})[PC]', option_symbol)
            if not match:
                logger.warning("Could not parse expiration date from option symbol",
                              event_category="data",
                              event_type="option_symbol_parse_warning",
                              symbol=option_symbol)
                return 7  # Default fallback

            date_str = match.group(1)

            # Parse YYMMDD format
            year = 2000 + int(date_str[0:2])
            month = int(date_str[2:4])
            day = int(date_str[4:6])

            exp_date = datetime(year, month, day, tzinfo=timezone.utc)
            now = clock.now_utc()

            dte = (exp_date.date() - now.date()).days

            return max(0, dte)  # Never negative

        except Exception as e:
            logger.error("Failed to parse DTE from option symbol",
                        event_category="error",
                        event_type="dte_parse_error",
                        symbol=option_symbol,
                        error=str(e))
            return 7  # Default fallback

    def _parse_option_symbol(self, option_symbol: str) -> tuple:
        """
        Parse option symbol to extract underlying, strike, and DTE.

        Option symbol format: AMD251031C00350000
        - Underlying: AMD (1-6 letters before date)
        - Date: 251031 (YYMMDD)
        - Type: P (Put) or C (Call)
        - Strike: 00350000 (last 8 digits / 1000 = $350.00)

        Args:
            option_symbol: Full option symbol

        Returns:
            Tuple of (underlying_symbol, strike_price, dte)
        """
        import re
        from datetime import datetime, timezone

        try:
            # Use fully anchored regex pattern to parse entire symbol at once
            # OCC standard: 1-6 letter underlying + 6-digit date + P/C + 8-digit strike
            pattern = r'^([A-Z]{1,6})(\d{6})([PC])(\d{8})$'
            match = re.match(pattern, option_symbol.strip().upper())

            if match:
                underlying = match.group(1)
                date_str = match.group(2)
                # option_type = match.group(3)  # P or C - not used currently
                strike_str = match.group(4)

                # Parse date
                year = 2000 + int(date_str[0:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                exp_date = datetime(year, month, day, tzinfo=timezone.utc)
                now = clock.now_utc()
                dte = max(0, (exp_date.date() - now.date()).days)

                # Parse strike price
                strike_price = float(strike_str) / 1000.0

                return underlying, strike_price, dte

            # Fallback to legacy parsing for non-standard formats
            logger.debug("Option symbol did not match standard OCC format, using fallback parsing",
                        event_category="data",
                        event_type="option_symbol_fallback_parse",
                        symbol=option_symbol)

            # Extract underlying symbol (letters at start)
            underlying_match = re.match(r'^([A-Z]+)', option_symbol.upper())
            underlying = underlying_match.group(1) if underlying_match else option_symbol[:3]

            # Extract date portion (6 digits immediately before P/C)
            date_match = re.search(r'(\d{6})[PC]', option_symbol.upper())
            if date_match:
                date_str = date_match.group(1)
                year = 2000 + int(date_str[0:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                exp_date = datetime(year, month, day, tzinfo=timezone.utc)
                now = clock.now_utc()
                dte = max(0, (exp_date.date() - now.date()).days)
            else:
                dte = 7  # Default fallback

            # Extract strike price (last 8 digits / 1000)
            strike_match = re.search(r'[PC](\d{8})$', option_symbol.upper())
            if strike_match:
                strike_price = float(strike_match.group(1)) / 1000.0
            else:
                strike_price = 0

            return underlying, strike_price, dte

        except Exception as e:
            logger.debug("Failed to parse option symbol",
                        event_category="data",
                        event_type="option_symbol_parse_debug",
                        symbol=option_symbol,
                        error=str(e))
            # Return safe defaults
            return option_symbol[:3] if len(option_symbol) >= 3 else option_symbol, 0, 7

    def _get_profit_target_for_dte(self, dte: int) -> float:
        """
        Get profit target based on DTE using configured bands.

        Args:
            dte: Days to expiration

        Returns:
            Profit target percentage (0.0-1.0)
        """
        # If dynamic profit targets disabled, use static target
        if not self.config.use_dynamic_profit_target:
            return self.config.profit_taking_static_target

        # Find matching DTE band
        for band in self.config.profit_taking_dte_bands:
            if band['dte'] == dte:
                target = band['profit_target']

                logger.debug("Using DTE band profit target",
                            event_category="trade",
                            event_type="profit_target_dte_band",
                            dte=dte,
                            target=f"{target*100:.0f}%",
                            description=band.get('description', ''))

                # Apply safety bounds
                return max(
                    self.config.profit_taking_min_target,
                    min(target, self.config.profit_taking_max_target)
                )

        # No exact match - check if long-dated (DTE > 7)
        if dte > 7:
            target = self.config.profit_taking_default_long_dte
            logger.debug("Using long DTE default profit target",
                        event_category="trade",
                        event_type="profit_target_long_dte",
                        dte=dte,
                        target=f"{target*100:.0f}%")
            return target

        # Fallback to static target
        logger.warning("No DTE band found, using static profit target",
                      event_category="trade",
                      event_type="profit_target_static_fallback",
                      dte=dte,
                      static_target=f"{self.config.profit_taking_static_target*100:.0f}%")
        return self.config.profit_taking_static_target

    def should_close_call_early(self, call_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Determine if a short call should be closed early for profit or stop loss.

        Uses dynamic DTE-based profit targets optimized for theta decay curves.

        Args:
            call_position: Short call position details
            current_option_data: Current option market data with delta, etc. (unused in Phase 1)

        Returns:
            True if position should be closed early
        """
        try:
            unrealized_pl = float(call_position['unrealized_pl'])
            position_value = abs(float(call_position['market_value']))

            option_symbol = call_position['symbol']

            # Profit target: Dynamic based on DTE (theta-optimized)
            if unrealized_pl > 0 and position_value > 0:
                # Hold period check: skip profit-target if position too new
                entry_time = self._entry_times.get(option_symbol)
                if entry_time:
                    hours_held = (clock.now() - entry_time).total_seconds() / 3600
                    if hours_held < self.config.profit_taking_min_hold_hours:
                        return False

                profit_percentage = unrealized_pl / position_value

                # Get dynamic profit target based on DTE
                dte = self._parse_dte_from_option_symbol(option_symbol)
                profit_target = self._get_profit_target_for_dte(dte)

                if profit_percentage >= profit_target:
                    logger.info("Call position reached dynamic profit target",
                               event_category="trade",
                               event_type="call_profit_target_reached",
                               symbol=option_symbol,
                               dte=dte,
                               profit_pct=round(profit_percentage * 100, 1),
                               target_pct=round(profit_target * 100, 1))
                    return True

            # Stop loss logic for short-term options (enabled for calls)
            if self.config.use_call_stop_loss and unrealized_pl < 0:
                return self._check_call_stop_loss(call_position, current_option_data)

            return False

        except Exception as e:
            logger.error("Failed to evaluate early close",
                        event_category="error",
                        event_type="early_close_evaluation_error",
                        error=str(e))
            return False

    def _check_call_stop_loss(self, call_position: Dict[str, Any], current_option_data: Dict[str, Any] = None) -> bool:
        """Check if call position should be closed due to stop loss.
        
        Args:
            call_position: Call position details
            current_option_data: Current option market data
            
        Returns:
            True if stop loss should be triggered
        """
        try:
            unrealized_pl = float(call_position['unrealized_pl'])
            position_value = abs(float(call_position['market_value']))
            
            # Method 1: Traditional premium-based stop loss (adjusted for time decay)
            if position_value > 0:
                loss_percentage = abs(unrealized_pl) / position_value
                
                # For short-term options, use a higher threshold since time decay is expected
                stop_loss_threshold = self.config.call_stop_loss_percent * self.config.stop_loss_multiplier
                
                if loss_percentage >= stop_loss_threshold:
                    logger.warning("Call position hit premium stop loss",
                                  event_category="risk",
                                  event_type="call_premium_stop_loss",
                                  symbol=call_position['symbol'],
                                  loss_pct=loss_percentage,
                                  threshold=stop_loss_threshold)
                    return True
            
            # Method 2: Delta-based stop loss (if current option data available)
            if current_option_data and 'delta' in current_option_data:
                current_delta = abs(current_option_data['delta'])
                
                # If delta > 0.5, the call is likely ITM and stock moved significantly up
                if current_delta > 0.5:  # Delta > 0.5 means we're likely ITM
                    logger.warning("Call position hit delta stop loss",
                                  event_category="risk",
                                  event_type="call_delta_stop_loss",
                                  symbol=call_position['symbol'],
                                  current_delta=current_delta)
                    return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to check call stop loss",
                        event_category="error",
                        event_type="call_stop_loss_check_error",
                        error=str(e))
            return False

    def handle_call_assignment(self, assignment_info: Dict[str, Any], wheel_state_manager=None) -> Dict[str, Any]:
        """Handle when a short call gets assigned (shares called away).

        Args:
            assignment_info: Assignment details
            wheel_state_manager: Optional wheel state manager for proper state transitions

        Returns:
            Assignment handling result with wheel state updates
        """
        try:
            symbol = assignment_info['symbol']
            shares_assigned = assignment_info.get('shares', 0)
            strike_price = assignment_info.get('strike_price', 0)
            assignment_date = assignment_info.get('date', clock.now())

            logger.info("Handling call assignment",
                       event_category="trade",
                       event_type="call_assignment_handling",
                       symbol=symbol,
                       shares=shares_assigned,
                       strike=strike_price)

            # Update wheel state if manager provided
            wheel_result = None
            if wheel_state_manager:
                wheel_result = wheel_state_manager.handle_call_assignment(
                    symbol, shares_assigned, strike_price, assignment_date, assignment_info
                )

            # Calculate realized profit/loss
            # This would include the premium received plus capital gain/loss
            realized_pnl = 0.0
            if wheel_result and 'capital_gain' in wheel_result:
                realized_pnl = wheel_result['capital_gain']

            result = {
                'action_type': 'assignment_handled',
                'strategy': 'call_assignment',
                'symbol': symbol,
                'shares_assigned': shares_assigned,
                'assignment_price': strike_price,
                'realized_pnl': realized_pnl,
                'timestamp': assignment_date.isoformat(),
                'wheel_cycle_completed': wheel_result.get('wheel_cycle_completed', False) if wheel_result else False,
                'next_action': 'look_for_new_put_opportunity' if wheel_result and wheel_result.get('wheel_cycle_completed') else 'continue_wheel_strategy'
            }

            # Include wheel state information if available
            if wheel_result:
                result['wheel_state_transition'] = {
                    'phase_before': wheel_result.get('phase_before', {}).value if hasattr(wheel_result.get('phase_before', {}), 'value') else None,
                    'phase_after': wheel_result.get('phase_after', {}).value if hasattr(wheel_result.get('phase_after', {}), 'value') else None,
                    'remaining_shares': wheel_result.get('remaining_shares', 0)
                }

                if wheel_result.get('completed_cycle'):
                    result['completed_wheel_cycle'] = wheel_result['completed_cycle']

            logger.info("Call assignment handled with wheel state management",
                       event_category="trade",
                       event_type="call_assignment_complete",
                       symbol=symbol,
                       shares_assigned=shares_assigned,
                       wheel_cycle_completed=result['wheel_cycle_completed'],
                       next_phase=result.get('wheel_state_transition', {}).get('phase_after'))

            # Enhanced position update logging
            log_position_update(
                logger,
                event_type="call_assignment",
                symbol=symbol,
                position_status="assigned",
                position_type="call",
                action="assignment",
                shares=shares_assigned,
                assignment_price=strike_price,
                realized_pnl=realized_pnl,
                wheel_cycle_completed=result['wheel_cycle_completed'],
                phase_before=result.get('wheel_state_transition', {}).get('phase_before'),
                phase_after=result.get('wheel_state_transition', {}).get('phase_after')
            )

            return result

        except Exception as e:
            logger.error("Failed to handle call assignment",
                        event_category="error",
                        event_type="call_assignment_error",
                        error=str(e))
            return {'error': str(e)}