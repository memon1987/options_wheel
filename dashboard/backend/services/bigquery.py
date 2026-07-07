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

    # FC-031: get_pnl_by_symbol removed — option-leg-only P&L contradicted
    # the reconciled scorecard (share_side_pnl absent). Use
    # get_per_symbol_scorecard.

    def get_premium_summary(self, days: int = 30) -> Dict[str, Any]:
        """Premium collection summary.

        Returns gross AND net numbers so the dashboard can show both:
          - total_premium (gross): sum of every option premium collected when
            sold to open. Counts $5 collected even if the position was closed
            for $4 the next day.
          - net_realized_pnl: sum of realized_pnl across closed trades. Equals
            gross premium kept on assigned/expired/called-away positions, plus
            (premium_collected − buyback_cost) for early-closed positions.
            This is the "actual cash earned" number.
          - bought_back: gross − net. Money paid out in buyback costs.
        """
        query = f"""
        SELECT
            SUM(COALESCE(premium_total, 0)) AS total_premium,
            SUM(CASE WHEN option_type = 'put'  THEN COALESCE(premium_total, 0) ELSE 0 END) AS put_premium,
            SUM(CASE WHEN option_type = 'call' THEN COALESCE(premium_total, 0) ELSE 0 END) AS call_premium,
            SUM(CASE WHEN outcome != 'open' THEN COALESCE(realized_pnl, 0) ELSE 0 END) AS net_realized_pnl,
            COUNT(*) AS trade_count
        FROM `{self.dataset}.trades_with_outcomes`
        WHERE DATE(transaction_time, 'America/New_York') >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """
        results = self._run_query(query)
        if results:
            row = results[0]
            gross = row.get('total_premium') or 0
            net = row.get('net_realized_pnl') or 0
            return {
                'total_premium': gross,
                'put_premium':   row.get('put_premium')   or 0,
                'call_premium':  row.get('call_premium')  or 0,
                'net_realized_pnl': net,
                'bought_back': gross - net,
                'trade_count':   row.get('trade_count')   or 0,
            }
        return {
            'total_premium': 0, 'put_premium': 0, 'call_premium': 0,
            'net_realized_pnl': 0, 'bought_back': 0, 'trade_count': 0,
        }

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
            'net_realized_pnl': premium_data.get('net_realized_pnl', 0),
            'bought_back': premium_data.get('bought_back', 0),
            # FC-031: win_rate/return_30d removed — they were hardcoded None
            # since FC-018. Cycle-level win rate lives in get_wheel_cycle_stats;
            # account returns live in get_portfolio_returns.
            'avg_premium': avg_premium,
        }

    # ================================================================
    # FC-018: wheel-centric dashboard data sources
    # ================================================================

    def get_per_symbol_scorecard(self, days: int = 365) -> List[Dict[str, Any]]:
        """Per-underlying summary for the FC-018 Overview matrix.

        Joins the FC-018 scorecard view with vs-buy-and-hold deltas. Returns
        one row per underlying with cycle counts, premium, realized P&L,
        share-side P&L (FC-019), and wheel-vs-buy-and-hold comparison.
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
                s.share_side_pnl,
                s.total_realized_pnl,
                s.open_count,
                s.open_put_count,
                s.open_call_count,
                s.open_option_premium,
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
                bh.price_now_date,
                bh.price_at_start_date,
                bh.bh_dollar_pnl,
                bh.wheel_mtm_pnl,
                bh.wheel_minus_bh
            FROM `{self.dataset}.fc018_per_symbol_scorecard` s
            LEFT JOIN `{self.dataset}.fc018_vs_buy_and_hold_per_symbol` bh
                USING (underlying)
            WHERE s.last_trade_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ORDER BY s.total_realized_pnl DESC
            """
            rows = self._run_query(query)
            # FC-031: attach FIFO open-lot basis (display/breakeven only — never
            # summed into P&L; acquisition cost is already expensed in the
            # share_side_pnl cash ledger).
            try:
                lot_bases = self.get_open_lot_bases()
                for r in rows:
                    lot = lot_bases.get(r.get("symbol"))
                    r["open_lot_shares"] = lot["shares"] if lot else 0
                    r["open_lot_basis_per_share"] = lot["basis_per_share"] if lot else None
                    r["open_lot_acquired_at"] = lot["acquired_at"] if lot else None
            except Exception:
                logger.info("open-lot basis merge failed — scorecard ships without it")
                for r in rows:
                    r.setdefault("open_lot_shares", None)
                    r.setdefault("open_lot_basis_per_share", None)
                    r.setdefault("open_lot_acquired_at", None)
            return rows
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
            occ_symbol,
            order_id,
            expiration,
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

    def get_phase_timing(self, symbol: str, days: int = 730) -> Dict[str, Any]:
        """Days spent in each phase for one underlying.

        Phases:
          - cash_waiting: no open puts, no shares
          - short_put: open put(s), no shares
          - long_stock: holding shares, no open call
          - covered: holding shares + open call

        Computed by walking events chronologically (Python; SQL for this is
        more pain than it's worth at <100 events per symbol). Returns
        seconds-in-phase totals + a normalized days breakdown for charting.
        """
        # Pull every option event for this symbol, with running_shares from
        # acb_timeline_per_symbol so we already know stock state at each point.
        query = f"""
        SELECT
            event_time,
            activity_type,
            option_type,
            side,
            outcome,
            running_shares
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
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))
        except Exception as e:
            logger.error(f"phase_timing query failed for {symbol}: {e}")
            return {"cash_waiting": 0, "short_put": 0, "long_stock": 0, "covered": 0,
                    "first_event": None, "last_event": None}

        if not results:
            return {"cash_waiting": 0, "short_put": 0, "long_stock": 0, "covered": 0,
                    "first_event": None, "last_event": None}

        from datetime import datetime, timezone
        # Walk events; track open-put count and open-call count.
        open_puts = 0
        open_calls = 0
        in_phase = "cash_waiting"
        prev_time = None
        totals = {"cash_waiting": 0.0, "short_put": 0.0, "long_stock": 0.0, "covered": 0.0}

        def classify(open_puts: int, open_calls: int, shares: int) -> str:
            if shares > 0 and open_calls > 0:
                return "covered"
            if shares > 0:
                return "long_stock"
            if open_puts > 0:
                return "short_put"
            return "cash_waiting"

        for row in results:
            t = row["event_time"]
            shares = int(row["running_shares"] or 0)
            atype = row["activity_type"]
            otype = row["option_type"]
            side = row["side"]
            outcome = row["outcome"]

            # Accumulate time-in-phase since previous event.
            if prev_time is not None:
                delta = (t - prev_time).total_seconds()
                totals[in_phase] = totals.get(in_phase, 0.0) + delta

            # Update open-position counters from this event.
            if atype == "FILL":
                if side in ("sell_short", "sell"):
                    if otype == "put":
                        open_puts += 1
                    elif otype == "call":
                        open_calls += 1
                elif side in ("buy_to_close", "buy"):
                    if otype == "put":
                        open_puts = max(0, open_puts - 1)
                    elif otype == "call":
                        open_calls = max(0, open_calls - 1)
            elif atype == "OPASN":
                # Assignment closes a short option. running_shares already
                # reflects the share movement.
                if otype == "put":
                    open_puts = max(0, open_puts - 1)
                elif otype == "call":
                    open_calls = max(0, open_calls - 1)
            elif atype == "OPEXP":
                if otype == "put":
                    open_puts = max(0, open_puts - 1)
                elif otype == "call":
                    open_calls = max(0, open_calls - 1)

            in_phase = classify(open_puts, open_calls, shares)
            prev_time = t

        # Trail to "now" with the final phase.
        if prev_time is not None:
            now = datetime.now(timezone.utc)
            if prev_time.tzinfo is None:
                prev_time = prev_time.replace(tzinfo=timezone.utc)
            delta = (now - prev_time).total_seconds()
            totals[in_phase] = totals.get(in_phase, 0.0) + delta

        return {
            "cash_waiting": round(totals["cash_waiting"] / 86400, 2),
            "short_put": round(totals["short_put"] / 86400, 2),
            "long_stock": round(totals["long_stock"] / 86400, 2),
            "covered": round(totals["covered"] / 86400, 2),
            "first_event": results[0]["event_time"].isoformat() if results else None,
            "last_event": results[-1]["event_time"].isoformat() if results else None,
            "current_phase": in_phase,
        }

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
            optrd_event_count,
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

    def get_account_baseline(self) -> Dict[str, Any]:
        """Return the account's starting capital for inception-P&L calculations.

        Sums every JNLC (cash journal) activity ever ingested. Net deposits
        minus withdrawals gives the actual amount of capital the user put in.
        For a single-deposit paper account this is just the funding amount.

        Falls back to the ``BASELINE_DEPOSITS`` env var (default 100_000.0)
        if the JNLC ingest hasn't run yet (e.g., during initial deploy of
        FC-019 before the backfill triggers). The fallback path is logged so
        operators can spot when they're seeing stale data.
        """
        query = f"""
        SELECT SUM(COALESCE(net_amount, 0)) AS total_jnlc, COUNT(*) AS event_count
        FROM `{self.dataset}.trades_from_activities`
        WHERE activity_type = 'JNLC'
        """
        try:
            results = self._run_query(query)
            if results and results[0].get('event_count', 0) > 0:
                total = float(results[0].get('total_jnlc') or 0)
                return {
                    "starting_capital": total,
                    "jnlc_event_count": int(results[0].get('event_count') or 0),
                    "source": f"BQ:trades_from_activities (sum of {results[0].get('event_count')} JNLC events)",
                }
        except Exception as e:
            logger.warning(f"JNLC sum query failed; falling back to env: {e}")

        # Fallback path
        try:
            baseline = float(os.environ.get("BASELINE_DEPOSITS", "100000"))
        except (TypeError, ValueError):
            baseline = 100000.0
        return {
            "starting_capital": baseline,
            "jnlc_event_count": 0,
            "source": "env:BASELINE_DEPOSITS fallback (no JNLC rows ingested yet)",
        }

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

    # ================================================================
    # FC-031: vetted portfolio metrics + bot execution health
    # (docs/plans/fc-031.md; adversarial review in docs/investigations/)
    # ================================================================

    # Deploy date of the FC-029 risk re-tune (call delta band, hard
    # cost-basis floor, drawdown pause). Used to split cycle/put stats
    # into before/after regimes so the parameter change is measurable.
    FC029_DEPLOY_DATE = "2026-05-08"

    # Known, dated reconciliation gaps. Each entry documents a measured
    # broker-vs-ledger discrepancy we have investigated and accepted.
    # NEVER add an entry without an investigation doc — this list exists to
    # keep the banner honest, not to silence it.
    KNOWN_RECONCILIATION_GAPS = [
        {
            "symbol": "AMD",
            "amount": -1594.0,
            "as_of": "2026-05-05",
            "reason": "Alpaca paper-engine anomaly: OPTRDs net +100 shares but "
                      "positions API reports 0 (FC-019 execution notes; "
                      "docs/investigations/amd-reconciliation.md)",
        },
    ]

    def get_cash_flows(self) -> List[Dict[str, Any]]:
        """Dated external cash flows (JNLC): deposits positive."""
        query = f"""
        SELECT
            COALESCE(activity_date, DATE(transaction_time, 'America/New_York')) AS flow_date,
            SUM(COALESCE(net_amount, 0)) AS amount
        FROM `{self.dataset}.trades_from_activities`
        WHERE activity_type = 'JNLC'
        GROUP BY flow_date
        ORDER BY flow_date ASC
        """
        try:
            return self._run_query(query)
        except Exception:
            logger.info("cash_flows query failed — returning empty list")
            return []

    def get_fees_total(self) -> float:
        """Lifetime FEE cash (negative). First-class reconciliation component."""
        try:
            rows = self._run_query(f"""
                SELECT SUM(COALESCE(net_amount, 0)) AS fees
                FROM `{self.dataset}.trades_from_activities`
                WHERE activity_type = 'FEE'
            """)
            return float(rows[0]["fees"] or 0) if rows else 0.0
        except Exception:
            return 0.0

    def _equity_points(self, days: int = 3650):
        """(date, equity) tuples from equity_history_from_alpaca."""
        rows = self.get_portfolio_value_history(days=days)
        return [(r["date"], float(r["portfolio_value"]))
                for r in rows if r.get("portfolio_value") is not None]

    def get_portfolio_returns(self, current_nlv: Optional[float] = None,
                              nlv_source: str = "live") -> Dict[str, Any]:
        """Account-level XIRR / TWR / drawdown from flows + equity history.

        ``current_nlv`` (from the live bot proxy) REPLACES any same-date
        equity row rather than appending (a duplicate date would create a
        zero-length TWR sub-period). When None, the last equity row is the
        terminal point and ``nlv_source`` should say so.
        """
        from datetime import date as _date
        from services import returns as R

        flows_rows = self.get_cash_flows()
        flows = [(r["flow_date"], float(r["amount"])) for r in flows_rows]
        equity = self._equity_points()

        today = _date.today()
        if current_nlv is not None:
            equity = [(d, v) for d, v in equity if d != today]
            equity.append((today, float(current_nlv)))
        equity.sort()

        terminal = equity[-1] if equity else None
        first_deposit = min((d for d, _ in flows), default=None)
        days_running = (terminal[0] - first_deposit).days if terminal and first_deposit else None

        xirr_val = R.xirr(flows, terminal) if terminal and flows else None
        twr_val = R.twr(equity, flows)
        dd = R.max_drawdown(equity, flows)
        dd_dollars = R.dollar_drawdown(equity, flows)

        return {
            "xirr": xirr_val,
            "twr_cumulative": twr_val,
            "twr_annualized": R.annualize(twr_val, days_running) if days_running else None,
            "max_drawdown": dd["max_dd"],
            "max_drawdown_peak": str(dd["max_dd_peak"]) if dd["max_dd_peak"] else None,
            "max_drawdown_trough": str(dd["max_dd_trough"]) if dd["max_dd_trough"] else None,
            "current_drawdown": dd["current_dd"],
            "max_drawdown_dollars": dd_dollars["max_dd_dollars"],
            "current_drawdown_dollars": dd_dollars["current_dd_dollars"],
            "days_since_first_deposit": days_running,
            "deposit_count": len(flows),
            # Single-deposit accounts: XIRR is algebraically the CAGR since
            # inception — the label must say so (review F9).
            "single_deposit": len(flows) <= 1,
            "nlv_source": nlv_source if current_nlv is not None else "last equity row (live proxy unavailable)",
            "as_of": str(terminal[0]) if terminal else None,
        }

    def get_equity_curve_indexed(self, days: int = 3650) -> List[Dict[str, Any]]:
        """TWR-indexed wheel curve vs SPY price index, base 100 at window start.

        Caption context (frontend renders it): SPY is price-only (understates
        buy-and-hold by ~1.2%/yr of dividends) and the paper account credits
        0% on idle cash where a live account would earn T-bill yield.
        """
        from services import returns as R

        flows_rows = self.get_cash_flows()
        flows = [(r["flow_date"], float(r["amount"])) for r in flows_rows]
        equity = self._equity_points(days=days)
        wheel_series = R.twr_series(equity, flows)
        wheel = {d.isoformat() if hasattr(d, "isoformat") else str(d): round(v, 4)
                 for d, v in wheel_series}

        spy_rows = self.get_stock_history("SPY", days=days)
        window_start = equity[0][0] if equity else None
        spy_rows = [r for r in spy_rows if window_start is None or r["date"] >= window_start]
        spy = {}
        if spy_rows:
            base = float(spy_rows[0]["close"])
            if base > 0:
                spy = {str(r["date"]): round(100.0 * float(r["close"]) / base, 4)
                       for r in spy_rows}

        dates = sorted(set(wheel) | set(spy))
        return [{"date": d, "wheel": wheel.get(d), "benchmark": spy.get(d)} for d in dates]

    def get_monthly_cashflow(self, months: int = 24) -> List[Dict[str, Any]]:
        """Net option cash flow by month from the FC-031 view."""
        try:
            query = f"""
            SELECT month, net_option_cashflow, put_net_cashflow, call_net_cashflow,
                   gross_premium, buyback_cost, event_count
            FROM `{self.dataset}.fc031_monthly_option_cashflow`
            ORDER BY month DESC
            LIMIT {int(months)}
            """
            rows = self._run_query(query)
            rows.reverse()
            return rows
        except Exception:
            logger.info("monthly_option_cashflow query failed — returning empty list")
            return []

    def _overlapping_lot_symbols(self) -> List[str]:
        """Symbols that ever held >1 concurrent 100-share lot.

        Their per-cycle rows are mis-paired until FC-020 lands; they are
        EXCLUDED from cycle aggregates (and the exclusion disclosed) rather
        than fabricating expectancy from known-wrong rows (review F3).
        """
        try:
            rows = self._run_query(f"""
                SELECT underlying
                FROM `{self.dataset}.fc018_acb_timeline_per_symbol`
                GROUP BY underlying
                HAVING MAX(running_shares) > 100
            """)
            return [r["underlying"] for r in rows]
        except Exception:
            return []

    def get_wheel_cycle_stats(self, days: int = 3650) -> Dict[str, Any]:
        """Closed-wheel-cycle win rate / expectancy, with disclosures.

        - Overlapping-lot symbols excluded (FC-020 mis-pairing) and counted.
        - Open cycles reported beside closed stats with their MTM-to-date so
          survivorship is visible (losing cycles stay open longest).
        - FC-029 before/after regime split on the cycle's put date.
        """
        excluded = self._overlapping_lot_symbols()
        excl_list = ", ".join(f"'{s}'" for s in excluded) or "''"
        try:
            closed = self._run_query(f"""
                SELECT
                    underlying,
                    put_date,
                    COALESCE(total_premium, 0) + COALESCE(capital_gain, 0) AS cycle_pnl,
                    put_strike * 100 * ABS(COALESCE(shares, 100) / 100) AS collateral,
                    GREATEST(COALESCE(duration_days, 1), 1) AS duration_days
                FROM `{self.dataset}.wheel_cycles_from_activities`
                WHERE call_date IS NOT NULL
                  AND underlying NOT IN ({excl_list})
                  AND assignment_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {int(days)} DAY)
            """)
            open_rows = self._run_query(f"""
                SELECT
                    c.underlying,
                    COALESCE(c.total_premium, 0) + COALESCE(c.capital_gain, 0) AS cash_to_date,
                    bh.current_shares,
                    bh.price_now
                FROM `{self.dataset}.wheel_cycles_from_activities` c
                LEFT JOIN `{self.dataset}.fc018_vs_buy_and_hold_per_symbol` bh
                    ON bh.underlying = c.underlying
                WHERE c.call_date IS NULL
                  AND c.underlying NOT IN ({excl_list})
            """)
        except Exception:
            logger.info("wheel_cycle_stats queries failed")
            return {"closed_count": 0, "excluded_overlapping_symbols": excluded}

        def _stats(rows):
            pnls = [float(r["cycle_pnl"]) for r in rows]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            n = len(pnls)
            win_rate = len(wins) / n if n else None
            avg_win = sum(wins) / len(wins) if wins else None
            avg_loss = sum(losses) / len(losses) if losses else None
            expectancy = (sum(pnls) / n) if n else None
            # ONLY permitted aggregate rate: Σ P&L / Σ collateral-days
            # (averaging per-cycle ratios re-imports the annualization
            # lie — review F11).
            coll_days = sum(float(r["collateral"]) * float(r["duration_days"]) for r in rows)
            per_dollar_day = (sum(pnls) / coll_days) if coll_days > 0 else None
            return {
                "count": n, "win_rate": win_rate, "avg_win": avg_win,
                "avg_loss": avg_loss, "expectancy": expectancy,
                "pnl_per_collateral_day": per_dollar_day,
            }

        # MTM for open cycles: cash-to-date already expensed acquisition, so
        # add full share market value once per symbol (convention: F1).
        seen_symbols = set()
        open_mtm = 0.0
        for r in open_rows:
            open_mtm += float(r["cash_to_date"] or 0)
            sym = r["underlying"]
            if sym not in seen_symbols:
                seen_symbols.add(sym)
                shares = float(r["current_shares"] or 0)
                price = float(r["price_now"] or 0)
                if shares > 0 and price > 0:
                    open_mtm += shares * price

        pre = [r for r in closed if str(r["put_date"]) < self.FC029_DEPLOY_DATE]
        post = [r for r in closed if str(r["put_date"]) >= self.FC029_DEPLOY_DATE]

        return {
            **_stats(closed),
            "closed_count": len(closed),
            "open_count": len(open_rows),
            "open_mtm_to_date": round(open_mtm, 2) if open_rows else 0.0,
            "excluded_overlapping_symbols": excluded,
            "regime_pre_fc029": _stats(pre),
            "regime_post_fc029": _stats(post),
            "fc029_deploy_date": self.FC029_DEPLOY_DATE,
        }

    def get_put_trade_stats(self, days: int = 3650) -> Dict[str, Any]:
        """Unassigned-put trade stats, reported SEPARATELY from cycle stats.

        Blending puts into one "campaign win rate" re-imports the banned
        per-contract delta artifact (review F4). The calibration stat is
        held-to-expiry only: assignments / (assignments + expirations) —
        early closes never faced the expiry lottery (review F5).
        """
        try:
            rows = self._run_query(f"""
                SELECT
                    outcome,
                    COUNT(*) AS n,
                    COUNTIF(COALESCE(realized_pnl, 0) > 0) AS wins,
                    SUM(COALESCE(realized_pnl, 0)) AS pnl,
                    COUNTIF(DATE(transaction_time, 'America/New_York')
                            >= '{self.FC029_DEPLOY_DATE}') AS n_post_fc029
                FROM `{self.dataset}.trades_with_outcomes`
                WHERE option_type = 'put'
                  AND outcome != 'open'
                  AND DATE(transaction_time, 'America/New_York')
                      >= DATE_SUB(CURRENT_DATE(), INTERVAL {int(days)} DAY)
                GROUP BY outcome
            """)
        except Exception:
            logger.info("put_trade_stats query failed")
            return {"closed_count": 0}

        by = {r["outcome"]: r for r in rows}
        n_assign = int(by.get("assignment", {}).get("n", 0) or 0)
        n_expire = int(by.get("expiration", {}).get("n", 0) or 0)
        n_early = int(by.get("early_close", {}).get("n", 0) or 0)
        closed_unassigned = [by[o] for o in ("expiration", "early_close") if o in by]
        n_closed = sum(int(r["n"]) for r in closed_unassigned)
        wins = sum(int(r["wins"]) for r in closed_unassigned)
        pnl = sum(float(r["pnl"] or 0) for r in closed_unassigned)
        held_to_expiry = n_assign + n_expire

        return {
            "closed_count": n_closed,
            "win_rate": (wins / n_closed) if n_closed else None,
            "net_pnl": pnl,
            "assignment_count": n_assign,
            "expiration_count": n_expire,
            "early_close_count": n_early,
            "pct_closed_early": (n_early / (n_early + held_to_expiry))
                                if (n_early + held_to_expiry) else None,
            # Calibration vs |put delta| (0.10–0.20 band): held-to-expiry only.
            "assignment_rate_held_to_expiry": (n_assign / held_to_expiry)
                                              if held_to_expiry else None,
            "put_delta_band": [0.10, 0.20],
        }

    def get_reconciliation(self, current_nlv: Optional[float],
                           live_positions: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Falsifiable broker-vs-ledger reconciliation (review F6/F15).

        Identity: NLV − deposits = closed net cash P&L + open-option premium
        + fees + market value of live positions (stocks + options, signed).
        Residual ≈ 0 unless the BQ ledger disagrees with the broker — missed
        activities or paper-engine anomalies, which is what this detects.
        """
        baseline = self.get_account_baseline()
        deposits = float(baseline.get("starting_capital") or 0)
        fees = self.get_fees_total()

        try:
            rows = self._run_query(f"""
                SELECT
                    SUM(COALESCE(total_realized_pnl, 0)) AS realized_cash,
                    SUM(COALESCE(open_option_premium, 0)) AS open_premium
                FROM `{self.dataset}.fc018_per_symbol_scorecard`
            """)
            realized_cash = float(rows[0]["realized_cash"] or 0) if rows else 0.0
            open_premium = float(rows[0]["open_premium"] or 0) if rows else 0.0
        except Exception:
            realized_cash, open_premium = 0.0, 0.0

        live_mv = None
        live_shares_by_symbol: Dict[str, float] = {}
        if live_positions is not None:
            live_mv = 0.0
            for p in live_positions:
                try:
                    live_mv += float(p.get("market_value") or 0)
                except (TypeError, ValueError):
                    continue
                sym = str(p.get("symbol") or "")
                # Stock rows: plain ticker (no OCC digits tail)
                if sym and not any(c.isdigit() for c in sym):
                    try:
                        live_shares_by_symbol[sym] = (
                            live_shares_by_symbol.get(sym, 0.0)
                            + float(p.get("qty") or 0))
                    except (TypeError, ValueError):
                        pass

        # View-vs-live share count mismatches (the AMD anomaly surface).
        mismatches: List[Dict[str, Any]] = []
        try:
            view_rows = self._run_query(f"""
                SELECT underlying, current_shares
                FROM `{self.dataset}.fc018_per_symbol_scorecard`
                WHERE COALESCE(current_shares, 0) != 0
            """)
            if live_positions is not None:
                view_by = {r["underlying"]: float(r["current_shares"] or 0)
                           for r in view_rows}
                for sym in set(view_by) | set(live_shares_by_symbol):
                    v = view_by.get(sym, 0.0)
                    l = live_shares_by_symbol.get(sym, 0.0)
                    if v != l:
                        mismatches.append(
                            {"symbol": sym, "view_shares": v, "live_shares": l})
        except Exception:
            pass

        residual = None
        status = "unknown"
        known_total = sum(g["amount"] for g in self.KNOWN_RECONCILIATION_GAPS)
        if current_nlv is not None and live_mv is not None:
            residual = (float(current_nlv) - deposits) - (
                realized_cash + open_premium + fees + live_mv)
            threshold = max(500.0, 0.005 * float(current_nlv))
            net = residual - known_total
            known_syms = {g["symbol"] for g in self.KNOWN_RECONCILIATION_GAPS}
            new_mismatch = any(m["symbol"] not in known_syms for m in mismatches)
            stale_gap = any(g["symbol"] not in {m["symbol"] for m in mismatches}
                            for g in self.KNOWN_RECONCILIATION_GAPS)
            status = "warn" if (abs(net) > threshold or new_mismatch or stale_gap) else "ok"

        return {
            "nlv": current_nlv,
            "deposits": deposits,
            "deposits_source": baseline.get("source"),
            "realized_cash_pnl": realized_cash,
            "open_option_premium": open_premium,
            "fees": fees,
            "live_market_value": live_mv,
            "residual": residual,
            "residual_net_of_known_gaps": (residual - known_total)
                                          if residual is not None else None,
            "known_gaps": self.KNOWN_RECONCILIATION_GAPS,
            "share_count_mismatches": mismatches,
            "status": status,
        }

    def get_bot_anomalies(self) -> List[Dict[str, Any]]:
        """Bot-health anomaly flags on an INDEPENDENT trading calendar.

        The calendar comes from SPY bars (stock_history_from_alpaca), not
        from the scheduler's own events — a totally dead scheduler must
        still light up "zero scans on a trading day" (review F7).
        """
        flags: List[Dict[str, Any]] = []

        # Trading days (SPY bars), most recent first. Bars land at 17:00 ET,
        # so "today" is naturally excluded until after the close — no
        # intraday false positives.
        try:
            cal_rows = self._run_query(f"""
                SELECT date FROM `{self.dataset}.stock_history_from_alpaca`
                WHERE symbol = 'SPY'
                ORDER BY date DESC LIMIT 10
            """)
            trading_days = [str(r["date"]) for r in cal_rows]
            calendar_source = "SPY bars"
        except Exception:
            trading_days = []
            calendar_source = "unavailable"
        if not trading_days:
            # Fallback: self-derived calendar, labeled (blind to total outage).
            try:
                cal_rows = self._run_query(f"""
                    SELECT DISTINCT DATE(timestamp, 'America/New_York') AS date
                    FROM `{self.dataset}.executions`
                    ORDER BY date DESC LIMIT 10
                """)
                trading_days = [str(r["date"]) for r in cal_rows]
                calendar_source = "self-derived (SPY bars unavailable — blind to total outage)"
            except Exception:
                pass

        # Daily scan/order counts.
        daily = {}
        try:
            for r in self._run_query(f"""
                SELECT DATE(timestamp, 'America/New_York') AS date,
                       SUM(scan_count) AS scans, SUM(trades_executed) AS orders
                FROM `{self.dataset}.executions`
                WHERE DATE(timestamp, 'America/New_York')
                      >= DATE_SUB(CURRENT_DATE(), INTERVAL 45 DAY)
                GROUP BY date
            """):
                daily[str(r["date"])] = r
        except Exception:
            pass

        recent = trading_days[:7]
        zero_scan_days = [d for d in recent
                          if float((daily.get(d) or {}).get("scans") or 0) == 0]
        if zero_scan_days:
            flags.append({
                "severity": "critical",
                "code": "zero_scan_trading_days",
                "message": f"No scans on {len(zero_scan_days)} of the last "
                           f"{len(recent)} trading days ({calendar_source})",
                "since": min(zero_scan_days),
                "evidence": zero_scan_days,
            })

        streak_days = trading_days[:3]
        if streak_days and all(
                float((daily.get(d) or {}).get("scans") or 0) > 0
                and float((daily.get(d) or {}).get("orders") or 0) == 0
                for d in streak_days):
            flags.append({
                "severity": "warning",
                "code": "no_orders_streak",
                "message": "Scans ran but zero orders placed for the last "
                           f"{len(streak_days)} trading days",
                "since": min(streak_days),
                "evidence": streak_days,
            })

        # Gate 100%-block streaks: any stage fully blocking for the last 3
        # trading days that passed >0 candidates over the trailing 30d.
        try:
            gate_rows = self._run_query(f"""
                WITH daily AS (
                    SELECT DATE(timestamp, 'America/New_York') AS date, stage,
                           COUNTIF(result = 'pass') AS passed,
                           COUNTIF(result = 'fail') AS blocked
                    FROM `{self.dataset}.scans`
                    WHERE DATE(timestamp, 'America/New_York')
                          >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
                      AND stage IS NOT NULL
                    GROUP BY date, stage
                )
                SELECT stage,
                       SUM(passed) AS passed_30d,
                       COUNTIF(passed = 0 AND blocked > 0
                               AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY))
                         AS full_block_days_recent
                FROM daily
                GROUP BY stage
                HAVING passed_30d > 0 AND full_block_days_recent >= 3
            """)
            for r in gate_rows:
                flags.append({
                    "severity": "warning",
                    "code": "gate_full_block_streak",
                    "message": f"Stage '{r['stage']}' blocked 100% of candidates on "
                               f"{r['full_block_days_recent']} recent days despite a "
                               "non-zero 30d pass baseline",
                    "since": None,
                    "evidence": {"stage": r["stage"]},
                })
        except Exception:
            pass

        # Ingest staleness with per-job thresholds.
        from datetime import datetime, timezone, timedelta
        ingest = self.get_ingest_health()
        thresholds = {
            "trades_from_activities": timedelta(hours=6),
            "equity_history_from_alpaca": timedelta(hours=78),
            "stock_history_from_alpaca": timedelta(hours=78),
        }
        now = datetime.now(timezone.utc)
        for table, last in ingest.items():
            limit = thresholds.get(table)
            if limit is None:
                continue
            if last is None:
                flags.append({"severity": "warning", "code": "ingest_never_ran",
                              "message": f"{table}: no rows ever ingested",
                              "since": None, "evidence": None})
                continue
            try:
                age = now - datetime.fromisoformat(last.replace("Z", "+00:00"))
                if age > limit:
                    flags.append({
                        "severity": "warning", "code": "ingest_stale",
                        "message": f"{table}: last ingest {int(age.total_seconds() // 3600)}h ago "
                                   f"(threshold {int(limit.total_seconds() // 3600)}h)",
                        "since": last, "evidence": None,
                    })
            except ValueError:
                pass

        return flags

    def get_optrd_events(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Raw OPTRD share events, oldest first (input to the FIFO lot walk)."""
        where = "AND symbol = @symbol" if symbol else ""
        query = f"""
        SELECT symbol, transaction_time, qty, price, net_amount
        FROM `{self.dataset}.trades_from_activities`
        WHERE activity_type = 'OPTRD' AND symbol IS NOT NULL AND symbol != ''
        {where}
        ORDER BY transaction_time ASC
        """
        try:
            from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig
            job_config = QueryJobConfig(query_parameters=(
                [ScalarQueryParameter("symbol", "STRING", symbol)] if symbol else []))
            results = self.client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row.items()) for row in results]
        except Exception:
            logger.info("optrd_events query failed — returning empty list")
            return []

    def get_open_lot_bases(self) -> Dict[str, Dict[str, Any]]:
        """FIFO open-lot basis per symbol (display/breakeven only)."""
        from services.lots import open_lot_basis
        events = self.get_optrd_events()
        by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for ev in events:
            by_symbol.setdefault(ev["symbol"], []).append(ev)
        out = {}
        for sym, evs in by_symbol.items():
            basis = open_lot_basis(evs)
            basis["acquired_at"] = (str(basis["acquired_at"])
                                    if basis["acquired_at"] else None)
            out[sym] = basis
        return out

    def get_drawdown_pauses(self, live_positions: Optional[List[Dict[str, Any]]],
                            threshold: float,
                            threshold_source: str) -> Dict[str, Any]:
        """Symbols the R3 drawdown pause is (inferred to be) blocking.

        Inferred from prices, not bot telemetry — labeled as such in the UI.
        Reference price = latest OPASN put strike (what the bot compares
        against per FC-029), shares from LIVE positions, pause window bounded
        at the open lot's acquisition date (review F8).
        """
        held: Dict[str, float] = {}
        if live_positions:
            for p in live_positions:
                sym = str(p.get("symbol") or "")
                if sym and not any(c.isdigit() for c in sym):
                    try:
                        qty = float(p.get("qty") or 0)
                    except (TypeError, ValueError):
                        continue
                    if qty > 0:
                        held[sym] = held.get(sym, 0.0) + qty

        result = {"threshold": threshold, "threshold_source": threshold_source,
                  "paused": [], "share_count_mismatches": []}
        if not held:
            return result

        syms = ", ".join(f"'{s}'" for s in held)
        try:
            strikes = {r["underlying"]: float(r["strike"])
                       for r in self._run_query(f"""
                SELECT underlying,
                       ARRAY_AGG(strike_price ORDER BY transaction_time DESC LIMIT 1)[OFFSET(0)] AS strike
                FROM `{self.dataset}.trades_from_activities`
                WHERE activity_type = 'OPASN' AND option_type = 'put'
                  AND underlying IN ({syms})
                GROUP BY underlying
            """) if r.get("strike") is not None}
        except Exception:
            strikes = {}

        lot_bases = {}
        try:
            lot_bases = {s: b for s, b in self.get_open_lot_bases().items() if s in held}
        except Exception:
            pass

        for sym, qty in held.items():
            ref = strikes.get(sym)
            if not ref or ref <= 0:
                continue
            pause_floor = (1.0 - threshold) * ref
            acquired = (lot_bases.get(sym) or {}).get("acquired_at")
            acquired_date = str(acquired)[:10] if acquired else "1900-01-01"
            try:
                bars = self._run_query(f"""
                    SELECT date, close FROM `{self.dataset}.stock_history_from_alpaca`
                    WHERE symbol = '{sym}' AND date >= '{acquired_date}'
                    ORDER BY date DESC LIMIT 90
                """)
            except Exception:
                bars = []
            if not bars:
                continue
            latest = bars[0]
            if float(latest["close"]) >= pause_floor:
                continue
            days_paused = 0
            for b in bars:
                if float(b["close"]) < pause_floor:
                    days_paused += 1
                else:
                    break
            result["paused"].append({
                "symbol": sym,
                "shares": qty,
                "assignment_strike": ref,
                "pause_floor": round(pause_floor, 2),
                "last_close": float(latest["close"]),
                "last_close_date": str(latest["date"]),
                "trading_days_paused": days_paused,
                "pct_below_strike": round(1.0 - float(latest["close"]) / ref, 4),
            })

        return result


# Singleton instance
_bq_service: Optional[BigQueryService] = None


def get_bigquery_service() -> BigQueryService:
    """Get or create the BigQuery service singleton."""
    global _bq_service
    if _bq_service is None:
        _bq_service = BigQueryService()
    return _bq_service
