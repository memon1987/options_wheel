"""RejectionTally must be able to name every stage that can block a day.

FC-057: stage 1 was missing. A symbol blocked on the price band or volume floor
produced NO tally entry, so a screen reported it as simply having done nothing —
`insufficient`, 0% days in position, no reason given. That is how a $400
`max_stock_price` silently excluded SPY, QQQ and AMD for months while their
verdicts were read as strategy results rather than config exclusions.

The event was always emitted with full detail (`stock_rejected_filter`, carrying
the price and the band it missed). Nothing counted it.

FC-068 is the same failure mode, caught before it shipped. Repointing the replay
onto the production pipeline changed the vocabulary the tally listens for: the
old table counted `no_suitable_puts`, whose ONLY emitter lived inside the
deleted `put_seller.find_put_opportunity`, while the scanner-path event for an
empty put chain — `stage_7_complete_not_found` — was unmapped. Built without the
correction, "no put cleared delta/DTE/premium" (the constraint that makes
F/PFE/KMI/VZ untradeable, and a `binding_constraint` value in `backtest_runs`)
would have produced zero tally entries. Its call-side twin
`stage_8_complete_not_found` is mapped for the same reason.
"""

import pytest

from src.backtesting.engine.rejections import (
    _REASONS,
    _SELECTION_DROP_REASONS,
    RejectionTally,
)
from src.strategy.execution_engine import DROP_REASONS
from src.utils import clock
from datetime import datetime


# Every stage the LIVE pipeline can block at, and the event it emits when it
# does. A stage missing from _REASONS is invisible in every report the engine
# writes. Each entry names the emitter so a future deletion has to confront it.
STAGE_EVENTS = {
    # market_data.filter_suitable_stocks
    "stock_rejected_filter": "stage 1 — price/volume band",
    # market_data.find_suitable_puts — the put leg's binding constraint
    "stage_7_complete_not_found": "stage 7 — no put cleared the bands",
    # market_data.find_suitable_calls — the call leg's
    "stage_8_complete_not_found": "stage 8 — no call cleared the bands",
    # put_seller._calculate_position_size
    "stage_8_blocked": "stage 8 — position sizing",
    # options_scanner.scan_for_call_opportunities
    "call_scan_skipped_cost_basis_unresolved": "scan — floor unresolved",
    "call_scan_skipped_cost_basis_divergent": "scan — floor divergent",
    "call_scan_skipped_quote_unavailable": "scan — quote unusable",
    # execution_engine.execute_batch
    "naked_call_blocked": "execution — insufficient shares",
    "unroutable_opportunity": "execution — unroutable",
}

# Deleted with the engine path (FC-068). Left in _REASONS these would read as
# coverage while counting nothing — a table row with no emitter is worse than
# an absent one, because it looks like the stage is watched.
RETIRED_EVENTS = [
    "stock_filtered_by_gap_risk",
    "rejected_high_gap_frequency",
    "stage_4_blocked",
    "stage_5_blocked",
    "stage_6_blocked",
    "put_blocked_by_wheel_state",
    "covered_call_drawdown_pause",
    "no_suitable_puts",
    "position_size_validation_failed",
]


class TestEveryBlockingStageIsNameable:
    @pytest.mark.parametrize("event,stage", sorted(STAGE_EVENTS.items()))
    def test_stage_has_a_tally_reason(self, event, stage):
        assert event in _REASONS, (
            f"{stage} emits {event!r} but RejectionTally cannot name it — a day "
            f"blocked there shows as 'no reason', which is how the price-band "
            f"exclusion of SPY/QQQ/AMD stayed invisible (FC-057)"
        )

    def test_stage_1_is_the_one_that_was_missing(self):
        """Pins the specific regression rather than only the general rule."""
        assert _REASONS["stock_rejected_filter"] == "price/volume band (stage 1)"

    @pytest.mark.parametrize("event", RETIRED_EVENTS)
    def test_a_dead_event_is_not_still_listed(self, event):
        assert event not in _REASONS, (
            f"{event!r} has no emitter after FC-068 but is still in the tally "
            f"table — it will never fire, and its presence implies a stage is "
            f"being watched that no longer exists"
        )


class TestTallyCountsStageOne:
    def test_a_price_band_rejection_becomes_a_named_reason(self):
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {
                "event_type": "stock_rejected_filter",
                "symbol": "SPY",
                "reasons": ["price $736.47 outside $10.0-$400.0"],
            })

        summary = tally.summary()
        assert summary.get("price/volume band (stage 1)") == 1, (
            f"stage-1 block not counted; summary={summary!r}"
        )

    def test_an_unmapped_event_is_still_ignored(self):
        """The tally names known stages; it must not invent reasons."""
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {"event_type": "some_unrelated_event"})

        assert tally.summary() == {}


class TestTheChainEmptyEventsAreNamed:
    """FC-068's headline taxonomy correction.

    These two events are the most common no-trade outcomes in production — the
    $0.50 premium floor on the put side, the cost-basis floor on the call side.
    Both were emitted on every scan; neither was counted.
    """

    def _one(self, event_type):
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {"event_type": event_type,
                                           "symbol": "PFE"})
        return tally.summary()

    def test_an_empty_put_chain_becomes_a_named_put_side_reason(self):
        """Fails against the pre-FC-068 table, where this event was unmapped
        and `no_suitable_puts` (emitter deleted) held the bucket."""
        summary = self._one("stage_7_complete_not_found")
        assert summary == {"no put cleared delta/DTE/premium (stage 7)"
                           : 1}, f"summary={summary!r}"

    def test_an_empty_call_chain_becomes_a_named_call_side_reason(self):
        summary = self._one("stage_8_complete_not_found")
        assert summary == {
            "no call cleared floor/delta/DTE/premium (stage 8, scan)": 1
        }, f"summary={summary!r}"

    def test_candidate_days_still_track_the_found_case(self):
        """`stage_7_complete_found` is the positive twin and must keep working
        — the scanner drives `find_suitable_puts` just as the seller did."""
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {"event_type": "stage_7_complete_found"})
        assert tally.candidate_days == 1


class TestSelectionDropsAreBucketedByReason:
    """FC-068 made batch selection the stage that decides what trades.

    `selection_dropped` is ONE event carrying a `reason` field, so a flat
    _REASONS row would collapse every drop into a single bucket and the tally
    would be blind to *why* the deciding stage decided — the FC-057 failure
    mode at a new stage.
    """

    def _drop(self, reason):
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {
                "event_type": "selection_dropped",
                "reason": reason,
                "stage": "select_batch",
                "symbol": "AAPL",
            })
        return tally.summary()

    def test_selection_drop_reasons_are_tallied(self):
        assert self._drop("insufficient_buying_power") == {
            "selection: insufficient buying power": 1
        }

    @pytest.mark.parametrize("reason", DROP_REASONS)
    def test_every_closed_enum_value_has_a_bucket(self, reason):
        """The enum is exhaustive by construction in execution_engine; the
        tally must track it or a new drop reason goes silently uncounted."""
        assert reason in _SELECTION_DROP_REASONS
        assert len(self._drop(reason)) == 1

    def test_two_reasons_on_one_day_are_two_buckets(self):
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            for reason in ("insufficient_buying_power", "duplicate_underlying"):
                tally.processor(None, "info", {"event_type": "selection_dropped",
                                               "reason": reason})
        assert set(tally.summary()) == {
            "selection: insufficient buying power",
            "selection: duplicate underlying",
        }

    def test_a_selection_drop_with_no_reason_is_not_invented(self):
        """A malformed event must not become a mystery bucket."""
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 3, 2, 16, 0)):
            tally.processor(None, "info", {"event_type": "selection_dropped"})
        assert tally.summary() == {}


class TestTheEarningsGateEventsAreNamed:
    """FC-013 §5 — test 18.

    A replay day where the earnings gate blocked everything must say so. The
    FC-057 failure mode is a verdict that reads "this symbol did nothing" when
    the truth is "a filter excluded it" — and an earnings-week symbol is
    excluded on every scan of that week.
    """

    def _one(self, event_type, symbol="AMZN"):
        tally = RejectionTally()
        with clock.frozen(datetime(2026, 7, 30, 16, 0)):
            tally.processor(None, "info", {"event_type": event_type,
                                           "symbol": symbol})
        return tally.summary()

    def test_a_put_side_blackout_becomes_a_named_reason(self):
        """Fails against the pre-FC-013 table, where this event was unmapped."""
        assert self._one("put_scan_skipped_earnings_blackout") == {
            "earnings blackout (scan, put)": 1}

    def test_a_call_side_span_emptied_chain_becomes_a_named_reason(self):
        """The label says what the event now MEANS post-rev-2.2: the span
        predicate removed every qualifying strike, not "the symbol is within
        N days"."""
        assert self._one("call_scan_skipped_earnings_blackout") == {
            "earnings span emptied the chain (scan, call)": 1}

    @pytest.mark.parametrize("event", [
        "put_scan_skipped_earnings_unknown",
        "call_scan_skipped_earnings_unknown",
    ])
    def test_the_unknown_events_are_deliberately_unmapped(self, event):
        """Not an oversight — do not "fix" this.

        In a replay the historical calendar never returns unknown (table-backed,
        fail-open on gaps and reported instead), so a mapping would be an entry
        with no replay emitter: coverage that counts nothing, which is exactly
        what FC-068's rewrite of this table removed.
        """
        assert event not in _REASONS
        assert self._one(event) == {}
