"""Options scanning utilities for wheel strategy opportunity identification."""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import structlog
import numpy as np

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..utils.config import Config
from ..utils.logging_events import log_performance_metric, log_error_event
from ..utils.positions import get_stock_positions
from ..strategy.cost_basis import CostBasisResolver, SOURCE_DIVERGENT
from .decision_record import (
    OUTCOME_BLOCKED,
    OUTCOME_NOT_ELIGIBLE,
    OUTCOME_NO_CANDIDATES,
    REASON_FLOOR_DIVERGENT,
    REASON_FLOOR_UNRESOLVED,
    REASON_INSUFFICIENT_SHARES,
    REASON_NO_QUALIFYING_STRIKES,
    REASON_QUOTE_UNAVAILABLE,
    STAGE_SCAN,
    DecisionRecorder,
    UncoveredDaysResolver,
    covered_underlyings,
    mint_run_id,
    position_mark_price,
    underwater_pct,
)

logger = structlog.get_logger(__name__)


class OptionsScanner:
    """Scanner for identifying options wheel trading opportunities."""
    
    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager, config: Config):
        """Initialize options scanner.
        
        Args:
            alpaca_client: Alpaca API client
            market_data: Market data manager
            config: Configuration instance
        """
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        # FC-065: the covered-call floor is Alpaca's avg_entry_price for the
        # equity position, with BigQuery running inline as a divergence
        # cross-check that can veto the broker's number but never supply one.
        self.cost_basis_resolver = CostBasisResolver(
            alpaca_client, config, allow_bigquery=True
        )
        # FC-065 Phase 4: the `uncovered_days` label. One batched BigQuery
        # query per scan for every held symbol, behind its own patchable
        # chokepoint (see tests/conftest.py).
        self.uncovered_days_resolver = UncoveredDaysResolver()

    def scan_for_put_opportunities(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Scan for cash-secured put opportunities across all configured stocks.
        
        Args:
            max_results: Maximum number of opportunities to return
            
        Returns:
            List of put opportunities sorted by attractiveness
        """
        try:
            logger.info("Scanning for put opportunities", event_category="system", event_type="put_scan_started", symbol_count=len(self.config.stock_symbols))
            
            opportunities = []
            
            # Get suitable stocks first
            suitable_stocks = self.market_data.filter_suitable_stocks(self.config.stock_symbols)
            
            for stock in suitable_stocks:
                symbol = stock['symbol']
                
                # Skip if we already have positions in this stock
                if self._has_existing_position(symbol):
                    continue
                
                # Get put opportunities for this stock
                puts = self.market_data.find_suitable_puts(symbol)
                
                for put in puts[:3]:  # Top 3 puts per stock
                    opportunity = self._create_put_opportunity(put, stock)
                    if opportunity:
                        opportunities.append(opportunity)
            
            # Sort by overall attractiveness score
            opportunities.sort(key=lambda x: x.get('attractiveness_score', 0), reverse=True)

            logger.info("Put scan completed",
                       total_opportunities=len(opportunities),
                       returning=min(max_results, len(opportunities)))

            # Enhanced logging for BigQuery analytics
            log_performance_metric(
                logger,
                metric_name="put_opportunities_discovered",
                metric_value=len(opportunities),
                metric_unit="count",
                symbols_scanned=len(self.config.stock_symbols),
                suitable_stocks=len(suitable_stocks),
                returning=min(max_results, len(opportunities)),
                top_score=opportunities[0].get('attractiveness_score', 0) if opportunities else 0,
                avg_score=sum(opp.get('attractiveness_score', 0) for opp in opportunities) / len(opportunities) if opportunities else 0,
                avg_annual_return=sum(opp.get('annual_return_percent', 0) for opp in opportunities) / len(opportunities) if opportunities else 0
            )

            return opportunities[:max_results]
            
        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="scan_failure",
                error_message=str(e),
                component="options_scanner",
                recoverable=True,
                scan_type="put"
            )
            return []
    
    def scan_for_call_opportunities(self, max_results: int = 10,
                                    run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scan for covered call opportunities on assigned stock positions.

        Args:
            max_results: Maximum number of opportunities to return
            run_id: FC-065 Phase 4 — the identifier joining this scan to the
                ``/run`` that executes from its blob. ``/scan`` mints it and
                passes it here; a caller that omits it (the CLI ``--command
                scan``) gets a self-contained one so its decisions are still
                recorded, they just have no execution stage to join to.

        Returns:
            List of call opportunities sorted by attractiveness
        """
        recorder: Optional[DecisionRecorder] = None
        recorded_symbols: List[str] = []
        try:
            logger.info("Scanning for covered call opportunities")

            opportunities = []

            # Get current stock positions
            positions = self.alpaca.get_positions()
            stock_positions = get_stock_positions(positions)

            # FC-065 Phase 4: one decision record per held symbol per cycle.
            # The scan stage writes the row for every symbol IT terminates
            # (not eligible / blocked / no candidates); symbols that produced
            # candidates are terminated by /run instead, so a held symbol with
            # no row at all for a scan-hour means the cycle did not complete —
            # which is the point of the fill-rate check.
            recorder = DecisionRecorder(run_id or mint_run_id(), STAGE_SCAN)
            held_symbols = [p['symbol'] for p in stock_positions]
            uncovered_days = self.uncovered_days_resolver.resolve(
                held_symbols, covered_underlyings(positions)
            )

            for position in stock_positions:
                symbol = position['symbol']
                shares = int(float(position['qty']))
                mark_price = position_mark_price(position)
                labels = {
                    'shares': shares,
                    'current_price': mark_price,
                    'uncovered_days': uncovered_days.get(symbol),
                }

                # Only consider positions with at least 100 shares
                if shares < 100:
                    recorder.record(symbol, OUTCOME_NOT_ELIGIBLE,
                                    REASON_INSUFFICIENT_SHARES, **labels)
                    recorded_symbols.append(symbol)
                    continue

                # CRITICAL: Resolve cost basis per share for protection.
                # This ensures we never sell calls below cost basis (guaranteed loss).
                # FC-065: the floor is Alpaca's avg_entry_price, verified inline
                # against reconstructed assignment history (BigQuery). Both
                # failure modes below skip the symbol for this scan.
                try:
                    raw_cost_basis = float(position.get('cost_basis') or 0)
                except (TypeError, ValueError):
                    raw_cost_basis = 0.0
                resolution = self.cost_basis_resolver.resolve_detailed(
                    symbol, position, shares
                )
                cost_basis_per_share = resolution['basis']
                cost_basis_source = resolution['source']
                cross_check = resolution.get('cross_check') or {}

                # FAIL CLOSED on a divergent cross-check. The broker reported a
                # number and the assignment history says it is wrong — presence
                # with a wrong value, which the zero check below cannot catch.
                if cost_basis_source == SOURCE_DIVERGENT:
                    logger.warning("Skipping call scan - cost basis divergent",
                                   event_category="trade",
                                   event_type="call_scan_skipped_cost_basis_divergent",
                                   symbol=symbol,
                                   shares=shares,
                                   broker_basis=resolution.get('broker_basis'),
                                   expected_basis=cross_check.get('expected_basis'),
                                   basis_delta=cross_check.get('basis_delta'),
                                   tolerance=cross_check.get('tolerance'),
                                   reconstructed_shares=cross_check.get('reconstructed_shares'),
                                   reason=cross_check.get('reason'))
                    recorder.record(symbol, OUTCOME_BLOCKED, REASON_FLOOR_DIVERGENT,
                                    cost_basis_per_share=resolution.get('broker_basis'),
                                    underwater=underwater_pct(
                                        mark_price, resolution.get('broker_basis')),
                                    **labels)
                    recorded_symbols.append(symbol)
                    continue

                # FAIL CLOSED on an unresolved cost basis. This floor is the
                # first of the two below-basis protections: find_suitable_calls
                # warns and continues when min_strike_price <= 0, so "no basis"
                # must mean "no calls", never "any strike". (FC-050 restored the
                # second one, the execute-time floor in call_seller.)
                if cost_basis_per_share <= 0:
                    logger.warning("Skipping call scan - cost basis unresolved",
                                   event_category="trade",
                                   event_type="call_scan_skipped_cost_basis_unresolved",
                                   symbol=symbol,
                                   shares=shares,
                                   cost_basis=raw_cost_basis,
                                   avg_entry_price=resolution.get('broker_basis'))
                    recorder.record(symbol, OUTCOME_BLOCKED, REASON_FLOOR_UNRESOLVED,
                                    cost_basis_per_share=cost_basis_per_share,
                                    **labels)
                    recorded_symbols.append(symbol)
                    continue

                # FC-065: the cross-check's verdict is logged on every scan of
                # every held symbol, including when it could not run. An
                # "unavailable" run is not an "all clear" — it is the state in
                # which the floor rests on a single broker field with nothing
                # watching it, which is precisely what needs to be visible.
                logger.info("Cost basis cross-check completed",
                            event_category="risk",
                            event_type="cost_basis_cross_check",
                            symbol=symbol,
                            source=cost_basis_source,
                            resolved_basis=cost_basis_per_share,
                            status=cross_check.get('status'),
                            expected_basis=cross_check.get('expected_basis'),
                            basis_delta=cross_check.get('basis_delta'),
                            tolerance=cross_check.get('tolerance'),
                            reason=cross_check.get('reason'))

                # Get call opportunities filtered by cost basis
                calls = self.market_data.find_suitable_calls(
                    symbol,
                    min_strike_price=cost_basis_per_share
                )

                logger.debug("Filtering calls for cost basis protection",
                            symbol=symbol,
                            cost_basis_per_share=cost_basis_per_share,
                            calls_found=len(calls))

                floor_labels = dict(labels)
                floor_labels['cost_basis_per_share'] = cost_basis_per_share
                floor_labels['underwater'] = underwater_pct(
                    mark_price, cost_basis_per_share)

                if not calls:
                    # THE "nothing happened" CASE. Before this record, an
                    # underwater symbol simply produced no output anywhere —
                    # NVDA has ended every scan since 07-30 at
                    # `stage_8_complete_not_found` and nothing downstream said
                    # so. It is now a labelled row.
                    recorder.record(symbol, OUTCOME_NO_CANDIDATES,
                                    REASON_NO_QUALIFYING_STRIKES,
                                    candidates=0,
                                    reason_counts=self._symbol_rejection_counts(symbol),
                                    **floor_labels)
                    recorded_symbols.append(symbol)
                    continue

                created = 0
                for call in calls[:3]:  # Top 3 calls per position
                    opportunity = self._create_call_opportunity(
                        call, position, cost_basis_per_share
                    )
                    if opportunity:
                        opportunities.append(opportunity)
                        created += 1

                if created == 0:
                    # The chain had qualifying strikes but none survived
                    # opportunity construction — today that means the stock
                    # quote was unusable (fail-closed, FC-065 Phase 1).
                    recorder.record(symbol, OUTCOME_NO_CANDIDATES,
                                    REASON_QUOTE_UNAVAILABLE,
                                    candidates=0,
                                    reason_counts=self._symbol_rejection_counts(symbol),
                                    **floor_labels)
                    recorded_symbols.append(symbol)
                    continue

                # Terminated by /run, not here. Logged so the hand-off is
                # visible even when /run never happens.
                logger.info("Decision deferred to execution stage",
                            event_category="system",
                            event_type="decision_record_deferred",
                            run_id=recorder.run_id,
                            symbol=symbol,
                            candidates=created,
                            uncovered_days=labels['uncovered_days'],
                            underwater_pct=floor_labels['underwater'])


            # Sort by overall attractiveness score
            opportunities.sort(key=lambda x: x.get('attractiveness_score', 0), reverse=True)

            logger.info("Call scan completed",
                       total_opportunities=len(opportunities),
                       returning=min(max_results, len(opportunities)))

            # Enhanced logging for BigQuery analytics
            log_performance_metric(
                logger,
                metric_name="call_opportunities_discovered",
                metric_value=len(opportunities),
                metric_unit="count",
                stock_positions=len(stock_positions),
                positions_with_100_shares=len([p for p in stock_positions if int(float(p['qty'])) >= 100]),
                returning=min(max_results, len(opportunities)),
                top_score=opportunities[0].get('attractiveness_score', 0) if opportunities else 0,
                avg_score=sum(opp.get('attractiveness_score', 0) for opp in opportunities) / len(opportunities) if opportunities else 0,
                avg_annual_return=sum(opp.get('annual_premium_return_percent', 0) for opp in opportunities) / len(opportunities) if opportunities else 0
            )

            return opportunities[:max_results]
            
        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="scan_failure",
                error_message=str(e),
                component="options_scanner",
                recoverable=True,
                scan_type="call"
            )
            return []
        finally:
            # Flush in `finally`, not on the happy path: a scan that dies
            # halfway still knows what it decided about the symbols it got
            # to, and losing that is losing exactly the cycles worth
            # investigating.
            if recorder is not None:
                recorder.flush(expected_symbols=recorded_symbols)

    @staticmethod
    def _call_rejection_counts(stats: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        """Non-zero chain-rejection counts from a stats dict, or ``{}``.

        Defensive about the shape because ``market_data`` is a ``MagicMock``
        in much of the suite, where attribute access returns another mock
        rather than raising.
        """
        counts = stats if isinstance(stats, dict) else {}
        out: Dict[str, int] = {}
        for key, value in counts.items():
            if key == 'total_rejected':
                continue
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            if count > 0:
                out[str(key)] = count
        return out

    def _symbol_rejection_counts(self, symbol: str) -> Dict[str, int]:
        """Look up ``symbol``'s last chain-rejection breakdown from market data."""
        published = getattr(self.market_data, 'last_call_rejection_stats', None)
        stats = published.get(symbol) if isinstance(published, dict) else None
        return self._call_rejection_counts(stats)

    def scan_all_opportunities(self) -> Dict[str, List[Dict[str, Any]]]:
        """Scan for both put and call opportunities.
        
        Returns:
            Dictionary with 'puts' and 'calls' opportunity lists
        """
        try:
            put_opportunities = self.scan_for_put_opportunities(20)
            call_opportunities = self.scan_for_call_opportunities(10)
            
            return {
                'puts': put_opportunities,
                'calls': call_opportunities,
                'scan_timestamp': datetime.now().isoformat(),
                'total_opportunities': len(put_opportunities) + len(call_opportunities)
            }
            
        except Exception as e:
            logger.error("Failed to scan all opportunities", event_category="error", event_type="scan_failed", error=str(e))
            return {'puts': [], 'calls': [], 'error': str(e)}
    
    def _create_put_opportunity(self, put_option: Dict[str, Any], stock_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a put opportunity record with scoring.
        
        Args:
            put_option: Put option data
            stock_info: Stock information
            
        Returns:
            Put opportunity with scoring
        """
        try:
            symbol = stock_info['symbol']
            current_price = stock_info['current_price']
            
            # Calculate key metrics
            premium = put_option['mid_price']
            strike = put_option['strike_price']
            dte = put_option['dte']
            delta = abs(put_option.get('delta', 0))
            
            # Calculate returns
            if dte > 0 and strike > 0:
                annual_return = (premium / strike) * (365 / dte) * 100
            else:
                annual_return = 0
            
            # Distance from current price
            otm_percentage = ((current_price - strike) / current_price) * 100 if current_price > 0 else 0
            
            # Liquidity score (basic)
            volume = put_option.get('volume', 0)
            open_interest = put_option.get('open_interest', 0)
            liquidity_score = min(100, (volume * 0.3 + open_interest * 0.7) / 10)
            
            # Calculate attractiveness score (0-100)
            attractiveness_score = self._calculate_put_attractiveness_score(
                annual_return, delta, otm_percentage, liquidity_score, dte
            )
            
            opportunity = {
                'type': 'put',
                'symbol': symbol,
                'option_symbol': put_option['symbol'],
                'current_stock_price': current_price,
                'strike_price': strike,
                'premium': premium,
                'dte': dte,
                'delta': delta,
                'annual_return_percent': annual_return,
                'otm_percentage': otm_percentage,
                'liquidity_score': liquidity_score,
                'attractiveness_score': attractiveness_score,
                'expiration_date': put_option['expiration_date'],
                'bid': put_option.get('bid', 0),
                'ask': put_option.get('ask', 0),
                'volume': volume,
                'open_interest': open_interest,
                'implied_volatility': put_option.get('implied_volatility', 0),
                'scan_timestamp': datetime.now().isoformat()
            }
            
            return opportunity
            
        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="opportunity_creation_failed",
                error_message=str(e),
                component="options_scanner",
                recoverable=True,
                opportunity_type="put",
                symbol=stock_info.get('symbol', 'unknown')
            )
            return None
    
    def _create_call_opportunity(self, call_option: Dict[str, Any], stock_position: Dict[str, Any],
                                 cost_basis_per_share: float) -> Optional[Dict[str, Any]]:
        """Create a call opportunity record with scoring.

        Args:
            call_option: Call option data
            stock_position: Stock position information
            cost_basis_per_share: Per-share cost basis already resolved by the
                caller (FC-050). Passed in rather than recomputed so the floor
                that filtered the chain, the one carried on the opportunity and
                the one enforced at execution are the same number.

        Returns:
            Call opportunity with scoring
        """
        try:
            symbol = stock_position['symbol']
            shares_owned = int(float(stock_position['qty']))

            # Get current stock price. FC-065 (folded in from the removed
            # Phase 3): a failed quote used to fail OPEN here — the opportunity
            # was still emitted, with every price-relative metric (annualized
            # return, OTM distance, attractiveness score) computed against a
            # current price of 0. Fail closed for this symbol instead;
            # the next cycle re-evaluates in minutes.
            stock_metrics = self.market_data.get_stock_metrics(symbol) or {}
            try:
                current_price = float(stock_metrics.get('current_price', 0) or 0)
            except (TypeError, ValueError):
                current_price = 0.0

            if current_price <= 0:
                logger.warning("Skipping call opportunity - stock quote unavailable",
                               event_category="trade",
                               event_type="call_scan_skipped_quote_unavailable",
                               symbol=symbol,
                               option_symbol=call_option.get('symbol'))
                return None

            # Calculate key metrics
            premium = call_option['mid_price']
            strike = call_option['strike_price']
            dte = call_option['dte']
            delta = abs(call_option.get('delta', 0))
            
            # Calculate maximum contracts
            max_contracts = shares_owned // 100
            
            if max_contracts <= 0:
                return None
            
            # Calculate returns
            premium_income = premium * 100 * max_contracts  # Per contract premium
            
            if dte > 0:
                annual_premium_return = (premium / current_price) * (365 / dte) * 100 if current_price > 0 else 0
            else:
                annual_premium_return = 0
            
            # Calculate total return if assigned
            if strike > cost_basis_per_share:
                capital_gain = (strike - cost_basis_per_share) * 100 * max_contracts
                total_return_if_assigned = premium_income + capital_gain
            else:
                capital_loss = (cost_basis_per_share - strike) * 100 * max_contracts
                total_return_if_assigned = premium_income - capital_loss
            
            # Distance above current price
            otm_percentage = ((strike - current_price) / current_price) * 100 if current_price > 0 else 0
            
            # Liquidity score
            volume = call_option.get('volume', 0)
            open_interest = call_option.get('open_interest', 0)
            liquidity_score = min(100, (volume * 0.3 + open_interest * 0.7) / 10)
            
            # Calculate attractiveness score
            attractiveness_score = self._calculate_call_attractiveness_score(
                annual_premium_return, delta, otm_percentage, liquidity_score, dte, 
                strike > cost_basis_per_share
            )
            
            opportunity = {
                'type': 'call',
                'symbol': symbol,
                'option_symbol': call_option['symbol'],
                'current_stock_price': current_price,
                'strike_price': strike,
                'premium': premium,
                'dte': dte,
                'delta': delta,
                'shares_owned': shares_owned,
                'max_contracts': max_contracts,
                'cost_basis_per_share': cost_basis_per_share,
                'premium_income': premium_income,
                'annual_premium_return_percent': annual_premium_return,
                'total_return_if_assigned': total_return_if_assigned,
                'otm_percentage': otm_percentage,
                'liquidity_score': liquidity_score,
                'attractiveness_score': attractiveness_score,
                # FC-065 Phase 2: ``>=``, matching the gates. Every floor gate
                # rejects only ``strike < floor`` (market_data's chain filter,
                # call_seller's execute-time check, risk_manager.validate_roll),
                # so an at-floor strike is admitted and sold — GOOGL's 370C was.
                # With strict ``>`` this flag read False on exactly those
                # writes: a warning that gated nothing and contradicted the
                # behaviour. At-floor keeps both premiums and gives up no
                # capital, which is the decided policy, so the flag says so.
                'assignment_above_cost_basis': strike >= cost_basis_per_share,
                'expiration_date': call_option['expiration_date'],
                'bid': call_option.get('bid', 0),
                'ask': call_option.get('ask', 0),
                'volume': volume,
                'open_interest': open_interest,
                'implied_volatility': call_option.get('implied_volatility', 0),
                'scan_timestamp': datetime.now().isoformat()
            }
            
            return opportunity
            
        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="opportunity_creation_failed",
                error_message=str(e),
                component="options_scanner",
                recoverable=True,
                opportunity_type="call",
                symbol=stock_position.get('symbol', 'unknown')
            )
            return None
    
    def _calculate_put_attractiveness_score(self, annual_return: float, delta: float, 
                                          otm_percentage: float, liquidity_score: float, 
                                          dte: int) -> float:
        """Calculate attractiveness score for put opportunity (0-100).
        
        Args:
            annual_return: Annualized return percentage
            delta: Option delta (absolute value)
            otm_percentage: Percentage out of the money
            liquidity_score: Liquidity score (0-100)
            dte: Days to expiration
            
        Returns:
            Attractiveness score (0-100)
        """
        try:
            score = 0
            
            # Return component (40 points max)
            return_score = min(40, annual_return * 2)  # 20% annual = 40 points
            score += return_score
            
            # Delta component (20 points max) - prefer 0.15-0.25 delta
            target_delta = 0.20
            # Ensure delta is in valid range [0, 1]
            delta_capped = max(0, min(1, delta))
            delta_penalty = abs(delta_capped - target_delta) * 100  # Penalty for deviation
            delta_score = max(0, min(20, 20 - delta_penalty))  # Cap between 0 and 20
            score += delta_score
            
            # OTM component (15 points max) - prefer 5-15% OTM
            if 5 <= otm_percentage <= 15:
                otm_score = 15
            elif otm_percentage < 5:
                otm_score = max(0, 15 - (5 - otm_percentage) * 2)
            else:
                otm_score = max(0, 15 - (otm_percentage - 15) * 1)
            score += otm_score
            
            # Liquidity component (15 points max)
            score += min(15, liquidity_score * 0.15)
            
            # DTE component (10 points max) - prefer shorter DTE, max at target
            max_dte = self.config.put_target_dte
            if dte <= max_dte:
                # Score higher for shorter DTE (more time decay)
                dte_score = 10 * (max_dte - dte + 1) / (max_dte + 1)
            else:
                dte_score = 0  # No points if exceeds maximum
            score += dte_score
            
            return min(100, max(0, score))
            
        except Exception as e:
            logger.error("Failed to calculate put attractiveness score", event_category="error", event_type="put_score_calculation_failed", error=str(e))
            return 0
    
    def _calculate_call_attractiveness_score(self, annual_return: float, delta: float, 
                                           otm_percentage: float, liquidity_score: float, 
                                           dte: int, above_cost_basis: bool) -> float:
        """Calculate attractiveness score for call opportunity (0-100).
        
        Args:
            annual_return: Annualized premium return percentage
            delta: Option delta (absolute value)
            otm_percentage: Percentage out of the money
            liquidity_score: Liquidity score (0-100)
            dte: Days to expiration
            above_cost_basis: Whether strike is above cost basis
            
        Returns:
            Attractiveness score (0-100)
        """
        try:
            score = 0
            
            # Return component (35 points max)
            return_score = min(35, annual_return * 3)  # ~12% annual = 35 points
            score += return_score
            
            # Delta component (20 points max) - prefer 0.15-0.25 delta
            target_delta = 0.20
            # Ensure delta is in valid range [0, 1]
            delta_capped = max(0, min(1, delta))
            delta_penalty = abs(delta_capped - target_delta) * 100
            delta_score = max(0, min(20, 20 - delta_penalty))  # Cap between 0 and 20
            score += delta_score

            # OTM component (15 points max) - prefer 2-10% OTM
            if 2 <= otm_percentage <= 10:
                otm_score = 15
            elif otm_percentage < 2:
                otm_score = max(0, 15 - (2 - otm_percentage) * 3)
            else:
                otm_score = max(0, 15 - (otm_percentage - 10) * 1)
            score += otm_score
            
            # Above cost basis bonus (15 points max)
            if above_cost_basis:
                score += 15
            else:
                score += 5  # Small bonus even if below cost basis (still collect premium)
            
            # Liquidity component (10 points max)
            score += min(10, liquidity_score * 0.1)
            
            # DTE component (5 points max) - prefer shorter DTE, max at target
            max_dte = self.config.call_target_dte
            if dte <= max_dte:
                # Score higher for shorter DTE (more time decay)
                dte_score = 5 * (max_dte - dte + 1) / (max_dte + 1)
            else:
                dte_score = 0  # No points if exceeds maximum
            score += dte_score
            
            return min(100, max(0, score))
            
        except Exception as e:
            logger.error("Failed to calculate call attractiveness score", event_category="error", event_type="call_score_calculation_failed", error=str(e))
            return 0
    
    def _has_existing_position(self, symbol: str) -> bool:
        """Check if we already have positions in a stock.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if we have existing positions
        """
        try:
            positions = self.alpaca.get_positions()
            
            # Check for direct stock positions
            for position in positions:
                if position['symbol'] == symbol:
                    return True
                    
                # Check option positions (simplified check)
                if position['asset_class'] == 'us_option' and symbol in position['symbol']:
                    return True
            
            return False
            
        except Exception as e:
            logger.error("Failed to check existing positions", event_category="error", event_type="position_check_failed", symbol=symbol, error=str(e))
            return True  # Conservative assumption
    
    def get_market_overview(self) -> Dict[str, Any]:
        """Get market overview for wheel strategy context.
        
        Returns:
            Market overview metrics
        """
        try:
            overview = {
                'scan_timestamp': datetime.now().isoformat(),
                'configured_stocks': len(self.config.stock_symbols),
                'suitable_stocks': 0,
                'average_iv_rank': 0,
                'market_conditions': 'neutral'
            }
            
            # Analyze configured stocks
            suitable_count = 0
            iv_ranks = []
            
            for symbol in self.config.stock_symbols[:10]:  # Sample first 10 for performance
                try:
                    stock_metrics = self.market_data.get_stock_metrics(symbol)
                    if stock_metrics.get('suitable_for_wheel', False):
                        suitable_count += 1
                    
                    # Get options data for IV analysis
                    options_data = self.market_data.get_option_chain_with_analysis(symbol)
                    if options_data['puts']:
                        avg_iv = np.mean([opt.get('implied_volatility', 0) for opt in options_data['puts'][:5]])
                        if avg_iv > 0:
                            iv_ranks.append(avg_iv)
                            
                except Exception:
                    continue
            
            overview['suitable_stocks'] = suitable_count
            
            if iv_ranks:
                overview['average_iv_rank'] = np.mean(iv_ranks) * 100  # Convert to percentage
                
                # Simple market condition assessment
                avg_iv = np.mean(iv_ranks)
                if avg_iv > 0.30:
                    overview['market_conditions'] = 'high_volatility'
                elif avg_iv < 0.15:
                    overview['market_conditions'] = 'low_volatility'
                else:
                    overview['market_conditions'] = 'normal'
            
            return overview
            
        except Exception as e:
            logger.error("Failed to get market overview", event_category="error", event_type="market_overview_failed", error=str(e))
            return {'error': str(e)}