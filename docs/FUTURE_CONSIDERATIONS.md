# Future Considerations

A running list of things we want to **research and write a plan for** before coding. This file is a **precursor to todos**, not a todo list itself. Entries here are ideas and open questions — they become actionable only after a plan file is published in `docs/plans/`.

## Lifecycle

```
1. Consideration  →  added here, loosely scoped, questions open
2. Research        →  investigation, data gathering, comments, alternatives
3. Plan published  →  a file in docs/plans/<slug>.md with the agreed approach
4. Execution       →  code changes are made against the plan
5. Archived        →  moved to "Completed" below with a link to the plan + PR
```

**Rule of thumb:** nothing graduates from this file into code until step 3 is done. See `docs/CLAUDE.md` ("Plan-First Development") for the enforcement rule.

---

## Entry template

Copy this when adding a new consideration. Keep it short — detail belongs in the eventual plan file, not here.

```markdown
### FC-NNN: <short title>

**Status:** Consideration | Researching | Plan drafted | Plan published | Executing | Done
**Size estimate:** S | M | L  (M/L require a plan file before code changes)
**Owner:** <who is thinking about this>
**Plan file:** `docs/plans/<slug>.md` (once published)

**Problem / opportunity:** 1–3 sentences on what prompted this.

**Open questions:**
- ...
- ...

**Links:** related evals (`PERFORMANCE_EVAL_CATALOG.md#EVAL-XXX`), issues, PRs, logs.
```

---

## Active Considerations

### FC-001: Symbol universe optimization

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** 8 of 14 configured symbols have never traded (AAPL, MSFT, QQQ, SPY, F, PFE, KMI, VZ). They burn ~6k API calls/month and slow scans. Before removing them or adding replacements, we need a plan covering rollout, monitoring, and reversion.

**Open questions:**
- Remove the 8 dead-weight symbols in one change or stage it?
- Which replacement candidates (META, TSLA, COIN, PLTR) clear our filters in a backtest?
- Do we raise `max_stock_price` from $400 to bring MSFT/QQQ/SPY into range, or leave them out?
- How do we validate the change hasn't reduced premium throughput?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-010.

---

### FC-002: AMD gap-risk filter re-tuning

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** AMD is our top premium generator but is gap-filtered on 47% of scans (262 of 553). Filter thresholds may be over-conservative for this symbol. A plan needs to weigh actual realized overnight gaps against the threshold and consider per-symbol tuning vs. a global change.

**Open questions:**
- What's the distribution of AMD's actual overnight gaps vs the current filter?
- Do we support per-symbol gap thresholds, or keep one global?
- How do we avoid over-fitting to AMD's recent history?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-010, `docs/AMD_GAP_RISK_ANALYSIS_2025.md`.

---

### FC-003: DTE target optimization (7 → 2–3?)

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Current 7 DTE target may be suboptimal. Shorter DTE has higher per-trade ROI but potentially higher assignment risk. A change here touches strategy config, risk thresholds, profit-target DTE bands, and scan cadence.

**Open questions:**
- Does 2–3 DTE net ROI (after assignment losses) actually beat 7 DTE?
- Do profit-target bands need to be re-tuned for the new DTE?
- Do we ramp via A/B (some symbols at 3 DTE, others at 7) or flip the whole universe?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-004, EVAL-002.

---

### FC-004: Autonomous eval-driven parameter tuning

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `PERFORMANCE_EVAL_CATALOG.md` describes a scheduled runner + results storage + threshold checker + config proposer + human-in-the-loop gate. This is a multi-component build that needs a plan before any code lands.

**Open questions:**
- What's the minimum viable first eval to automate (EVAL-011 share-commitment verification is the highest-safety candidate)?
- Where does the scheduled runner live (Cloud Scheduler + Cloud Run job, or inline with the strategy?)
- What schema for the `eval_results` audit table?
- What are the hard per-parameter safety bounds?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` "Future Automation Architecture" section.

---

### FC-005: Per-symbol strategy parameters

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Low-priced symbols (F, PFE, KMI, VZ) fail the global `min_put_premium` because their option premiums are structurally smaller. Either remove them or support per-symbol DTE/premium overrides. Touches config schema, filter code, docs, tests.

**Open questions:**
- Do we actually want these low-priced symbols, or is it simpler to drop them (see FC-001)?
- Config shape: per-symbol overrides map, or a tier system?
- How does this interact with the gap-risk controls (FC-002)?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-007, EVAL-010.

---

## Completed

_Move entries here once a plan has been published, executed, and merged. Include plan file + PR/commit link._

<!--
Example:
### FC-000: Covered call share commitment verification
- Plan: `docs/plans/covered-call-share-commitment.md`
- Executed: commit abc1234 (Apr 6 2026)
- Eval: `PERFORMANCE_EVAL_CATALOG.md` EVAL-011
-->
