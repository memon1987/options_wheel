"""
BigQuery service for historical data queries.

Provides access to trading data stored in dedicated BigQuery tables.

FC-012 (2026-04-24): trade-execution queries now read from Alpaca-sourced
``trades_with_outcomes`` view (raw in ``trades_from_activities``), portfolio
equity from ``equity_history_from_alpaca``, wheel cycles from
``wheel_cycles_from_activities`` view. Scan/error/execution queries are
unchanged — they remain on ``AnalyticsWriter``-written tables.
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

    # ================================================================
    # FC-012: Alpaca-sourced trade queries (trades_with_outcomes view)
    # ================================================================

    def get_recent_trades(self, days: int = 7, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent opening option trades with outcomes.

        Field names preserve the dashboard frontend contract: ``timestamp_et``,
        ``contracts``, ``event_type``. The frontend reads ``timestamp_et ??
        date_et`` and ``trade.contracts`` directly.
        """
        query = f"""
        SELECT
            transaction_time AS timestamp,
            DATETIME(transaction_time, 'America/New_York') AS timestamp_et,
            DATE(transaction_time, 'America/New_York') AS date_et,
            symbol,
            underlying,
            option_type,
            side,
            CASE
                WHEN option_type = 'put'  AND side IN ('sell_short','sell') THEN 'put_sale_executed'
                WHEN option_type = 'call' AND side IN ('sell_short','sell') THEN 'call_sale_executed'
                ELSE 'option_trade'
            END AS event_type,
            CASE
                WHEN option_type = 'put'  THEN 'cash_secured_put'
                WHEN option_type = 'call' THEN 'covered_call'
                ELSE NULL
            END AS strategy,
            'filled' AS status,
            qty,
            CAST(ABS(qty) AS INT64) AS contracts,
            price AS premium,
            premium_total AS total_premium,
            CAST(NULL AS FLOAT64) AS limit_price,
            price AS fill_price,
            order_id,
            CAST(NULL AS STRING) AS client_order_id,
            strike_price,
            CASE
                WHEN option_type = 'put'
                    THEN strike_price * ABS(qty) * 100
                ELSE NULL
            END AS collateral,
            dte_at_event AS dte,
            expiration,
            CASE
                WHEN option_type = 'put' AND strike_price IS NOT NULL AND strike_price > 0
                    THEN SAFE_DIVIDE(premium_total, strike_price * ABS(qty) * 100)
                ELSE NULL
            END AS roi,
            outcome,
            outcome_price,
            realized_pnl,
            transaction_time AS filled_at
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY transaction_time DESC
        LIMIT {limit}
        """
        return self._run_query(query)

    def get_pnl_by_symbol(self, days: int = 30) -> List[Dict[str, Any]]:
        """Trade count and P&L per underlying."""
        query = f"""
        SELECT
            underlying AS symbol,
            COUNT(*) AS trade_count,
            SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
            SUM(COALESCE(premium_total, 0)) AS total_premium
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY underlying
        ORDER BY trade_count DESC
        LIMIT 20
        """
        return self._run_query(query)

    def get_premium_summary(self, days: int = 30) -> Dict[str, Any]:
        """Premium collection summary."""
        query = f"""
        SELECT
            SUM(COALESCE(premium_total, 0)) AS total_premium,
            SUM(CASE WHEN option_type = 'put'  THEN COALESCE(premium_total, 0) ELSE 0 END) AS put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(premium_total, 0) ELSE 0 END) AS call_premium,
            COUNT(*) AS trade_count
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        results = self._run_query(query)
        if results:
            row = results[0]
            return {
                'total_premium': row.get('total_premium') or 0,
                'put_premium':   row.get('put_premium')   or 0,
                'call_premium':  row.get('call_premium')  or 0,
                'trade_count':   row.get('trade_count')   or 0,
            }
        return {'total_premium': 0, 'put_premium': 0, 'call_premium': 0, 'trade_count': 0}

    def get_premium_by_symbol(self, days: int = 30) -> List[Dict[str, Any]]:
        """Premium breakdown by underlying."""
        query = f"""
        SELECT
            underlying AS symbol,
            SUM(COALESCE(premium_total, 0)) AS total_premium,
            SUM(CASE WHEN option_type = 'put'  THEN COALESCE(premium_total, 0) ELSE 0 END) AS put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(premium_total, 0) ELSE 0 END) AS call_premium,
            COUNT(*) AS trade_count
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY underlying
        ORDER BY total_premium DESC
        """
        return self._run_query(query)

    def get_premium_by_day(self, days: int = 30) -> List[Dict[str, Any]]:
        """Daily premium totals for charting."""
        query = f"""
        SELECT
            DATE(transaction_time, 'America/New_York') AS date,
            SUM(COALESCE(premium_total, 0)) AS total_premium,
            SUM(CASE WHEN option_type = 'put'  THEN COALESCE(premium_total, 0) ELSE 0 END) AS put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(premium_total, 0) ELSE 0 END) AS call_premium,
            COUNT(*) AS trade_count
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        GROUP BY date
        ORDER BY date ASC
        """
        return self._run_query(query)

    def get_position_updates(self, days: int = 30) -> List[Dict[str, Any]]:
        """Completed wheel cycles (from Alpaca-reconstructed view)."""
        try:
            query = f"""
            SELECT
                put_assignment_time AS timestamp,
                underlying AS symbol,
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
            FROM `{self.dataset}.wheel_cycles_from_activities`
            WHERE assignment_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            ORDER BY assignment_date DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("wheel_cycles_from_activities query failed — returning empty list")
            return []

    def get_portfolio_value_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """Portfolio equity history from Alpaca's portfolio/history endpoint.

        Note: ``cash`` and ``buying_power`` are not retained historically by
        Alpaca — they return ``None``. Dashboard consumers that need current
        cash/buying_power should call ``/v2/account`` live instead.
        """
        try:
            query = f"""
            SELECT
                date,
                equity AS portfolio_value,
                CAST(NULL AS FLOAT64) AS cash,
                CAST(NULL AS FLOAT64) AS buying_power
            FROM `{self.dataset}.equity_history_from_alpaca`
            WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            ORDER BY date ASC
            """
            return self._run_query(query)
        except Exception:
            logger.info("equity_history_from_alpaca query failed — returning empty list")
            return []

    # ================================================================
    # Bot-sourced queries — unchanged (no Alpaca equivalent)
    # ================================================================

    def get_daily_summary(self, days: int = 30) -> List[Dict[str, Any]]:
        """Daily operations summary from executions table."""
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
        """Filtering pipeline statistics from scans table."""
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
        """Recent errors from errors table."""
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
        """Hybrid: scan/error counts from executions, trade counts from Alpaca view."""
        ops_query = f"""
        SELECT
            SUM(trades_executed) as total_trades,
            SUM(scan_count) as total_scans,
            SUM(errors) as total_errors,
            COUNT(DISTINCT DATE(timestamp, 'America/New_York')) as trading_days
        FROM `{self.dataset}.executions`
        WHERE DATE(timestamp, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        # Trade counts now come from the Alpaca-sourced view
        trade_counts_query = f"""
        SELECT
            COUNTIF(option_type = 'put') AS total_puts_sold,
            COUNTIF(outcome = 'early_close') AS total_early_closes
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        ops_results = self._run_query(ops_query)
        trade_counts = self._run_query(trade_counts_query)

        raw_metrics = ops_results[0] if ops_results else {}
        trade_metrics = trade_counts[0] if trade_counts else {}

        for d in (raw_metrics, trade_metrics):
            for key in list(d.keys()):
                if d[key] is None:
                    d[key] = 0

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

    def get_call_rolls(self, days: int = 30) -> List[Dict[str, Any]]:
        """Call roll history (FC-006) — out of FC-012 scope, unchanged."""
        try:
            query = f"""
            SELECT
                timestamp_et,
                symbol,
                underlying,
                event_type,
                current_strike,
                new_strike,
                old_strike,
                net_debit,
                net_credit,
                net_premium,
                contracts,
                filled_qty,
                roll_count,
                skip_reason,
                success,
                next_earnings_date,
                days_to_earnings,
                btc_order_id,
                stc_order_id
            FROM `{self.dataset}.call_rolls`
            WHERE date_et >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            ORDER BY timestamp_et DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("call_rolls query failed — returning empty list")
            return []


# Singleton instance
_bq_service: Optional[BigQueryService] = None


def get_bigquery_service() -> BigQueryService:
    """Get or create the BigQuery service singleton."""
    global _bq_service
    if _bq_service is None:
        _bq_service = BigQueryService()
    return _bq_service
