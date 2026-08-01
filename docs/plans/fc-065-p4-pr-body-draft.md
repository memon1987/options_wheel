# PR body draft — FC-065 Phase 4: make the decision legible

> **Not yet opened.** Phase 4 branches from `fc-065/phase-2-roller-floor`
> (tip `7a02ea6`). One PR per unit, dependency first — this PR opens after
> Phase 2 (#76) merges, and its base becomes `main` at that point. Paste this
> file's body into the PR then; delete this file in the bookkeeping commit
> after the PR is open.

**Plan:** `docs/plans/fc-065.md` §Phase 4
**Branch:** `fc-065/phase-4-decision-record`
**Base:** `fc-065/phase-2-roller-floor` → `main` once #76 merges

---

## What this is

For any held symbol on any cycle, a durable answer to **"did we sell a call,
and if not, why not."**

Today the honest answer is *silence*. An underwater position quietly yields
nothing; no event says so. NVDA has ended every scan since 2026-07-30 at
`stage_8_complete_not_found` and nothing downstream records it. And even the
structured logs that describe it live only in Cloud Logging's 30-day window,
because the BigQuery sink died 2025-11-22 (FC-046) — *a question about last
month's decisions is already unanswerable*.

Three commits, one per plan concern.

---

## 1. Fix the zeroed `call_sale_executed` telemetry (`1537da7`)

**Every production covered-call fill has been logging `shares_covered=0`,
`stock_cost_basis=0`, `total_return_if_called=0`.** The event read
wheel-engine-only keys; production runs the scanner path, which emits
`cost_basis_per_share` / `max_contracts` instead. Fourth instance of the
untyped-shape root cause (FC-050 fixed the floor's copy), and the reason
FC-029's standing production-validation item has been unsatisfiable.

Two new accessors next to `opportunity_floor_per_share`, same shape-tolerant
pattern:

- `opportunity_shares_covered` — `shares_covered` → `contracts * 100` →
  `max_contracts * 100`. **Never `shares_owned`**: a 300-share position writing
  one contract covers 100 shares, and the event is about the *write*.
- `opportunity_total_return_if_called` — derived from the quantities actually
  sold. Neither producer carries a usable figure at execution time: the
  wheel-engine key is absent on scanner opportunities, and the scanner's own
  `total_return_if_assigned` is `max_contracts`-scaled, so it overstates any
  write that selection sized down.

`stock_cost_basis` keeps its documented total-dollar units but is derived from
the per-share floor the gate actually enforced; the event gains
`cost_basis_per_share` so the floor is legible without arithmetic.

## 2. The decision record (`b0ab5ec`)

New `options_wheel.decision_events`, written through `AnalyticsWriter`.
Adopts **FC-044 Phase 1's design — that phase is subsumed here**; FC-044's
Phase 2 grid UI reads this table.

- **`run_id`** minted once per `/scan`, stamped onto every opportunity (not
  only the blob envelope — `get_pending_opportunities` hands `/run` the
  opportunity list and nothing else, so envelope-only would have meant
  changing that return shape and every caller with it), recovered at `/run`.
  A pre-Phase-4 blob mints an orphan id and says so rather than dropping the
  cycle's telemetry.
- **Closed outcome enum** — `sold | no_candidates | dropped | blocked |
  not_eligible`, each with its own reason vocabulary; FC-038's selection enum
  is reused verbatim for `dropped`. An unknown outcome **raises**; the recorder
  refuses the row and logs `decision_record_invalid` rather than writing an
  `unknown`.
- **Two labels on every row** — `underwater_pct` (signed, **negative is
  underwater**, per the plan's own "−8.9%") and `uncovered_days`. Derivations
  below.
- **Dedup key `(run_id, symbol, stage)`**, carried as the streaming
  `insertId`; an unkeyed row is refused outright, and every reader dedups on
  the key again.
- **Schema** — typed scalars plus a REPEATED RECORD for the chain-rejection
  breakdown.
- **Fill rate** — one row per held symbol per scan-hour expected;
  `decision_records_written` at every flush, queryable form in the runbook.

The two currently-silent `/run` filters (idempotency, non-retryable) now
produce rows — they are two of the ways a symbol vanishes between the stages.
The engine publishes `last_drop_reasons` from its single `_log_drop`
chokepoint, so ranking and selection cannot diverge from what the record says.
The scan-side flush is in a `finally`: a cycle that crashed is exactly the
cycle worth investigating.

## 3. Repoint the FC-030/FC-031 pause observability (`40de57c`)

The dashboard card and the daily alert both inferred "pause" from the latest
OPASN put strike. **There is no pause** (OQ-3 removed the gate), and **the
reference price was wrong** — since Phase 1 the floor is `avg_entry_price`,
one put premium *below* the strike they compared against, so near the
threshold the alert and the bot disagreed about the same position. Under
hold-until-recovery that alert is the only escalation control for idle capital.

Both now read `decision_events`. The alert becomes **"symbol uncovered ≥ 7
trading days"**.

**Deliberately unchanged, so the repoint needs no `gcloud` action:** the
`DRAWDOWN_PAUSE_ALERT` / `_CHECK_FAILED` markers, the policy's match filter,
the notification channel, the scheduler job, `PAUSE_ALERT_THRESHOLD_DAYS`, and
both route paths. Renaming the marker would have silently disarmed the alert —
the FC-030 fire-drill failure in a different costume.

Both sides of the API boundary move together (`types/v2.ts` + the card).
`share_count_mismatches` is preserved (the AMD anomaly's only trace).

---

## Approved deviation: no `paused` outcome

**The plan's Phase 4 enum text still lists `paused{drawdown, duration_days}`.
It is deliberately NOT implemented.**

That text predates OQ-3. The operator's binding decision removed the pause gate
entirely (plan §"Phase 3 — REMOVED"), so **no code path can produce a `paused`
row**. A value no producer can emit is not a state; it is a trap for whoever
queries this table in six months and reads "0 paused" as "the pause never
fired" rather than "the pause does not exist." What the plan asked the pause to
carry — `duration_days` — ships instead as `uncovered_days`, on *every* row, as
§Phase 3's strikethrough directs.

Pinned by `test_paused_is_deliberately_absent`. Re-adding the value is a
one-line change if a gate is ever built.

## Other plan gaps I hit (reported, not silently resolved)

1. **The plan says "one decision record per held symbol per cycle" but the
   decision is split across two stateless requests.** Implemented as: exactly
   one *terminal* row per held symbol per cycle, written by whichever stage
   terminated it. The scan stage terminates `not_eligible` / `blocked` /
   `no_candidates`; `/run` terminates `sold` / `dropped`. Consequence, stated
   plainly: **a held symbol with candidates whose `/run` never happens gets no
   row at all.** That is not a hole being papered over — it is the exact
   condition the fill-rate check exists to surface (silent non-execution hid
   FC-031 for 11 days and let the roller never fire). A
   `decision_record_deferred` log event at scan time keeps the archaeology
   possible. Documented in the runbook.
2. **`blocked{floor|unresolved|divergent}`** in the plan's enum text reads as
   three variants; the two real states are `floor_unresolved` and
   `floor_divergent`, matching the two events Phase 1 emits. Implemented as two.
3. **Scope note.** Decision rows cover the **covered-call** decision on held
   symbols only. Put-side selection drops are out of scope for this phase (the
   plan says "per held symbol"); FC-044's grid will want them and can add a
   third stage without a schema change.

## Deviations from FC-044's design

FC-044 Phase 1 is adopted nearly field-for-field. Two departures, both
deliberate:

1. **No `metrics JSON` column.** Metrics are typed scalars; the
   chain-rejection breakdown is a `REPEATED RECORD(reason, count)`.
   String-ifying arrays or structs into a BigQuery column is the 2026-04-07
   lesson this project already paid for once — it produced a dataset whose
   wildcard queries could not be run at all.
2. **FC-044's `gate` column is folded into `stage` + `reason`.** A separate
   gate name would have been a third vocabulary saying the same thing as the
   outcome/reason pair.

FC-044's open question *"does Phase 1 subsume FC-030's pause-observability
metric?"* is answered **yes** by commit 3.

---

## The two label derivations

**`underwater_pct` = `(current_price − cost_basis_per_share) / cost_basis_per_share`.**
Signed; **negative is below the floor**, matching the plan's example.
`current_price` is the broker's own mark — `market_value / qty` off the Alpaca
position dict the scanner already holds. Chosen over a `get_stock_metrics`
quote for two reasons: it costs no API call for the symbols that produced no
candidates (precisely the population this record exists for), and it cannot
disagree with the `avg_entry_price` on the same dict the way an independently
fetched quote can. `NULL` when not computable — a different claim from 0%.

**`uncovered_days` = trading days a held symbol has gone without a covered
call.** Stateless by construction (wheel-state persistence has never worked),
derived in two steps:

1. **Alpaca positions, already in hand.** An open short call on the underlying
   means covered *right now* → `0`, no BigQuery round trip. Classified through
   `strict_option_type`; never a substring match (FC-041/043/045/048/052).
2. **BigQuery `trades_from_activities`** for the rest, **one batched query per
   scan** for all held symbols. Anchor = the most recent **call-leg** activity
   on the underlying (a write, close, expiry or exercise — any of them means
   the shares were covered that day). A lot that has never had a call written
   falls back to the **put assignment** that created it, the day the shares
   became coverable. Trading days counted against the
   `stock_history_from_alpaca` benchmark calendar (FC-031's), not a hand-rolled
   weekday count — holidays are real and "≥ 7 trading days" is an alert
   boundary.

`NULL` is never coerced to `0`: no history, BigQuery unreachable, or gated off
all mean "we could not tell". Those symbols go to a separate
`unknown_uncovered_days` list on the card and log `_CHECK_FAILED` on the daily
check, so an underivable label cannot read as an all-clear.

Cost: one extra batched BigQuery query per `/scan`, on top of the per-symbol
cross-check Phase 1 kept. It is behind its own patchable chokepoint
(`UncoveredDaysResolver._lookup_uncovered_days`), added to `conftest`'s
hermeticity guard alongside `CostBasisResolver._lookup_assignment_basis`.

---

## Schema

`options_wheel.decision_events`, day-partitioned on `timestamp`:

`run_id`, `run_ts`, `stage`, `endpoint`, `symbol`, `outcome`, `reason`,
`shares`, `cost_basis_per_share`, `current_price`, `underwater_pct`,
`uncovered_days`, `candidates`, `option_symbol`, `strike_price`, `premium`,
`contracts`, `order_id`, `reason_counts` (REPEATED RECORD), `dedup_key`.

Full table, enum and query cookbook: `docs/operations/DECISION_RECORDS.md`.

---

## Test evidence

**Full suite: 951 passing** (baseline on the Phase 2 branch base: 859; **+92**).
`__pycache__` cleared before every run — a stale `.pyc` from a reviewer's
mutation testing made correct code misbehave once already (FC-032).

Frontend: `tsc --noEmit` clean, `eslint --max-warnings 0` clean, **72 vitest
passing**.

New/changed tests:

| File | Adds | Covers |
|---|---|---|
| `tests/test_decision_record.py` | 54 | enum closure, dedup + insertId, run_id round trip, both labels, row shape, `/run` stage precedence, flush containment |
| `tests/test_options_scanner.py` | +12 | one row per held symbol including the nothing-happened case, `finally`-flush survival, covered→0, underivable→NULL |
| `tests/test_call_seller.py` | +7 | non-zero economics on a scanner-shaped opportunity |
| `tests/test_execution_engine.py` | +6 | `last_drop_reasons` publication, outage vs no-shares, no cross-cycle inheritance |
| `tests/test_dashboard_pause_alert.py` | rewritten, 27 | repointed selection/formatting, read-query dedup, `get_uncovered_symbols`, degraded paths |
| `tests/test_analytics_writer.py` | 1 changed | `decision_events` added to the managed-table contract, deliberately |

### Pre-change proof for the telemetry fix

The plan's P4 verification requires `call_sale_executed` non-zero economics to
**fail on current code**. Restored `HEAD:src/strategy/call_seller.py` over the
working tree (`git show` + overwrite; equivalent to the stash proof) and ran
the new class alone:

```
tests/test_call_seller.py::TestCallSaleExecutedTelemetryFC065P4
  → 7 failed
```

All seven, including the wheel-engine-shape symmetry test (its fixture carries
no `total_return_if_called`, so pre-change it logged 0 too). File restored;
suite back to 951.

### Mutation record — 14 run, **14 caught**

| # | Mutation | Result |
|---|---|---|
| A | `call_sale_executed` back to `opportunity.get('shares_covered', 0)` — *verbatim pre-change code* | **4 failed** |
| A2 | `total_return_if_called` back to the raw opportunity key | **5 failed** |
| B | Open the outcome enum (`validate_outcome` never raises) | **2 failed** |
| C | Drop `row_ids` from `write_decision_events` (no insertId dedup) | **1 failed** |
| D | Accept unkeyed decision rows | **1 failed** |
| E | Drop `PARTITION BY dedup_key` from the read query | **1 failed** |
| F | Flip the `underwater_pct` sign convention | **4 failed** |
| G | Undecidable `uncovered_days` becomes `0` instead of `None` | **4 failed** |
| H | Stop recording the nothing-happened case | **6 failed** |
| I | Never reset `last_drop_reasons` between cycles | **1 failed** |
| J | `shares_covered` falls back to `shares_owned` | **6 failed** |
| K | Flush only on the happy path (drop the `finally`) | **11 failed** |
| L | Drop the `not_selected` fallback in the `/run` stage | **3 failed** |
| M | Query BigQuery even for symbols with an open short call | **3 failed** |

Every guard the plan asks for is shown able to fire: the closed enum (B), the
dedup on both sides (C/D/E), the non-zero economics (A/A2/J), the
nothing-happened row (H/K), and "could not tell ≠ zero" (G).

---

## Post-merge steps

1. **No table bootstrap needed.** `AnalyticsWriter._ensure_all_tables()`
   creates `decision_events` from its code-defined schema on the bot's next
   cold start. No `bq mk`, no DDL.
2. **No alert-policy or scheduler change needed.** The marker strings, match
   filter, notification channel, scheduler job and threshold env var are all
   unchanged by design. `deploy/monitoring/pause_alert_policy.json`'s *filter*
   is byte-identical; only its `displayName` and documentation text changed, so
   re-applying it is **optional and cosmetic**:
   ```bash
   TOKEN=$(gcloud auth print-access-token)
   curl -sS -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d @deploy/monitoring/pause_alert_policy.json \
     "https://monitoring.googleapis.com/v3/<POLICY_NAME>?updateMask=displayName,documentation"
   ```
3. **Deploy verification, first in-hours cycle:**
   - `/scan` response carries `run_id`; the same id appears on `/run`'s
     `opportunities_retrieved` line. No `run_id_missing_on_blob` warnings after
     the first cycle (one is expected if a pre-deploy blob is still live).
   - One `decision_events` row per held symbol per scan-hour — run the
     fill-rate query in `docs/operations/DECISION_RECORDS.md`.
   - **The acceptance check:** NVDA's silent exclusion appears as
     `no_candidates / no_qualifying_strikes` with a non-null `underwater_pct`
     around −8% to −9% against a `cost_basis_per_share` of 218.43, and a
     populated `uncovered_days`.
   - The first covered-call fill logs non-zero `shares_covered` /
     `stock_cost_basis` / `total_return_if_called` — this finally satisfies
     FC-029's standing production-validation item.
   - Bot Health → Uncovered Positions renders from `decision_events`.
   - `/scan` latency: one extra batched BigQuery query on top of Phase 1's
     ~18.5s. Watch it stays inside the ~25s expectation.
4. **Scheduler timing worth a look, not a change.** The daily check runs 17:45
   ET, chosen for the 17:00 stock-history ingest that the *old* price inference
   depended on. The new source is `decision_events`, written by the last
   in-hours scan, so 17:45 is still fine — but the dependency it was chosen for
   no longer exists.
5. **FC bookkeeping:** mark FC-044 **Phase 1 subsumed by FC-065 Phase 4**
   (Phase 2 grid still open, now unblocked — its hard prerequisite was this
   table); note the FC-030/FC-031 repoint on both entries; move FC-065 forward.
6. **Delete `docs/plans/fc-065-p4-pr-body-draft.md`** once the PR is open.

## Residual risks

- **The alert now depends on the bot writing rows.** If the bot service stops
  writing (rollback to a pre-Phase-4 revision, BigQuery outage), the card
  empties and the alert goes quiet — a *different* silent-failure surface from
  the one it had. Mitigated by the fill-rate query and the
  `unknown_uncovered_days` list, and called out at the top of the runbook's
  triage section. Not eliminated.
- **`uncovered_days` is only as good as `trades_from_activities`.** A symbol
  whose call history predates the activities backfill anchors on its put
  assignment instead, which overstates the gap. Visible in the data (the anchor
  is queryable), not silently wrong.
- **One more BigQuery query on the `/scan` path.** Batched, but it is a second
  place a BigQuery outage can slow the scan. It fails to `None` (label
  unavailable), never blocks a write.
