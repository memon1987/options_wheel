#!/usr/bin/env python3
"""One-time migration: backfill dedicated BQ tables from log-sink data.

Reads historical data from the options_wheel_logs.run_googleapis_com_stderr_*
tables and inserts it into the new dedicated options_wheel.* tables.

Run once after the new tables are created:
    python scripts/backfill_analytics.py

This uses JSON_VALUE(TO_JSON_STRING()) for safe extraction from the
inconsistent log-sink schemas. The dedicated tables have fixed schemas.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from google.cloud import bigquery

PROJECT_ID = os.environ.get("GCP_PROJECT", "gen-lang-client-0607444019")
LOG_DATASET = "options_wheel_logs"
ANALYTICS_DATASET = "options_wheel"


def main():
    # Create dataset and all tables first via AnalyticsWriter
    print("Creating dataset and tables...")
    from src.data.analytics_writer import AnalyticsWriter
    writer = AnalyticsWriter(project_id=PROJECT_ID)
    if writer.enabled:
        print(f"  Dataset and tables created in {PROJECT_ID}.{ANALYTICS_DATASET}")
    else:
        print("  ERROR: AnalyticsWriter failed to initialize. Check GCP credentials.")
        return

    client = bigquery.Client(project=PROJECT_ID)
    log_table = f"`{PROJECT_ID}.{LOG_DATASET}.run_googleapis_com_stderr_*`"
    suffix_filter = "_TABLE_SUFFIX BETWEEN '20251015' AND '20260406'"

    # ------------------------------------------------------------------ #
    # 1. Backfill trades
    # ------------------------------------------------------------------ #
    print("Backfilling trades...")
    trades_query = f"""
    INSERT INTO `{PROJECT_ID}.{ANALYTICS_DATASET}.trades`
    (order_id, symbol, underlying, option_type, side, qty, strike_price,
     premium, limit_price, total_premium, collateral, status, strategy,
     dte, roi, timestamp)
    SELECT
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.order_id'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.symbol'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.underlying'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.option_type'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.side'),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.contracts') AS INT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.strike_price') AS FLOAT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.premium') AS FLOAT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.limit_price') AS FLOAT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.premium') AS FLOAT64)
          * SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.contracts') AS FLOAT64) * 100,
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.collateral_required') AS FLOAT64),
        'backfilled',
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.strategy'),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.dte') AS INT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.roi') AS FLOAT64),
        timestamp
    FROM {log_table}
    WHERE JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_category') = 'trade'
        AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_type') IN (
            'put_sale_executed', 'call_sale_executed', 'early_close_executed'
        )
        AND {suffix_filter}
    """
    result = client.query(trades_query).result()
    print(f"  Trades backfilled: {result.total_rows if hasattr(result, 'total_rows') else 'done'}")

    # ------------------------------------------------------------------ #
    # 2. Backfill errors
    # ------------------------------------------------------------------ #
    print("Backfilling errors...")
    errors_query = f"""
    INSERT INTO `{PROJECT_ID}.{ANALYTICS_DATASET}.errors`
    (timestamp, event_type, error_type, error_message, symbol, component, recoverable)
    SELECT
        timestamp,
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_type'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.error_type'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.error_message'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.symbol'),
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.component'),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.recoverable') AS BOOL)
    FROM {log_table}
    WHERE JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_category') = 'error'
        AND {suffix_filter}
    """
    result = client.query(errors_query).result()
    print(f"  Errors backfilled: done")

    # ------------------------------------------------------------------ #
    # 3. Backfill executions (from strategy_execution_completed events)
    # ------------------------------------------------------------------ #
    print("Backfilling executions...")
    exec_query = f"""
    INSERT INTO `{PROJECT_ID}.{ANALYTICS_DATASET}.executions`
    (timestamp, endpoint, status, duration_seconds, trades_executed, trades_failed)
    SELECT
        timestamp,
        '/run',
        JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.status'),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.duration_seconds') AS FLOAT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.trades_executed') AS INT64),
        SAFE_CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.trades_failed') AS INT64)
    FROM {log_table}
    WHERE JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_type') = 'strategy_execution_completed'
        AND {suffix_filter}
    """
    result = client.query(exec_query).result()
    print(f"  Executions backfilled: done")

    # ------------------------------------------------------------------ #
    # 4. Backfill wheel cycles — REMOVED in FC-069 (item 10).
    #    The wheel_cycles table it inserted into was snapshotted and
    #    dropped; the six hand-identified cycles it wrote are recoverable
    #    from git history and from trades_from_activities, which is the
    #    authoritative source the wheel_cycles_from_activities view reads.
    # ------------------------------------------------------------------ #

    print("\nBackfill complete.")
    print("Note: wheel_cycles removed in FC-069; order_statuses removed in FC-035; "
          "position_snapshots and scans removed in FC-012.")


if __name__ == "__main__":
    main()
