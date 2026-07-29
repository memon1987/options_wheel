"""Tally *why* the strategy declined to trade on each decision day.

A fitness verdict that does not name its own binding constraint is close to
useless for the decision it feeds. An adversarial review produced an AMD run
reading "unfit, held a position on 5 of 60 decision days" — while the real story
was that candidates existed on 41 of those 60 days and the gap-risk filter
excluded the symbol from 2025-01-13 onward. A reader concludes "AMD is a bad
wheel symbol" when the finding is "our gap filter excludes AMD in elevated-vol
regimes." Those imply completely different actions.

Rather than reimplement the filter logic (which would immediately drift from the
live code this FC exists to replay), this listens to the structured events the
live stages *already* emit and counts them.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Optional

import structlog

from ...utils import clock

# Live event_type -> the human-facing reason a day produced no trade. Ordered
# roughly by how early the stage sits in the pipeline.
_REASONS = {
    # FC-057: stage 1 was invisible. A symbol blocked on the price band or
    # volume floor produced NO tally entry at all, so a screen reported it as
    # simply having done nothing -- "insufficient", "0% days in position", no
    # reason given. That is how a $400 max_stock_price silently excluded SPY,
    # QQQ and AMD for months while their verdicts were read as strategy
    # results. The event was always emitted with full detail; nothing counted it.
    "stock_rejected_filter": "price/volume band (stage 1)",
    "stock_filtered_by_gap_risk": "gap-risk filter (stage 2)",
    "rejected_high_gap_frequency": "gap-risk filter (stage 2)",
    "stage_4_blocked": "execution gap check (stage 4)",
    "stage_5_blocked": "wheel state (stage 5)",
    "stage_6_blocked": "already holding a position or order (stage 6)",
    "no_suitable_puts": "no put cleared delta/DTE/premium (stage 7)",
    "stage_8_blocked": "position sizing (stage 8)",
    "position_size_validation_failed": "position sizing (stage 8)",
    "put_blocked_by_wheel_state": "wheel state (stage 5)",
    "covered_call_drawdown_pause": "drawdown pause (cost-basis floor)",
    # Execution-stage failures (FC-048). Without these the tally cannot see an
    # opportunity that was found and ranked but died at the router or in the
    # wrong seller -- which is exactly how the covered-call misroute stayed
    # invisible: every call was rejected here and nothing counted it.
    "unroutable_opportunity": "unroutable opportunity (execution)",
    "call_rejected_by_put_seller": "wrong_seller: call sent to put_seller (execution)",
    "put_rejected_by_call_seller": "wrong_seller: put sent to call_seller (execution)",
}


class RejectionTally:
    """Counts blocking reasons emitted during a replay.

    Installed as a structlog processor for the duration of the run and removed
    afterwards. Never raises into the run: a diagnostic that can break the thing
    it is diagnosing is not worth having.
    """

    def __init__(self) -> None:
        # Keyed by (day, reason) so a reason counts ONCE per day. Live emits two
        # events for one logical gap rejection — analyze_gap_risk's inner
        # _is_suitable_for_trading and the outer filter_symbols_by_gap_risk —
        # and both map to the same bucket. Counting events produced "335 days"
        # against 206 decision days: impossible on its face, and exactly the
        # class of dishonest metric this review round existed to remove.
        self._seen: set = set()
        self._candidate_days: set = set()
        self._prev_config: Optional[dict] = None

    # ------------------------------------------------------------------ #
    def processor(self, logger, name, event_dict):
        try:
            event_type = event_dict.get("event_type", "")
            # structlog.configure() is PROCESS-global, so this processor sees
            # events from every thread. clock.is_frozen() is thread-local and is
            # the only reliable "this event came from the replay" signal.
            #
            # Tagging outside this guard mislabelled LIVE events as backtest=true
            # — the mirror of the analytics-singleton bug, and worse for its own
            # purpose: FC-039 filters `backtest != true`, so a mislabelled live
            # event is silently DROPPED from real analysis. A false negative is
            # worse than the untagged-replay false positive this fills.
            if not clock.is_frozen():
                return event_dict
            day = clock.now().date()

            # Synthetic cycles must be distinguishable from live ones in Cloud
            # Logging. Promised by the plan (§5).
            event_dict.setdefault("backtest", True)
            reason = _REASONS.get(event_type)
            if reason and day is not None:
                self._seen.add((day, reason))
            # Days on which the chain *was examined* and offered a qualifying
            # candidate. Not a count of days a tradeable option existed: when an
            # earlier stage blocks, stage 7 never runs.
            if event_type == "stage_7_complete_found" and day is not None:
                self._candidate_days.add(day)
        except Exception:  # noqa: BLE001 - diagnostics must never break a run
            pass
        return event_dict

    def __enter__(self) -> "RejectionTally":
        try:
            self._prev_config = structlog.get_config()
            processors = list(self._prev_config.get("processors", []))
            structlog.configure(processors=[self.processor] + processors)
        except Exception:  # noqa: BLE001
            self._prev_config = None
        return self

    def __exit__(self, *exc) -> None:
        if self._prev_config is not None:
            try:
                structlog.configure(**self._prev_config)
            except Exception:  # noqa: BLE001
                pass
        return None

    # ------------------------------------------------------------------ #
    @property
    def candidate_days(self) -> int:
        return len(self._candidate_days)

    def summary(self) -> Dict[str, int]:
        """Distinct DAYS blocked, per reason, descending."""
        per_reason: Counter = Counter(reason for _day, reason in self._seen)
        return dict(per_reason.most_common())

    def binding_constraint(self) -> Optional[str]:
        """The reason that blocked the most days, if any."""
        top = Counter(r for _d, r in self._seen).most_common(1)
        return top[0][0] if top else None
