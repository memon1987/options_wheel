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
        # Filter to only actual trade events, not validation/evaluation events
        # Using explicit event_type list to avoid duplicates from similar event names
        query = f"""
        SELECT
            timestamp_et,
            date_et,
            symbol,
            underlying,
            event_type,
            event,
            strategy,
            premium,
            contracts,
            limit_price
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND symbol IS NOT NULL
            AND symbol != ''
            AND event_type IN (
                'put_sale_executed',
                'call_sale_executed',
                'put_sale_executing',
                'call_sale_executing',
                'put_assignment',
                'call_assignment',
                'option_expired',
                'buy_to_close_executed'
            )
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
            raw_metrics = results[0]
            # Convert None to 0 for all numeric fields
            for key in raw_metrics:
                if raw_metrics[key] is None:
                    raw_metrics[key] = 0

            # Get premium data from trades_executed
            premium_data = self.get_premium_summary(days)
            total_premium = premium_data.get('total_premium', 0)
            trade_count = premium_data.get('trade_count', 0)
            avg_premium = total_premium / trade_count if trade_count > 0 else 0

            # Map to frontend expected field names
            return {
                'total_trades_30d': raw_metrics.get('total_trades', 0),
                'total_opportunities': raw_metrics.get('total_opportunities', 0),
                'total_scans': raw_metrics.get('total_scans', 0),
                'total_errors': raw_metrics.get('total_errors', 0),
                'trading_days': raw_metrics.get('trading_days', 0),
                'total_premium_30d': total_premium,
                'put_premium_30d': premium_data.get('put_premium', 0),
                'call_premium_30d': premium_data.get('call_premium', 0),
                'win_rate': None,  # TODO: Calculate from trade outcomes
                'avg_premium': avg_premium,
                'return_30d': None,  # TODO: Calculate from portfolio values
            }
        return {
            'total_trades_30d': 0,
            'total_opportunities': 0,
            'total_scans': 0,
            'total_errors': 0,
            'trading_days': 0,
            'total_premium_30d': 0,
            'put_premium_30d': 0,
            'call_premium_30d': 0,
            'win_rate': None,
            'avg_premium': 0,
            'return_30d': None,
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

    def get_premium_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get premium collection summary.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with premium metrics
        """
        query = f"""
        SELECT
            SUM(premium * contracts * 100) as total_premium,
            SUM(CASE WHEN strategy = 'sell_put' THEN premium * contracts * 100 ELSE 0 END) as put_premium,
            SUM(CASE WHEN strategy = 'sell_call' THEN premium * contracts * 100 ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND event_type LIKE '%executed%'
            AND premium IS NOT NULL
        """
        results = self._run_query(query)
        if results:
            row = results[0]
            return {
                'total_premium': row.get('total_premium') or 0,
                'put_premium': row.get('put_premium') or 0,
                'call_premium': row.get('call_premium') or 0,
                'trade_count': row.get('trade_count') or 0
            }
        return {'total_premium': 0, 'put_premium': 0, 'call_premium': 0, 'trade_count': 0}

    def get_premium_by_symbol(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get premium breakdown by symbol.

        Args:
            days: Number of days to analyze

        Returns:
            List of per-symbol premium data
        """
        query = f"""
        SELECT
            underlying as symbol,
            SUM(premium * contracts * 100) as total_premium,
            SUM(CASE WHEN strategy = 'sell_put' THEN premium * contracts * 100 ELSE 0 END) as put_premium,
            SUM(CASE WHEN strategy = 'sell_call' THEN premium * contracts * 100 ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND event_type LIKE '%executed%'
            AND premium IS NOT NULL
        GROUP BY underlying
        ORDER BY total_premium DESC
        """
        return self._run_query(query)

    def get_premium_by_day(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily premium totals for charting.

        Args:
            days: Number of days of history

        Returns:
            List of daily premium data
        """
        query = f"""
        SELECT
            date_et as date,
            SUM(premium * contracts * 100) as total_premium,
            SUM(CASE WHEN strategy = 'sell_put' THEN premium * contracts * 100 ELSE 0 END) as put_premium,
            SUM(CASE WHEN strategy = 'sell_call' THEN premium * contracts * 100 ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND event_type LIKE '%executed%'
            AND premium IS NOT NULL
        GROUP BY date_et
        ORDER BY date_et ASC
        """
        return self._run_query(query)

    def get_daily_stock_snapshots(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily unrealized P&L snapshots for stock holdings.

        Args:
            days: Number of days of history

        Returns:
            List of daily stock snapshot data
        """
        query = f"""
        SELECT
            DATE(timestamp, 'America/New_York') as date_et,
            jsonPayload.symbol as symbol,
            SAFE_CAST(jsonPayload.shares AS FLOAT64) as shares,
            SAFE_CAST(jsonPayload.cost_basis AS FLOAT64) as cost_basis,
            SAFE_CAST(jsonPayload.current_price AS FLOAT64) as current_price,
            SAFE_CAST(jsonPayload.unrealized_pl AS FLOAT64) as unrealized_pl,
            SAFE_CAST(jsonPayload.unrealized_pl_pct AS FLOAT64) as unrealized_pl_pct,
            SAFE_CAST(jsonPayload.days_held AS INT64) as days_held
        FROM `{PROJECT_ID}.options_wheel_logs.run_googleapis_com_stderr_*`
        WHERE jsonPayload.event_type = 'daily_stock_snapshot'
            AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY))
        ORDER BY timestamp DESC
        """
        return self._run_query(query)

    def get_position_updates(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get wheel cycle completion events from position updates.

        Args:
            days: Number of days to look back

        Returns:
            List of wheel cycle data with premium breakdown
        """
        query = f"""
        SELECT
            jsonPayload.symbol as symbol,
            SAFE_CAST(jsonPayload.put_premium_collected AS FLOAT64) as put_premium_collected,
            SAFE_CAST(jsonPayload.call_premium_collected AS FLOAT64) as call_premium_collected,
            SAFE_CAST(jsonPayload.total_premium AS FLOAT64) as total_premium,
            SAFE_CAST(jsonPayload.capital_gain AS FLOAT64) as capital_gain,
            SAFE_CAST(jsonPayload.total_return AS FLOAT64) as total_return,
            SAFE_CAST(jsonPayload.cycle_duration_days AS INT64) as duration_days,
            SAFE_CAST(jsonPayload.cost_basis AS FLOAT64) as cost_basis,
            SAFE_CAST(jsonPayload.exit_price AS FLOAT64) as exit_price,
            DATETIME(timestamp, 'America/New_York') as cycle_end,
            DATE(timestamp, 'America/New_York') as date_et
        FROM `{PROJECT_ID}.options_wheel_logs.run_googleapis_com_stderr_*`
        WHERE jsonPayload.event_type = 'wheel_cycle_complete'
            AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY))
        ORDER BY timestamp DESC
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
