# FC-002 / FC-042 B1 — the stage-2 gap-risk filter, A/B'd

**Date:** 2026-07-29
**Plan:** [docs/plans/fc-042.md](../plans/fc-042.md) Track B1
**FC entry:** FC-002 in [docs/FUTURE_CONSIDERATIONS.md](../FUTURE_CONSIDERATIONS.md)
**Harness:** [`tools/diagnostics/fc002_gap_filter_ab.py`](../../tools/diagnostics/fc002_gap_filter_ab.py)
**Scope:** **stage 2 only** — `GapDetector.analyze_gap_risk` / `_is_suitable_for_trading`
(gap frequency + realized-vol cap). Stage 4, the execution gap gate, is a different
control, was studied separately in [fc-036-gap-gate-study.md](fc-036-gap-gate-study.md),
and is not re-examined here.

**This document is evidence, not a change.** No live threshold moves on this study. Any
change to `gap_risk_controls` gates on FC-002's own plan plus two adversarial reviews.

---

## Pre-registration

*Written and committed before any result was produced (commit history is the receipt).*

The failure mode this section exists to prevent: running eight arms, picking the one with
the best headline return, and calling it evidence. The rules below name in advance what
would argue **against** loosening the filter.

### What would argue AGAINST loosening (keep the filter as-is)

- **R1 — the premise holds in real money.** Among the 330 real sell-to-open fills, entries
  taken when the underlying's trailing realized vol was high show materially worse realized
  economics than entries taken when it was low. "Materially worse" = any of: realized P&L
  per entry at least **25% lower**, assignment rate at least **1.5×** higher, or a worst-decile
  loss at least **2×** larger. If elevated vol really predicts bad outcomes in this book,
  this is where it shows, and the cap is defensible even if expensive.
- **R2 — loosening buys return by taking risk.** In the engine A/B, a loosening arm raises
  return on collateral but degrades risk: max drawdown worsens by more than the ROC
  improvement in relative terms, or worst cycle worsens by more than 50%.
- **R3 — the filter is genuinely selective.** In the daily-bar synthetic short-put overlay
  over 2024-02 → 2026-07 (a far larger sample than the engine's handful of entries), the
  symbol-days the status-quo filter **blocks** show worse expected per-entry P&L than the
  days it allows, with the sign stable under ±20% scaling of the modeled premium.
- **R4 — the filter is not actually binding.** Loosening changes the block rate by less
  than 5 percentage points on NVDA/AMD. Then the change buys nothing and is pure
  over-fitting risk.

### What would argue FOR loosening

All three, jointly:

1. The filter's block decisions show **no discriminating power** on real outcomes (R1 fails).
2. Blocked days are **no worse** than allowed days in the overlay (R3 fails).
3. Blocked days are **numerous** — a large opportunity cost, not a rounding error.

### Arm-selection rules, also pre-registered

- No recommendation of a specific threshold that works on **one** symbol. A proposal must
  hold its sign on at least 3 of the 4 study symbols, or it is over-fit to NVDA.
- Prefer the **simplest** arm that captures most of the available benefit. A vol-relative
  percentile gate that beats a fixed cap by a hair is not worth the extra machinery.
- A **negative / no-change-warranted** result is a valid and valuable outcome. FC-036's
  most useful output was its AGAINST verdict.
- The **real-fills layer overrules the engine A/B** wherever they disagree. FC-036 proved
  the engine alone can call a threshold "free" that real fills price at $1,900.

---

*(Results follow. This file is committed in two steps: pre-registration first, then
findings.)*
