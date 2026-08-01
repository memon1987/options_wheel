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

**Full suite: 989 passing** (baseline on the Phase 2 branch base: 859; **+130**).
`__pycache__` cleared before every run — a stale `.pyc` from a reviewer's
mutation testing made correct code misbehave once already (FC-032).

Frontend: `tsc --noEmit` clean, `eslint --max-warnings 0` clean, **77 vitest
passing** (9 files).

New/changed tests:

| File | Adds | Covers |
|---|---|---|
| `tests/test_decision_record.py` | 80 | enum closure, dedup + insertId, run_id round trip, both labels, row shape, `/run` stage precedence, flush containment, **run-stage label carriage, the resolver SQL, `run_ts` stability, flush-once** |
| `tests/test_options_scanner.py` | +16 | one row per held symbol including the nothing-happened case, `finally`-flush survival, covered→0, underivable→NULL, **label stamping onto the blob, covered-WITH-candidates, build-failure attribution** |
| `tests/test_dashboard_pause_alert.py` | rewritten, 36 | repointed selection/formatting, read-query dedup + `sold` precedence, `get_uncovered_symbols`, **degraded flag, held-minus-rows, endpoint honouring both** |
| `tests/test_call_seller.py` | +7 | non-zero economics on a scanner-shaped opportunity |
| `tests/test_execution_engine.py` | +7 | `last_call_drop_reasons` publication, outage vs no-shares, no cross-cycle inheritance, **puts never leaking into a call's reason** |
| `UncoveredPositionsCard.test.tsx` | 5 (new) | the card's three distinct states: clear / unknown / unreadable |
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
no `total_return_if_called`, so pre-change it logged 0 too). File restored.

### Mutation record

**Round 1 — 14 run, 14 caught** (pre-review):

| # | Mutation | Result |
|---|---|---|
| A | `call_sale_executed` back to `opportunity.get('shares_covered', 0)` — *verbatim pre-change code* | **4 failed** |
| A2 | `total_return_if_called` back to the raw opportunity key | **5 failed** |
| B | Disable the outcome check in `validate_outcome` | **2 failed** |
| B-full | Open the enum entirely (outcome **and** reason checks) | **4 failed** |
| C | Drop `row_ids` from `write_decision_events` (no insertId dedup) | **1 failed** |
| D | Accept unkeyed decision rows | **1 failed** |
| E | Drop `PARTITION BY dedup_key` from the read query | **1 failed** |
| F | Flip the `underwater_pct` sign convention | **4 failed** |
| G | Undecidable `uncovered_days` becomes `0` instead of `None` | **4 failed** |
| H | Stop recording the nothing-happened case | **6 failed** |
| I | Never reset drop reasons between cycles | **1 failed** |
| J | `shares_covered` falls back to `shares_owned` | **6 failed** |
| K | Flush only on the happy path (drop the scanner's `finally`) | **11 failed** |
| L | Drop the `not_selected` fallback in the `/run` stage | **3 failed** |
| M | Query BigQuery even for symbols with an open short call | **3 failed** |

> **Correction on B, owed in writing.** The round-1 record said "2 failed" and
> the review said the full-suite count is 4. Both are right about different
> mutations, and re-running settled it: disabling *only* the outcome check
> fails 2 tests; disabling the whole validator (outcome **and** reason) fails
> 4 — `test_reason_is_scoped_to_its_outcome` and `test_sold_takes_no_reason`
> join in. The original entry under-described its own mutation rather than
> mis-counting it. Both variants are now listed and both are caught.

**Round 2 — the review's own mutations, plus 15 on the fixes. All caught.**

The two that **previously survived the full 951-test suite**:

| # | Reviewer mutation | Before | Now |
|---|---|---|---|
| R1 | Delete `b.symbol = @calendar_symbol` from the calendar join (~9× day-count inflation in production) | **SURVIVED** | **1 failed** — `test_the_calendar_join_is_symbol_scoped` |
| R2 | Remove the `is_call_opportunity` guard in `record_run_stage` (a put fill recorded as a sold covered call) | **SURVIVED** | **2 failed** — `test_a_put_FILL_is_never_recorded_as_a_sold_covered_call`, `test_a_put_is_refused_even_if_the_caller_passes_one` |

And the fixes themselves:

| # | Mutation | Result |
|---|---|---|
| N1 | Revert the anchor to `COALESCE` (re-assignment inherits the old lot's clock) | **1 failed** |
| N2 | Drop `uncovered_days` from the `/run` labels — *BLOCKER 1 verbatim* | **3 failed** |
| N3 | Stop stamping labels onto the blob | **2 failed** |
| N4 | A `sold` row no longer hard-sets `uncovered_days = 0` | **1 failed** |
| N5 | Swallow the `decision_events` query failure again — *BLOCKER 2(a) verbatim* | **1 failed** |
| N6 | Drop the held-minus-rows unknown bucket — *BLOCKER 2(b) verbatim* | **2 failed** |
| N7 | Endpoint ignores the degraded flag | **1 failed** |
| N8 | Drop the read-side `sold` precedence | **1 failed** |
| N9 | `/run` flush back on the success path only | **1 failed** |
| N10 | `run_ts` back to per-stage `now()` | **1 failed** |
| N11 | Drop the calendar-staleness compensation | **1 failed** |
| N12 | Reader treats a `sold` row as unknown again | **1 failed** |
| N13 | Drop reasons collect puts as well as calls | **1 failed** *(survived on first attempt — see below)* |
| N14 | `mint_run_id` relabels naive local time as `Z` | **1 failed** |
| N15 | Resolver inlines its own SQL copy again | **1 failed** |

> **N13 survived its first run and is recorded as such.** Scoping drop reasons
> to calls shipped without a test, so the harness caught my own gap before the
> reviewers could. `test_a_dropped_put_never_becomes_a_calls_drop_reason` now
> pins it: a selected AAPL call drops the AAPL put as `duplicate_underlying`
> (only one position per underlying across both pools), and that reason must
> not reach the covered-call channel.

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
3. **Deploy verification, first in-hours cycle** (the review's fixes make two
   of these checks sharper — a `_CHECK_FAILED` on day one now means something
   specific):
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
   - Bot Health → Uncovered Positions renders from `decision_events`, and
     shows neither the unavailable state nor a populated
     `unknown_uncovered_days` list once a full cycle has run.
   - **The 17:45 check should be quiet.** A `_CHECK_FAILED` on the first
     evening means either the table is unreadable or a held symbol produced no
     rows — both now specific, actionable signals rather than noise.
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

- **The alert depends on the bot writing rows — and that is now itself
  detected.** *(Claim corrected after review: the first draft said the
  `unknown_uncovered_days` list mitigated the no-rows case. It structurally
  could not — no rows meant no entries to list.)* The reader now computes
  **held symbols minus symbols with rows**, so a dead writer puts every held
  symbol into `unknown_uncovered_days` and logs `_CHECK_FAILED`, emailing the
  operator within one trading day. The fill-rate query is **not** the control
  and is documented as a within-cycle diagnostic only: its `cycles` CTE derives
  from `decision_events` itself, so it cannot see total write silence.
- **`uncovered_days` is only as good as `trades_from_activities`.** A symbol
  whose call history predates the activities backfill anchors on its put
  assignment instead, which overstates the gap. Visible in the data (the
  anchor is queryable), not silently wrong.
- **Calendar staleness is compensated, not eliminated.** Trailing days after
  the calendar's last bar are counted as weekdays, so a market holiday inside
  that 1–2 day window reads one day high. Documented.
- **`DATE(transaction_time)` is UTC** while the calendar is exchange-local, so
  an activity after 20:00 ET anchors to the next day — ±1 day on a ≥7-day
  threshold. Noted in the SQL and the runbook; not corrected.
- **One more BigQuery query on the `/scan` path.** Batched, but it is a second
  place a BigQuery outage can slow the scan. It fails to `None` (label
  unavailable), never blocks a write.
- **`create_table(exists_ok=True)` never reconciles schema drift** — adding a
  column to `_SCHEMAS` will not alter the live table. Pre-existing
  `AnalyticsWriter` behaviour across all four managed tables, but it now rides
  the table the operator alert reads. Recorded under *Known limitations* in the
  runbook; a future column addition needs an explicit `bq update`.

---

## Review disposition — two reviews, REQUEST_CHANGES ×2, **no disagreements**

Both reviewers independently demonstrated the same two central defects with
live probes. The core machinery (closed enum, dedup discipline, telemetry fix)
was praised by both and is unchanged.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | **BLOCKER** | `/run` rows carried NULL `uncovered_days` → daily `_CHECK_FAILED` for every actively-trading symbol, and the ≥7 contract unimplemented for half the enum | **Fixed** — labels ride the blob (`stamp_decision_labels`); `sold` hard-sets 0; reader treats `sold` as covered. Mutations N2/N3/N4/N12 |
| 2a | **BLOCKER** | `get_uncovered_symbols` swallowed its query exception and returned `status: ok` | **Fixed** — `decision_source_available` flag; endpoint returns degraded + `_CHECK_FAILED`; card renders unavailable. Mutations N5/N7 |
| 2b | **BLOCKER** | A held symbol with zero rows vanished from both lists (dead writer, rollback, failed auto-create) | **Fixed** — held-minus-rows → `unknown_uncovered_days`. Mutation N6 |
| 3 | HIGH | Anchor must be `GREATEST`, not `COALESCE` (AMZN called away 04-23, re-assigned 06-06 → false ≥7 alert on day one) | **Fixed** — `GREATEST` + re-assignment case pinned. Mutation N1 |
| 4 | HIGH | "Monitored via fill-rate query" is not a control | **Fixed** — daily checker documented as *the* control, with a failure/latency table; fill-rate demoted to within-cycle diagnostic and its blind spot stated; reader log raised to warning |
| 5 | MED | Resolver SQL invisible to the suite (reviewer's calendar-join mutation survived) | **Fixed** — `uncovered_days_sql` module-level builder + 7 pinning tests. Mutations R1/N11/N15 |
| 6 | MED | Read-side outcome precedence (a `/run` retry shadows the true `sold` row) | **Fixed** — `IF(outcome = 'sold', 0, 1)` first in the dedup ordering; reviewers' stated preference. Mutation N8 |
| 7 | MED | `/run` flush not in a `finally` | **Fixed** — `RunDecisionFlusher`, flush-once, called from `finally`. Mutation N9 |
| 8a | MED | Calendar staleness ≈2-day undercount | **Fixed by compensation** (weekday add-back), residual holiday effect documented |
| 8b | MED | `run_ts` not actually stable across stages | **Fixed** — derived from `run_id`. Mutation N10 |
| L1 | LOW | Mutation B's failure count | **Fixed** — both variants re-run and recorded; the original entry under-described its mutation |
| L2 | LOW | `is_call_opportunity` guard unpinned (reviewer mutation R2 survived) | **Fixed** — guard is now defence-in-depth in `record_run_stage`; a put fill produces no row. Mutation R2 |
| L3 | LOW | Put drops could collide with call drop reasons | **Fixed** — renamed `last_call_drop_reasons`, call-scoped at the chokepoint. Mutation N13 |
| L4 | LOW | `mint_run_id` stamped naive local time under a `Z` | **Fixed** — converts instead of relabelling. Mutation N14 |
| L5 | LOW | `quote_unavailable` hard-attribution misfiles builder failures | **Fixed** (cheap) — new `opportunity_build_failed` reason, distinguished off the cached quote |
| L6 | LOW | `create_table(exists_ok=True)` never reconciles schema drift | **Accepted, documented** — pre-existing across all four managed tables; noted that it now rides the table the alert reads |
| L7 | LOW | A local CLI scan with ambient GCP creds writes production rows | **Accepted, documented** — same exposure as every `AnalyticsWriter` caller; rows identifiable by `run_id` mint time; backtest replay already safe (no-op writer) |
| L8 | LOW | UTC `DATE(transaction_time)` ±1-day boundary | **Accepted, documented** — comment in the SQL builder and a runbook entry |

**Nothing was dismissed silently, and I did not disagree with any finding.**
One thing worth flagging to the operator rather than the reviewers: fixing
BLOCKER 1 by carrying the label on the blob means a `/run` row's
`uncovered_days` is up to ~20 minutes stale (the blob's TTL). That is correct
for the question being asked — "how long had these shares gone uncovered when
this decision was made" — but a reader comparing a `/run` row against a
same-day `/scan` row for a *different* cycle should not expect them to agree
to the day.
