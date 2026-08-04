"""Contract tests for AnalyticsWriter's managed table set.

`_ensure_all_tables()` auto-creates a BigQuery table for every key in
`_SCHEMAS` on service start. That makes the schema dict a deploy-time side
effect, not just a declaration: re-adding a key silently recreates the table on
the next cold start.

FC-035 dropped `order_statuses` (never populated — the poll feeding it never
executed; fills come from the activities ingestor). FC-069 item 10 dropped
`wheel_cycles` (every row zero-gain by construction, re-duplicated on every
cold start, zero readers). Without a contract test, re-adding either schema
entry would quietly resurrect the dropped table.
"""

from src.data.analytics_writer import _SCHEMAS, _HAS_BIGQUERY


def test_order_statuses_is_not_a_managed_table():
    """Deleted in FC-035. Re-adding this key recreates the dropped BQ table."""
    assert "order_statuses" not in _SCHEMAS, (
        "order_statuses was dropped in FC-035; re-adding it to _SCHEMAS would "
        "auto-recreate the table on the next deploy via _ensure_all_tables()"
    )


def test_managed_table_set_is_explicit():
    """Adding a genuinely new analytics table must be a conscious edit here.

    When BigQuery isn't installed, _SCHEMAS is empty by design.
    """
    if not _HAS_BIGQUERY:
        assert _SCHEMAS == {}
        return

    # `decision_events` added deliberately by FC-065 Phase 4. Auto-creation on
    # the next cold start IS the bootstrap — no manual `bq mk` step.
    assert set(_SCHEMAS) == {"errors", "executions", "decision_events"}, (
        f"managed analytics tables changed: {sorted(_SCHEMAS)}. Each key here is "
        "auto-created in BigQuery on service start — update this test "
        "deliberately if that is intended."
    )


def test_wheel_cycles_is_not_a_managed_table():
    """Deleted in FC-069 item 10. Re-adding this key recreates the dropped table.

    The table's rows were garbage by construction: `capital_gain` derived from
    a `wheel_state` field that never resolved (always 0), and the per-instance
    dedup did not survive cold starts, so every fresh instance re-wrote the
    same assignments from a 7-day activity window. Completed cycles are read
    from the `wheel_cycles_from_activities` VIEW, which is unaffected.
    """
    assert "wheel_cycles" not in _SCHEMAS, (
        "wheel_cycles was dropped in FC-069; re-adding it to _SCHEMAS would "
        "auto-recreate the table on the next deploy via _ensure_all_tables()"
    )


def test_writer_has_no_order_status_method():
    """The only writer of the dropped table is gone."""
    from src.data.analytics_writer import AnalyticsWriter

    assert not hasattr(AnalyticsWriter, "write_order_status")


def test_writer_has_no_wheel_cycle_method():
    """The only writer of the FC-069-dropped table is gone."""
    from src.data.analytics_writer import AnalyticsWriter

    assert not hasattr(AnalyticsWriter, "write_wheel_cycle")
