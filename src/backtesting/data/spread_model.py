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
    def calibrate(cls, samples: list[dict], *, return_diagnostics: bool = False):
        """Fit a SpreadModel from real live-chain snapshots.

        Each sample is a dict with keys ``mark``, ``moneyness``, and observed
        ``half_spread`` (all in dollars/share). We fit ``base_frac`` and
        ``otm_widening`` by least-squares regression of observed half-spread
        fraction on moneyness, keeping the structural floor/cheap terms at
        defaults.

        Two classes of sample MUST be excluded or the fit is biased, because
        the linear model is not the data-generating process for them:

        * **Cheap-regime** (``mark < cheap_threshold``): ``half_spread`` adds
          ``cheap_widening`` for these at prediction time. Leaving them in the
          fit absorbs that term into the intercept, where it is then applied a
          second time on evaluation — double-counting.
        * **Floor-pinned** (``half_spread <= abs_floor``): these are a
          microstructure constant, not a draw from a fractional process.
          Dividing a constant by ``mark`` injects spurious mark-dependence,
          and because they cluster deep OTM they corrupt the slope directly.

        Measured on a real 450-contract chain sample those groups were 25% and
        42% of rows; including them drove ``base_frac`` to 0.0129 against a
        0.05 default (a ~4x tightening of modeled spreads, i.e. an optimistic
        bias in exactly the delta band the strategy trades) and
        ``otm_widening`` to 0.64 against 0.10.

        Args:
            samples: observed contracts.
            return_diagnostics: when True, return ``(model, diagnostics)``.
                Callers intending to COMMIT fitted parameters must use this
                and check ``diagnostics['usable']`` — a defaulted or clamped
                result is otherwise indistinguishable from a genuine fit.

        Returns:
            The fitted model, or ``(model, diagnostics)``. Falls back to the
            default model whenever the sample cannot support a fit.
        """
        usable_pts = []
        n_cheap = n_floor = 0
        for s in samples:
            mark = s.get("mark", 0)
            hs = s.get("half_spread", 0)
            if mark <= 0 or hs < 0:
                continue
            if mark < cls.cheap_threshold:
                n_cheap += 1
                continue
            if hs <= cls.abs_floor + 1e-9:
                n_floor += 1
                continue
            usable_pts.append((s["moneyness"], hs / mark))

        diag = {
            "n_input": len(samples),
            "n_used": len(usable_pts),
            "n_excluded_cheap": n_cheap,
            "n_excluded_floor": n_floor,
            "r_squared": None,
            "moneyness_min": None,
            "moneyness_max": None,
            "clamp_hit": False,
            "usable": False,
            "reason": "",
        }

        def _result(model):
            return (model, diag) if return_diagnostics else model

        if len(usable_pts) < 10:
            diag["reason"] = (f"only {len(usable_pts)} usable samples after "
                              f"exclusions (need >= 10) — DEFAULTS RETURNED, "
                              f"NOT A FIT")
            return _result(cls())

        n = len(usable_pts)
        xs = [x for x, _ in usable_pts]
        sx = sum(xs)
        sy = sum(y for _, y in usable_pts)
        sxx = sum(x * x for x, _ in usable_pts)
        sxy = sum(x * y for x, y in usable_pts)
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-12:
            diag["reason"] = ("moneyness has no variation — DEFAULTS RETURNED, "
                              "NOT A FIT")
            return _result(cls())

        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n

        mean_y = sy / n
        ss_tot = sum((y - mean_y) ** 2 for _, y in usable_pts)
        ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in usable_pts)
        diag["r_squared"] = (1 - ss_res / ss_tot) if ss_tot > 0 else None
        diag["moneyness_min"] = min(xs)
        diag["moneyness_max"] = max(xs)
        diag["clamp_hit"] = intercept < 0.005 or slope < 0.0

        if diag["clamp_hit"]:
            diag["reason"] = (f"fit ran off the rails (raw intercept "
                              f"{intercept:.4f}, slope {slope:.4f}); a clamp "
                              f"was applied — NOT SAFE TO COMMIT")
        elif diag["moneyness_min"] > 0.02:
            diag["reason"] = (f"no observations near the money (min moneyness "
                              f"{diag['moneyness_min']:.3f}); base_frac is "
                              f"EXTRAPOLATED, not measured")
        elif diag["r_squared"] is not None and diag["r_squared"] < 0.30:
            diag["reason"] = (f"poor fit (R^2 = {diag['r_squared']:.2f}); "
                              f"moneyness explains little of the spread")
        else:
            diag["usable"] = True
            diag["reason"] = "fit passes basic validity checks"

        return _result(cls(
            base_frac=max(0.005, intercept),
            otm_widening=max(0.0, slope),
        ))
