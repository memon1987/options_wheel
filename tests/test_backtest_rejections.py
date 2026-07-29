"""RejectionTally must be able to name every stage that can block a day.

FC-057: stage 1 was missing. A symbol blocked on the price band or volume floor
produced NO tally entry, so a screen reported it as simply having done nothing —
`insufficient`, 0% days in position, no reason given. That is how a $400
`max_stock_price` silently excluded SPY, QQQ and AMD for months while their
verdicts were read as strategy results rather than config exclusions.

The event was always emitted with full detail (`stock_rejected_filter`, carrying
the price and the band it missed). Nothing counted it.
"""

import pytest

from src.backtesting.engine.rejections import _REASONS, RejectionTally
from src.utils import clock
from datetime import datetime


# Every stage the pipeline can block at, and the event it emits when it does.
# A stage missing from _REASONS is invisible in every report the engine writes.
STAGE_EVENTS = {
    "stock_rejected_filter": "stage 1 — price/volume band",
    "stock_filtered_by_gap_risk": "stage 2 — gap risk",
    "stage_4_blocked": "stage 4 — execution gap",
    "stage_5_blocked": "stage 5 — wheel state",
    "stage_6_blocked": "stage 6 — already holding",
    "no_suitable_puts": "stage 7 — no candidate",
    "stage_8_blocked": "stage 8 — position sizing",
    "covered_call_drawdown_pause": "drawdown pause",
}


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
