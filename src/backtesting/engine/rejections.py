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

# Live event_type -> the human-facing reason a day produced no trade. Ordered
# roughly by how early the stage sits in the pipeline.
_REASONS = {
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
}


class RejectionTally:
    """Counts blocking reasons emitted during a replay.

    Installed as a structlog processor for the duration of the run and removed
    afterwards. Never raises into the run: a diagnostic that can break the thing
    it is diagnosing is not worth having.
    """

    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.candidate_days: int = 0
        self._prev_config: Optional[dict] = None

    # ------------------------------------------------------------------ #
    def processor(self, logger, name, event_dict):
        try:
            event_type = event_dict.get("event_type", "")
            reason = _REASONS.get(event_type)
            if reason:
                self.counts[reason] += 1
            # Days on which the chain *did* offer a qualifying candidate — the
            # denominator that separates "no opportunity existed" from
            # "an opportunity existed and something else blocked it".
            if event_type == "stage_7_complete_found":
                self.candidate_days += 1
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
    def summary(self) -> Dict[str, int]:
        """Reasons in descending order of how often they blocked a day."""
        return dict(self.counts.most_common())

    def binding_constraint(self) -> Optional[str]:
        """The reason that blocked the most days, if any."""
        top = self.counts.most_common(1)
        return top[0][0] if top else None
