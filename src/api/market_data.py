"""Market data utilities for options wheel strategy."""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import structlog

from .alpaca_client import AlpacaClient
from ..utils.config import Config

logger = structlog.get_logger(__name__)


class MarketDataManager:
    """Manager for market data operations and analysis."""
    
    def __init__(self, alpaca_client: AlpacaClient, config: Config):
        """Initialize market data manager.
        
        Args:
            alpaca_client: Alpaca client instance
            config: Configuration instance
        """
        self.alpaca = alpaca_client
        self.config = config
        
    def get_stock_metrics(self, symbol: str) -> Dict[str, Any]:
        """Get comprehensive stock metrics for wheel strategy evaluation.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with stock metrics
        """
        try:
            # Get current quote
            quote = self.alpaca.get_stock_quote(symbol)
            current_price = (quote['bid'] + quote['ask']) / 2
            
            # Get historical data for metrics calculation
            bars = self.alpaca.get_stock_bars(symbol, days=30)
            
            if bars.empty:
                logger.warning("No historical data available", symbol=symbol)
                return {}
            
            # Calculate metrics
            avg_volume = bars['volume'].mean()
            price_volatility = bars['close'].pct_change().std() * np.sqrt(252)  # Annualized
            
            # Price criteria check
            meets_price_criteria = (
                self.config.min_stock_price <= current_price <= self.config.max_stock_price
            )
            
            # Volume criteria check
            meets_volume_criteria = avg_volume >= self.config.min_avg_volume
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'bid': quote['bid'],
                'ask': quote['ask'],
                'bid_ask_spread': quote['ask'] - quote['bid'],
                'avg_volume': avg_volume,
                'price_volatility': price_volatility,
                'meets_price_criteria': meets_price_criteria,
                'meets_volume_criteria': meets_volume_criteria,
                'suitable_for_wheel': meets_price_criteria and meets_volume_criteria
            }
            
        except Exception as e:
            logger.error("Failed to get stock metrics", symbol=symbol, error=str(e))
            return {}
    
    def filter_suitable_stocks(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Filter stocks suitable for wheel strategy.

        Args:
            symbols: List of stock symbols to evaluate

        Returns:
            List of suitable stocks with metrics
        """
        suitable_stocks = []
        rejected_stocks = []

        for symbol in symbols:
            metrics = self.get_stock_metrics(symbol)
            if metrics and metrics.get('suitable_for_wheel', False):
                suitable_stocks.append(metrics)
                logger.info("Stock passed price/volume filter",
                           symbol=symbol,
                           price=metrics['current_price'],
                           avg_volume=int(metrics['avg_volume']),
                           volatility=round(metrics['price_volatility'], 3))
            elif metrics:
                # Log rejection reason
                rejection_reasons = []
                if not metrics.get('meets_price_criteria'):
                    rejection_reasons.append(f"price ${metrics['current_price']:.2f} outside ${self.config.min_stock_price}-${self.config.max_stock_price}")
                if not metrics.get('meets_volume_criteria'):
                    rejection_reasons.append(f"volume {int(metrics['avg_volume']):,} < {self.config.min_avg_volume:,}")

                logger.info("Stock rejected by price/volume filter",
                           symbol=symbol,
                           reasons=rejection_reasons,
                           price=metrics['current_price'],
                           avg_volume=int(metrics['avg_volume']))
                rejected_stocks.append(symbol)

        # Sort by liquidity (volume) and low volatility preference
        suitable_stocks.sort(key=lambda x: (-x['avg_volume'], x['price_volatility']))

        logger.info("STAGE 1 COMPLETE: Price/Volume filtering",
                   event_category="filtering",
                   event_type="stage_1_complete",
                   total_analyzed=len(symbols),
                   passed=len(suitable_stocks),
                   rejected=len(rejected_stocks),
                   passed_symbols=[s['symbol'] for s in suitable_stocks],
                   rejected_symbols=rejected_stocks)

        return suitable_stocks
    
    def get_option_chain_with_analysis(self, symbol: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get options chain with analysis for wheel strategy.
        
        Args:
            symbol: Underlying stock symbol
            
        Returns:
            Dictionary with 'puts' and 'calls' lists
        """
        try:
            options_chain = self.alpaca.get_options_chain(symbol)
            
            if not options_chain:
                logger.warning("No options chain data", symbol=symbol)
                return {'puts': [], 'calls': []}
            
            # Get current stock price
            stock_metrics = self.get_stock_metrics(symbol)
            current_price = stock_metrics.get('current_price', 0)
            
            puts = []
            calls = []
            
            now = datetime.now()
            
            for option in options_chain:
                # Calculate days to expiration
                exp_date = option['expiration_date']

                # Skip options with missing expiration date
                if exp_date is None:
                    continue

                if isinstance(exp_date, str):
                    exp_date = datetime.fromisoformat(exp_date.replace('Z', '+00:00'))

                dte = (exp_date - now).days
                
                # Calculate mid price
                if option['bid'] > 0 and option['ask'] > 0:
                    mid_price = (option['bid'] + option['ask']) / 2
                else:
                    mid_price = option['last_price']
                
                # Add calculated fields
                option_data = option.copy()
                option_data.update({
                    'dte': dte,
                    'mid_price': mid_price,
                    'bid_ask_spread': option['ask'] - option['bid'] if option['ask'] > option['bid'] else 0,
                    'moneyness': option['strike_price'] / current_price if current_price > 0 else 0
                })
                
                # Separate puts and calls
                if option['option_type'].upper() == 'PUT':
                    puts.append(option_data)
                else:
                    calls.append(option_data)
            
            return {'puts': puts, 'calls': calls}
            
        except Exception as e:
            logger.error("Failed to get options chain", symbol=symbol, error=str(e))
            return {'puts': [], 'calls': []}
    
    def find_suitable_puts(self, symbol: str) -> List[Dict[str, Any]]:
        """Find put options suitable for selling in wheel strategy.
        
        Args:
            symbol: Underlying stock symbol
            
        Returns:
            List of suitable put options, sorted by attractiveness
        """
        options_data = self.get_option_chain_with_analysis(symbol)
        puts = options_data['puts']

        logger.info("STAGE 7: Options chain criteria - starting put scan",
                   event_category="filtering",
                   event_type="stage_7_start",
                   symbol=symbol,
                   total_puts_in_chain=len(puts),
                   target_dte=self.config.put_target_dte,
                   min_premium=self.config.min_put_premium,
                   delta_range=self.config.put_delta_range)

        suitable_puts = []
        rejected_count = 0

        for put in puts:
            # Filter by strategy criteria
            if not self._meets_put_criteria(put):
                rejected_count += 1
                continue

            # Calculate annualized return
            if put['dte'] > 0 and put['mid_price'] > 0:
                annual_return = (put['mid_price'] / put['strike_price']) * (365 / put['dte'])
                put['annual_return'] = annual_return
                put['return_score'] = annual_return * (1 - abs(put.get('delta', 0)))  # Prefer lower delta

                suitable_puts.append(put)

        # Sort by return score (higher is better)
        suitable_puts.sort(key=lambda x: x.get('return_score', 0), reverse=True)

        if suitable_puts:
            best_put = suitable_puts[0]
            logger.info("STAGE 7 COMPLETE: Options chain criteria - puts found",
                       event_category="filtering",
                       event_type="stage_7_complete_found",
                       symbol=symbol,
                       total_puts=len(puts),
                       rejected=rejected_count,
                       suitable_count=len(suitable_puts),
                       best_put_strike=best_put['strike_price'],
                       best_put_premium=best_put['mid_price'],
                       best_put_dte=best_put['dte'],
                       best_put_delta=best_put.get('delta', 0))
        else:
            logger.info("STAGE 7 COMPLETE: Options chain criteria - NO suitable puts",
                       event_category="filtering",
                       event_type="stage_7_complete_not_found",
                       symbol=symbol,
                       total_puts=len(puts),
                       rejected=rejected_count,
                       reason="no_puts_met_criteria")

        return suitable_puts[:5]  # Return top 5
    
    def find_suitable_calls(self, symbol: str, min_strike_price: float = 0.0) -> List[Dict[str, Any]]:
        """Find call options suitable for selling in wheel strategy.

        Args:
            symbol: Underlying stock symbol
            min_strike_price: Minimum strike price (typically cost basis to avoid guaranteed losses)

        Returns:
            List of suitable call options, sorted by attractiveness
        """
        options_data = self.get_option_chain_with_analysis(symbol)
        calls = options_data['calls']
        
        suitable_calls = []
        
        for call in calls:
            # CRITICAL: Cost basis protection - never sell calls below cost basis
            if min_strike_price > 0 and call['strike_price'] < min_strike_price:
                logger.debug("Call rejected: strike below cost basis",
                           symbol=symbol,
                           strike=call['strike_price'],
                           cost_basis=min_strike_price)
                continue

            # Filter by strategy criteria
            if not self._meets_call_criteria(call):
                continue
            
            # Calculate annualized return
            if call['dte'] > 0 and call['mid_price'] > 0:
                annual_return = (call['mid_price'] / call['strike_price']) * (365 / call['dte'])
                call['annual_return'] = annual_return
                call['return_score'] = annual_return * (1 - abs(call.get('delta', 0)))  # Prefer lower delta
                
                suitable_calls.append(call)
        
        # Sort by return score (higher is better)
        suitable_calls.sort(key=lambda x: x.get('return_score', 0), reverse=True)
        
        logger.info("Found suitable calls", 
                   symbol=symbol, 
                   total_calls=len(calls), 
                   suitable_count=len(suitable_calls))
        
        return suitable_calls[:5]  # Return top 5
    
    def _meets_put_criteria(self, put_option: Dict[str, Any]) -> bool:
        """Check if put option meets wheel strategy criteria.
        
        Args:
            put_option: Put option data
            
        Returns:
            True if option meets criteria
        """
        # DTE criteria - less than or equal to target
        max_dte = self.config.put_target_dte
        
        if put_option['dte'] > max_dte:
            return False
        
        # Premium criteria
        if put_option['mid_price'] < self.config.min_put_premium:
            return False
        
        # Delta criteria
        delta = abs(put_option.get('delta', 0))
        delta_range = self.config.put_delta_range
        
        if not (delta_range[0] <= delta <= delta_range[1]):
            return False
        
        # Liquidity criteria (basic)
        if put_option['volume'] == 0 and put_option['open_interest'] < 10:
            return False
        
        return True
    
    def _meets_call_criteria(self, call_option: Dict[str, Any]) -> bool:
        """Check if call option meets wheel strategy criteria.
        
        Args:
            call_option: Call option data
            
        Returns:
            True if option meets criteria
        """
        # DTE criteria - less than or equal to target
        max_dte = self.config.call_target_dte
        
        if call_option['dte'] > max_dte:
            return False
        
        # Premium criteria
        if call_option['mid_price'] < self.config.min_call_premium:
            return False
        
        # Delta criteria
        delta = abs(call_option.get('delta', 0))
        delta_range = self.config.call_delta_range
        
        if not (delta_range[0] <= delta <= delta_range[1]):
            return False
        
        # Liquidity criteria (basic)
        if call_option['volume'] == 0 and call_option['open_interest'] < 10:
            return False
        
        return True