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

    # ================================================================
    # FC-018: wheel-centric dashboard data sources
    # ================================================================

    def get_per_symbol_scorecard(self, days: int = 365) -> List[Dict[str, Any]]:
        """Per-underlying summary for the FC-018 Overview matrix.

        Joins the FC-018 scorecard view with vs-buy-and-hold deltas. Returns
        one row per underlying with cycle counts, premium, realized P&L,
        current ACB, and wheel-vs-buy-and-hold comparison.
        """
        try:
            query = f"""
            SELECT
                s.underlying AS symbol,
                s.trade_count,
                s.cycles_completed,
                s.total_premium,
                s.put_premium,
                s.call_premium,
                s.realized_pnl,
                s.open_count,
                s.put_assignment_count,
                s.called_away_count,
                s.early_close_count,
                s.expiration_count,
                s.cycle_capital_gain,
                s.avg_cycle_days,
                s.first_trade_time,
                s.last_trade_time,
                s.current_shares,
                s.current_acb_per_share,
                s.current_cumulative_net_premium,
                bh.price_now,
                bh.bh_dollar_pnl,
                bh.wheel_minus_bh
            FROM `{self.dataset}.fc018_per_symbol_scorecard` s
            LEFT JOIN `{self.dataset}.fc018_vs_buy_and_hold_per_symbol` bh
                USING (underlying)
            WHERE s.last_trade_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ORDER BY s.total_premium DESC
            """
            return self._run_query(query)
        except Exception:
            logger.info("per_symbol_scorecard query failed — returning empty list")
            return []

    def get_acb_timeline(self, symbol: str, days: int = 730) -> List[Dict[str, Any]]:
        """ACB walk events for one underlying. Powers the per-symbol drilldown chart."""
        # Bind symbol via parameterized query — defensive against injection
        # even though this comes from a route param, not user form input.
        query = f"""
        SELECT
            event_time,
            event_date,
            activity_type,
            option_type,
            side,
            qty,
            strike_price,
            premium_total,
            outcome,
            realized_pnl,
            net_premium_delta,
            shares_delta,
            cumulative_net_premium,
            running_shares,
            running_share_cost,
            acb_per_share,
            event_label
        FROM `{self.dataset}.fc018_acb_timeline_per_symbol`
        WHERE underlying = @symbol
          AND event_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        ORDER BY event_time ASC
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=[
                ScalarQueryParameter("symbol", "STRING", symbol),
                ScalarQueryParameter("days", "INT64", days),
            ])
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row.items()) for row in results]
        except Exception as e:
            logger.error(f"acb_timeline query failed for {symbol}: {e}")
            return []

    def get_decision_quality(self, symbol: str, days: int = 365) -> List[Dict[str, Any]]:
        """% of max profit captured at close, per closed trade for one symbol.

        Derived from `trades_with_outcomes`: for each opening FILL with an
        early_close outcome, capture_pct = (premium_total - close_cost) / premium_total.
        """
        query = f"""
        SELECT
            transaction_time AS open_time,
            close_transaction_time AS close_time,
            symbol AS occ_symbol,
            option_type,
            strike_price,
            premium_total,
            close_price,
            close_qty,
            outcome,
            realized_pnl,
            CASE
                WHEN outcome = 'early_close'
                     AND premium_total IS NOT NULL AND premium_total > 0
                THEN realized_pnl / premium_total
                WHEN outcome IN ('expiration', 'assignment', 'called_away')
                THEN 1.0
                ELSE NULL
            END AS capture_ratio,
            DATE_DIFF(
                DATE(COALESCE(close_transaction_time, transaction_time), 'America/New_York'),
                DATE(transaction_time, 'America/New_York'),
                DAY
            ) AS days_held
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE underlying = @symbol
          AND outcome != 'open'
          AND DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        ORDER BY transaction_time DESC
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=[
                ScalarQueryParameter("symbol", "STRING", symbol),
                ScalarQueryParameter("days", "INT64", days),
            ])
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row.items()) for row in results]
        except Exception as e:
            logger.error(f"decision_quality query failed for {symbol}: {e}")
            return []

    def get_vs_buy_and_hold(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Wheel-vs-buy-and-hold summary for a single underlying."""
        query = f"""
        SELECT *
        FROM `{self.dataset}.fc018_vs_buy_and_hold_per_symbol`
        WHERE underlying = @symbol
        LIMIT 1
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=[
                ScalarQueryParameter("symbol", "STRING", symbol),
            ])
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))
            return dict(results[0].items()) if results else None
        except Exception as e:
            logger.error(f"vs_buy_and_hold query failed for {symbol}: {e}")
            return None

    def get_wheel_cycles_for_symbol(self, symbol: str, days: int = 730) -> List[Dict[str, Any]]:
        """Wheel cycles for a single underlying.

        Reads from `wheel_cycles_from_activities` (FC-018/FC-012 view), filtered
        by underlying. Used by the per-symbol drilldown's CycleTable. Wider
        window than the legacy `/api/history/wheel-cycles` endpoint, which
        caps at 90 days.
        """
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
            calls_in_cycle,
            cycle_call_gross_premium,
            cycle_call_net_realized,
            capital_gain,
            total_premium,
            total_return,
            duration_days,
            shares
        FROM `{self.dataset}.wheel_cycles_from_activities`
        WHERE underlying = @symbol
          AND assignment_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        ORDER BY assignment_date DESC
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=[
                ScalarQueryParameter("symbol", "STRING", symbol),
                ScalarQueryParameter("days", "INT64", days),
            ])
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row.items()) for row in results]
        except Exception as e:
            logger.error(f"wheel_cycles_for_symbol query failed for {symbol}: {e}")
            return []

    def get_stock_history(self, symbol: str, days: int = 365) -> List[Dict[str, Any]]:
        """Daily OHLC bars for one symbol over the last N days."""
        query = f"""
        SELECT date, open, high, low, close, volume
        FROM `{self.dataset}.stock_history_from_alpaca`
        WHERE symbol = @symbol
          AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        ORDER BY date ASC
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=[
                ScalarQueryParameter("symbol", "STRING", symbol),
                ScalarQueryParameter("days", "INT64", days),
            ])
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row.items()) for row in results]
        except Exception:
            logger.info(f"stock_history query failed for {symbol} — returning empty list")
            return []

    def get_ingest_health(self) -> Dict[str, Any]:
        """Last-successful-ingest timestamps for the FC-012/FC-018 ingestors.

        Used by the Bot Health page to surface stale-data warnings.
        """
        out: Dict[str, Any] = {}
        sources = [
            ("trades_from_activities", "ingested_at"),
            ("equity_history_from_alpaca", "ingested_at"),
            ("stock_history_from_alpaca", "ingested_at"),
        ]
        for table, ts_field in sources:
            try:
                row = next(iter(self.client.query(
                    f"SELECT MAX({ts_field}) AS last FROM `{self.dataset}.{table}`"
                ).result(timeout=30)), None)
                last = row["last"] if row else None
                out[table] = last.isoformat() if last else None
            except Exception:
                out[table] = None
        return out

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
