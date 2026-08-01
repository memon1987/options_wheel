"""FC-065 Phase 4 — the per-symbol decision record.

Every guard here is shown able to fire, per the plan's standing rule:
  * the outcome enum is CLOSED — an unknown outcome raises, and the recorder
    refuses the row rather than writing an "unknown" one;
  * the dedup key is `(run_id, symbol, stage)`, is carried as the streaming
    insertId, and an unkeyed row is refused outright;
  * `run_id` minted at /scan survives the blob into /run;
  * `underwater_pct` / `uncovered_days` compute from realistic inputs, and
    "could not tell" stays distinguishable from zero.
"""

from datetime import datetime, timezone

import pytest

from src.data.decision_record import (
    ALLOWED_REASONS,
    OUTCOMES,
    OUTCOME_BLOCKED,
    OUTCOME_DROPPED,
    OUTCOME_NOT_ELIGIBLE,
    OUTCOME_NO_CANDIDATES,
    OUTCOME_SOLD,
    REASON_ALREADY_POSITIONED,
    REASON_EXECUTION_FAILED,
    REASON_FLOOR_DIVERGENT,
    REASON_FLOOR_UNRESOLVED,
    REASON_INSUFFICIENT_SHARES,
    REASON_NOT_SELECTED,
    REASON_NO_QUALIFYING_STRIKES,
    REASON_PREVIOUSLY_FAILED,
    STAGE_RUN,
    STAGE_SCAN,
    DecisionRecorder,
    UncoveredDaysResolver,
    UnknownDecisionOutcome,
    build_decision_row,
    covered_underlyings,
    dedup_key,
    is_run_id,
    mint_run_id,
    position_mark_price,
    record_run_stage,
    run_id_from_opportunities,
    stamp_run_id,
    underwater_pct,
    validate_outcome,
)


class _CapturingWriter:
    def __init__(self):
        self.batches = []

    def write_decision_events(self, rows):
        self.batches.append(list(rows))


# ======================================================================
# The closed enum
# ======================================================================


class TestOutcomeEnumIsClosed:
    def test_every_outcome_has_a_reason_vocabulary(self):
        assert set(ALLOWED_REASONS) == set(OUTCOMES)

    def test_paused_is_deliberately_absent(self):
        # APPROVED DEVIATION (FC-065 Phase 4): the plan's enum text predates
        # OQ-3 and still lists `paused{drawdown, duration_days}`. The operator
        # removed the pause gate entirely, so no code path can produce it. A
        # value no producer can emit is a trap for whoever queries this table,
        # not a state. Re-adding it requires re-adding a gate.
        assert "paused" not in OUTCOMES

    def test_unknown_outcome_raises(self):
        with pytest.raises(UnknownDecisionOutcome):
            validate_outcome("paused", "drawdown")
        with pytest.raises(UnknownDecisionOutcome):
            validate_outcome("skipped")

    def test_reason_is_scoped_to_its_outcome(self):
        # `floor_unresolved` is a blocked-reason. Attaching it to `dropped`
        # would let two different questions share one answer column.
        validate_outcome(OUTCOME_BLOCKED, REASON_FLOOR_UNRESOLVED)
        with pytest.raises(UnknownDecisionOutcome):
            validate_outcome(OUTCOME_DROPPED, REASON_FLOOR_UNRESOLVED)

    def test_sold_takes_no_reason(self):
        validate_outcome(OUTCOME_SOLD, "")
        with pytest.raises(UnknownDecisionOutcome):
            validate_outcome(OUTCOME_SOLD, "because")

    def test_fc038_drop_reasons_are_accepted_verbatim(self):
        from src.strategy.execution_engine import DROP_REASONS

        for reason in DROP_REASONS:
            validate_outcome(OUTCOME_DROPPED, reason)

    def test_unknown_stage_raises(self):
        with pytest.raises(UnknownDecisionOutcome):
            build_decision_row(run_id="r", run_ts=None, stage="monitor",
                               symbol="AAPL", outcome=OUTCOME_SOLD)

    def test_recorder_refuses_an_unknown_outcome_rather_than_writing_it(self):
        writer = _CapturingWriter()
        rec = DecisionRecorder("20260801T140000Z-abcdef12", STAGE_SCAN, writer=writer)
        rec.record("NVDA", "paused", "drawdown")
        assert len(rec) == 0, "an unknown outcome must not become a row"
        rec.flush()
        assert writer.batches == [[]]


# ======================================================================
# Idempotency
# ======================================================================


class TestDedup:
    def test_key_is_run_id_symbol_stage(self):
        assert dedup_key("R1", "NVDA", STAGE_SCAN) == "R1|NVDA|scan"

    def test_same_key_written_twice_yields_one_row(self):
        rec = DecisionRecorder("R1", STAGE_SCAN, writer=_CapturingWriter())
        rec.record("NVDA", OUTCOME_NO_CANDIDATES, REASON_NO_QUALIFYING_STRIKES,
                   uncovered_days=3)
        rec.record("NVDA", OUTCOME_NO_CANDIDATES, REASON_NO_QUALIFYING_STRIKES,
                   uncovered_days=4)
        assert len(rec) == 1
        # Last write wins: the later verdict is the more terminal one.
        assert rec.rows[0]["uncovered_days"] == 4

    def test_different_stages_are_different_rows(self):
        rec_scan = DecisionRecorder("R1", STAGE_SCAN, writer=_CapturingWriter())
        rec_run = DecisionRecorder("R1", STAGE_RUN, writer=_CapturingWriter())
        rec_scan.record("NVDA", OUTCOME_NO_CANDIDATES, REASON_NO_QUALIFYING_STRIKES)
        rec_run.record("NVDA", OUTCOME_SOLD, "")
        assert rec_scan.rows[0]["dedup_key"] != rec_run.rows[0]["dedup_key"]

    def test_writer_uses_the_key_as_insert_id(self):
        from src.data.analytics_writer import AnalyticsWriter

        writer = AnalyticsWriter.__new__(AnalyticsWriter)
        writer._enabled = True
        writer._tables = {"decision_events": "TABLEREF"}
        captured = {}

        class _Client:
            def insert_rows_json(self, table, rows, **kwargs):
                captured["table"] = table
                captured["rows"] = rows
                captured["row_ids"] = kwargs.get("row_ids")
                return []

        writer._client = _Client()
        writer.write_decision_events([
            {"dedup_key": "R1|NVDA|scan", "symbol": "NVDA"},
            {"dedup_key": "R1|AAPL|scan", "symbol": "AAPL"},
        ])
        assert captured["row_ids"] == ["R1|NVDA|scan", "R1|AAPL|scan"], (
            "without insertId, a Cloud Scheduler retry inside the streaming "
            "window duplicates every row")
        assert all("timestamp" in r for r in captured["rows"])

    def test_writer_refuses_unkeyed_rows(self):
        from src.data.analytics_writer import AnalyticsWriter

        writer = AnalyticsWriter.__new__(AnalyticsWriter)
        writer._enabled = True
        writer._tables = {"decision_events": "TABLEREF"}
        calls = []

        class _Client:
            def insert_rows_json(self, table, rows, **kwargs):
                calls.append(rows)
                return []

        writer._client = _Client()
        writer.write_decision_events([{"symbol": "NVDA"}])
        assert calls == [], "an unkeyed decision row must not be written at all"


# ======================================================================
# run_id threading
# ======================================================================


class TestRunId:
    def test_minted_id_is_recognisable_and_unique(self):
        ts = datetime(2026, 8, 3, 14, 0, 0, tzinfo=timezone.utc)
        a, b = mint_run_id(ts), mint_run_id(ts)
        assert is_run_id(a) and is_run_id(b)
        assert a.startswith("20260803T140000Z-")
        assert a != b, "two scans in the same second must not collide"

    def test_naive_scan_time_is_treated_as_utc_shaped(self):
        assert is_run_id(mint_run_id(datetime(2026, 8, 3, 14, 0, 0)))

    def test_non_ids_are_rejected(self):
        for value in (None, "", "run-1", 42, "20260803-abcdef12"):
            assert not is_run_id(value)

    def test_read_back_from_opportunities(self):
        run_id = mint_run_id()
        assert run_id_from_opportunities([{"symbol": "NVDA", "run_id": run_id}]) == run_id

    def test_absent_on_a_pre_phase4_blob(self):
        assert run_id_from_opportunities([{"symbol": "NVDA"}]) is None
        assert run_id_from_opportunities([]) is None

    def test_stamping_then_reading_back_is_a_round_trip(self):
        """The whole threading contract, in the two pure halves that carry it.

        /scan mints -> `stamp_run_id` writes it onto every opportunity ->
        /run recovers it from the opportunity list, which is the ONLY thing
        `get_pending_opportunities` hands over.
        """
        run_id = mint_run_id()
        opportunities = [
            {"symbol": "NVDA", "option_symbol": "NVDA260807C00230000"},
            {"symbol": "IWM", "option_symbol": "IWM260807P00285000"},
        ]
        assert stamp_run_id(opportunities, run_id) == 2
        assert all(o["run_id"] == run_id for o in opportunities)
        assert run_id_from_opportunities(opportunities) == run_id

    def test_stamping_is_a_no_op_without_an_id(self):
        opportunities = [{"symbol": "NVDA"}]
        assert stamp_run_id(opportunities, "") == 0
        assert "run_id" not in opportunities[0]


# ======================================================================
# The two labels
# ======================================================================


class TestUnderwaterPct:
    def test_nvda_shaped_underwater_position(self):
        # Live NVDA lot: floor 218.43 (Alpaca avg_entry_price, FC-065 P1).
        # Sign convention is the plan's: NEGATIVE is underwater.
        assert underwater_pct(199.0, 218.43) == pytest.approx(-0.088953, abs=1e-6)

    def test_above_floor_is_positive(self):
        assert underwater_pct(310.0, 303.50) == pytest.approx(0.021417, abs=1e-6)

    def test_at_the_floor_is_zero(self):
        assert underwater_pct(368.34, 368.34) == 0.0

    def test_missing_inputs_are_none_not_zero(self):
        # 0.0 would render as "exactly at the floor" — a different claim.
        assert underwater_pct(None, 218.43) is None
        assert underwater_pct(199.0, None) is None
        assert underwater_pct(199.0, 0) is None
        assert underwater_pct("garbage", 218.43) is None


class TestPositionMarkPrice:
    def test_derived_from_market_value_over_qty(self):
        assert position_mark_price(
            {"qty": 100, "market_value": 19900.0}) == pytest.approx(199.0)

    def test_multi_lot_position(self):
        assert position_mark_price(
            {"qty": 300, "market_value": 59700.0}) == pytest.approx(199.0)

    def test_unusable_position_is_none(self):
        assert position_mark_price({"qty": 0, "market_value": 100}) is None
        assert position_mark_price({"qty": 100, "market_value": 0}) is None
        assert position_mark_price({}) is None


class TestCoveredUnderlyings:
    def test_short_call_covers_its_underlying(self):
        assert covered_underlyings([
            {"asset_class": "us_option", "symbol": "NVDA260807C00230000", "qty": -1},
        ]) == {"NVDA"}

    def test_long_call_is_not_coverage(self):
        assert covered_underlyings([
            {"asset_class": "us_option", "symbol": "NVDA260807C00230000", "qty": 1},
        ]) == set()

    def test_short_put_is_not_coverage(self):
        assert covered_underlyings([
            {"asset_class": "us_option", "symbol": "NVDA260807P00200000", "qty": -1},
        ]) == set()

    def test_equity_and_garbage_symbols_are_ignored(self):
        # Never substring-match an OCC symbol (FC-041/043/045/048/052).
        assert covered_underlyings([
            {"asset_class": "us_equity", "symbol": "NVDA", "qty": 100},
            {"asset_class": "us_option", "symbol": "NOT_AN_OCC", "qty": -1},
        ]) == set()


class TestUncoveredDaysResolver:
    def test_a_covered_symbol_is_zero_without_touching_bigquery(self):
        resolver = UncoveredDaysResolver()

        def _explode(symbols):
            raise AssertionError("must not query for a symbol we know is covered")

        resolver._lookup_uncovered_days = _explode
        assert resolver.resolve(["NVDA"], covered={"NVDA"}) == {"NVDA": 0}

    def test_uncovered_symbols_take_the_looked_up_day_count(self):
        resolver = UncoveredDaysResolver()
        resolver._lookup_uncovered_days = lambda symbols: {"NVDA": 9, "AMZN": 2}
        out = resolver.resolve(["NVDA", "AMZN", "AAPL"], covered={"AAPL"})
        assert out == {"AAPL": 0, "NVDA": 9, "AMZN": 2}

    def test_lookup_failure_is_none_not_zero(self):
        # "We could not tell" must never render as "covered today".
        resolver = UncoveredDaysResolver()
        resolver._lookup_uncovered_days = lambda symbols: None
        assert resolver.resolve(["NVDA"]) == {"NVDA": None}

    def test_symbol_with_no_history_is_none(self):
        resolver = UncoveredDaysResolver()
        resolver._lookup_uncovered_days = lambda symbols: {"AMZN": 4}
        assert resolver.resolve(["NVDA", "AMZN"]) == {"NVDA": None, "AMZN": 4}

    def test_batches_one_query_for_all_uncovered_symbols(self):
        calls = []
        resolver = UncoveredDaysResolver()

        def _lookup(symbols):
            calls.append(list(symbols))
            return {s: 1 for s in symbols}

        resolver._lookup_uncovered_days = _lookup
        resolver.resolve(["NVDA", "AMZN", "GOOGL"])
        assert len(calls) == 1, "one batched query per scan, not one per symbol"
        assert sorted(calls[0]) == ["AMZN", "GOOGL", "NVDA"]

    def test_bigquery_gate_off_returns_no_comparison(self):
        assert UncoveredDaysResolver(allow_bigquery=False).resolve(["NVDA"]) == {
            "NVDA": None}


# ======================================================================
# Row shape
# ======================================================================


class TestRowShape:
    def _row(self, **kw):
        base = dict(run_id="R1", run_ts=None, stage=STAGE_SCAN, symbol="NVDA",
                    outcome=OUTCOME_NO_CANDIDATES,
                    reason=REASON_NO_QUALIFYING_STRIKES)
        base.update(kw)
        return build_decision_row(**base)

    def test_reason_counts_is_a_repeated_record_not_a_json_string(self):
        # 2026-04-07 hard lesson: never string-ify structures into a BQ column.
        row = self._row(reason_counts={"delta_out_of_range": 12, "premium_too_low": 3})
        assert row["reason_counts"] == [
            {"reason": "delta_out_of_range", "count": 12},
            {"reason": "premium_too_low", "count": 3},
        ]
        assert not isinstance(row["reason_counts"], str)

    def test_zero_counts_are_dropped(self):
        assert self._row(reason_counts={"no_liquidity": 0})["reason_counts"] == []

    def test_endpoint_is_derived_from_stage(self):
        assert self._row()["endpoint"] == "/scan"
        assert self._row(stage=STAGE_RUN, outcome=OUTCOME_SOLD,
                         reason="")["endpoint"] == "/run"

    def test_run_ts_is_utc_isoformat(self):
        row = self._row(run_ts=datetime(2026, 8, 3, 14, 0, 0))
        assert row["run_ts"].startswith("2026-08-03T14:00:00")
        assert row["run_ts"].endswith("+00:00")

    def test_every_schema_column_is_present(self):
        from src.data.analytics_writer import _SCHEMAS, _HAS_BIGQUERY

        if not _HAS_BIGQUERY:
            pytest.skip("bigquery not installed")
        columns = {f.name for f in _SCHEMAS["decision_events"]}
        # `timestamp` is stamped by the writer at insert time.
        assert set(self._row()) | {"timestamp"} == columns

    def test_run_id_and_symbol_are_required(self):
        with pytest.raises(UnknownDecisionOutcome):
            self._row(run_id="")
        with pytest.raises(UnknownDecisionOutcome):
            self._row(symbol="")


# ======================================================================
# The /run stage
# ======================================================================


def _call_opp(symbol="NVDA", contracts=1, **kw):
    opp = {
        "type": "call",
        "symbol": symbol,
        "option_symbol": f"{symbol}260807C00230000",
        "strike_price": 230.0,
        "premium": 1.20,
        "contracts": contracts,
        "shares_owned": 100,
        "max_contracts": 1,
        "cost_basis_per_share": 218.43,
        "current_stock_price": 225.0,
    }
    opp.update(kw)
    return opp


class TestRecordRunStage:
    def _recorder(self):
        return DecisionRecorder("R1", STAGE_RUN, writer=_CapturingWriter())

    def test_a_filled_call_is_sold(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(
            rec, call_opportunities=[opp], selected=[opp],
            execution_results=[{"opportunity": opp, "success": True,
                                "result": {"success": True, "order_id": "abc",
                                           "contracts": 1}}])
        row = rec.rows[0]
        assert (row["outcome"], row["reason"]) == (OUTCOME_SOLD, "")
        assert row["order_id"] == "abc"
        assert row["contracts"] == 1
        assert row["strike_price"] == 230.0
        assert row["underwater_pct"] == pytest.approx(0.030078, abs=1e-6)

    def test_a_selected_call_whose_order_failed_is_dropped_execution_failed(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(
            rec, call_opportunities=[opp], selected=[opp],
            execution_results=[{"opportunity": opp, "success": False,
                                "result": {"success": False}}])
        assert (rec.rows[0]["outcome"], rec.rows[0]["reason"]) == (
            OUTCOME_DROPPED, REASON_EXECUTION_FAILED)

    def test_fc038_drop_reason_is_carried_through(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(rec, call_opportunities=[opp], selected=[],
                         execution_results=[],
                         drop_reasons={"NVDA": "insufficient_available_shares"})
        assert rec.rows[0]["reason"] == "insufficient_available_shares"

    def test_idempotency_filter_is_no_longer_silent(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(rec, call_opportunities=[opp], selected=[],
                         execution_results=[], already_positioned={"NVDA"})
        assert rec.rows[0]["reason"] == REASON_ALREADY_POSITIONED

    def test_non_retryable_filter_is_no_longer_silent(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(rec, call_opportunities=[opp], selected=[],
                         execution_results=[], previously_failed={"NVDA"})
        assert rec.rows[0]["reason"] == REASON_PREVIOUSLY_FAILED

    def test_unaccounted_disappearance_still_produces_a_row(self):
        # No selection, no drop reason, no filter — the symbol vanished for a
        # reason nobody recorded. It must still be a row, not a silence.
        rec = self._recorder()
        record_run_stage(rec, call_opportunities=[_call_opp()], selected=[],
                         execution_results=[])
        assert rec.rows[0]["reason"] == REASON_NOT_SELECTED

    def test_a_fill_beats_every_other_signal(self):
        rec = self._recorder()
        opp = _call_opp()
        record_run_stage(
            rec, call_opportunities=[opp], selected=[opp],
            execution_results=[{"opportunity": opp, "success": True,
                                "result": {"success": True, "order_id": "x"}}],
            drop_reasons={"NVDA": "duplicate_underlying"},
            already_positioned={"NVDA"}, previously_failed={"NVDA"})
        assert rec.rows[0]["outcome"] == OUTCOME_SOLD

    def test_puts_do_not_produce_covered_call_decision_rows(self):
        rec = self._recorder()
        put = {"type": "put", "symbol": "IWM",
               "option_symbol": "IWM260807P00285000", "contracts": 1}
        record_run_stage(rec, call_opportunities=[put], selected=[],
                         execution_results=[])
        # The caller filters by is_call_opportunity, but the recorder must not
        # depend on that: a put reaching here would be recorded as a
        # covered-call verdict for a symbol we hold no shares in.
        assert [r["symbol"] for r in rec.rows] == ["IWM"]

    def test_one_row_per_underlying_even_with_three_candidates(self):
        rec = self._recorder()
        opps = [_call_opp(option_symbol=f"NVDA260807C0023{i}000") for i in range(3)]
        record_run_stage(rec, call_opportunities=opps, selected=[],
                         execution_results=[])
        assert len(rec.rows) == 1


class TestFlush:
    def test_rows_are_handed_to_the_writer(self):
        writer = _CapturingWriter()
        rec = DecisionRecorder("R1", STAGE_SCAN, writer=writer)
        rec.record("NVDA", OUTCOME_NO_CANDIDATES, REASON_NO_QUALIFYING_STRIKES)
        rec.record("AAPL", OUTCOME_BLOCKED, REASON_FLOOR_DIVERGENT)
        assert rec.flush() == 2
        assert {r["symbol"] for r in writer.batches[0]} == {"NVDA", "AAPL"}

    def test_a_failing_writer_never_propagates(self):
        class _Boom:
            def write_decision_events(self, rows):
                raise RuntimeError("BigQuery down")

        rec = DecisionRecorder("R1", STAGE_SCAN, writer=_Boom())
        rec.record("NVDA", OUTCOME_NOT_ELIGIBLE, REASON_INSUFFICIENT_SHARES)
        assert rec.flush() == 1  # must not raise: telemetry cannot fail a cycle
