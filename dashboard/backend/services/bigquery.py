"""
BigQuery service for historical data queries.

Provides access to trading data stored in dedicated BigQuery tables.
"""

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError
from typing import Dict, Any, List, Optional
import os
import logging

logger = logging.getLogger(__name__)

# Project and dataset configuration
# GCP_PROJECT is set in Cloud Run environment, fallback to GOOGLE_CLOUD_PROJECT
PROJECT_ID = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0607444019")
DATASET_ID = "options_wheel"


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
        Get recent trades from the trades table.

        Args:
            days: Number of days to look back
            limit: Maximum number of trades to return

        Returns:
            List of trade records
        """
        query = f"""
        SELECT
            timestamp,
            DATE(timestamp, 'America/New_York') as date_et,
            symbol,
            underlying,
            option_type,
            side,
            strategy,
            status,
            qty,
            premium,
            total_premium,
            limit_price,
            fill_price,
            order_id,
            client_order_id,
            strike_price,
            collateral,
            dte,
            expiration,
            roi,
            outcome,
            outcome_price,
            realized_pnl,
            filled_at
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND symbol IS NOT NULL
            AND symbol != ''
        ORDER BY timestamp DESC
        LIMIT {limit}
        """
        return self._run_query(query)

    def get_daily_summary(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily operations summary aggregated from executions table.

        Args:
            days: Number of days to look back

        Returns:
            List of daily summary records
        """
        query = f"""
        SELECT
            DATE(timestamp, 'America/New_York') as date_et,
            SUM(scan_count) as total_scans,
            SUM(opportunities_found) as total_opportunities,
            SUM(trades_executed) as total_executions,
            SUM(errors) as total_errors,
            ROUND(AVG(duration_seconds), 2) as avg_scan_duration_sec,
            SUM(trades_failed) as total_trades_failed
        FROM `{self.dataset}.executions`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY date_et
        ORDER BY date_et DESC
        """
        return self._run_query(query)

    def get_filtering_stats(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get filtering pipeline statistics from scans table.

        Args:
            days: Number of days to look back

        Returns:
            List of filtering stage stats
        """
        query = f"""
        SELECT
            DATE(timestamp, 'America/New_York') as date_et,
            stage,
            result,
            COUNT(*) as total_events,
            COUNT(DISTINCT symbol) as unique_symbols,
            COUNTIF(result = 'pass') as passed,
            COUNTIF(result = 'fail') as blocked,
            reason,
            AVG(premium) as avg_premium,
            AVG(delta) as avg_delta,
            AVG(dte) as avg_dte
        FROM `{self.dataset}.scans`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND stage IS NOT NULL
        GROUP BY date_et, stage, result, reason
        ORDER BY date_et DESC, stage
        """
        return self._run_query(query)

    def get_recent_errors(self, days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent errors from the errors table.

        Args:
            days: Number of days to look back
            limit: Maximum number of errors to return

        Returns:
            List of error records
        """
        query = f"""
        SELECT
            timestamp,
            DATE(timestamp, 'America/New_York') as date_et,
            event_type,
            error_type,
            error_message,
            symbol,
            underlying,
            component,
            recoverable,
            request_id
        FROM `{self.dataset}.errors`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY timestamp DESC
        LIMIT {limit}
        """
        return self._run_query(query)

    def get_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Calculate performance metrics over a period from trades + executions.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with performance metrics
        """
        # Aggregate from executions table
        ops_query = f"""
        SELECT
            SUM(trades_executed) as total_trades,
            SUM(scan_count) as total_scans,
            SUM(errors) as total_errors,
            COUNT(DISTINCT DATE(timestamp, 'America/New_York')) as trading_days
        FROM `{self.dataset}.executions`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        # Count by strategy from trades table
        trade_counts_query = f"""
        SELECT
            COUNT(CASE WHEN option_type = 'put' AND side = 'sell' THEN 1 END) as total_puts_sold,
            COUNT(CASE WHEN side = 'buy' THEN 1 END) as total_early_closes
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        ops_results = self._run_query(ops_query)
        trade_counts = self._run_query(trade_counts_query)

        raw_metrics = ops_results[0] if ops_results else {}
        trade_metrics = trade_counts[0] if trade_counts else {}

        # Convert None to 0 for all numeric fields
        for d in (raw_metrics, trade_metrics):
            for key in list(d.keys()):
                if d[key] is None:
                    d[key] = 0

        # Get premium data from trades table
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
        Get trade count and P&L breakdown by symbol.

        Args:
            days: Number of days to analyze

        Returns:
            List of per-symbol trade counts and realized P&L
        """
        query = f"""
        SELECT
            underlying as symbol,
            COUNT(*) as trade_count,
            SUM(COALESCE(realized_pnl, 0)) as realized_pnl,
            SUM(COALESCE(total_premium, 0)) as total_premium
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY underlying
        ORDER BY trade_count DESC
        LIMIT 20
        """
        return self._run_query(query)

    def get_portfolio_value_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get portfolio value history from position_snapshots.

        Args:
            days: Number of days of history

        Returns:
            List of daily portfolio value records
        """
        query = f"""
        SELECT
            date,
            portfolio_value,
            cash,
            buying_power
        FROM `{self.dataset}.position_snapshots`
        WHERE symbol = 'PORTFOLIO'
            AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY date ASC
        """
        return self._run_query(query)

    def get_premium_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get premium collection summary from trades table.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with premium metrics
        """
        query = f"""
        SELECT
            SUM(COALESCE(total_premium, 0)) as total_premium,
            SUM(CASE WHEN option_type = 'put' THEN COALESCE(total_premium, 0) ELSE 0 END) as put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(total_premium, 0) ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND side = 'sell'
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
            SUM(COALESCE(total_premium, 0)) as total_premium,
            SUM(CASE WHEN option_type = 'put' THEN COALESCE(total_premium, 0) ELSE 0 END) as put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(total_premium, 0) ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND side = 'sell'
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
            DATE(timestamp, 'America/New_York') as date,
            SUM(COALESCE(total_premium, 0)) as total_premium,
            SUM(CASE WHEN option_type = 'put' THEN COALESCE(total_premium, 0) ELSE 0 END) as put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(total_premium, 0) ELSE 0 END) as call_premium,
            COUNT(*) as trade_count
        FROM `{self.dataset}.trades`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND side = 'sell'
            AND premium IS NOT NULL
        GROUP BY date
        ORDER BY date ASC
        """
        return self._run_query(query)

    def get_daily_stock_snapshots(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily position snapshots for stock holdings.

        Args:
            days: Number of days of history

        Returns:
            List of daily stock snapshot data
        """
        try:
            query = f"""
            SELECT
                date,
                symbol,
                shares,
                contracts,
                cost_basis,
                market_value,
                unrealized_pnl,
                current_price
            FROM `{self.dataset}.position_snapshots`
            WHERE asset_class != 'account'
                AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                AND symbol IS NOT NULL
            ORDER BY date DESC, symbol
            """
            return self._run_query(query)
        except Exception:
            logger.info("No position_snapshots data found — returning empty list")
            return []

    def get_position_updates(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get completed wheel cycles.

        Args:
            days: Number of days to look back

        Returns:
            List of wheel cycle data with premium breakdown
        """
        try:
            query = f"""
            SELECT
                timestamp,
                symbol,
                put_date,
                put_strike,
                put_premium,
                assignment_date,
                call_date,
                call_strike,
                call_premium,
                capital_gain,
                total_premium,
                total_return,
                duration_days,
                shares
            FROM `{self.dataset}.wheel_cycles`
            WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            ORDER BY timestamp DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("wheel_cycles query failed — returning empty list")
            return []


# Singleton instance
_bq_service: Optional[BigQueryService] = None


def get_bigquery_service() -> BigQueryService:
    """Get or create the BigQuery service singleton."""
    global _bq_service
    if _bq_service is None:
        _bq_service = BigQueryService()
    return _bq_service
