"""Overnight gap detection and risk management for options wheel strategy."""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import structlog

from ..utils.config import Config
from ..utils.logging_events import log_risk_event, log_error_event
from ..api.alpaca_client import AlpacaClient

logger = structlog.get_logger(__name__)


class GapDetector:
    """Detects and analyzes overnight gaps for risk management."""

    def __init__(self, config: Config, alpaca_client: AlpacaClient):
        """Initialize gap detector.

        Args:
            config: Configuration instance
            alpaca_client: Alpaca client for data
        """
        self.config = config
        self.alpaca = alpaca_client
        self._gap_cache = {}

    def analyze_gap_risk(self, symbol: str, analysis_date: datetime) -> Dict:
        """Analyze gap risk for a stock on a specific date.

        Args:
            symbol: Stock symbol to analyze
            analysis_date: Date to analyze (typically current/trade date)

        Returns:
            Dict with gap analysis results
        """
        if not self.config.enable_gap_detection:
            return {'gap_risk_score': 0.0, 'suitable_for_trading': True}

        try:
            # Get historical data for gap analysis
            lookback_date = analysis_date - timedelta(days=self.config.gap_lookback_days + 10)
            df = self.alpaca.get_stock_bars(symbol, days=self.config.gap_lookback_days + 20)

            if df.empty:
                logger.warning("No data for gap analysis",
                              event_category="data",
                              event_type="no_gap_analysis_data",
                              symbol=symbol)
                return {'gap_risk_score': 1.0, 'suitable_for_trading': False}

            # Calculate overnight gaps
            gaps_analysis = self._calculate_overnight_gaps(df)

            # Calculate historical volatility
            volatility = self._calculate_historical_volatility(df)

            # Check current day gap (if market has opened)
            current_gap = self._detect_current_gap(symbol, analysis_date, df)

            # Combine metrics for risk score
            risk_score = self._calculate_gap_risk_score(
                gaps_analysis, volatility, current_gap
            )

            # Determine if suitable for trading
            suitable = self._is_suitable_for_trading(gaps_analysis, volatility, current_gap)

            return {
                'gap_risk_score': risk_score,
                'suitable_for_trading': suitable,
                'historical_gaps': gaps_analysis,
                'historical_volatility': volatility,
                'current_gap': current_gap,
                'analysis_date': analysis_date
            }

        except Exception as e:
            logger.error("Failed to analyze gap risk",
                        event_category="error",
                        event_type="gap_risk_analysis_error",
                        symbol=symbol,
                        error=str(e))
            return {'gap_risk_score': 1.0, 'suitable_for_trading': False}

    def _calculate_overnight_gaps(self, df: pd.DataFrame) -> Dict:
        """Calculate overnight gap statistics from historical data.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dict with gap statistics
        """
        # Calculate overnight gaps (open vs previous close)
        df = df.copy()
        df['prev_close'] = df['close'].shift(1)
        df['overnight_gap'] = (df['open'] - df['prev_close']) / df['prev_close']
        df['gap_percent'] = df['overnight_gap'] * 100

        # Remove first row (no previous close)
        gaps = df['overnight_gap'].dropna()
        gap_percentages = df['gap_percent'].dropna()

        # Calculate statistics
        total_days = len(gaps)
        if total_days == 0:
            return {'total_days': 0, 'gap_frequency': 0, 'avg_gap_size': 0}

        # Count significant gaps using quality control threshold
        quality_threshold = self.config.quality_gap_threshold
        significant_gaps = np.abs(gap_percentages) > quality_threshold
        gap_frequency = significant_gaps.sum() / total_days

        # Large gaps (>5%)
        large_gaps = np.abs(gap_percentages) > 5.0
        large_gap_frequency = large_gaps.sum() / total_days

        # Gap size statistics
        avg_gap_size = np.abs(gap_percentages).mean()
        max_gap_size = np.abs(gap_percentages).max()
        gap_volatility = gap_percentages.std()

        # Up vs down gaps using quality control threshold
        up_gaps = (gap_percentages > quality_threshold).sum()
        down_gaps = (gap_percentages < -quality_threshold).sum()

        return {
            'total_days': total_days,
            'gap_frequency': gap_frequency,
            'large_gap_frequency': large_gap_frequency,
            'avg_gap_size': avg_gap_size,
            'max_gap_size': max_gap_size,
            'gap_volatility': gap_volatility,
            'up_gaps': up_gaps,
            'down_gaps': down_gaps,
            'gap_direction_bias': (up_gaps - down_gaps) / max(1, up_gaps + down_gaps)
        }

    def _calculate_historical_volatility(self, df: pd.DataFrame) -> float:
        """Calculate annualized historical volatility.

        Args:
            df: DataFrame with price data

        Returns:
            Annualized volatility
        """
        if len(df) < 10:
            return 0.0

        # Calculate daily returns
        returns = df['close'].pct_change().dropna()

        # Annualized volatility
        volatility = returns.std() * np.sqrt(252)
        return volatility

    def _detect_current_gap(self, symbol: str, date: datetime, df: pd.DataFrame) -> Dict:
        """Detect gap for current trading day.

        Args:
            symbol: Stock symbol
            date: Current date
            df: Historical price data

        Returns:
            Dict with current gap information
        """
        try:
            # Convert date to timezone-aware if needed
            if date.tzinfo is None:
                import pytz
                date = pytz.UTC.localize(date)

            # Get today's data if available
            target_date = date.date()

            # Create boolean mask with same index as df
            df_dates = pd.Series([idx.date() for idx in df.index], index=df.index)

            if target_date in df_dates.values:
                # Use .loc with boolean indexer that has matching index
                today_data = df.loc[df_dates == target_date].iloc[0]

                # Get previous trading day close
                previous_data = df.loc[df_dates < target_date].iloc[-1]

                gap_percent = ((today_data['open'] - previous_data['close']) /
                              previous_data['close']) * 100

                return {
                    'has_gap': abs(gap_percent) > self.config.premarket_gap_threshold,
                    'gap_percent': gap_percent,
                    'gap_direction': 'up' if gap_percent > 0 else 'down',
                    'previous_close': previous_data['close'],
                    'current_open': today_data['open']
                }
            else:
                return {'has_gap': False, 'gap_percent': 0.0}

        except Exception as e:
            # Conservative fallback: assume large gap to block trading on error
            # This prevents trading when we can't verify gap safety
            log_error_event(
                logger,
                error_type="current_gap_detection_failed",
                error_message=str(e),
                component="gap_detector",
                recoverable=True,
                symbol=symbol,
                fallback_behavior="blocking_assumed_large_gap"
            )
            return {
                'has_gap': True,  # Assume gap exists (conservative)
                'gap_percent': 999.0,  # Large value to trigger blocking
                'detection_failed': True,
                'error': str(e)
            }

    def _calculate_gap_risk_score(self, gaps_analysis: Dict, volatility: float,
                                 current_gap: Dict) -> float:
        """Calculate overall gap risk score (0.0 = low risk, 1.0 = high risk).

        Args:
            gaps_analysis: Historical gap analysis
            volatility: Historical volatility
            current_gap: Current day gap info

        Returns:
            Risk score between 0.0 and 1.0
        """
        score = 0.0

        # Historical gap frequency (0-0.4 points)
        gap_freq = gaps_analysis.get('gap_frequency', 0)
        score += min(0.4, gap_freq * 2.67)  # 15% frequency = 0.4 points

        # Historical volatility (0-0.3 points)
        vol_score = min(0.3, volatility / self.config.max_historical_vol * 0.3)
        score += vol_score

        # Current gap penalty (0-0.3 points)
        if current_gap.get('has_gap', False):
            gap_size = abs(current_gap.get('gap_percent', 0))
            current_score = min(0.3, gap_size / 10.0 * 0.3)  # 10% gap = 0.3 points
            score += current_score

        return min(1.0, score)

    def _is_suitable_for_trading(self, gaps_analysis: Dict, volatility: float,
                                current_gap: Dict) -> bool:
        """Determine if stock is suitable for new positions.

        Args:
            gaps_analysis: Historical gap analysis
            volatility: Historical volatility
            current_gap: Current day gap info

        Returns:
            True if suitable for trading
        """
        # Check historical gap frequency
        gap_freq = gaps_analysis.get('gap_frequency', 0)
        if gap_freq > self.config.max_gap_frequency:
            logger.info("Stock rejected due to high gap frequency",
                       event_category="filtering",
                       event_type="rejected_high_gap_frequency",
                       frequency=gap_freq,
                       limit=self.config.max_gap_frequency)
            return False

        # Check historical volatility
        if volatility > self.config.max_historical_vol:
            logger.info("Stock rejected due to high volatility",
                       event_category="filtering",
                       event_type="rejected_high_volatility",
                       volatility=volatility,
                       limit=self.config.max_historical_vol)
            return False

        # Check current gap
        if current_gap.get('has_gap', False):
            gap_size = abs(current_gap.get('gap_percent', 0))
            if gap_size > self.config.max_overnight_gap_percent:
                # Check if this was due to detection failure (fallback behavior)
                if current_gap.get('detection_failed', False):
                    log_risk_event(
                        logger,
                        event_type="stock_blocked_gap_detection_failure",
                        symbol=current_gap.get('symbol', 'unknown'),
                        risk_type="gap_detection_error",
                        action_taken="stock_excluded_conservative_fallback",
                        gap_percent=gap_size,
                        threshold=self.config.max_overnight_gap_percent,
                        detection_error=current_gap.get('error', 'unknown')
                    )
                else:
                    logger.info("Stock rejected due to current large gap",
                               event_category="filtering",
                               event_type="rejected_large_gap",
                               gap=gap_size,
                               limit=self.config.max_overnight_gap_percent)
                return False

        return True

    def should_close_position_due_to_gap(self, position: Dict, current_price: float,
                                        previous_close: float) -> bool:
        """Determine if position should be closed due to overnight gap.

        Args:
            position: Option position dict
            current_price: Current stock price
            previous_close: Previous day's closing price

        Returns:
            True if position should be closed
        """
        if not self.config.enable_gap_detection:
            return False

        # Calculate overnight gap
        gap_percent = abs((current_price - previous_close) / previous_close * 100)

        if gap_percent > self.config.max_overnight_gap_percent:
            logger.warning("Large overnight gap detected",
                          event_category="risk",
                          event_type="large_overnight_gap",
                          gap_percent=gap_percent,
                          threshold=self.config.max_overnight_gap_percent,
                          position=position['symbol'])
            return True

        return False

    def get_market_open_delay(self, symbol: str, date: datetime) -> int:
        """Get recommended delay after market open for gap situations.

        Args:
            symbol: Stock symbol
            date: Trading date

        Returns:
            Minutes to delay after market open
        """
        if not self.config.enable_gap_detection:
            return 0

        gap_analysis = self.analyze_gap_risk(symbol, date)
        current_gap = gap_analysis.get('current_gap', {})

        if current_gap.get('has_gap', False):
            return self.config.market_open_delay_minutes

        return 0

    def filter_stocks_by_gap_risk(self, symbols: List[str],
                                 analysis_date: datetime) -> List[str]:
        """Filter stock list by gap risk criteria.

        Args:
            symbols: List of stock symbols to filter
            analysis_date: Date for analysis

        Returns:
            Filtered list of symbols suitable for trading
        """
        if not self.config.enable_gap_detection:
            return symbols

        suitable_symbols = []
        rejected_symbols = []

        for symbol in symbols:
            gap_analysis = self.analyze_gap_risk(symbol, analysis_date)
            if gap_analysis.get('suitable_for_trading', False):
                suitable_symbols.append(symbol)
                logger.info("Stock passed gap risk filter",
                           event_category="filtering",
                           event_type="stock_passed_gap_filter",
                           symbol=symbol,
                           gap_risk_score=round(gap_analysis.get('gap_risk_score', 0), 3),
                           gap_frequency=round(gap_analysis.get('historical_gaps', {}).get('gap_frequency', 0), 3),
                           volatility=round(gap_analysis.get('historical_volatility', 0), 3))
            else:
                rejected_symbols.append(symbol)
                # Enhanced risk event logging
                log_risk_event(
                    logger,
                    event_type="stock_filtered_by_gap_risk",
                    symbol=symbol,
                    risk_type="gap_risk",
                    action_taken="stock_excluded",
                    gap_risk_score=gap_analysis.get('gap_risk_score', 1.0),
                    gap_frequency=gap_analysis.get('historical_gaps', {}).get('gap_frequency', 0),
                    historical_volatility=gap_analysis.get('historical_volatility', 0)
                )

        logger.info("STAGE 2 COMPLETE: Gap risk analysis",
                   event_category="filtering",
                   event_type="stage_2_complete",
                   input_symbols=len(symbols),
                   passed=len(suitable_symbols),
                   rejected=len(rejected_symbols),
                   passed_symbols=", ".join(suitable_symbols),
                   rejected_symbols=", ".join(rejected_symbols))

        return suitable_symbols

    def can_execute_trade(self, symbol: str, execution_time: datetime) -> Dict:
        """Check if trade can be executed based on current gap conditions.

        Args:
            symbol: Stock symbol for trade
            execution_time: Intended execution time

        Returns:
            Dict with execution decision and gap information
        """
        if not self.config.enable_gap_detection:
            return {
                'can_execute': True,
                'reason': 'gap_detection_disabled',
                'current_gap_percent': 0.0
            }

        try:
            # Get current market data
            current_quote = self.alpaca.get_stock_quote(symbol)
            current_price = (current_quote['bid'] + current_quote['ask']) / 2

            # Get previous trading day close
            previous_close = self._get_previous_close(symbol, execution_time)
            if previous_close is None:
                logger.warning("Cannot determine previous close for gap check",
                              event_category="data",
                              event_type="no_previous_close",
                              symbol=symbol)
                return {
                    'can_execute': False,
                    'reason': 'no_previous_close_data',
                    'current_gap_percent': 0.0
                }

            # Calculate overnight gap
            gap_percent = ((current_price - previous_close) / previous_close) * 100

            # Check against execution threshold
            if abs(gap_percent) > self.config.execution_gap_threshold:
                # Enhanced risk event logging for blocked trade
                log_risk_event(
                    logger,
                    event_type="execution_gap_exceeded",
                    symbol=symbol,
                    risk_type="gap_risk",
                    action_taken="trade_blocked",
                    gap_percent=gap_percent,
                    threshold=self.config.execution_gap_threshold,
                    previous_close=previous_close,
                    current_price=current_price
                )

                return {
                    'can_execute': False,
                    'reason': 'execution_gap_exceeded',
                    'current_gap_percent': gap_percent,
                    'threshold': self.config.execution_gap_threshold,
                    'previous_close': previous_close,
                    'current_price': current_price
                }

            return {
                'can_execute': True,
                'reason': 'gap_within_limits',
                'current_gap_percent': gap_percent,
                'threshold': self.config.execution_gap_threshold,
                'previous_close': previous_close,
                'current_price': current_price
            }

        except Exception as e:
            # Enhanced error logging
            log_error_event(
                logger,
                error_type="gap_check_error",
                error_message=str(e),
                component="gap_detector",
                recoverable=True,
                symbol=symbol
            )
            return {
                'can_execute': False,
                'reason': 'gap_check_error',
                'current_gap_percent': 0.0,
                'error': str(e)
            }

    def _get_previous_close(self, symbol: str, current_time: datetime) -> Optional[float]:
        """Get previous trading day's closing price.

        Args:
            symbol: Stock symbol
            current_time: Current time for reference

        Returns:
            Previous close price or None
        """
        try:
            # Look back to find previous trading day
            lookback_date = current_time - timedelta(days=3)  # Look back 3 days to ensure we get data

            # Get recent stock data
            df = self.alpaca.get_stock_bars(symbol, days=5)
            if df.empty:
                return None

            # Ensure current_time is timezone-aware for comparison with df.index
            if current_time.tzinfo is None:
                import pytz
                current_time = pytz.UTC.localize(current_time)

            # Find the most recent close before current time
            recent_data = df[df.index < current_time]
            if recent_data.empty:
                return None

            return recent_data['close'].iloc[-1]

        except Exception as e:
            logger.error("Failed to get previous close",
                        event_category="error",
                        event_type="previous_close_error",
                        symbol=symbol,
                        error=str(e))
            return None

    def get_execution_delay_recommendation(self, symbol: str, current_time: datetime) -> Dict:
        """Get recommendation for delaying trade execution due to gaps.

        Args:
            symbol: Stock symbol
            current_time: Current time

        Returns:
            Dict with delay recommendation
        """
        gap_check = self.can_execute_trade(symbol, current_time)

        if gap_check['can_execute']:
            return {
                'delay_recommended': False,
                'delay_minutes': 0,
                'reason': 'no_gap_detected'
            }

        # If gap detected, recommend waiting
        gap_percent = abs(gap_check.get('current_gap_percent', 0))

        if gap_percent <= 3.0:
            # Small gap - wait standard delay
            delay_minutes = self.config.market_open_delay_minutes
        elif gap_percent <= 5.0:
            # Medium gap - wait longer
            delay_minutes = self.config.market_open_delay_minutes * 2
        else:
            # Large gap - wait much longer or skip day
            delay_minutes = self.config.market_open_delay_minutes * 4

        return {
            'delay_recommended': True,
            'delay_minutes': delay_minutes,
            'reason': f'gap_detected_{gap_percent:.1f}percent',
            'gap_percent': gap_percent,
            'original_delay': self.config.market_open_delay_minutes
        }