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
        Get recent trades from the trades_executed table with order status.

        Args:
            days: Number of days to look back
            limit: Maximum number of trades to return

        Returns:
            List of trade records with order_status from polling job
        """
        # Query trades from the trades_executed view.
        # Order status join removed — order_status/filled_avg_price fields
        # don't exist in the current schema. poll_order_statuses() will
        # populate these going forward; the join can be re-added once data exists.
        query = f"""
        SELECT
            timestamp_et,
            date_et,
            symbol,
            underlying,
            event_type,
            strategy,
            premium,
            contracts,
            limit_price,
            order_id,
            strike_price,
            collateral_required,
            dte
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND symbol IS NOT NULL
            AND symbol != ''
            AND event_type IN (
                'put_sale_executed',
                'call_sale_executed',
                'early_close_executed',
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
            error_type,
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
        # Get scan/error counts from daily_operations_summary (fields that exist)
        ops_query = f"""
        SELECT
            SUM(total_executions) as total_trades,
            SUM(total_scans) as total_scans,
            SUM(total_errors) as total_errors,
            COUNT(DISTINCT date_et) as trading_days
        FROM `{self.dataset}.daily_operations_summary`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        # Get puts_sold/early_closes from trades_executed (not in daily_operations_summary)
        trade_counts_query = f"""
        SELECT
            COUNT(CASE WHEN event_type = 'put_sale_executed' THEN 1 END) as total_puts_sold,
            COUNT(CASE WHEN event_type IN ('early_close_executed', 'buy_to_close_executed') THEN 1 END) as total_early_closes
        FROM `{self.dataset}.trades_executed`
        WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        ops_results = self._run_query(ops_query)
        trade_counts = self._run_query(trade_counts_query)

        raw_metrics = ops_results[0] if ops_results else {}
        trade_metrics = trade_counts[0] if trade_counts else {}

        # Convert None to 0 for all numeric fields
        for d in (raw_metrics, trade_metrics):
            for key in d:
                if d[key] is None:
                    d[key] = 0

        # Get premium data from trades_executed
        premium_data = self.get_premium_summary(days)
        total_premium = premium_data.get('total_premium', 0)
        trade_count = premium_data.get('trade_count', 0)
        avg_premium = total_premium / trade_count if trade_count > 0 else 0

        return {
            'total_trades': raw_metrics.get('total_trades', 0),
            'total_puts_sold': trade_metrics.get('total_puts_sold', 0),
            'total_early_closes': trade_metrics.get('total_early_closes', 0),
            'total_scans': raw_metrics.get('total_scans', 0),
            'total_errors': raw_metrics.get('total_errors', 0),
            'trading_days': raw_metrics.get('trading_days', 0),
            'total_premium': total_premium,
            'put_premium_30d': premium_data.get('put_premium', 0),
            'call_premium_30d': premium_data.get('call_premium', 0),
            'win_rate': None,
            'avg_premium': avg_premium,
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
        # daily_stock_snapshot events are forward-only (not yet populated).
        # Return empty list gracefully if no events exist.
        try:
            query = f"""
            SELECT
                DATE(timestamp, 'America/New_York') as date_et,
                JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.symbol') as symbol,
                SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.premium') AS FLOAT64) as premium,
                SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.strike_price') AS FLOAT64) as strike_price,
                SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.unrealized_pl') AS FLOAT64) as unrealized_pl,
                SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.market_value') AS FLOAT64) as market_value,
                SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.profit_pct') AS FLOAT64) as profit_pct
            FROM `{PROJECT_ID}.options_wheel_logs.run_googleapis_com_stderr_*`
            WHERE JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_type') = 'daily_stock_snapshot'
                AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY))
                AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.symbol') IS NOT NULL
            ORDER BY timestamp DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("No daily_stock_snapshot events found — returning empty list")
            return []

    def get_position_updates(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get wheel cycle completion events from position updates.

        Args:
            days: Number of days to look back

        Returns:
            List of wheel cycle data with premium breakdown
        """
        # wheel_cycle_complete events are logged when a full wheel cycle
        # completes (put assigned → call assigned → shares called away).
        # Note: backfilled events ran locally and didn't reach BQ.
        # View will populate once live events flow from Cloud Run.
        try:
            query = f"""
            SELECT *
            FROM `{self.dataset}.wheel_cycles`
            ORDER BY logged_at DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("wheel_cycles view query failed — returning empty list")
            return []


# Singleton instance
_bq_service: Optional[BigQueryService] = None


def get_bigquery_service() -> BigQueryService:
    """Get or create the BigQuery service singleton."""
    global _bq_service
    if _bq_service is None:
        _bq_service = BigQueryService()
    return _bq_service
