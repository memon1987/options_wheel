#!/usr/bin/env python3
"""Monday-only options wheel backtesting with Friday expirations (5 DTE)."""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import pandas as pd
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.backtesting.historical_data import HistoricalDataManager
from src.utils.config import Config
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig


class MondayOnlyBacktester:
    """Enhanced backtester for Monday-only entries with Friday expirations."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        """Initialize Monday-only backtester.

        Args:
            config_path: Path to configuration file
        """
        load_dotenv()
        self.config = Config(config_path)
        self.data_manager = HistoricalDataManager(self.config)

        # Detailed trade tracking
        self.trade_log = []
        self.position_history = []

        # Stock position tracking for wheel strategy
        self.stock_positions = {}  # symbol -> {shares: int, cost_basis: float, acquired_date: datetime}
        self.wheel_cycles = []  # Track complete wheel cycles

    def get_mondays_in_range(self, start_date: datetime, end_date: datetime) -> List[datetime]:
        """Get all Mondays within a date range.

        Args:
            start_date: Start of range
            end_date: End of range

        Returns:
            List of Monday dates
        """
        mondays = []
        current = start_date

        # Find first Monday
        while current.weekday() != 0:  # Monday is 0
            current += timedelta(days=1)

        # Collect all Mondays until end_date
        while current <= end_date:
            mondays.append(current)
            current += timedelta(weeks=1)

        return mondays

    def get_following_friday(self, monday_date: datetime) -> datetime:
        """Get the Friday following a given Monday.

        Args:
            monday_date: Monday date

        Returns:
            Following Friday date
        """
        # Friday is 4 days after Monday
        return monday_date + timedelta(days=4)

    def add_stock_position(self, symbol: str, shares: int, cost_basis: float, acquired_date: datetime):
        """Add or update stock position from assignment.

        Args:
            symbol: Stock symbol
            shares: Number of shares (positive for long)
            cost_basis: Cost basis per share
            acquired_date: Date acquired
        """
        if symbol not in self.stock_positions:
            self.stock_positions[symbol] = {
                'shares': 0,
                'total_cost': 0.0,
                'acquired_date': acquired_date
            }

        position = self.stock_positions[symbol]

        # Update position (average cost basis for additional shares)
        current_total_cost = position['shares'] * position.get('avg_cost', cost_basis)
        new_total_cost = current_total_cost + (shares * cost_basis)
        new_total_shares = position['shares'] + shares

        position['shares'] = new_total_shares
        position['total_cost'] = new_total_cost
        position['avg_cost'] = new_total_cost / new_total_shares if new_total_shares > 0 else 0

        if shares > 0:  # Only update acquired date for new long positions
            position['acquired_date'] = acquired_date

        print(f"   📈 STOCK POSITION UPDATED: {symbol}")
        print(f"      Shares: {position['shares']}")
        print(f"      Avg Cost: ${position['avg_cost']:.2f}")

    def remove_stock_position(self, symbol: str, shares: int, call_away_price: float, call_away_date: datetime):
        """Remove stock position when called away.

        Args:
            symbol: Stock symbol
            shares: Number of shares removed (positive)
            call_away_price: Price per share when called away
            call_away_date: Date called away
        """
        if symbol not in self.stock_positions:
            return

        position = self.stock_positions[symbol]

        if position['shares'] >= shares:
            # Calculate realized gain/loss on called away shares
            avg_cost = position['avg_cost']
            realized_pnl = (call_away_price - avg_cost) * shares

            # Update position
            position['shares'] -= shares
            remaining_total_cost = position['avg_cost'] * position['shares']
            position['total_cost'] = remaining_total_cost

            print(f"   📉 STOCK CALLED AWAY: {symbol}")
            print(f"      Shares Called: {shares}")
            print(f"      Call Price: ${call_away_price:.2f}")
            print(f"      Realized P&L: ${realized_pnl:.2f}")
            print(f"      Remaining Shares: {position['shares']}")

            # Remove position if no shares left
            if position['shares'] <= 0:
                del self.stock_positions[symbol]
                print(f"      Position Closed: {symbol}")

            return realized_pnl

        return 0

    def has_stock_position(self, symbol: str) -> bool:
        """Check if we have a stock position for covered call selling.

        Args:
            symbol: Stock symbol to check

        Returns:
            True if we have shares available for covered calls
        """
        return (symbol in self.stock_positions and
                self.stock_positions[symbol]['shares'] >= 100)

    def analyze_monday_call_options(self, symbol: str, monday_date: datetime,
                                  friday_expiration: datetime) -> Dict[str, Any]:
        """Analyze available call options for Monday covered call entry.

        Args:
            symbol: Stock symbol
            monday_date: Monday entry date
            friday_expiration: Target Friday expiration

        Returns:
            Analysis of available call options
        """
        print(f"\n📅 ANALYZING {symbol} CALL OPTIONS FOR {monday_date.strftime('%Y-%m-%d')} (Monday)")
        print(f"   Target Expiration: {friday_expiration.strftime('%Y-%m-%d')} (Friday)")
        print(f"   Strategy: COVERED CALL on {self.stock_positions[symbol]['shares']} shares")
        print("-" * 70)

        # Get stock price on Monday
        stock_data = self.data_manager.get_stock_data(
            symbol, monday_date, monday_date + timedelta(days=1)
        )

        if stock_data.empty:
            return {'error': f'No stock data for {monday_date}'}

        stock_price = stock_data['close'].iloc[0]
        print(f"   {symbol} Stock Price: ${stock_price:.2f}")
        print(f"   Avg Cost Basis: ${self.stock_positions[symbol]['avg_cost']:.2f}")

        # Get options chain for Monday
        try:
            options_chain = self.data_manager.get_option_chain_historical_bars(
                symbol, monday_date, stock_price
            )
        except Exception as e:
            return {'error': f'Failed to get options chain: {str(e)}'}

        if not options_chain:
            return {'error': 'No options chain data available'}

        # Extract call options from the response
        all_calls = options_chain.get('calls', [])

        # Filter for call options with Friday expiration
        friday_calls = []
        target_exp_str = friday_expiration.strftime('%Y-%m-%d')

        for option in all_calls:
            # Handle expiration date format (could be datetime object or string)
            exp_date = option.get('expiration_date')
            if exp_date:
                if isinstance(exp_date, str):
                    exp_str = exp_date.split('T')[0]  # Remove time component if present
                else:
                    exp_str = exp_date.strftime('%Y-%m-%d')

                if (exp_str == target_exp_str and
                    option.get('bid', 0) > 0 and
                    option.get('volume', 0) > 0):

                    friday_calls.append(option)

        print(f"   Available Call Options: {len(all_calls)}")
        print(f"   Friday Expiration Calls: {len(friday_calls)}")

        if not friday_calls:
            return {
                'error': 'No suitable call options found',
                'monday_date': monday_date,
                'friday_expiration': friday_expiration,
                'stock_price': stock_price
            }

        # Apply strategy criteria for covered calls
        suitable_calls = []
        min_premium = getattr(self.config, 'min_call_premium', 0.30)

        # For covered calls, we typically want ATM or slightly OTM calls
        # Delta range for calls: 0.15-0.70 (allows slightly OTM calls with good premiums)
        delta_min, delta_max = getattr(self.config, 'call_delta_range', (0.15, 0.70))
        for call in friday_calls:
            premium = call.get('bid', 0)
            volume = call.get('volume', 0)
            strike = call.get('strike_price', 0)

            # Calculate approximate delta for calls
            # For calls: higher strike = lower delta, ATM calls have ~0.50 delta
            moneyness = stock_price / strike if strike > 0 else 0

            if moneyness > 1.0:  # ITM calls
                # ITM calls have higher deltas (0.5 to 0.9)
                itm_amount = moneyness - 1.0
                approx_delta = 0.5 + (itm_amount * 2.0)  # Increases as more ITM
            else:  # OTM calls
                # OTM calls have lower deltas (0.1 to 0.5)
                # At ATM (moneyness=1.0), delta = 0.5
                # Further OTM = lower delta
                approx_delta = 0.5 * moneyness

            approx_delta = min(0.95, max(0.05, approx_delta))  # Clamp between 0.05-0.95

            # Quality scoring for calls
            quality_score = 0.0

            # Premium component (30%)
            if premium >= min_premium:
                quality_score += 0.3 * min(1.0, premium / (min_premium * 2))

            # Volume component (25%)
            volume_score = min(1.0, volume / 1000.0)
            quality_score += 0.25 * volume_score

            # Delta component (25%) - prefer moderate deltas
            delta_target = (delta_min + delta_max) / 2
            delta_score = 1.0 - abs(approx_delta - delta_target) / delta_target
            quality_score += 0.25 * delta_score

            # Strike selection component (20%) - prefer slightly OTM
            strike_distance_pct = (strike - stock_price) / stock_price
            if 0 <= strike_distance_pct <= 0.05:  # 0-5% OTM preferred
                quality_score += 0.2
            elif -0.02 <= strike_distance_pct < 0:  # Slightly ITM acceptable
                quality_score += 0.15
            elif 0.05 < strike_distance_pct <= 0.10:  # 5-10% OTM less preferred
                quality_score += 0.1

            call['quality_score'] = quality_score
            call['approx_delta'] = approx_delta
            call['moneyness'] = moneyness

            # Filter by criteria
            # CRITICAL: Cost basis protection - never sell calls below cost basis
            cost_basis = self.stock_positions[symbol]['avg_cost']

            if (premium >= min_premium and
                volume > 0 and
                delta_min <= approx_delta <= delta_max and
                strike > stock_price * 0.98 and  # Don't sell calls too far ITM
                strike >= cost_basis):  # NEVER sell below cost basis to avoid guaranteed loss

                suitable_calls.append(call)

        print(f"   Strategy-Suitable Calls: {len(suitable_calls)}")

        if not suitable_calls:
            return {
                'error': 'No calls meeting strategy criteria',
                'monday_date': monday_date,
                'friday_expiration': friday_expiration,
                'stock_price': stock_price,
                'total_calls': len(friday_calls)
            }

        # Select best call option
        best_call = max(suitable_calls, key=lambda x: x['quality_score'])

        print(f"   Best Option: {best_call['strike_price']:.0f}C")
        print(f"   Premium: ${best_call['bid']:.2f}")
        print(f"   Delta: {best_call['approx_delta']:.3f}")
        print(f"   Volume: {best_call.get('volume', 0):.0f}")
        print(f"   Quality Score: {best_call['quality_score']:.3f}")

        return {
            'monday_date': monday_date,
            'friday_expiration': friday_expiration,
            'stock_price': stock_price,
            'best_call': best_call,
            'all_suitable_calls': suitable_calls,
            'total_calls_analyzed': len(friday_calls)
        }

    def analyze_monday_options(self, symbol: str, monday_date: datetime,
                              friday_expiration: datetime) -> Dict[str, Any]:
        """Analyze available options for a Monday entry.

        Args:
            symbol: Stock symbol
            monday_date: Monday entry date
            friday_expiration: Target Friday expiration

        Returns:
            Analysis of available options
        """
        print(f"\n📅 ANALYZING {symbol} OPTIONS FOR {monday_date.strftime('%Y-%m-%d')} (Monday)")
        print(f"   Target Expiration: {friday_expiration.strftime('%Y-%m-%d')} (Friday)")
        print("-" * 70)

        # Get stock price on Monday
        stock_data = self.data_manager.get_stock_data(
            symbol, monday_date, monday_date + timedelta(days=1)
        )

        if stock_data.empty:
            return {'error': f'No stock data for {monday_date}'}

        stock_price = stock_data['close'].iloc[0]
        print(f"   {symbol} Stock Price: ${stock_price:.2f}")

        # Get options chain for Monday
        try:
            chain_data = self.data_manager.get_option_chain_historical_bars(
                symbol, monday_date, stock_price, 45
            )

            if not chain_data or not chain_data.get('puts'):
                return {'error': f'No options data for {monday_date}'}

            puts = chain_data['puts']
            print(f"   Available Put Options: {len(puts)}")

            # Filter for Friday expiration (5 DTE)
            friday_puts = []
            target_exp_str = friday_expiration.strftime('%Y-%m-%d')

            for put in puts:
                exp_date = put.get('expiration_date')
                if exp_date:
                    if isinstance(exp_date, str):
                        exp_str = exp_date.split('T')[0]
                    else:
                        exp_str = exp_date.strftime('%Y-%m-%d')

                    if exp_str == target_exp_str:
                        friday_puts.append(put)

            print(f"   Friday Expiration Puts: {len(friday_puts)}")

            if not friday_puts:
                return {'error': f'No puts expiring on {target_exp_str}'}

            # Apply strategy criteria
            suitable_puts = []
            delta_min, delta_max = self.config.put_delta_range
            min_premium = self.config.min_put_premium

            for put in friday_puts:
                delta = abs(put.get('delta', 0.0))
                bid = put.get('bid', 0.0)
                volume = put.get('volume', 0)

                if (delta_min <= delta <= delta_max and
                    bid >= min_premium and
                    volume > 0 and
                    bid > 0):

                    # Calculate quality score
                    volume_score = min(1.0, volume / 100)
                    spread = put.get('ask', 0) - bid
                    spread_pct = (spread / bid * 100) if bid > 0 else 100
                    spread_score = max(0, 1 - (spread_pct / 15.0))
                    premium_score = min(1.0, bid / 5.0)
                    delta_score = 1.0  # All deltas are in range

                    quality_score = (
                        volume_score * 0.25 +
                        spread_score * 0.35 +
                        premium_score * 0.25 +
                        delta_score * 0.15
                    )

                    put['quality_score'] = quality_score
                    suitable_puts.append(put)

            # Sort by quality score
            suitable_puts.sort(key=lambda x: x.get('quality_score', 0), reverse=True)

            print(f"   Strategy-Suitable Puts: {len(suitable_puts)}")

            if suitable_puts:
                best_put = suitable_puts[0]
                print(f"   Best Option: {best_put['strike_price']:.1f}P")
                print(f"   Premium: ${best_put['bid']:.2f}")
                print(f"   Delta: {abs(best_put.get('delta', 0)):.3f}")
                print(f"   Volume: {best_put.get('volume', 0)}")
                print(f"   Quality Score: {best_put.get('quality_score', 0):.3f}")

            return {
                'monday_date': monday_date,
                'friday_expiration': friday_expiration,
                'stock_price': stock_price,
                'total_puts': len(puts),
                'friday_puts': len(friday_puts),
                'suitable_puts': len(suitable_puts),
                'best_put': suitable_puts[0] if suitable_puts else None,
                'all_suitable': suitable_puts
            }

        except Exception as e:
            return {'error': f'Options analysis failed: {e}'}

    def execute_monday_trade(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute a trade based on Monday analysis.

        Args:
            analysis: Monday options analysis

        Returns:
            Trade execution details or None
        """
        if 'error' in analysis or not analysis.get('best_put'):
            return None

        best_put = analysis['best_put']

        trade = {
            'entry_date': analysis['monday_date'],
            'expiration_date': analysis['friday_expiration'],
            'symbol': best_put.get('underlying', 'UNH'),
            'option_symbol': best_put.get('symbol', 'N/A'),
            'strike_price': best_put['strike_price'],
            'entry_premium': best_put['bid'],
            'entry_delta': abs(best_put.get('delta', 0)),
            'entry_stock_price': analysis['stock_price'],
            'volume': best_put.get('volume', 0),
            'quality_score': best_put.get('quality_score', 0),
            'status': 'open',
            'dte_at_entry': 5,
            'trade_type': 'put',  # Mark as put trade
        }

        print(f"   ✅ TRADE EXECUTED: Sold {trade['strike_price']:.1f}P for ${trade['entry_premium']:.2f}")

        return trade

    def execute_monday_call_trade(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute a Monday covered call trade.

        Args:
            analysis: Call option analysis from analyze_monday_call_options

        Returns:
            Trade details or None if no trade executed
        """
        if 'error' in analysis or not analysis.get('best_call'):
            return None

        best_call = analysis['best_call']

        trade = {
            'entry_date': analysis['monday_date'],
            'expiration_date': analysis['friday_expiration'],
            'symbol': best_call.get('underlying', analysis.get('symbol', 'UNH')),
            'option_symbol': best_call.get('symbol', 'N/A'),
            'strike_price': best_call['strike_price'],
            'entry_premium': best_call['bid'],
            'entry_delta': abs(best_call.get('delta', 0)),
            'entry_stock_price': analysis['stock_price'],
            'volume': best_call.get('volume', 0),
            'quality_score': best_call.get('quality_score', 0),
            'status': 'open',
            'dte_at_entry': 5,
            'trade_type': 'call',  # Mark as covered call
            'stock_cost_basis': self.stock_positions[analysis.get('symbol', 'UNH')]['avg_cost']
        }

        print(f"   ✅ COVERED CALL EXECUTED: Sold {trade['strike_price']:.1f}C for ${trade['entry_premium']:.2f}")

        return trade

    def track_position_daily(self, trade: Dict[str, Any], current_date: datetime) -> Dict[str, Any]:
        """Track position value on a daily basis.

        Args:
            trade: Active trade
            current_date: Current tracking date

        Returns:
            Updated position tracking
        """
        # Get current stock price
        stock_data = self.data_manager.get_stock_data(
            trade['symbol'], current_date, current_date + timedelta(days=1)
        )

        if stock_data.empty:
            return {'error': f'No stock data for {current_date}'}

        current_stock_price = stock_data['close'].iloc[0]
        days_to_expiration = (trade['expiration_date'] - current_date).days

        # Get current option price if available (for non-expired contracts)
        current_option_price = 0.0
        if days_to_expiration >= 0:
            try:
                # Try to get current option price using historical bars
                from alpaca.data import OptionHistoricalDataClient
                from alpaca.data.requests import OptionBarsRequest
                from alpaca.data.timeframe import TimeFrame

                option_client = OptionHistoricalDataClient(
                    api_key=self.config.alpaca_api_key,
                    secret_key=self.config.alpaca_secret_key
                )

                bars_request = OptionBarsRequest(
                    symbol_or_symbols=[trade['option_symbol']],
                    timeframe=TimeFrame.Day,
                    start=current_date,
                    end=current_date + timedelta(days=1)
                )

                bars_response = option_client.get_option_bars(bars_request)

                if hasattr(bars_response, 'df') and not bars_response.df.empty:
                    df = bars_response.df
                    if hasattr(df.index, 'get_level_values'):
                        option_data = df.loc[trade['option_symbol']]
                        if hasattr(option_data, 'iloc'):
                            option_data = option_data.iloc[0]
                        current_option_price = float(option_data['close'])

            except Exception as e:
                # If we can't get current option price, estimate based on intrinsic value
                trade_type = trade.get('trade_type', 'put')

                if trade_type == 'put':
                    if current_stock_price < trade['strike_price']:
                        # ITM put - intrinsic value
                        current_option_price = trade['strike_price'] - current_stock_price
                    else:
                        # OTM put - minimal time value
                        time_factor = max(0.01, days_to_expiration / 5.0)
                        current_option_price = max(0.01, trade['entry_premium'] * time_factor * 0.1)
                else:  # call
                    if current_stock_price > trade['strike_price']:
                        # ITM call - intrinsic value
                        current_option_price = current_stock_price - trade['strike_price']
                    else:
                        # OTM call - minimal time value
                        time_factor = max(0.01, days_to_expiration / 5.0)
                        current_option_price = max(0.01, trade['entry_premium'] * time_factor * 0.1)

        # Calculate P&L (we're short the option)
        position_pnl = trade['entry_premium'] - current_option_price

        # Calculate intrinsic value based on option type
        trade_type = trade.get('trade_type', 'put')
        if trade_type == 'put':
            intrinsic_value = max(0, trade['strike_price'] - current_stock_price)
        else:  # call
            intrinsic_value = max(0, current_stock_price - trade['strike_price'])

        tracking = {
            'date': current_date,
            'stock_price': current_stock_price,
            'option_price': current_option_price,
            'days_to_expiration': days_to_expiration,
            'position_pnl': position_pnl,
            'pnl_percent': (position_pnl / trade['entry_premium'] * 100) if trade['entry_premium'] > 0 else 0,
            'intrinsic_value': intrinsic_value,
            'time_value': max(0, current_option_price - intrinsic_value)
        }

        return tracking

    def close_position(self, trade: Dict[str, Any], close_date: datetime,
                      close_reason: str) -> Dict[str, Any]:
        """Close a position and calculate final P&L.

        Args:
            trade: Trade to close
            close_date: Date of closure
            close_reason: Reason for closure

        Returns:
            Final trade results
        """
        # Get final tracking
        final_tracking = self.track_position_daily(trade, close_date)

        if 'error' in final_tracking:
            # If we can't get final tracking, use expiration logic
            stock_data = self.data_manager.get_stock_data(
                trade['symbol'], close_date, close_date + timedelta(days=1)
            )

            if not stock_data.empty:
                final_stock_price = stock_data['close'].iloc[0]

                if close_reason == 'expiration':
                    # At expiration, option worth intrinsic value
                    trade_type = trade.get('trade_type', 'put')

                    if trade_type == 'put':
                        final_option_price = max(0, trade['strike_price'] - final_stock_price)
                        assigned = final_stock_price < trade['strike_price']
                    else:  # call
                        final_option_price = max(0, final_stock_price - trade['strike_price'])
                        assigned = final_stock_price > trade['strike_price']

                    final_pnl = trade['entry_premium'] - final_option_price
                else:
                    # Early close - estimate
                    final_option_price = 0.01  # Assume we bought back at minimal cost
                    final_pnl = trade['entry_premium'] - final_option_price
                    assigned = False

                final_tracking = {
                    'date': close_date,
                    'stock_price': final_stock_price,
                    'option_price': final_option_price,
                    'position_pnl': final_pnl,
                    'pnl_percent': (final_pnl / trade['entry_premium'] * 100) if trade['entry_premium'] > 0 else 0
                }
            else:
                # No data available - make conservative estimate
                final_tracking = {
                    'date': close_date,
                    'stock_price': trade['entry_stock_price'],
                    'option_price': 0.01,
                    'position_pnl': trade['entry_premium'] - 0.01,
                    'pnl_percent': 98.0  # Assume most premium captured
                }

        # Determine if assigned based on option type
        trade_type = trade.get('trade_type', 'put')
        if close_reason == 'expiration':
            if trade_type == 'put':
                assigned = final_tracking['stock_price'] < trade['strike_price']
            else:  # call
                assigned = final_tracking['stock_price'] > trade['strike_price']
        else:
            assigned = False

        closed_trade = trade.copy()
        closed_trade.update({
            'status': 'closed',
            'close_date': close_date,
            'close_reason': close_reason,
            'final_stock_price': final_tracking['stock_price'],
            'final_option_price': final_tracking['option_price'],
            'final_pnl': final_tracking['position_pnl'],
            'final_pnl_percent': final_tracking['pnl_percent'],
            'assigned': assigned,
            'days_held': (close_date - trade['entry_date']).days,
        })

        print(f"   🔒 POSITION CLOSED: {close_reason}")
        print(f"      Final P&L: ${closed_trade['final_pnl']:.2f} ({closed_trade['final_pnl_percent']:.1f}%)")
        print(f"      Assigned: {'Yes' if assigned else 'No'}")

        # Handle assignment for wheel strategy
        if assigned and trade.get('trade_type', 'put') == 'put':
            # Add stock position from put assignment
            self.add_stock_position(
                symbol=trade['symbol'],
                shares=100,  # Standard option contract
                cost_basis=trade['strike_price'],
                acquired_date=close_date
            )
        elif assigned and trade.get('trade_type') == 'call':
            # Remove stock position from call assignment
            realized_pnl = self.remove_stock_position(
                symbol=trade['symbol'],
                shares=100,
                call_away_price=trade['strike_price'],
                call_away_date=close_date
            )
            # Add stock P&L to option P&L
            closed_trade['stock_pnl'] = realized_pnl
            closed_trade['total_pnl'] = closed_trade['final_pnl'] + realized_pnl

        return closed_trade

    def run_monday_backtest(self, symbol: str, weeks: int = 12) -> Dict[str, Any]:
        """Run complete Monday-only backtest.

        Args:
            symbol: Stock symbol to test
            weeks: Number of weeks to test

        Returns:
            Complete backtest results
        """
        print(f"🔍 MONDAY-ONLY BACKTESTING: {symbol}")
        print("=" * 80)
        print(f"Strategy: Enter positions only on Mondays, target Friday expirations (5 DTE)")
        print(f"Period: Past {weeks} weeks")

        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(weeks=weeks)

        # Convert to datetime for consistency
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.min.time())

        print(f"Date Range: {start_date} to {end_date}")

        # Get all Mondays in range
        mondays = self.get_mondays_in_range(start_datetime, end_datetime)
        print(f"Trading Mondays: {len(mondays)}")

        all_trades = []
        active_positions = []

        # Process each Monday
        for i, monday in enumerate(mondays, 1):
            friday = self.get_following_friday(monday)

            print(f"\n{'='*20} WEEK {i} {'='*20}")
            print(f"Monday: {monday.strftime('%Y-%m-%d')}")
            print(f"Friday: {friday.strftime('%Y-%m-%d')}")

            # Check if we have stock position for covered calls
            trade_executed = False

            if self.has_stock_position(symbol):
                # We have stock - look for covered call opportunities
                print(f"   📈 STOCK POSITION DETECTED: {self.stock_positions[symbol]['shares']} shares")
                call_analysis = self.analyze_monday_call_options(symbol, monday, friday)

                if 'error' not in call_analysis:
                    # Execute covered call trade
                    trade = self.execute_monday_call_trade(call_analysis)

                    if trade:
                        all_trades.append(trade)
                        active_positions.append(trade)
                        trade_executed = True

                        # Track this position until Friday expiration
                        current_date = monday + timedelta(days=1)
                        daily_tracking = []

                        while current_date <= friday:
                            if current_date.weekday() < 5:
                                tracking = self.track_position_daily(trade, current_date)
                                if 'error' not in tracking:
                                    daily_tracking.append(tracking)
                            current_date += timedelta(days=1)

                        # Close position at expiration
                        closed_trade = self.close_position(trade, friday, 'expiration')

                        # Update the trade in our list
                        for j, t in enumerate(all_trades):
                            if (t['entry_date'] == trade['entry_date'] and
                                t['strike_price'] == trade['strike_price']):
                                all_trades[j] = closed_trade
                                break

                        active_positions = [p for p in active_positions if p != trade]
                        closed_trade['daily_tracking'] = daily_tracking

                else:
                    print(f"   ❌ NO COVERED CALL: {call_analysis['error']}")

            # WHEEL STRATEGY FIX: Only sell puts if NO stock position
            # If no covered call executed AND no stock position, look for put opportunities
            if not trade_executed and not self.has_stock_position(symbol):
                put_analysis = self.analyze_monday_options(symbol, monday, friday)

                if 'error' not in put_analysis:
                    # Execute put trade
                    trade = self.execute_monday_trade(put_analysis)

                    if trade:
                        all_trades.append(trade)
                        active_positions.append(trade)

                        # Track this position until Friday expiration
                        current_date = monday + timedelta(days=1)
                        daily_tracking = []

                        while current_date <= friday:
                            if current_date.weekday() < 5:
                                tracking = self.track_position_daily(trade, current_date)
                                if 'error' not in tracking:
                                    daily_tracking.append(tracking)
                            current_date += timedelta(days=1)

                        # Close position at expiration
                        closed_trade = self.close_position(trade, friday, 'expiration')

                        # Update the trade in our list
                        for j, t in enumerate(all_trades):
                            if (t['entry_date'] == trade['entry_date'] and
                                t['strike_price'] == trade['strike_price']):
                                all_trades[j] = closed_trade
                                break

                        active_positions = [p for p in active_positions if p != trade]
                        closed_trade['daily_tracking'] = daily_tracking

                else:
                    print(f"   ❌ NO PUT TRADE: {put_analysis['error']}")
            elif not trade_executed and self.has_stock_position(symbol):
                print(f"   ⚠️  PUT SELLING BLOCKED: Holding stock position (proper wheel strategy)")

        # Calculate overall results
        closed_trades = [t for t in all_trades if t.get('status') == 'closed']

        if closed_trades:
            total_premium = sum(t['entry_premium'] for t in closed_trades)
            total_pnl = sum(t['final_pnl'] for t in closed_trades)
            winning_trades = [t for t in closed_trades if t['final_pnl'] > 0]
            assigned_trades = [t for t in closed_trades if t.get('assigned', False)]

            results = {
                'symbol': symbol,
                'period_weeks': weeks,
                'total_mondays': len(mondays),
                'total_trades': len(closed_trades),
                'winning_trades': len(winning_trades),
                'win_rate': len(winning_trades) / len(closed_trades) * 100,
                'total_premium_collected': total_premium,
                'total_pnl': total_pnl,
                'average_pnl_per_trade': total_pnl / len(closed_trades),
                'pnl_percentage': (total_pnl / total_premium * 100) if total_premium > 0 else 0,
                'assignments': len(assigned_trades),
                'assignment_rate': len(assigned_trades) / len(closed_trades) * 100,
                'all_trades': all_trades,
                'start_date': start_date,
                'end_date': end_date
            }

            return results
        else:
            return {
                'error': 'No completed trades found',
                'symbol': symbol,
                'period_weeks': weeks,
                'total_mondays': len(mondays)
            }


def main():
    """Main backtesting execution."""
    print("🔍 MONDAY-ONLY OPTIONS WHEEL BACKTESTING")
    print("=" * 60)

    try:
        backtester = MondayOnlyBacktester()

        # Run backtest for UNH over past 12 weeks
        results = backtester.run_monday_backtest('UNH', weeks=12)

        if 'error' not in results:
            # Print summary results
            print(f"\n📊 BACKTEST RESULTS SUMMARY")
            print("=" * 50)
            print(f"Symbol: {results['symbol']}")
            print(f"Period: {results['period_weeks']} weeks")
            print(f"Total Mondays: {results['total_mondays']}")
            print(f"Total Trades: {results['total_trades']}")
            print(f"Win Rate: {results['win_rate']:.1f}%")
            print(f"Total Premium Collected: ${results['total_premium_collected']:.2f}")
            print(f"Total P&L: ${results['total_pnl']:.2f}")
            print(f"Average P&L per Trade: ${results['average_pnl_per_trade']:.2f}")
            print(f"Overall Return: {results['pnl_percentage']:.1f}%")
            print(f"Assignments: {results['assignments']} ({results['assignment_rate']:.1f}%)")

            return results
        else:
            print(f"❌ Backtest failed: {results['error']}")
            return None

    except Exception as e:
        print(f"❌ Error running backtest: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    results = main()