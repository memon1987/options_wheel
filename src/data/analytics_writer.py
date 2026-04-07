"""Dedicated BigQuery analytics writer with explicit schemas.

Replaces the fragile Cloud Logging → BQ log sink approach with direct
writes to purpose-built, time-partitioned tables.  Each table has a
code-defined schema — no auto-detection, no wildcard query conflicts.

Manages these tables in the ``options_wheel`` dataset:
  - trades        (expanded from TradeJournal)
  - errors        (replaces errors_all log-sink view)
  - executions    (replaces execution_cycle_results + daily_operations_summary)
  - scans         (replaces filtering_stage_summary)
  - wheel_cycles  (replaces wheel_cycles log-sink view)
  - position_snapshots (new — portfolio value history)
  - order_statuses     (new — fill price tracking)

Design principles:
  - Graceful no-op if BigQuery is unavailable
  - ``insert_rows_json`` for simple, low-latency writes
  - All tables time-partitioned by ``timestamp``
  - Schema changes = add NULLABLE columns (safe in BQ)
"""

import os
import structlog
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = structlog.get_logger(__name__)

try:
    from google.cloud import bigquery
    _HAS_BIGQUERY = True
except ImportError:
    _HAS_BIGQUERY = False
    bigquery = None  # type: ignore

# --------------------------------------------------------------------------- #
# Schema definitions
# --------------------------------------------------------------------------- #

_SCHEMAS: Dict[str, list] = {}

if _HAS_BIGQUERY:
    _SCHEMAS = {
        "errors": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("event_type", "STRING"),
            bigquery.SchemaField("error_type", "STRING"),
            bigquery.SchemaField("error_message", "STRING"),
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("underlying", "STRING"),
            bigquery.SchemaField("component", "STRING"),
            bigquery.SchemaField("recoverable", "BOOLEAN"),
            bigquery.SchemaField("request_id", "STRING"),
            bigquery.SchemaField("stack_trace", "STRING"),
        ],
        "executions": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("endpoint", "STRING", description="/scan, /run, /monitor"),
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("duration_seconds", "FLOAT"),
            bigquery.SchemaField("scan_count", "INTEGER"),
            bigquery.SchemaField("opportunities_found", "INTEGER"),
            bigquery.SchemaField("trades_executed", "INTEGER"),
            bigquery.SchemaField("trades_failed", "INTEGER"),
            bigquery.SchemaField("errors", "INTEGER"),
            bigquery.SchemaField("buying_power_before", "FLOAT"),
            bigquery.SchemaField("buying_power_after", "FLOAT"),
            bigquery.SchemaField("portfolio_value", "FLOAT"),
            bigquery.SchemaField("request_id", "STRING"),
        ],
        "scans": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("stage", "STRING", description="stage_1, stage_2, ..., stage_8"),
            bigquery.SchemaField("result", "STRING", description="passed, blocked, not_found"),
            bigquery.SchemaField("reason", "STRING"),
            bigquery.SchemaField("premium", "FLOAT"),
            bigquery.SchemaField("delta", "FLOAT"),
            bigquery.SchemaField("dte", "INTEGER"),
            bigquery.SchemaField("strike_price", "FLOAT"),
            bigquery.SchemaField("current_price", "FLOAT"),
            bigquery.SchemaField("scan_id", "STRING"),
        ],
        "wheel_cycles": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("put_date", "DATE"),
            bigquery.SchemaField("put_strike", "FLOAT"),
            bigquery.SchemaField("put_premium", "FLOAT"),
            bigquery.SchemaField("assignment_date", "DATE"),
            bigquery.SchemaField("call_date", "DATE"),
            bigquery.SchemaField("call_strike", "FLOAT"),
            bigquery.SchemaField("call_premium", "FLOAT"),
            bigquery.SchemaField("capital_gain", "FLOAT"),
            bigquery.SchemaField("total_premium", "FLOAT"),
            bigquery.SchemaField("total_return", "FLOAT"),
            bigquery.SchemaField("duration_days", "INTEGER"),
            bigquery.SchemaField("shares", "INTEGER"),
        ],
        "position_snapshots": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("date", "DATE"),
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("asset_class", "STRING", description="us_equity, us_option, account"),
            bigquery.SchemaField("shares", "INTEGER"),
            bigquery.SchemaField("contracts", "INTEGER"),
            bigquery.SchemaField("cost_basis", "FLOAT"),
            bigquery.SchemaField("market_value", "FLOAT"),
            bigquery.SchemaField("unrealized_pnl", "FLOAT"),
            bigquery.SchemaField("current_price", "FLOAT"),
            bigquery.SchemaField("portfolio_value", "FLOAT"),
            bigquery.SchemaField("cash", "FLOAT"),
            bigquery.SchemaField("buying_power", "FLOAT"),
        ],
        "order_statuses": [
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("order_id", "STRING"),
            bigquery.SchemaField("client_order_id", "STRING"),
            bigquery.SchemaField("symbol", "STRING"),
            bigquery.SchemaField("underlying", "STRING"),
            bigquery.SchemaField("side", "STRING"),
            bigquery.SchemaField("order_type", "STRING"),
            bigquery.SchemaField("status", "STRING", description="filled, expired, canceled, partial"),
            bigquery.SchemaField("limit_price", "FLOAT"),
            bigquery.SchemaField("filled_price", "FLOAT"),
            bigquery.SchemaField("filled_qty", "INTEGER"),
            bigquery.SchemaField("submitted_at", "TIMESTAMP"),
            bigquery.SchemaField("filled_at", "TIMESTAMP"),
        ],
    }


class AnalyticsWriter:
    """Write structured analytics data to dedicated BigQuery tables.

    Manages table creation and row insertion for 7 analytics tables
    (trades table is handled by the existing TradeJournal).

    If BigQuery is unavailable, all write methods are silent no-ops.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        dataset_id: str = "options_wheel",
    ):
        self._enabled = False
        self._tables: Dict[str, Any] = {}

        if not _HAS_BIGQUERY:
            return

        self._project_id = (
            project_id
            or os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        )
        if not self._project_id:
            logger.warning("No GCP project ID — AnalyticsWriter disabled")
            return

        self._dataset_id = dataset_id

        try:
            self._client = bigquery.Client(project=self._project_id)
            self._ensure_all_tables()
            self._enabled = True
            logger.info(
                "AnalyticsWriter initialised",
                event_category="system",
                event_type="analytics_writer_initialized",
                project=self._project_id,
                dataset=self._dataset_id,
                tables=list(_SCHEMAS.keys()),
            )
        except Exception:
            logger.warning("Failed to initialise AnalyticsWriter — disabled",
                          exc_info=True)

    def _ensure_all_tables(self) -> None:
        """Create dataset and all tables if they don't exist."""
        dataset_ref = bigquery.DatasetReference(self._project_id, self._dataset_id)
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        self._client.create_dataset(dataset, exists_ok=True)

        for table_name, schema in _SCHEMAS.items():
            table_ref = dataset_ref.table(table_name)
            table = bigquery.Table(table_ref, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="timestamp",
            )
            self._client.create_table(table, exists_ok=True)
            self._tables[table_name] = table_ref

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Generic write
    # ------------------------------------------------------------------

    def _write(self, table_name: str, row: dict) -> None:
        """Insert a single row into a named table."""
        if not self._enabled or table_name not in self._tables:
            return
        if "timestamp" not in row:
            row["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            errors = self._client.insert_rows_json(self._tables[table_name], [row])
            if errors:
                logger.error("AnalyticsWriter insert errors",
                            table=table_name, errors=str(errors)[:200])
        except Exception:
            logger.debug("AnalyticsWriter insert failed",
                        table=table_name, exc_info=True)

    def _write_batch(self, table_name: str, rows: List[dict]) -> None:
        """Insert multiple rows into a named table."""
        if not self._enabled or not rows or table_name not in self._tables:
            return
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            if "timestamp" not in row:
                row["timestamp"] = now
        try:
            errors = self._client.insert_rows_json(self._tables[table_name], rows)
            if errors:
                logger.error("AnalyticsWriter batch insert errors",
                            table=table_name, count=len(rows),
                            errors=str(errors)[:200])
        except Exception:
            logger.debug("AnalyticsWriter batch insert failed",
                        table=table_name, exc_info=True)

    # ------------------------------------------------------------------
    # Typed write methods
    # ------------------------------------------------------------------

    def write_error(self, *, event_type: str, error_type: str = "",
                    error_message: str = "", symbol: str = "",
                    underlying: str = "", component: str = "",
                    recoverable: bool = True, request_id: str = "",
                    stack_trace: str = "", **extra) -> None:
        self._write("errors", {
            "event_type": event_type,
            "error_type": error_type,
            "error_message": error_message[:1000],
            "symbol": symbol,
            "underlying": underlying,
            "component": component,
            "recoverable": recoverable,
            "request_id": request_id,
            "stack_trace": stack_trace[:2000],
        })

    def write_execution(self, *, endpoint: str, status: str,
                        duration_seconds: float = 0,
                        scan_count: int = 0, opportunities_found: int = 0,
                        trades_executed: int = 0, trades_failed: int = 0,
                        errors: int = 0, buying_power_before: float = 0,
                        buying_power_after: float = 0,
                        portfolio_value: float = 0,
                        request_id: str = "", **extra) -> None:
        self._write("executions", {
            "endpoint": endpoint,
            "status": status,
            "duration_seconds": duration_seconds,
            "scan_count": scan_count,
            "opportunities_found": opportunities_found,
            "trades_executed": trades_executed,
            "trades_failed": trades_failed,
            "errors": errors,
            "buying_power_before": buying_power_before,
            "buying_power_after": buying_power_after,
            "portfolio_value": portfolio_value,
            "request_id": request_id,
        })

    def write_scan_result(self, *, symbol: str, stage: str,
                          result: str, reason: str = "",
                          premium: float = 0, delta: float = 0,
                          dte: int = 0, strike_price: float = 0,
                          current_price: float = 0,
                          scan_id: str = "", **extra) -> None:
        self._write("scans", {
            "symbol": symbol,
            "stage": stage,
            "result": result,
            "reason": reason,
            "premium": premium,
            "delta": delta,
            "dte": dte,
            "strike_price": strike_price,
            "current_price": current_price,
            "scan_id": scan_id,
        })

    def write_scan_results_batch(self, rows: List[dict]) -> None:
        """Write a batch of scan results (e.g., all stages for one scan cycle)."""
        self._write_batch("scans", rows)

    def write_wheel_cycle(self, *, symbol: str, put_date: str = "",
                          put_strike: float = 0, put_premium: float = 0,
                          assignment_date: str = "", call_date: str = "",
                          call_strike: float = 0, call_premium: float = 0,
                          capital_gain: float = 0, total_premium: float = 0,
                          total_return: float = 0, duration_days: int = 0,
                          shares: int = 100, **extra) -> None:
        self._write("wheel_cycles", {
            "symbol": symbol,
            "put_date": put_date or None,
            "put_strike": put_strike,
            "put_premium": put_premium,
            "assignment_date": assignment_date or None,
            "call_date": call_date or None,
            "call_strike": call_strike,
            "call_premium": call_premium,
            "capital_gain": capital_gain,
            "total_premium": total_premium,
            "total_return": total_return,
            "duration_days": duration_days,
            "shares": shares,
        })

    def write_position_snapshot(self, *, date: str, symbol: str,
                                 asset_class: str = "account",
                                 shares: int = 0, contracts: int = 0,
                                 cost_basis: float = 0,
                                 market_value: float = 0,
                                 unrealized_pnl: float = 0,
                                 current_price: float = 0,
                                 portfolio_value: float = 0,
                                 cash: float = 0,
                                 buying_power: float = 0, **extra) -> None:
        self._write("position_snapshots", {
            "date": date,
            "symbol": symbol,
            "asset_class": asset_class,
            "shares": shares,
            "contracts": contracts,
            "cost_basis": cost_basis,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "current_price": current_price,
            "portfolio_value": portfolio_value,
            "cash": cash,
            "buying_power": buying_power,
        })

    def write_position_snapshots_batch(self, rows: List[dict]) -> None:
        """Write a batch of position snapshots (e.g., all positions at once)."""
        self._write_batch("position_snapshots", rows)

    def write_order_status(self, *, order_id: str, symbol: str,
                           status: str, side: str = "",
                           order_type: str = "", underlying: str = "",
                           client_order_id: str = "",
                           limit_price: float = 0,
                           filled_price: float = 0,
                           filled_qty: int = 0,
                           submitted_at: str = "",
                           filled_at: str = "", **extra) -> None:
        self._write("order_statuses", {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "symbol": symbol,
            "underlying": underlying,
            "side": side,
            "order_type": order_type,
            "status": status,
            "limit_price": limit_price,
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "submitted_at": submitted_at or None,
            "filled_at": filled_at or None,
        })

    # ------------------------------------------------------------------
    # Query helpers (for dashboard)
    # ------------------------------------------------------------------

    def query(self, table_name: str, query_sql: str) -> List[dict]:
        """Run a query and return results as list of dicts."""
        if not self._enabled:
            return []
        try:
            result = self._client.query(query_sql).result(timeout=60)
            return [dict(row) for row in result]
        except Exception:
            logger.debug("AnalyticsWriter query failed",
                        table=table_name, exc_info=True)
            return []

    @property
    def project_id(self) -> str:
        return self._project_id or ""

    @property
    def dataset_id(self) -> str:
        return self._dataset_id


# --------------------------------------------------------------------------- #
# Module-level singleton
# --------------------------------------------------------------------------- #

_instance: Optional[AnalyticsWriter] = None


def get_analytics_writer() -> AnalyticsWriter:
    """Get or create the AnalyticsWriter singleton."""
    global _instance
    if _instance is None:
        _instance = AnalyticsWriter()
    return _instance
