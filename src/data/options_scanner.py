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
        
    def scan_for_put_opportunities(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Scan for cash-secured put opportunities across all configured stocks.
        
        Args:
            max_results: Maximum number of opportunities to return
            
        Returns:
            List of put opportunities sorted by attractiveness
        """
        try:
            logger.info("Scanning for put opportunities", symbols=len(self.config.stock_symbols))
            
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
    
    def scan_for_call_opportunities(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Scan for covered call opportunities on assigned stock positions.
        
        Args:
            max_results: Maximum number of opportunities to return
            
        Returns:
            List of call opportunities sorted by attractiveness
        """
        try:
            logger.info("Scanning for covered call opportunities")
            
            opportunities = []
            
            # Get current stock positions
            positions = self.alpaca.get_positions()
            stock_positions = [p for p in positions if p['asset_class'] == 'us_equity' and float(p['qty']) > 0]
            
            for position in stock_positions:
                symbol = position['symbol']
                shares = int(float(position['qty']))

                # Only consider positions with at least 100 shares
                if shares < 100:
                    continue

                # CRITICAL: Calculate cost basis per share for protection
                # This ensures we never sell calls below cost basis (guaranteed loss)
                cost_basis_per_share = float(position['cost_basis']) / shares

                # Get call opportunities filtered by cost basis
                calls = self.market_data.find_suitable_calls(
                    symbol,
                    min_strike_price=cost_basis_per_share
                )

                logger.debug("Filtering calls for cost basis protection",
                            symbol=symbol,
                            cost_basis_per_share=cost_basis_per_share,
                            calls_found=len(calls))
                
                for call in calls[:3]:  # Top 3 calls per position
                    opportunity = self._create_call_opportunity(call, position)
                    if opportunity:
                        opportunities.append(opportunity)
            
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
            logger.error("Failed to scan all opportunities", error=str(e))
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
            if dte > 0:
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
    
    def _create_call_opportunity(self, call_option: Dict[str, Any], stock_position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a call opportunity record with scoring.
        
        Args:
            call_option: Call option data
            stock_position: Stock position information
            
        Returns:
            Call opportunity with scoring
        """
        try:
            symbol = stock_position['symbol']
            shares_owned = int(float(stock_position['qty']))
            cost_basis_per_share = float(stock_position['cost_basis']) / shares_owned
            
            # Get current stock price
            stock_metrics = self.market_data.get_stock_metrics(symbol)
            current_price = stock_metrics.get('current_price', 0)
            
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
                'assignment_above_cost_basis': strike > cost_basis_per_share,
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
            delta_penalty = abs(delta - target_delta) * 100  # Penalty for deviation
            delta_score = max(0, 20 - delta_penalty)
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
            logger.error("Failed to calculate put attractiveness score", error=str(e))
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
            delta_penalty = abs(delta - target_delta) * 100
            delta_score = max(0, 20 - delta_penalty)
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
            logger.error("Failed to calculate call attractiveness score", error=str(e))
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
            logger.error("Failed to check existing positions", symbol=symbol, error=str(e))
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
            logger.error("Failed to get market overview", error=str(e))
            return {'error': str(e)}