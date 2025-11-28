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
        Get recent trades from the trades_executed table.

        Args:
            days: Number of days to look back
            limit: Maximum number of trades to return

        Returns:
            List of trade records
        """
        query = f"""
        SELECT
            timestamp_et,
            date_et,
            symbol,
            event_type,
            event
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
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
            date_et,
            total_scans,
            total_opportunities,
            total_put_opportunities,
            total_call_opportunities,
            total_executions,
            total_errors,
            ROUND(avg_scan_duration_sec, 2) as avg_scan_duration_sec
        FROM `{self.dataset}.daily_operations_summary`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY date_et DESC
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
            date_et,
            stage_number,
            stage_name,
            total_events,
            unique_symbols,
            passed,
            blocked,
            found,
            not_found
        FROM `{self.dataset}.filtering_stage_summary`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND stage_name IS NOT NULL
        ORDER BY date_et DESC, stage_number
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
            date_et,
            event_type,
            event,
            symbol,
            severity,
            logger_name
        FROM `{self.dataset}.errors_all`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY timestamp_et DESC
        LIMIT {limit}
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
        # Get summary from daily_operations_summary
        query = f"""
        SELECT
            SUM(total_executions) as total_trades,
            SUM(total_opportunities) as total_opportunities,
            SUM(total_scans) as total_scans,
            SUM(total_errors) as total_errors,
            COUNT(DISTINCT date_et) as trading_days
        FROM `{self.dataset}.daily_operations_summary`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        results = self._run_query(query)
        if results:
            metrics = results[0]
            # Convert None to 0 for all numeric fields
            for key in metrics:
                if metrics[key] is None:
                    metrics[key] = 0
            return metrics
        return {
            'total_trades': 0,
            'total_opportunities': 0,
            'total_scans': 0,
            'total_errors': 0,
            'trading_days': 0
        }

    def get_pnl_by_symbol(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get trade count breakdown by symbol.

        Args:
            days: Number of days to analyze

        Returns:
            List of per-symbol trade counts
        """
        query = f"""
        SELECT
            symbol,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY symbol
        ORDER BY trade_count DESC
        LIMIT 20
        """
        return self._run_query(query)

    def get_portfolio_value_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily activity for charting.

        Args:
            days: Number of days of history

        Returns:
            List of daily activity stats
        """
        query = f"""
        SELECT
            date_et as date,
            total_executions as trades,
            total_opportunities as opportunities,
            total_errors as errors
        FROM `{self.dataset}.daily_operations_summary`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY date_et ASC
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
