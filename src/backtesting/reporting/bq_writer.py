"""Persist screen-mode results to BigQuery (`options_wheel.backtest_runs`).

One row per symbol per screening run, so demotion candidates are queryable and
the dashboard can consume them later.

Two deliberate choices, both learned the hard way in this FC:

**A failed write is reported, never swallowed.** `AnalyticsWriter` is
fire-and-forget by design — losing an analytics row is cheaper than blocking a
trade. This is the opposite: a screen that silently drops rows produces a
partial table an operator will read as complete, and that table is the input to
a demotion decision. Writes here return success, and the caller surfaces it.

**Every row carries its config hash and the engine's known biases.** A verdict
read six months from now is meaningless without knowing which premium floor and
delta band produced it, or that dividends were unmodeled at the time.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

try:  # pragma: no cover - exercised only where the dep is installed
    from google.cloud import bigquery
    _HAS_BIGQUERY = True
except ImportError:  # pragma: no cover
    _HAS_BIGQUERY = False

TABLE_NAME = "backtest_runs"


def _schema():
    """BigQuery schema for one screened symbol. Documented in docs/bigquery/."""
    f = bigquery.SchemaField
    return [
        # Run identity
        f("run_id", "STRING", mode="REQUIRED"),
        f("timestamp", "TIMESTAMP", mode="REQUIRED"),
        f("symbol", "STRING", mode="REQUIRED"),
        f("window_start", "DATE"),
        f("window_end", "DATE"),
        f("config_hash", "STRING"),
        f("engine_version", "STRING"),
        # Scope. Without these, "the latest run" (ORDER BY timestamp DESC) picks
        # whichever run happened last — so a 2-symbol ad-hoc probe hides a full
        # screen's demotion candidates and its failures. The endpoint's own 413
        # tells operators to make exactly those ad-hoc runs.
        f("run_kind", "STRING"),        # 'full' | 'adhoc'
        f("universe_size", "INTEGER"),  # symbols attempted in this run
        # Verdict — what a human acts on
        f("verdict", "STRING"),
        f("demote", "BOOL"),
        f("verdict_reasons", "STRING", mode="REPEATED"),
        f("binding_constraint", "STRING"),
        # Headline performance
        f("starting_cash", "FLOAT"),
        f("final_equity", "FLOAT"),
        f("total_return", "FLOAT"),
        f("annualized_return", "FLOAT"),
        f("annualized_return_on_collateral", "FLOAT"),
        f("benchmark_return", "FLOAT"),
        f("excess_return", "FLOAT"),
        # Attribution — never collapsed
        f("option_pnl", "FLOAT"),
        f("stock_pnl_realized", "FLOAT"),
        f("stock_pnl_unrealized", "FLOAT"),
        f("option_pnl_share", "FLOAT"),
        f("reconciliation_gap", "FLOAT"),
        # Activity and risk
        f("decision_days", "INTEGER"),
        f("days_in_position", "INTEGER"),
        f("days_in_position_fraction", "FLOAT"),
        f("cycles_completed", "INTEGER"),
        f("cycles_open", "INTEGER"),
        f("puts_sold", "INTEGER"),
        f("calls_sold", "INTEGER"),
        f("win_rate", "FLOAT"),
        f("assignment_rate", "FLOAT"),
        f("max_drawdown", "FLOAT"),
        f("days_underwater", "INTEGER"),
        f("avg_collateral", "FLOAT"),
        # Fill sensitivity — a verdict that flips is not a verdict
        f("bid_fill_return", "FLOAT"),
        f("verdict_flips_on_fill", "BOOL"),
        # Provenance
        f("known_biases", "STRING", mode="REPEATED"),
        f("error", "STRING"),
    ]


def config_hash(config) -> str:
    """Stable hash of the strategy parameters that shape a verdict.

    A verdict is only interpretable alongside the thresholds that produced it;
    without this, a re-run under a changed premium floor is indistinguishable
    from a genuine change in the symbol.
    """
    keys = [
        "put_target_dte", "call_target_dte", "put_delta_range", "call_delta_range",
        "min_put_premium", "min_call_premium", "max_position_size",
        "max_stock_price", "min_stock_price", "gap_lookback_days",
        "max_gap_frequency", "execution_gap_threshold",
    ]
    payload = {k: getattr(config, k, None) for k in keys}

    # The verdict is not computed from config alone: these live as module
    # constants and a default argument, and changing any of them flips symbols.
    # Omitting them made a threshold change byte-identical to a symbol change —
    # the exact confusion this hash exists to prevent.
    from ..evaluate import DEFAULT_FILL_HAIRCUT
    from ..metrics import fitness as _fit
    payload["_scoring"] = {
        "min_days_in_position": _fit.MIN_DAYS_IN_POSITION,
        "risk_free_rate": _fit.RISK_FREE_RATE,
        "max_drawdown_warn": _fit.MAX_DRAWDOWN_WARN,
        "fill_haircut": DEFAULT_FILL_HAIRCUT,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class BacktestRunWriter:
    """Writes screen-mode rows to `options_wheel.backtest_runs`."""

    def __init__(self, project_id: Optional[str] = None,
                 dataset_id: str = "options_wheel") -> None:
        self._enabled = False
        self._table = None

        if not _HAS_BIGQUERY:
            logger.warning("google-cloud-bigquery not installed — screen results "
                           "will NOT be persisted")
            return

        self._project_id = (
            project_id
            or os.environ.get("GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_PROJECT_ID")
        )
        if not self._project_id:
            logger.warning("No GCP project ID — screen results will NOT be persisted")
            return

        self._dataset_id = dataset_id
        try:
            self._client = bigquery.Client(project=self._project_id)
            dataset_ref = bigquery.DatasetReference(self._project_id, dataset_id)
            dataset = bigquery.Dataset(dataset_ref)
            dataset.location = "us-central1"
            self._client.create_dataset(dataset, exists_ok=True)

            table_ref = dataset_ref.table(TABLE_NAME)
            table = bigquery.Table(table_ref, schema=_schema())
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="timestamp",
            )
            existing = self._client.create_table(table, exists_ok=True)

            # create_table(exists_ok=True) returns the EXISTING table and never
            # reconciles its schema. Left alone, the first release that adds a
            # field makes every row carry an unknown key — and insert_rows_json
            # rejects the WHOLE request rather than the offending row, so a run
            # writes ZERO rows. Reconcile additive fields explicitly.
            have = {f.name for f in (existing.schema or [])}
            missing = [f for f in _schema() if f.name not in have]
            if missing:
                existing.schema = list(existing.schema) + missing
                self._client.update_table(existing, ["schema"])
                logger.info("Extended backtest_runs schema",
                            event_category="backtest",
                            event_type="screen_schema_extended",
                            added=[f.name for f in missing])
            self._table = table_ref
            self._enabled = True
        except Exception:
            logger.warning("BacktestRunWriter init failed — results will NOT be "
                           "persisted", exc_info=True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def write(self, rows: List[Dict[str, Any]]) -> bool:
        """Insert rows. Returns True only if every row landed.

        Unlike the fire-and-forget analytics path, the caller is expected to act
        on a False: a partially-written screen table reads as a complete one.
        """
        if not rows:
            return True
        if not self._enabled:
            logger.error(
                "Screen results NOT persisted — writer disabled",
                event_category="backtest", event_type="screen_write_skipped",
                rows=len(rows),
            )
            return False
        try:
            errors = self._client.insert_rows_json(self._table, rows)
        except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
            logger.error("Screen results write FAILED",
                         event_category="backtest",
                         event_type="screen_write_failed",
                         rows=len(rows), error=str(exc)[:200])
            return False
        if errors:
            logger.error("Screen results write returned errors",
                         event_category="backtest",
                         event_type="screen_write_errors",
                         errors=str(errors)[:400])
            return False
        logger.info("Screen results persisted",
                    event_category="backtest", event_type="screen_write_ok",
                    rows=len(rows), table=f"{self._dataset_id}.{TABLE_NAME}")
        return True


def build_row(*, run_id: str, symbol: str, report, sensitivity: Optional[dict],
              cfg_hash: str, engine_version: str,
              error: Optional[str] = None,
              run_kind: str = "full", universe_size: Optional[int] = None,
              window_start=None, window_end=None) -> Dict[str, Any]:
    """Flatten a FitnessReport into one BigQuery row.

    A symbol that failed still gets a row, carrying ``error`` and a null verdict.
    Dropping it would make the run look like it screened fewer symbols than it
    attempted — the difference between "KMI is fine" and "KMI was never checked".
    """
    now = datetime.now(timezone.utc).isoformat()
    if report is None:
        # A failed symbol keeps its window: a window-scoped query would
        # otherwise drop exactly the never-checked symbols the docs say to hunt.
        return {
            "run_id": run_id, "timestamp": now, "symbol": symbol,
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat() if window_end else None,
            "config_hash": cfg_hash, "engine_version": engine_version,
            "run_kind": run_kind, "universe_size": universe_size,
            "verdict": None, "demote": None, "error": (error or "unknown")[:500],
        }

    from .report import KNOWN_BIASES

    verdict = report.verdict()
    return {
        "run_id": run_id,
        "timestamp": now,
        "symbol": symbol,
        "window_start": report.start.isoformat(),
        "window_end": report.end.isoformat(),
        "config_hash": cfg_hash,
        "engine_version": engine_version,
        "run_kind": run_kind,
        "universe_size": universe_size,

        "verdict": verdict,
        # Demotion is a *recommendation*; the plan keeps the decision human.
        #
        # Two verdicts deliberately do NOT set it:
        #   'insufficient' — the window did not contain a completed cycle, which
        #     is a statement about the window, not the symbol;
        #   any verdict that flips between mid-fill and bid-fill — the report's
        #     own bias footer says such a verdict "is not a verdict", so acting
        #     on it would contradict the engine's own caveat.
        "demote": (
            verdict == "unfit"
            and not (sensitivity or {}).get("verdict_flips", False)
        ),
        "verdict_reasons": report.verdict_reasons(),
        "binding_constraint": _binding(report),

        "starting_cash": report.starting_cash,
        "final_equity": report.final_equity,
        "total_return": report.total_return,
        "annualized_return": report.annualized_return,
        "annualized_return_on_collateral": report.annualized_return_on_collateral,
        "benchmark_return": report.benchmark.total_return if report.benchmark else None,
        "excess_return": report.excess_return,

        "option_pnl": report.option_pnl,
        "stock_pnl_realized": report.stock_pnl,
        "stock_pnl_unrealized": report.unrealized_stock_pnl,
        "option_pnl_share": report.option_pnl_share,
        "reconciliation_gap": report.reconciliation_gap,

        "decision_days": report.decision_days,
        "days_in_position": report.days_in_position,
        "days_in_position_fraction": report.days_in_position_fraction,
        "cycles_completed": len(report.closed_cycles),
        "cycles_open": len(report.cycles) - len(report.closed_cycles),
        "puts_sold": report.puts_sold,
        "calls_sold": report.calls_sold,
        "win_rate": report.win_rate,
        "assignment_rate": report.assignment_rate,
        "max_drawdown": report.max_drawdown,
        "days_underwater": report.days_underwater,
        "avg_collateral": report.avg_collateral,

        "bid_fill_return": (sensitivity or {}).get("bid_return"),
        "verdict_flips_on_fill": (sensitivity or {}).get("verdict_flips"),

        "known_biases": [title for title, _detail in KNOWN_BIASES],
        "error": None,
    }


def _binding(report) -> Optional[str]:
    blocked = report.data_quality.get("blocked_days_by_reason") or {}
    return next(iter(blocked), None) if blocked else None
