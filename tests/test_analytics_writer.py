"""Contract tests for AnalyticsWriter's managed table set.

`_ensure_all_tables()` auto-creates a BigQuery table for every key in
`_SCHEMAS` on service start. That makes the schema dict a deploy-time side
effect, not just a declaration: re-adding a key silently recreates the table on
the next cold start.

FC-035 dropped `order_statuses` (never populated — the poll feeding it never
executed; fills come from the activities ingestor). Without a contract test,
re-adding the schema entry would quietly resurrect the dropped table.
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

    assert set(_SCHEMAS) == {"errors", "executions", "wheel_cycles"}, (
        f"managed analytics tables changed: {sorted(_SCHEMAS)}. Each key here is "
        "auto-created in BigQuery on service start — update this test "
        "deliberately if that is intended."
    )


def test_writer_has_no_order_status_method():
    """The only writer of the dropped table is gone."""
    from src.data.analytics_writer import AnalyticsWriter

    assert not hasattr(AnalyticsWriter, "write_order_status")
