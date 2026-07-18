"""Bid/ask spread model for backtest fills.

Alpaca serves no historical option quotes, so we cannot know the true bid/ask
that existed at a past decision point. We only have a trade-derived price (the
bar close), which we treat as the mark/mid. The strategy's fills, however,
depend on the spread: we sell near the bid, buy near the ask, and the live code
prices limit orders off the midpoint. So we *model* a half-spread and label
every value it produces as modeled (never presented as a real quote).

This replaces the old engine's flat ``close ± 2%`` fabrication. The default
here is a moneyness- and DTE-aware heuristic calibrated to typical retail
weekly spreads; ``SpreadModel.calibrate`` fits the parameters from real live
chain snapshots (collected going forward, and from FC-017 data as it
accumulates) so the model can be tightened per symbol.

The half-spread is expressed as a fraction of the option mark, with an absolute
floor (spreads never tighter than a penny or two even on liquid contracts) and
a widening for cheap/illiquid contracts where the percentage spread balloons.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadModel:
    """Model of half the bid-ask spread as a fraction of option mark.

    Attributes:
        base_frac: half-spread as a fraction of mark for a liquid, near-ATM,
            moderate-DTE contract (e.g. 0.05 => 5% half-spread => 10% full
            spread relative to mid).
        abs_floor: minimum half-spread in dollars/share (penny increments mean
            spreads rarely tighter than ~$0.01-0.03 even when liquid).
        otm_widening: extra half-spread fraction added linearly with how far OTM
            the contract is (|1 - K/S|), since deep-OTM weeklies quote wider.
        cheap_threshold: option mark below which the contract is treated as
            "cheap" and the spread widened (thin books on sub-$0.50 options).
        cheap_widening: additional half-spread fraction for cheap contracts.
    """

    base_frac: float = 0.05
    abs_floor: float = 0.02
    otm_widening: float = 0.10
    cheap_threshold: float = 0.50
    cheap_widening: float = 0.05

    def half_spread(self, mark: float, moneyness: float) -> float:
        """Half-spread in dollars/share for a contract at ``mark``.

        Args:
            mark: the option mark (mid) price per share.
            moneyness: |1 - strike/spot|; 0 at the money, grows OTM (and ITM).

        Returns:
            Half the modeled bid-ask spread, in dollars per share (>= abs_floor).
        """
        if mark <= 0:
            return self.abs_floor
        frac = self.base_frac + self.otm_widening * max(0.0, moneyness)
        if mark < self.cheap_threshold:
            frac += self.cheap_widening
        return max(self.abs_floor, frac * mark)

    def bid_ask(self, mark: float, moneyness: float) -> tuple[float, float]:
        """Return (bid, ask) around ``mark`` using the modeled half-spread.

        Bid is floored at zero so deep-OTM near-worthless contracts never quote
        a negative bid.
        """
        hs = self.half_spread(mark, moneyness)
        return max(0.0, mark - hs), mark + hs

    @classmethod
    def calibrate(cls, samples: list[dict]) -> "SpreadModel":
        """Fit a SpreadModel from real live-chain snapshots.

        Each sample is a dict with keys ``mark``, ``moneyness``, and observed
        ``half_spread`` (all in dollars/share). We fit ``base_frac`` and
        ``otm_widening`` by a simple least-squares regression of observed
        half-spread fraction on moneyness, keeping the structural floor/cheap
        terms at defaults. Returns the default model unchanged when there are
        too few samples to fit.

        This is intentionally simple: the goal is a defensible, per-symbol
        spread level, not a precise microstructure model.
        """
        pts = [
            (s["moneyness"], s["half_spread"] / s["mark"])
            for s in samples
            if s.get("mark", 0) > 0 and s.get("half_spread", 0) >= 0
        ]
        if len(pts) < 10:
            return cls()

        n = len(pts)
        sx = sum(x for x, _ in pts)
        sy = sum(y for _, y in pts)
        sxx = sum(x * x for x, _ in pts)
        sxy = sum(x * y for x, y in pts)
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-12:
            return cls()
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        return cls(
            base_frac=max(0.005, intercept),
            otm_widening=max(0.0, slope),
        )
