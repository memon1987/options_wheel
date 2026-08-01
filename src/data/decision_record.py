"""FC-065 Phase 4 — the per-symbol covered-call decision record.

For any held symbol on any cycle this module produces a durable answer to
"did we sell a call, and if not, why not."  It exists because the honest
answer today is *silence*: an underwater position yields nothing, no event
says so, and the structured logs that would tell you live only in Cloud
Logging's 30-day window (the BigQuery sink died 2025-11-22 — FC-046).

Shape, adopted from **FC-044 Phase 1's `decision_events` design** (that
phase is subsumed here; FC-044's Phase 2 grid UI reads this table):

  * one row per ``(run_id, symbol, stage)`` — the dedup key,
  * a **closed** outcome enum with a per-outcome reason vocabulary,
  * two legibility labels on every row (``underwater_pct``,
    ``uncovered_days``) — what survives of FC-029 R3 after OQ-3 removed the
    pause gate,
  * written through ``AnalyticsWriter`` to a dedicated, code-schema'd
    BigQuery table, never through the dead log sink.

Two deliberate departures from FC-044's sketch, both recorded in the plan's
Execution notes:

1. FC-044 proposed a ``metrics JSON`` column.  This module flattens the
   metrics to typed scalars and models the chain-rejection breakdown as a
   REPEATED RECORD instead.  String-ifying structures into a BigQuery column
   is the 2026-04-07 schema lesson this codebase paid for once already.
2. FC-044's ``gate`` column is folded into ``stage`` + ``reason``; a separate
   gate name would have been a third vocabulary saying the same thing.

**A cycle produces exactly one terminal row per held symbol, written by
whichever stage terminated it.**  The scan stage terminates a symbol that is
not eligible, is blocked by the floor, or produced no candidates; the run
stage terminates everything else (``sold`` / ``dropped``).  A held symbol
with *zero* rows for a scan-hour therefore means "the cycle did not complete
for this symbol" — a scheduler miss or a /run failure — which is exactly the
silent non-execution the fill-rate check watches for.  See
``docs/operations/DECISION_RECORDS.md``.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import structlog

from ..strategy.execution_engine import DROP_REASONS
from ..utils.option_symbols import strict_option_type

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

STAGE_SCAN = "scan"
STAGE_RUN = "run"
STAGES = (STAGE_SCAN, STAGE_RUN)

_ENDPOINT_BY_STAGE = {STAGE_SCAN: "/scan", STAGE_RUN: "/run"}

# ---------------------------------------------------------------------------
# The closed outcome enum
# ---------------------------------------------------------------------------
#
# NOTE (approved deviation, FC-065 Phase 4): the plan's enum text still lists a
# ``paused{drawdown, duration_days}`` variant, written before OQ-3.  The
# operator removed the pause gate entirely (plan §"Phase 3 ... REMOVED"), so
# there is no code path that could ever produce it — a value no producer can
# emit is not a state, it is a trap for whoever queries this table later.  It
# is deliberately absent.  If a pause gate is ever built, adding the value here
# is a one-line change and the validator will start accepting it.

OUTCOME_SOLD = "sold"
OUTCOME_NO_CANDIDATES = "no_candidates"
OUTCOME_DROPPED = "dropped"
OUTCOME_BLOCKED = "blocked"
OUTCOME_NOT_ELIGIBLE = "not_eligible"

OUTCOMES = (
    OUTCOME_SOLD,
    OUTCOME_NO_CANDIDATES,
    OUTCOME_DROPPED,
    OUTCOME_BLOCKED,
    OUTCOME_NOT_ELIGIBLE,
)

# --- reasons, scoped to the outcome they qualify -------------------------- #

# blocked{...}
REASON_FLOOR_UNRESOLVED = "floor_unresolved"
REASON_FLOOR_DIVERGENT = "floor_divergent"
# not_eligible{...}
REASON_INSUFFICIENT_SHARES = "insufficient_shares"
# no_candidates{...}
REASON_NO_QUALIFYING_STRIKES = "no_qualifying_strikes"
REASON_QUOTE_UNAVAILABLE = "quote_unavailable"
# dropped{...} — beyond FC-038's selection enum
REASON_EXECUTION_FAILED = "execution_failed"
REASON_ALREADY_POSITIONED = "already_positioned"
REASON_PREVIOUSLY_FAILED = "previously_failed"
REASON_NOT_SELECTED = "not_selected"

_DROPPED_REASONS = frozenset(DROP_REASONS) | {
    REASON_EXECUTION_FAILED,
    REASON_ALREADY_POSITIONED,
    REASON_PREVIOUSLY_FAILED,
    REASON_NOT_SELECTED,
}

ALLOWED_REASONS: Dict[str, frozenset] = {
    OUTCOME_SOLD: frozenset({""}),
    OUTCOME_NO_CANDIDATES: frozenset(
        {REASON_NO_QUALIFYING_STRIKES, REASON_QUOTE_UNAVAILABLE}),
    OUTCOME_DROPPED: _DROPPED_REASONS,
    OUTCOME_BLOCKED: frozenset({REASON_FLOOR_UNRESOLVED, REASON_FLOOR_DIVERGENT}),
    OUTCOME_NOT_ELIGIBLE: frozenset({REASON_INSUFFICIENT_SHARES}),
}


class UnknownDecisionOutcome(ValueError):
    """Raised for an outcome/reason pair outside the closed vocabulary.

    Deliberately an exception rather than a coerced ``"unknown"`` row: a
    silently-accepted novel outcome is how a decision table stops being a
    decision table.  Callers that must not crash a trading cycle catch it at
    the recorder boundary and drop the row *loudly* (see
    ``DecisionRecorder.record``).
    """


def validate_outcome(outcome: str, reason: str = "") -> None:
    """Raise :class:`UnknownDecisionOutcome` unless the pair is in the enum."""
    if outcome not in ALLOWED_REASONS:
        raise UnknownDecisionOutcome(
            f"unknown decision outcome {outcome!r}; expected one of {OUTCOMES}")
    allowed = ALLOWED_REASONS[outcome]
    if (reason or "") not in allowed:
        raise UnknownDecisionOutcome(
            f"reason {reason!r} is not valid for outcome {outcome!r}; "
            f"expected one of {sorted(allowed)}")


# ---------------------------------------------------------------------------
# run_id
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")


def mint_run_id(scan_time: Optional[datetime] = None) -> str:
    """Mint the identifier that joins one ``/scan`` to its ``/run``.

    Timestamp prefix so a human reading a row can place it in the day without
    a join, random suffix so two scans in the same second cannot collide.
    Minted **once per /scan** and carried into ``/run`` on the opportunity
    blob — before this, the blob itself was the only correlator between the
    two stateless requests (FC-044's survey).
    """
    ts = scan_time or datetime.now(timezone.utc)
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return f"{ts.strftime('%Y%m%dT%H%M%S')}Z-{uuid.uuid4().hex[:8]}"


def is_run_id(value: Any) -> bool:
    """True for a string minted by :func:`mint_run_id`."""
    return isinstance(value, str) and bool(_RUN_ID_RE.match(value))


def stamp_run_id(opportunities: Sequence[Dict[str, Any]], run_id: str) -> int:
    """Write ``run_id`` onto every opportunity; returns how many were stamped.

    Stamped per-opportunity rather than only on the blob envelope because
    ``OpportunityStore.get_pending_opportunities`` hands ``/run`` the
    opportunity list and nothing else — putting the id only in the envelope
    would have meant changing that return shape and every caller with it.
    """
    if not run_id:
        return 0
    stamped = 0
    for opportunity in opportunities or []:
        if isinstance(opportunity, dict):
            opportunity['run_id'] = run_id
            stamped += 1
    return stamped


def run_id_from_opportunities(opportunities: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The ``run_id`` stamped on a blob's opportunities, if any carry one.

    Returns ``None`` for a blob written before this phase deployed, so the
    caller can decide (``/run`` mints an orphan id and says so, rather than
    dropping the cycle's telemetry on the floor).
    """
    for opp in opportunities or []:
        candidate = opp.get("run_id") if isinstance(opp, dict) else None
        if is_run_id(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# The two legibility labels
# ---------------------------------------------------------------------------


def underwater_pct(current_price: Optional[float],
                   floor: Optional[float]) -> Optional[float]:
    """Signed price-vs-floor distance, as a fraction of the floor.

    **Sign convention matches the plan's own example** ("NVDA ... underwater
    −8.9%"): *negative is underwater*.  ``(price − floor) / floor``.  A
    positive value means the position is above its covered-call floor and
    strikes at or above the floor are available in principle.

    Returns ``None`` when either input is missing or the floor is
    non-positive — "not computable" is a distinct state from 0% and must not
    render as "at the floor".
    """
    try:
        price = float(current_price)
        base = float(floor)
    except (TypeError, ValueError):
        return None
    if base <= 0 or price <= 0:
        return None
    return round((price - base) / base, 6)


def position_mark_price(position: Dict[str, Any]) -> Optional[float]:
    """Broker mark for an equity position: ``market_value / qty``.

    Derived from the position dict the scanner already holds rather than a
    second quote fetch.  It is the broker's own mark, so it cannot disagree
    with the ``avg_entry_price`` on the same dict the way an independently
    fetched quote can, and it costs no API call for symbols that produced no
    candidates (which is precisely the population this record exists for).
    """
    try:
        qty = float(position.get("qty") or 0)
        market_value = float(position.get("market_value") or 0)
    except (TypeError, ValueError):
        return None
    if qty <= 0 or market_value <= 0:
        return None
    return market_value / qty


def covered_underlyings(positions: Iterable[Dict[str, Any]]) -> set:
    """Underlyings that currently have a short call open against them.

    Classification goes through ``strict_option_type`` — the canonical OCC
    parser.  Six instances of substring-matching an OCC symbol
    (FC-041/043/045/048/052) say do not hand-roll this.
    """
    covered = set()
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        if pos.get("asset_class") != "us_option":
            continue
        symbol = pos.get("symbol") or ""
        if strict_option_type(symbol) != "call":
            continue
        try:
            qty = float(pos.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if qty >= 0:  # long calls are not coverage
            continue
        from ..utils.option_symbols import parse_option_symbol
        underlying = parse_option_symbol(symbol).get("underlying")
        if underlying:
            covered.add(underlying)
    return covered


class UncoveredDaysResolver:
    """How many trading days a held symbol has gone without a covered call.

    **Stateless by construction** — wheel-state persistence has never worked
    (``STATE_STORAGE_BUCKET`` unset since inception), so this derives the
    answer from two durable sources the plan names:

    * **Alpaca positions** (already in hand): a symbol with an open short call
      is covered *right now*, so the answer is ``0`` without touching
      BigQuery.  This is the common case and it short-circuits first.
    * **BigQuery ``trades_from_activities``** for everything else: the anchor
      is the most recent **call-leg** activity on the underlying (a write, a
      close, an expiry or an exercise — any of them means the shares were
      covered that day).  A lot that has *never* had a call written falls back
      to the **put assignment** that created it, which is the day the shares
      became coverable.  Trading days are counted against the same
      ``stock_history_from_alpaca`` benchmark-symbol calendar the dashboard's
      anomaly detection uses (FC-031), not against a hand-rolled weekday
      count — holidays are real and ">= 7 trading days" is an alert boundary.

    Cost is **one batched query per scan** for all held symbols, not one per
    symbol; it is issued after the per-symbol floor work, so it adds a single
    round trip to a ~18s scan.

    ``None`` is returned for a symbol whose anchor cannot be established (no
    history, BigQuery unreachable, feature gated off).  ``None`` is *not*
    zero: it means "we could not tell", and the alert path treats it as such.
    """

    #: Trading-day calendar source. Matches the dashboard's BENCHMARK_SYMBOL
    #: default and the stock-history ingestor's benchmark set.
    CALENDAR_SYMBOL = os.getenv("BENCHMARK_SYMBOL", "SPY")

    def __init__(self, allow_bigquery: bool = True,
                 dataset_id: str = "options_wheel"):
        self.allow_bigquery = allow_bigquery
        self.dataset_id = dataset_id
        self._bq_client = None

    def resolve(self, symbols: Sequence[str],
                covered: Optional[set] = None) -> Dict[str, Optional[int]]:
        """``{symbol: trading days uncovered}``; ``0`` when covered today."""
        covered = covered or set()
        wanted = [s for s in dict.fromkeys(symbols) if s]
        result: Dict[str, Optional[int]] = {s: 0 for s in wanted if s in covered}

        to_lookup = [s for s in wanted if s not in covered]
        if not to_lookup:
            return result

        anchors = self._lookup_uncovered_days(to_lookup) or {}
        for symbol in to_lookup:
            value = anchors.get(symbol)
            result[symbol] = int(value) if value is not None else None
        return result

    def _lookup_uncovered_days(
        self, symbols: Sequence[str]
    ) -> Optional[Dict[str, int]]:
        """**The single BigQuery chokepoint of the decision-record layer.**

        The suite's hermeticity guard (``tests/conftest.py``) patches this one
        method, exactly as it does ``CostBasisResolver._lookup_assignment_basis``
        — any future BigQuery read on this path must come through here rather
        than open a second door.

        Returns ``None`` on any failure ("we could not tell"), never ``{}``
        masquerading as "zero days for everyone".
        """
        if not self.allow_bigquery:
            logger.debug("Uncovered-days lookup disabled",
                         event_category="data",
                         event_type="uncovered_days_lookup_disabled",
                         symbols=",".join(symbols))
            return None

        try:
            from google.cloud import bigquery
            if self._bq_client is None:
                project_id = (
                    os.environ.get('GCP_PROJECT')
                    or os.environ.get('GOOGLE_CLOUD_PROJECT')
                    or os.environ.get('GCP_PROJECT_ID')
                )
                self._bq_client = (bigquery.Client(project=project_id)
                                   if project_id else bigquery.Client())

            query = f"""
            WITH anchors AS (
              SELECT
                underlying,
                MAX(IF(option_type = 'call', DATE(transaction_time), NULL))
                  AS last_call_date,
                MAX(IF(activity_type = 'OPASN' AND option_type = 'put',
                       DATE(transaction_time), NULL)) AS last_assignment_date
              FROM `{self.dataset_id}.trades_from_activities`
              WHERE underlying IN UNNEST(@symbols)
              GROUP BY underlying
            ),
            anchored AS (
              SELECT underlying,
                     COALESCE(last_call_date, last_assignment_date) AS anchor_date,
                     last_call_date IS NOT NULL AS anchor_is_call
              FROM anchors
              WHERE COALESCE(last_call_date, last_assignment_date) IS NOT NULL
            )
            SELECT a.underlying AS underlying,
                   a.anchor_date AS anchor_date,
                   a.anchor_is_call AS anchor_is_call,
                   COUNT(b.date) AS trading_days
            FROM anchored a
            LEFT JOIN `{self.dataset_id}.stock_history_from_alpaca` b
              ON b.symbol = @calendar_symbol
             AND b.date > a.anchor_date
             AND b.date <= CURRENT_DATE()
            GROUP BY a.underlying, a.anchor_date, a.anchor_is_call
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter('symbols', 'STRING', list(symbols)),
                bigquery.ScalarQueryParameter('calendar_symbol', 'STRING',
                                              self.CALENDAR_SYMBOL),
            ])
            job = self._bq_client.query(query, job_config=job_config)
            return {
                row.get('underlying'): int(row.get('trading_days') or 0)
                for row in job.result(timeout=15)
                if row.get('underlying')
            }
        except Exception as e:
            logger.warning("Uncovered-days lookup failed; label unavailable",
                           event_category="data",
                           event_type="uncovered_days_lookup_failed",
                           symbols=",".join(symbols), error=str(e))
            return None


# ---------------------------------------------------------------------------
# Row construction + the recorder
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def dedup_key(run_id: str, symbol: str, stage: str) -> str:
    """``(run_id, symbol, stage)`` collapsed to one string.

    Doubles as the streaming ``insertId``, so a Cloud Scheduler retry of the
    same request is de-duplicated by BigQuery's own best-effort window, and as
    the partition key every reading query must dedup on.  Both halves matter:
    this codebase produced **36x duplicated ``wheel_cycles`` rows** from an
    unkeyed fire-and-forget writer, and insertId dedup alone is best-effort
    over a short window — a retry minutes later would slip through it.
    """
    return f"{run_id}|{symbol}|{stage}"


def build_decision_row(
    *,
    run_id: str,
    run_ts: Optional[datetime],
    stage: str,
    symbol: str,
    outcome: str,
    reason: str = "",
    shares: Optional[int] = None,
    cost_basis_per_share: Optional[float] = None,
    current_price: Optional[float] = None,
    underwater: Optional[float] = None,
    uncovered_days: Optional[int] = None,
    candidates: Optional[int] = None,
    option_symbol: str = "",
    strike_price: Optional[float] = None,
    premium: Optional[float] = None,
    contracts: Optional[int] = None,
    order_id: str = "",
    reason_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Build one validated ``decision_events`` row.

    Raises :class:`UnknownDecisionOutcome` for an out-of-vocabulary
    outcome/reason pair or an unknown ``stage``.
    """
    if stage not in STAGES:
        raise UnknownDecisionOutcome(
            f"unknown decision stage {stage!r}; expected one of {STAGES}")
    validate_outcome(outcome, reason)
    if not run_id:
        raise UnknownDecisionOutcome("decision rows require a run_id")
    if not symbol:
        raise UnknownDecisionOutcome("decision rows require a symbol")

    ts = run_ts or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    counts = [
        {"reason": str(key), "count": int(value)}
        for key, value in sorted((reason_counts or {}).items())
        if _as_int(value)
    ]

    return {
        "run_id": run_id,
        "run_ts": ts.astimezone(timezone.utc).isoformat(),
        "stage": stage,
        "endpoint": _ENDPOINT_BY_STAGE[stage],
        "symbol": symbol,
        "outcome": outcome,
        "reason": reason or "",
        "shares": _as_int(shares),
        "cost_basis_per_share": _as_float(cost_basis_per_share),
        "current_price": _as_float(current_price),
        "underwater_pct": _as_float(underwater),
        "uncovered_days": _as_int(uncovered_days),
        "candidates": _as_int(candidates),
        "option_symbol": option_symbol or "",
        "strike_price": _as_float(strike_price),
        "premium": _as_float(premium),
        "contracts": _as_int(contracts),
        "order_id": str(order_id or ""),
        "reason_counts": counts,
        "dedup_key": dedup_key(run_id, symbol, stage),
    }


class DecisionRecorder:
    """Collects one cycle-stage's decision rows and flushes them durably.

    In-request dedup is by ``dedup_key`` with **last write winning**: within a
    single stage the later verdict is the more terminal one (a symbol whose
    call was selected and then filled moves ``dropped`` -> ``sold``).
    """

    def __init__(self, run_id: str, stage: str,
                 run_ts: Optional[datetime] = None,
                 writer: Optional[Any] = None):
        if stage not in STAGES:
            raise UnknownDecisionOutcome(
                f"unknown decision stage {stage!r}; expected one of {STAGES}")
        self.run_id = run_id
        self.stage = stage
        self.run_ts = run_ts or datetime.now(timezone.utc)
        self._writer = writer
        self._rows: "Dict[str, Dict[str, Any]]" = {}

    # -- collection ---------------------------------------------------- #

    def record(self, symbol: str, outcome: str, reason: str = "", **fields: Any) -> None:
        """Add (or replace) this stage's row for ``symbol``.

        An out-of-vocabulary outcome is dropped **loudly** rather than written
        as an ``unknown``: the row is refused, an error event is emitted, and
        the cycle continues.  Trading must not stop because telemetry is
        malformed, and telemetry must not lie because trading continued.
        """
        try:
            row = build_decision_row(
                run_id=self.run_id, run_ts=self.run_ts, stage=self.stage,
                symbol=symbol, outcome=outcome, reason=reason, **fields)
        except UnknownDecisionOutcome as exc:
            logger.error("Refused an out-of-vocabulary decision record",
                         event_category="error",
                         event_type="decision_record_invalid",
                         symbol=symbol, outcome=outcome, reason=reason,
                         error=str(exc))
            return
        self._rows[row["dedup_key"]] = row

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return list(self._rows.values())

    def __len__(self) -> int:
        return len(self._rows)

    # -- durability ---------------------------------------------------- #

    def flush(self, expected_symbols: Optional[Sequence[str]] = None) -> int:
        """Write the collected rows and log the fill-rate observation.

        Returns the number of rows handed to the writer.  Never raises: a
        telemetry write must not be able to fail a trading cycle.
        """
        rows = self.rows
        try:
            writer = self._writer
            if writer is None:
                from .analytics_writer import get_analytics_writer
                writer = get_analytics_writer()
            writer.write_decision_events(rows)
        except Exception:
            logger.warning("Decision-record write failed",
                           event_category="data",
                           event_type="decision_records_write_failed",
                           run_id=self.run_id, stage=self.stage,
                           row_count=len(rows), exc_info=True)

        # Fill-rate observation. The FC-046 sink died silently for eight
        # months because nothing watched its throughput; the queryable form
        # of this check is in docs/operations/DECISION_RECORDS.md.
        expected = list(expected_symbols) if expected_symbols is not None else None
        missing = ([s for s in expected if dedup_key(self.run_id, s, self.stage)
                    not in self._rows] if expected is not None else [])
        logger.info("Decision records written",
                    event_category="system",
                    event_type="decision_records_written",
                    run_id=self.run_id,
                    stage=self.stage,
                    row_count=len(rows),
                    expected_count=len(expected) if expected is not None else None,
                    missing_symbols=",".join(missing))
        return len(rows)


# ---------------------------------------------------------------------------
# The /run stage
# ---------------------------------------------------------------------------


def is_call_opportunity(opportunity: Dict[str, Any]) -> bool:
    """True for a covered-call opportunity, classified off the OCC symbol.

    ``strict_option_type`` for the same reason ``execute_batch`` uses it: the
    OCC symbol is what actually gets traded, and the permissive parser's
    substring fallback resolves a bare ``'AAPL'`` to ``'put'``.
    """
    if not isinstance(opportunity, dict):
        return False
    return strict_option_type(opportunity.get('option_symbol') or '') == 'call'


def record_run_stage(
    recorder: DecisionRecorder,
    *,
    call_opportunities: Sequence[Dict[str, Any]],
    selected: Sequence[Dict[str, Any]],
    execution_results: Sequence[Dict[str, Any]],
    drop_reasons: Optional[Dict[str, str]] = None,
    already_positioned: Optional[Iterable[str]] = None,
    previously_failed: Optional[Iterable[str]] = None,
) -> List[str]:
    """Record one terminal row per underlying that reached ``/run``.

    ``call_opportunities`` is the **pre-filter** call population retrieved
    from the blob, so a symbol removed by the idempotency or non-retryable
    filter still gets a row — those two filters are silent today and are two
    of the ways a symbol can vanish between the stages.

    Precedence, most terminal first: a successful fill wins; then a selected
    opportunity whose order failed; then the two pre-selection filters; then
    FC-038's selection/ranking drop reason; and finally ``not_selected`` for
    anything ranked and neither selected nor explicitly dropped.

    Returns the symbols recorded, for the fill-rate log.
    """
    drop_reasons = drop_reasons or {}
    already = set(already_positioned or ())
    failed_before = set(previously_failed or ())

    by_symbol: Dict[str, Dict[str, Any]] = {}
    for opp in call_opportunities or []:
        symbol = opp.get('symbol') if isinstance(opp, dict) else None
        if symbol and symbol not in by_symbol:
            by_symbol[symbol] = opp

    selected_symbols = {
        opp.get('symbol') for opp in selected or []
        if isinstance(opp, dict) and is_call_opportunity(opp)
    }

    filled: Dict[str, Dict[str, Any]] = {}
    for entry in execution_results or []:
        if not isinstance(entry, dict) or not entry.get('success'):
            continue
        opp = entry.get('opportunity') or {}
        if not is_call_opportunity(opp):
            continue
        symbol = opp.get('symbol')
        if symbol:
            filled[symbol] = entry

    recorded: List[str] = []
    for symbol, opp in by_symbol.items():
        labels = {
            'shares': _as_int(opp.get('shares_owned')),
            'cost_basis_per_share': _as_float(opp.get('cost_basis_per_share')),
            'current_price': _as_float(opp.get('current_stock_price')),
            'underwater': underwater_pct(opp.get('current_stock_price'),
                                         opp.get('cost_basis_per_share')),
            'option_symbol': opp.get('option_symbol') or '',
            'strike_price': _as_float(opp.get('strike_price')),
            'premium': _as_float(opp.get('premium')),
        }

        entry = filled.get(symbol)
        if entry is not None:
            executed = entry.get('opportunity') or {}
            result = entry.get('result') or {}
            labels.update({
                'option_symbol': executed.get('option_symbol') or labels['option_symbol'],
                'strike_price': _as_float(executed.get('strike_price')),
                'premium': _as_float(executed.get('premium')),
            })
            recorder.record(symbol, OUTCOME_SOLD, "",
                            contracts=_as_int(result.get('contracts')
                                              or executed.get('contracts')),
                            order_id=str(result.get('order_id') or ""),
                            **labels)
            recorded.append(symbol)
            continue

        if symbol in selected_symbols:
            reason = REASON_EXECUTION_FAILED
        elif symbol in already:
            reason = REASON_ALREADY_POSITIONED
        elif symbol in failed_before:
            reason = REASON_PREVIOUSLY_FAILED
        else:
            reason = drop_reasons.get(symbol) or REASON_NOT_SELECTED

        recorder.record(symbol, OUTCOME_DROPPED, reason,
                        contracts=_as_int(opp.get('contracts')), **labels)
        recorded.append(symbol)

    return recorded
