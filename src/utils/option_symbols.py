"""
Option symbol generation utilities for historical backtesting.

Generates proper option symbols based on OCC (Options Clearing Corporation) format:
UNDERLYING + YY + MM + DD + C/P + STRIKE*1000 (8 digits)

Example: AAPL250117C00185000
- AAPL: Underlying symbol  
- 25: Year (2025)
- 01: Month (January)
- 17: Day (17th)
- C: Call (P for Put)
- 00185000: Strike price $185.00 * 1000 with padding
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
import calendar
import structlog

logger = structlog.get_logger()


class OptionSymbolGenerator:
    """Generate option symbols for backtesting with historical data."""
    
    def __init__(self):
        self.weekly_symbols = ['AAPL', 'SPY', 'QQQ', 'IWM', 'UNH', 'MSFT', 'GOOGL', 'NVDA']
        
    def get_expiration_dates(self, start_date: datetime, max_dte: int = 60) -> List[datetime]:
        """Get all option expiration dates within the specified DTE range.
        
        Args:
            start_date: Starting date for calculations
            max_dte: Maximum days to expiration to include
            
        Returns:
            List of expiration dates (Fridays) within the DTE range
        """
        expirations = []
        current_date = start_date
        end_date = start_date + timedelta(days=max_dte)
        
        # Find all Fridays within the range
        while current_date <= end_date:
            if current_date.weekday() == 4:  # Friday = 4
                expirations.append(current_date)
            current_date += timedelta(days=1)
        
        return expirations
    
    def get_monthly_expiration(self, year: int, month: int) -> datetime:
        """Get the monthly expiration date (3rd Friday) for a given month.
        
        Args:
            year: Year
            month: Month (1-12)
            
        Returns:
            Monthly expiration date
        """
        # Find first day of month
        first_day = datetime(year, month, 1)
        
        # Find first Friday
        days_ahead = 4 - first_day.weekday()  # Friday = 4
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        
        first_friday = first_day + timedelta(days=days_ahead)
        
        # Third Friday is first Friday + 14 days
        third_friday = first_friday + timedelta(days=14)
        
        return third_friday
    
    def generate_strike_prices(self, underlying_price: float, underlying: str) -> List[float]:
        """Generate reasonable strike prices around the current stock price.
        
        Args:
            underlying_price: Current stock price
            underlying: Stock symbol for strike spacing rules
            
        Returns:
            List of strike prices to test
        """
        strikes = []
        
        # Determine strike spacing based on stock price
        if underlying_price < 50:
            spacing = 1.0  # $1 increments
            range_factor = 0.20  # ±20%
        elif underlying_price < 100:
            spacing = 2.5  # $2.50 increments
            range_factor = 0.15  # ±15%
        elif underlying_price < 200:
            spacing = 5.0  # $5 increments
            range_factor = 0.15  # ±15%
        else:
            spacing = 10.0  # $10 increments
            range_factor = 0.10  # ±10%
        
        # Generate strikes around current price
        min_strike = underlying_price * (1 - range_factor)
        max_strike = underlying_price * (1 + range_factor)
        
        current_strike = int(min_strike / spacing) * spacing
        while current_strike <= max_strike:
            if current_strike > 0:
                strikes.append(current_strike)
            current_strike += spacing
        
        return strikes
    
    def format_option_symbol(self, underlying: str, expiration: datetime, 
                           option_type: str, strike: float) -> str:
        """Format an option symbol according to OCC standards.
        
        Args:
            underlying: Stock symbol
            expiration: Expiration date
            option_type: 'PUT' or 'CALL'
            strike: Strike price
            
        Returns:
            Properly formatted option symbol
        """
        # Format: UNDERLYING + YY + MM + DD + C/P + STRIKE*1000 (8 digits)
        year_str = f"{expiration.year % 100:02d}"
        month_str = f"{expiration.month:02d}"
        day_str = f"{expiration.day:02d}"
        type_str = "C" if option_type.upper() == "CALL" else "P"
        
        # Strike as 8-digit integer (price * 1000, padded)
        strike_int = int(strike * 1000)
        strike_str = f"{strike_int:08d}"
        
        symbol = f"{underlying}{year_str}{month_str}{day_str}{type_str}{strike_str}"
        
        return symbol
    
    def generate_option_universe(self, underlying: str, date: datetime, 
                               underlying_price: float, max_dte: int = 45) -> List[Dict[str, Any]]:
        """Generate a universe of option symbols for a given date and stock.
        
        Args:
            underlying: Stock symbol
            date: Current trading date
            underlying_price: Current stock price
            max_dte: Maximum days to expiration
            
        Returns:
            List of option metadata dictionaries
        """
        options = []
        
        # Get expiration dates
        expirations = self.get_expiration_dates(date, max_dte)
        
        # Get strike prices  
        strikes = self.generate_strike_prices(underlying_price, underlying)
        
        # Generate all combinations
        for expiration in expirations:
            dte = (expiration - date).days
            if dte <= 0:  # Skip expired options
                continue
                
            for strike in strikes:
                for option_type in ['PUT', 'CALL']:
                    symbol = self.format_option_symbol(underlying, expiration, option_type, strike)
                    
                    options.append({
                        'symbol': symbol,
                        'underlying': underlying,
                        'expiration_date': expiration,
                        'option_type': option_type,
                        'strike_price': strike,
                        'dte': dte
                    })
        
        logger.debug("Generated option universe", 
                    underlying=underlying, 
                    date=date.date(),
                    total_options=len(options),
                    expirations=len(expirations),
                    strikes=len(strikes))
        
        return options
    
    def validate_symbol_format(self, symbol: str) -> bool:
        """Validate that an option symbol follows the correct format.
        
        Args:
            symbol: Option symbol to validate
            
        Returns:
            True if valid format
        """
        try:
            # Basic length check (varies by underlying length)
            if len(symbol) < 15:
                return False
            
            # Should end with 8 digits
            if not symbol[-8:].isdigit():
                return False
            
            # Should have C or P before the strike
            if symbol[-9] not in ['C', 'P']:
                return False
            
            # Date part should be 6 digits  
            date_part = symbol[-15:-9]
            if not date_part.isdigit() or len(date_part) != 6:
                return False
            
            return True
            
        except Exception:
            return False


# Global instance for easy access
option_symbol_generator = OptionSymbolGenerator()