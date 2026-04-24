"""Alpaca Account Activities → BigQuery ingest (FC-012 Phase 2.1).

Pulls FILL, OPASN, and OPEXP activities from Alpaca's
``/v2/account/activities`` endpoint and appends them to the
``options_wheel.trades_from_activities`` table. Append-only; idempotent by
``activity_id``. Outcome projection happens read-side via the
``trades_with_outcomes`` view — this module does not UPDATE rows.

Cursor strategy:
  - FILL rows use ``transaction_time`` (ISO 8601 with ms).
  - OPASN/OPEXP rows use ``date`` (day-granular) + ``created_at``.
  - ``MAX(transaction_time) FROM trades_from_activities`` is the cursor for
    the next pull. Separately, ``MAX(activity_date)`` is tracked for
    OPASN/OPEXP (which arrive the morning after and carry only ``date``).

See ``docs/plans/fc-012.md`` §2.1.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import structlog

from src.api.alpaca_client import AlpacaClient
from src.utils.option_symbols import parse_option_symbol

logger = structlog.get_logger(__name__)

try:
    from google.cloud import bigquery
    _HAS_BIGQUERY = True
except ImportError:
    _HAS_BIGQUERY = False
    bigquery = None  # type: ignore


ACTIVITY_TYPES = "FILL,OPASN,OPEXP"
TABLE_NAME = "trades_from_activities"


if _HAS_BIGQUERY:
    _SCHEMA = [
        bigquery.SchemaField("activity_id", "STRING", mode="REQUIRED",
                             description="Unique Alpaca activity ID (idempotency key)"),
        bigquery.SchemaField("activity_type", "STRING",
                             description="FILL, OPASN, or OPEXP"),
        bigquery.SchemaField("transaction_time", "TIMESTAMP",
                             description="FILL: transaction_time; OPASN/OPEXP: created_at"),
        bigquery.SchemaField("activity_date", "DATE",
                             description="ET calendar date of the activity"),
        bigquery.SchemaField("order_id", "STRING"),
        bigquery.SchemaField("symbol", "STRING",
                             description="OCC symbol for options, ticker for stocks"),
        bigquery.SchemaField("underlying", "STRING"),
        bigquery.SchemaField("side", "STRING",
                             description="sell_short, buy_to_close, buy, sell, etc."),
        bigquery.SchemaField("qty", "FLOAT"),
        bigquery.SchemaField("price", "FLOAT"),
        bigquery.SchemaField("leaves_qty", "FLOAT"),
        bigquery.SchemaField("cum_qty", "FLOAT"),
        bigquery.SchemaField("order_status", "STRING"),
        bigquery.SchemaField("group_id", "STRING",
                             description="Join key for OPASN/OPEXP back to originating order"),
        bigquery.SchemaField("option_type", "STRING",
                             description="call, put, or null for stock"),
        bigquery.SchemaField("strike_price", "FLOAT"),
        bigquery.SchemaField("expiration", "DATE"),
        bigquery.SchemaField("dte_at_event", "INTEGER"),
        bigquery.SchemaField("premium_total", "FLOAT",
                             description="price * qty * 100 for option FILLs"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP",
                             description="When this row was written to BQ"),
    ]
else:
    _SCHEMA = []


class ActivitiesIngestor:
    """Pulls Alpaca account activities and appends to BigQuery (append-only)."""

    def __init__(self, alpaca: AlpacaClient, project_id: Optional[str] = None,
                 dataset_id: str = "options_wheel") -> None:
        self.alpaca = alpaca
        self._enabled = False
        self._client = None
        self._table_ref = None

        if not _HAS_BIGQUERY:
            logger.warning("google-cloud-bigquery not available — ActivitiesIngestor disabled")
            return

        self._project_id = (
            project_id
            or os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
        )
        if not self._project_id:
            logger.warning("No GCP project ID — ActivitiesIngestor disabled")
            return

        self._dataset_id = dataset_id

        try:
            self._client = bigquery.Client(project=self._project_id)
            self._ensure_table()
            self._enabled = True
            logger.info(
                "ActivitiesIngestor initialised",
                event_category="system",
                event_type="activities_ingestor_initialized",
                project=self._project_id,
                dataset=self._dataset_id,
                table=TABLE_NAME,
            )
        except Exception:
            logger.warning("Failed to initialise ActivitiesIngestor — disabled",
                           exc_info=True)

    def _ensure_table(self) -> None:
        """Create dataset and the trades_from_activities table if they don't exist."""
        dataset_ref = bigquery.DatasetReference(self._project_id, self._dataset_id)
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "us-central1"
        self._client.create_dataset(dataset, exists_ok=True)

        table_ref = dataset_ref.table(TABLE_NAME)
        table = bigquery.Table(table_ref, schema=_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="transaction_time",
        )
        table.clustering_fields = ["symbol", "activity_type"]
        self._client.create_table(table, exists_ok=True)
        self._table_ref = table_ref

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _read_cursor(self) -> tuple[Optional[str], bool]:
        """Return the earliest 'after' date that covers both FILL and OPASN/OPEXP.

        FILL rows use ``transaction_time``; OPASN/OPEXP use ``activity_date``.
        We take the MIN of both maxes as the cursor so neither type is missed.
        The idempotency check drops any rows re-fetched from the cursor day.

        Returns a tuple ``(cursor, ok)``:
          - ``cursor``: ISO date string, or ``None`` if the table is empty (full
            backfill) *or* the cursor query failed.
          - ``ok``: ``True`` on success (including empty-table); ``False`` if
            the query itself failed. Callers surface ``ok=False`` in the result
            dict so a failed cursor read does not masquerade as a fresh start.
        """
        if not self._enabled:
            return None, True

        query = f"""
            SELECT
              MAX(CASE WHEN activity_type = 'FILL' THEN DATE(transaction_time, 'America/New_York') END) AS max_fill_date,
              MAX(CASE WHEN activity_type IN ('OPASN','OPEXP') THEN activity_date END) AS max_opevent_date
            FROM `{self._project_id}.{self._dataset_id}.{TABLE_NAME}`
        """
        try:
            row = next(iter(self._client.query(query).result()), None)
            if row is None:
                return None, True
            fill_date = row["max_fill_date"]
            opevent_date = row["max_opevent_date"]
            candidates = [d for d in (fill_date, opevent_date) if d is not None]
            if not candidates:
                return None, True
            cursor_date = min(candidates)
            return cursor_date.isoformat(), True
        except Exception:
            logger.warning("Cursor read failed — falling back to full backfill",
                           event_category="error",
                           event_type="activities_ingest_cursor_failed",
                           exc_info=True)
            return None, False

    def _existing_ids(self, activity_ids: Iterable[str]) -> set:
        """Return the subset of ``activity_ids`` that already exist in the table."""
        if not self._enabled:
            return set()
        ids = [i for i in activity_ids if i]
        if not ids:
            return set()

        # Parametrized IN clause
        query = f"""
            SELECT activity_id
            FROM `{self._project_id}.{self._dataset_id}.{TABLE_NAME}`
            WHERE activity_id IN UNNEST(@ids)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", ids)]
        )
        try:
            result = self._client.query(query, job_config=job_config).result()
            return {row["activity_id"] for row in result}
        except Exception:
            logger.warning("Existing-id check failed — may double-insert",
                           exc_info=True)
            return set()

    # ------------------------------------------------------------------
    # Pull + normalize
    # ------------------------------------------------------------------

    def _pull_all(self, after: Optional[str]) -> List[Dict[str, Any]]:
        """Paginate through Alpaca activities starting from ``after``.

        Uses ascending order so the ``page_token`` walk produces a stable
        forward-only stream (newest activities last).
        """
        results: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        pages = 0
        while True:
            activities = self.alpaca.get_account_activities(
                activity_types=ACTIVITY_TYPES,
                after=after,
                page_size=100,
                page_token=page_token,
                direction="asc",
            )
            if not activities:
                break
            results.extend(activities)
            pages += 1
            if len(activities) < 100:
                break
            page_token = activities[-1].get("id")
            if pages >= 100:
                logger.warning("ActivitiesIngestor: hit 100-page cap",
                               event_category="system",
                               event_type="activities_ingest_page_cap",
                               collected=len(results))
                break
        return results

    @staticmethod
    def _normalize(activity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a raw Alpaca activity dict into a table row.

        Returns ``None`` if the activity is malformed (no ID).
        """
        activity_id = activity.get("id")
        if not activity_id:
            return None

        activity_type = activity.get("activity_type", "")
        symbol = activity.get("symbol", "") or ""

        # Timestamp normalization — BQ partition field must be non-null.
        # FILL: ``transaction_time``. OPASN/OPEXP: ``created_at``. If neither
        # is present, the row is malformed and is skipped (returning None).
        tx_time = activity.get("transaction_time") or activity.get("created_at")
        if not tx_time:
            return None

        activity_date = activity.get("date")  # present on OPASN/OPEXP

        # Numeric fields
        def _f(key: str) -> Optional[float]:
            v = activity.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        qty = _f("qty")
        price = _f("price")

        # OCC symbol parse — only meaningful for option symbols
        option_type: Optional[str] = None
        strike_price: Optional[float] = None
        expiration: Optional[str] = None
        dte_at_event: Optional[int] = None
        underlying = symbol

        # Option symbols look like e.g. AMD260501P00277500 (>=15 chars + letters+digits).
        # For OPTRD the symbol is an underlying ticker — skip parse in that case.
        if symbol and len(symbol) >= 15 and any(c.isdigit() for c in symbol):
            parsed = parse_option_symbol(symbol)
            if parsed.get("option_type") in ("put", "call"):
                option_type = parsed["option_type"]
                strike_price = parsed.get("strike_price") or None
                expiration = parsed.get("expiration_date")
                dte_at_event = parsed.get("dte")
                underlying = parsed.get("underlying") or symbol

        premium_total: Optional[float] = None
        if option_type and qty is not None and price is not None:
            # qty may be negative (sell); premium_total is signed by convention
            premium_total = price * abs(qty) * 100

        return {
            "activity_id": activity_id,
            "activity_type": activity_type,
            "transaction_time": tx_time,
            "activity_date": activity_date,
            "order_id": activity.get("order_id", ""),
            "symbol": symbol,
            "underlying": underlying,
            "side": activity.get("side", ""),
            "qty": qty,
            "price": price,
            "leaves_qty": _f("leaves_qty"),
            "cum_qty": _f("cum_qty"),
            "order_status": activity.get("order_status", ""),
            "group_id": activity.get("group_id", ""),
            "option_type": option_type,
            "strike_price": strike_price,
            "expiration": expiration,
            "dte_at_event": dte_at_event,
            "premium_total": premium_total,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def run_once(self) -> Dict[str, Any]:
        """Pull new activities and append them to BigQuery. Idempotent.

        Returns a summary dict for the endpoint response.
        """
        if not self._enabled:
            return {"status": "disabled", "reason": "BigQuery unavailable"}

        after, cursor_ok = self._read_cursor()
        logger.info("ActivitiesIngestor run_once starting",
                    event_category="system",
                    event_type="activities_ingest_started",
                    after=after,
                    cursor_ok=cursor_ok)

        try:
            raw_activities = self._pull_all(after)
        except Exception as exc:
            logger.error("ActivitiesIngestor pull failed",
                         event_category="error",
                         event_type="activities_ingest_pull_failed",
                         error=str(exc),
                         exc_info=True)
            return {"status": "failed", "reason": "pull_error",
                    "error": str(exc), "cursor_ok": cursor_ok}

        if not raw_activities:
            logger.info("ActivitiesIngestor no new activities",
                        event_category="system",
                        event_type="activities_ingest_no_new")
            return {"status": "ok", "fetched": 0, "inserted": 0,
                    "skipped": 0, "cursor_ok": cursor_ok}

        rows: List[Dict[str, Any]] = []
        malformed = 0
        for a in raw_activities:
            row = self._normalize(a)
            if row is None:
                malformed += 1
            else:
                rows.append(row)

        # Dedup against existing
        candidate_ids = [r["activity_id"] for r in rows]
        existing = self._existing_ids(candidate_ids)
        new_rows = [r for r in rows if r["activity_id"] not in existing]

        if not new_rows:
            logger.info("ActivitiesIngestor all activities already present",
                        event_category="system",
                        event_type="activities_ingest_all_duplicate",
                        fetched=len(rows),
                        malformed=malformed)
            return {"status": "ok", "fetched": len(rows),
                    "inserted": 0, "skipped": len(rows),
                    "malformed": malformed, "cursor_ok": cursor_ok}

        # Pass row_ids= for streaming-insert dedup (BigQuery best-effort).
        row_ids = [r["activity_id"] for r in new_rows]
        try:
            errors = self._client.insert_rows_json(
                self._table_ref, new_rows, row_ids=row_ids,
            )
            if errors:
                logger.error("ActivitiesIngestor BQ insert errors",
                             event_category="error",
                             event_type="activities_ingest_insert_errors",
                             errors=str(errors)[:500])
                # Per-row errors are not a retry-worthy failure; the scheduler
                # should not storm-retry. Surface as partial with 200 status.
                return {"status": "partial", "fetched": len(rows),
                        "inserted": 0, "skipped": len(existing),
                        "errors": str(errors)[:500],
                        "malformed": malformed, "cursor_ok": cursor_ok}
        except Exception as exc:
            logger.error("ActivitiesIngestor BQ insert failed",
                         event_category="error",
                         event_type="activities_ingest_insert_failed",
                         error=str(exc),
                         exc_info=True)
            return {"status": "failed", "reason": "insert_error",
                    "error": str(exc), "cursor_ok": cursor_ok}

        logger.info("ActivitiesIngestor inserted rows",
                    event_category="system",
                    event_type="activities_ingest_completed",
                    fetched=len(rows),
                    inserted=len(new_rows),
                    skipped=len(existing),
                    malformed=malformed)

        return {
            "status": "ok",
            "fetched": len(rows),
            "inserted": len(new_rows),
            "skipped": len(existing),
            "malformed": malformed,
            "cursor_ok": cursor_ok,
        }
