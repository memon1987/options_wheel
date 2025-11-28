"""
BigQuery service for historical data queries.

Provides access to trading logs stored in BigQuery via the log sink.
"""

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import os
import logging

logger = logging.getLogger(__name__)

# Project and dataset configuration
# GCP_PROJECT is set in Cloud Run environment, fallback to GOOGLE_CLOUD_PROJECT
PROJECT_ID = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0607444019")
DATASET_ID = "options_wheel_logs"


class BigQueryService:
    """Service for querying BigQuery trading data."""

    def __init__(self):
        self.client = bigquery.Client(project=PROJECT_ID)
        self.dataset = f"{PROJECT_ID}.{DATASET_ID}"

    def _run_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute a query and return results as list of dicts."""
        try:
            job = self.client.query(query)
            results = job.result(timeout=60)  # 60 second timeout
            return [dict(row.items()) for row in results]
        except GoogleCloudError as e:
            logger.error(f"BigQuery error: {e}")
            raise Exception(f"Database query failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in BigQuery query: {e}")
            raise Exception(f"Database query failed: {str(e)}")

    def get_recent_trades(self, days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent trades from the trades_executed view.

        Args:
            days: Number of days to look back
            limit: Maximum number of trades to return

        Returns:
            List of trade records
        """
        query = f"""
        SELECT
            timestamp_et,
            symbol,
            strategy,
            strike_price,
            premium,
            contracts,
            success,
            order_id,
            underlying_symbol,
            expiration_date
        FROM `{self.dataset}.trades_executed`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY timestamp_et DESC
        LIMIT {limit}
        """
        return self._run_query(query)

    def get_daily_summary(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily operations summary.

        Args:
            days: Number of days to look back

        Returns:
            List of daily summary records
        """
        query = f"""
        SELECT
            DATE_ET,
            total_scans,
            total_opportunities,
            trades_executed,
            total_errors
        FROM `{self.dataset}.daily_operations_summary`
        WHERE DATE_ET >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY DATE_ET DESC
        """
        return self._run_query(query)

    def get_filtering_stats(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get filtering pipeline statistics.

        Args:
            days: Number of days to look back

        Returns:
            List of filtering stage stats
        """
        query = f"""
        SELECT
            DATE_ET,
            stage_name,
            symbols_passed,
            symbols_rejected,
            total_processed
        FROM `{self.dataset}.filtering_stage_summary`
        WHERE DATE_ET >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY DATE_ET DESC, stage_name
        """
        return self._run_query(query)

    def get_recent_errors(self, days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent errors.

        Args:
            days: Number of days to look back
            limit: Maximum number of errors to return

        Returns:
            List of error records
        """
        query = f"""
        SELECT
            timestamp_et,
            error_type,
            error_message,
            symbol,
            context
        FROM `{self.dataset}.errors_all`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY timestamp_et DESC
        LIMIT {limit}
        """
        return self._run_query(query)

    def get_position_updates(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get position state transitions (wheel cycles).

        Args:
            days: Number of days to look back

        Returns:
            List of position update records
        """
        query = f"""
        SELECT
            timestamp_et,
            symbol,
            event_type,
            position_status,
            strike_price,
            premium,
            contracts
        FROM `{self.dataset}.position_updates`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY timestamp_et DESC
        """
        return self._run_query(query)

    def get_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Calculate performance metrics over a period.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with performance metrics
        """
        query = f"""
        SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_trades,
            ROUND(AVG(premium), 2) as avg_premium,
            ROUND(SUM(premium * contracts * 100), 2) as total_premium_collected,
            COUNT(DISTINCT underlying_symbol) as unique_underlyings,
            COUNT(DISTINCT DATE(timestamp_et)) as trading_days
        FROM `{self.dataset}.trades_executed`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        results = self._run_query(query)
        if results:
            metrics = results[0]
            # Calculate win rate
            total = metrics.get('total_trades', 0)
            successful = metrics.get('successful_trades', 0)
            metrics['win_rate'] = round(successful / total * 100, 1) if total > 0 else 0
            return metrics
        return {}

    def get_pnl_by_symbol(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get P&L breakdown by underlying symbol.

        Args:
            days: Number of days to analyze

        Returns:
            List of per-symbol P&L records
        """
        query = f"""
        SELECT
            underlying_symbol,
            COUNT(*) as trade_count,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_trades,
            ROUND(SUM(premium * contracts * 100), 2) as total_premium,
            ROUND(AVG(premium), 2) as avg_premium
        FROM `{self.dataset}.trades_executed`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY underlying_symbol
        ORDER BY total_premium DESC
        """
        return self._run_query(query)

    def get_portfolio_value_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily portfolio value for charting.

        Note: This requires portfolio snapshots to be logged.
        Falls back to cumulative premium if not available.

        Args:
            days: Number of days of history

        Returns:
            List of daily portfolio values
        """
        # Try to get portfolio snapshots first
        query = f"""
        SELECT
            DATE(timestamp_et) as date,
            MAX(portfolio_value) as portfolio_value
        FROM `{self.dataset}.all_logs`
        WHERE event_type = 'account_status'
            AND DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY DATE(timestamp_et)
        ORDER BY date
        """
        try:
            results = self._run_query(query)
            if results:
                return results
        except Exception:
            pass

        # Fallback: calculate cumulative premium collected
        query = f"""
        SELECT
            DATE(timestamp_et) as date,
            SUM(premium * contracts * 100) as daily_premium,
            SUM(SUM(premium * contracts * 100)) OVER (ORDER BY DATE(timestamp_et)) as cumulative_premium
        FROM `{self.dataset}.trades_executed`
        WHERE DATE(timestamp_et) >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND success = TRUE
        GROUP BY DATE(timestamp_et)
        ORDER BY date
        """
        return self._run_query(query)


# Singleton instance
_bq_service: Optional[BigQueryService] = None


def get_bigquery_service() -> BigQueryService:
    """Get or create the BigQuery service singleton."""
    global _bq_service
    if _bq_service is None:
        _bq_service = BigQueryService()
    return _bq_service
