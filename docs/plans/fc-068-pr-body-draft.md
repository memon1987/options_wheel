# FC-068: delete the dead engine call path; repoint the backtest to production

**Plan:** `docs/plans/fc-068.md` (rev 2, `4bc18b4`)
**Branch:** `fc-068/engine-path-deletion`
**Base:** stacked on `fc-065/phase-4-decision-record` (`0183aaa`); **opens against `main` once FC-065 P2 (#76) and P4 merge**
**Status:** built, not opened. Do not merge before P2/P4.

---

`WheelEngine.run_strategy_cycle()` and everything beneath it have not been called by
production since **2025-10-03** — `842dcce` removed them from `/run`, three days before the
live account's first fill. The backtest simulator was their only surviving caller, so every
backtest this project has ever run measured a strategy with a drawdown pause, gap filtering,
wheel-state phase gating on a state layer that has never been populated, per-cycle position
caps and single-candidate selection that production **does not have** — and without
production's two-pool batch selection and committed-share ledger, which it does.

Ten months of remediations landed on that unused half (FC-029 R2/R3, FC-048's origin,
FC-050's root cause, FC-065's finding). FC-065's three phases replaced everything the dead
path uniquely guarded. This deletes it and repoints the simulator.

## Commits

| | SHA | what |
|---|---|---|
| **A** | `f6c388e` | the deletion + the repoint (basis still = strike) |
| **B** | `88c26e5` | broker premium-netting of the assignment basis |
| **C** | `80fd346` | test-only; closes a gap the mutation record exposed |

A and B are **deliberately sequenced** (plan §10). One `ENGINE_VERSION` bump covers two
independent measurement changes, and a flipped verdict alone cannot say which one flipped
it. The plan rejected a second version tag and an attribution-only runtime flag — a config
switch whose only purpose is attribution is exactly the dead-knob species this FC family
deletes — in favour of two commits plus a measured decomposition, below. C changes no
production behaviour, so it does not disturb that boundary.

---

## Commit A — the deletion and the repoint

### Killed

**`src/strategy/wheel_engine.py`** — `run_strategy_cycle`, `_manage_existing_positions`,
`_evaluate_option_position`, `_can_open_new_positions`, `_find_new_opportunities`,
`_has_existing_position`, `_has_existing_option_position`, `get_strategy_status`,
`_get_stock_position_for_symbol`, `_log_daily_stock_snapshots`, plus the `gap_detector` /
`put_seller` / `call_seller` / `_pending_underlyings` constructor members and their imports.
**Survives:** `__init__` (slimmed), `reconcile_positions` (`/run` pre-trade housekeeping),
`run_rolling_cycle` (Friday `/roll`), `_extract_underlying_from_option_symbol`. 1293 → 671
lines.

**`src/strategy/call_seller.py`** — `evaluate_covered_call_opportunity`,
`_calculate_call_position`, `_resolve_cost_basis_floor`, the `CostBasisResolver` they shared,
and the `allow_bigquery_cost_basis` kwarg. `/run` already builds
`CallSeller(alpaca, market_data, config)` (`cloud_run_server.py:429`), so the signature change
is call-compatible. 935 → 669 lines.

**`src/strategy/put_seller.py`** — `find_put_opportunity`. 636 → 548 lines.

**Elsewhere** — `main.py --command run` + `run_strategy()` + the now-orphaned `--dry-run`
flag; `scripts/testing/test_live_engine.py`; the `max_stocks_evaluated_per_cycle` and
`max_new_positions_per_cycle` config properties and their `settings.yaml` keys.

> On the two knobs: their only consumers were stage 3 and stage 9 of
> `_find_new_opportunities`; both were `null` in `settings.yaml`, so neither ever limited
> anything. They are on **no FC-069 inventory line**, so leaving them would mint exactly the
> unowned corpses this FC family exists to end. `call_drawdown_pause_threshold` is
> **deliberately left orphaned** — FC-069 item 9 owns the knob together with its `/config`
> field and dashboard exposure (binding constraint 2).

### Stage-6 equivalence, stated precisely

`ExecutionEngine._available_shares` / `strict_option_type` and their tests cover the
**naked-call/oversell** half of what stage 6 checked. They do **not** cover the *open-order
duplicate window* — an unfilled resting order that positions-based checks cannot see. **No
live-path mechanism covers that window today either**; it is FC-009's standing territory, and
this deletion neither widens nor closes it. Live duplicate protection is the scanner's
`_has_existing_position` + `filter_duplicate_opportunities` + the opportunity store's
idempotency machinery.

### The repoint

The simulator day loop is now the production pipeline, stage for stage:

```
clear_failed_symbols()                    # per simulated day — see below
engine.reconcile_positions()              # as /run does before every cycle
scanner.scan_for_put_opportunities()      # default max_results, as /scan calls it
  + scanner.scan_for_call_opportunities() # mints its own run_id
exec_engine.filter_failed_opportunities   # NOW CALLED — see below
exec_engine.filter_duplicate_opportunities
exec_engine.rank_opportunities -> select_batch -> execute_batch
engine.run_rolling_cycle()                # Fridays only
```

One `MarketDataManager` is constructed in the simulator and shared by the scanner and both
sellers on the same injected adapter client. `CallSeller` gets **no** `wheel_state` — exactly
as `/run` builds it, so the replay mirrors production's orphaned state layer rather than a
richer fiction.

**`filter_failed_opportunities` is now called.** It was skipped behind a docstring claiming it
"reads the GCS opportunity store of previous production failures" — false; it reads a
module-global set. Two cadence/safety specs from the plan (rev 2, both reviewers):

- **Cleared at the top of each simulated day**, not once per run. Production's
  `_failed_symbols` clears roughly daily (Cloud Run cold start); a once-per-run clear over a
  months-long window would let a day-1 non-retryable failure suppress a symbol for the entire
  replay — a divergence from production, not fidelity to it.
- **Snapshot-and-restore around the run.** `/backtest/screen` exists **on the live trading
  server** (`cloud_run_server.py:1110`, disabled by default, opt-in via
  `ENABLE_SCREEN_ENDPOINT`); an in-server replay clearing the set would wipe what `/run`
  depends on. It also leaked across the 14 sequential per-symbol runs of a screen today; the
  restore ends that too. Standing precondition either way: the endpoint stays disabled on the
  trading service — the Cloud Run Job is the sanctioned screen runner.

**The Friday `run_rolling_cycle()` call is KEPT**, with the rationale stated honestly: the
`/roll` scheduler invokes that exact code, and the replay reproduces its exact **no-op**.
The mechanism, named: `evaluate_roll_opportunity` reads `quote.get('last_price')` /
`get('ask_price')` from a client that returns `bid`/`ask`, so price resolves to 0 and it
returns `None` at `call_roller.py:128–129` — *before* the eligibility gates, the FC-065 P2
floor, or P2's replay-BQ gate are reached (so that gate is unreachable in a replay; P2's own
test exercises the roller directly, which is why it still proves the gate). The honest limit:
FC-066's fix direction moves roll eligibility into the **monitor cycle**, which this replay
does not model, so the kept call is a seat for the current code, not a promise. To make the
seat load-bearing rather than silent, `SimulationResult` gained `rolls_evaluated` /
`rolls_executed` and a golden replay asserts `rolls_executed == 0` — when FC-066 lands it
flips a test instead of silently changing every measurement.

### Replay isolation

`OptionsScanner` hardcoded `allow_bigquery=True` (the PR #75 reviewer's finding), so the
repointed replay would have read production `trades_from_activities` against
`CURRENT_TIMESTAMP()` on **every simulated day**. It now takes an explicit
`allow_bigquery: bool = True` parameter threaded to both readers:

| # | component | side effect | gate |
|---|---|---|---|
| 1 | `OptionsScanner.cost_basis_resolver` | BQ divergence cross-check @ `CURRENT_TIMESTAMP()` | **NEW** param → `CostBasisResolver(allow_bigquery=…)`. Simulator passes `False` → cross-check "unavailable", broker floor stands |
| 2 | `OptionsScanner.uncovered_days_resolver` (P4) | one batched BQ query per scan | **NEW**, same param. `False` → `None` = "could not tell", the honest label |
| 3 | `DecisionRecorder.flush` (P4, scan stage) | BQ `decision_events` | already gated by the analytics-singleton swap; **new test pins it** |
| 4 | `ExecutionEngine.trade_journal` | BQ `trades` | already gated (`NoOpTradeJournal`) |
| 5 | `OpportunityStore` | GCS blob writes | not constructed in the replay; now stated in the docstring |
| 6 | `reconcile_positions` → `write_wheel_cycle` | BQ | singleton swap |
| 7 | `CallRoller` resolver (P2) | BQ on the roll path | `allow_bigquery_cost_basis=False` through `WheelEngine` |
| 8 | structured log events | Cloud Logging pollution | `RejectionTally` stamps `backtest=True` |
| 9 | `CallSeller` / `PutSeller` | **none post-slim** | the FC-065 P1 gate is retired by the deletion; its test pair is rewritten against the scanner |

Explicit constructor injection rather than a `clock.is_frozen()` check inside the chokepoints,
per the plan's rejected-alternative note: a data-access policy keyed off a clock utility is
action at a distance, `is_frozen()` is **thread-local** (a component built on a worker thread
would evade it exactly when it matters), and explicit injection is the mutation-tested seam
pattern FC-065 P1/P2 established. The forgotten-fourth-instance risk is double-covered by
`conftest.py`'s class-level chokepoint patches and by the census test in `test_cost_basis.py`.

### Rejection-taxonomy rewrite

The tally counted `no_suitable_puts`, whose **only** emitter lived inside the deleted
`find_put_opportunity`, while the scanner-path event for an empty put chain
(`stage_7_complete_not_found`, `market_data.py:366`) was **unmapped**. Built without the rev-2
correction, "no put cleared delta/DTE/premium" — the constraint that makes F/PFE/KMI/VZ
untradeable, and a `binding_constraint` value in `backtest_runs` — would have produced **zero
tally entries**: the FC-057 failure mode this module exists to end.

- **Added:** `stage_7_complete_not_found`, `stage_8_complete_not_found` (the call leg's
  binding constraint — the dominant call-side no-trade in production today; leaving it
  invisible while fixing the put leg would be the same defect twice),
  `call_scan_skipped_cost_basis_{unresolved,divergent}`, `call_scan_skipped_quote_unavailable`,
  `naked_call_blocked`.
- **`selection_dropped` is bucketed by its `reason` field** (the closed `DROP_REASONS` enum).
  It is one event type carrying five reasons; a flat row would collapse every drop into one
  bucket, and FC-068 makes selection *the stage that decides what trades*.
- **Deleted:** `stage_4_blocked`, `stage_5_blocked`, `stage_6_blocked`,
  `put_blocked_by_wheel_state`, `stock_filtered_by_gap_risk`, `rejected_high_gap_frequency`,
  `covered_call_drawdown_pause`, `no_suitable_puts`, `position_size_validation_failed`. A row
  with no emitter reads as coverage while counting nothing.

**Accepted gap, stated:** the scanner's put-side "already have a position on this symbol"
skip is **silent** (`options_scanner.py:106–107` logs nothing), so the replay cannot count it —
production emits nothing there either. The old stage-6 bucket has no replacement until
FC-069 item 12 rewires that check. Documented in `BACKTEST_ENGINE.md` rather than papered
over with a synthetic event the live path does not emit.

### `ENGINE_VERSION` → `'fc-068-prod-pipeline'`

Rows either side are non-comparable. Reported during the build: **FC-048 never bumped it**, so
its put-only boundary is timestamp-only (2026-07-29); this bump restores machine-queryable
provenance. Old rows keep their version string, so rollback needs no data work.

---

## Commit B — premium-netted assignment basis

`BacktestBroker._assign_put` booked the lot at `pos.strike`; the adapter derives
`avg_entry_price` from lot basis; post-FC-065-P1 the scanner floor **is** the adapter's
`avg_entry_price`. Production's floor is Alpaca's `avg_entry_price` = strike − the assigning
put's premium, verified to the penny on all four live lots. **The backtest floor sat one put
premium above production's** — accepted in writing in `docs/plans/fc-065.md` Phase 1 with
"FC-068 closes it".

Closed rather than accepted because **IWM**, a $1-strike-grid underlying, is in the
six-symbol effective universe: on a $1 grid a ~$1–1.50 offset moves the qualifying strike set
by a full rung.

**The ledger contract, pinned.** Only the **lot basis** changes:

```python
_record("put_assignment", …, price=pos.strike, cash_delta=-strike*shares,   # UNCHANGED
        detail={"strike": pos.strike, "basis": basis, …})
```

`metrics/cycles.py:158–179` derives the cycle's `cost_basis` share-weighted from
`event.price` and books `stock_pnl` against it at call-away, while `option_pnl` **separately**
counts the put premium at `sell_to_open`. Netting the premium into `event.price` (or the cash
delta) double-counts it in **every assigned cycle**. Named basis readers, all via
`event.price` → `cycle.cost_basis` (a grep for `average_cost_basis` misses all three):
`metrics/cycles.py`, `metrics/fitness.py:505–546` (`underwater_days`),
`reporting/report.py:305,443`. These keep reporting the **strike-based** cycle basis — the
cash-attribution number — while the *gating* floor becomes premium-netted, matching production,
where the same two-number split exists (Alpaca's floor vs the FC-024 ACB scorekeeping).

Sanity floor: `basis = netted if netted > 0 else pos.strike`. A premium at or above the strike
is not a real fill, and a non-positive basis would **silently disable** the covered-call floor
(`find_suitable_calls` warns and carries on when `min_strike_price <= 0`). Mutation M9 pins it.

One deliberate residual: `pos.entry_price` is the *haircut* fill premium, so the netting
reflects this engine's own fill model rather than a hypothetical mid fill — consistent with the
cash the ledger credited at open.

---

## Decomposition memo

**Window:** `2025-10-01 → 2026-07-01`, 188 decision days, $100,000, fill haircut 0.25.
Run at **old** (`0183aaa`, pre-FC-068), **A** (`f6c388e`), **B** (`88c26e5`) via the plan's
pinned NVDA window plus the IWM window where netting can move a strike rung.
Read-only against historical Alpaca data; **nothing written to `backtest_runs`** (this is the
`backtest` path, not `screen`, so `BacktestRunWriter` is never constructed).

### Headline: **no verdict flipped.** Both symbols read `marginal` at all three points.

That is the useful result — it means the per-commit deltas below are attributable without a
verdict change confounding them, and it is **not** a claim that verdicts are stable in general
(they were not re-run across the universe; the re-baseline screen is a post-merge step).

### NVDA — 2025-10-01 → 2026-07-01

| | old | A (repoint) | B (netting) |
|---|---:|---:|---:|
| verdict | marginal | marginal | marginal |
| total return | +0.81% | **+2.81%** | +2.52% |
| puts sold | 26 | **11** | 11 |
| calls sold | 7 | **12** | 12 |
| assignments | 2 | **3** | 3 |
| distinct call strikes sold | 5 | **8** | **6** |
| ledger events | 67 | 47 | 47 |

Rejection tally (days blocked, per reason):

| reason | old | A | B |
|---|---:|---:|---:|
| gap-risk filter (stage 2) | 80 | — | — |
| already holding a position or order (stage 6) | 74 | — | — |
| drawdown pause (cost-basis floor) | 12 | — | — |
| no call cleared floor/delta/DTE/premium (stage 8, scan) | — | **85** | **85** |
| selection: insufficient available shares | — | 35 | 34 |
| selection: duplicate underlying | — | 19 | 19 |

### IWM — 2025-10-01 → 2026-07-01

| | old | A (repoint) | B (netting) |
|---|---:|---:|---:|
| verdict | marginal | marginal | marginal |
| total return | +4.21% | **+5.82%** | +5.82% |
| puts sold | 30 | 32 | 32 |
| calls sold | **19** | **6** | 6 |
| assignments | 5 | 3 | 3 |
| distinct call strikes sold | 12 | 5 | 5 |

| reason | old | A | B |
|---|---:|---:|---:|
| already holding a position or order (stage 6) | 77 | — | — |
| drawdown pause (cost-basis floor) | 14 | — | — |
| no put cleared delta/DTE/premium (stage 7) | — | 1 | 1 |
| selection: duplicate underlying | — | **38** | **38** |
| selection: insufficient available shares | — | 16 | 16 |

### Attribution

**Commit A carries essentially all of the change.** Return moves +2.00pp on NVDA and +1.61pp
on IWM; the block-reason vocabulary is replaced wholesale (stages 2/6 and the pause vanish
with their emitters; the scan-stage and selection-stage reasons appear); position counts,
assignment counts and the call-strike mix all shift. Exactly what §8 of the plan predicted,
and why verdicts must be re-run rather than extrapolated.

**Commit B is small and symbol-dependent.**

- **IWM: zero delta.** Identical return, identical strike set, identical ledger. Worth stating
  plainly, because IWM's $1 grid is the case the plan named as the *reason* to close the gap.
  The netted basis did move (e.g. 2025-11-20 assignment: basis 230.00 → 229.17), but on this
  window it never crossed a rung boundary that changed a decision. The plan's argument was
  that it *can*, not that it always does — and the fix is one line.
- **NVDA: it moved the qualifying strike set**, on a $2.50 grid rather than IWM's $1. Distinct
  call strikes sold went 8 → 6 (`200.0` and `205.0` dropped), and return moved −0.29pp.
  Direction note for reviewers: a *lower* floor admits *more* strikes, so this is **not** a
  gating tightening. It is path divergence — a lower floor changes which call ranks best,
  which changes what is sold, which changes the next call-away/expiry and every cycle after.
  Non-monotone by construction.

### Reconciliation gap — checked, and **not** an FC-068 regression

`reconciliation_gap` (attribution total vs equity change) reads: NVDA old $0 → A $43 → B $25;
IWM old **$84** → A $14 → B $14. It is a **pre-existing** residual tied to cycles still open at
window end — it is $84 at `old`, with none of this branch's code present — and commit B
*reduces* it on NVDA and leaves it identical on IWM. A premium double-count would have
*increased* it by the premium on every assigned cycle. The controlled version of this check is
`test_attribution_conserves_through_a_full_netted_cycle` (mutation M8), which asserts the gap
stays at zero through a completed called-away cycle on the golden fixture.

---

## Mutation record

Standing rule: each guard is shown able to **fire**, not merely to exist. Each row applies a
source edit that reverts exactly the behaviour the test claims to pin, runs that test, and
requires it to fail.

| # | mutation applied | test | outcome |
|---|---|---|---|
| M1 | scanner replay-BQ gate: re-hardcode `allow_bigquery=True` on the cost-basis resolver (the PR #75 reviewer's original finding) | `test_scanner_cannot_query_bigquery_during_a_replay` | FAILED as required |
| M2 | uncovered-days replay gate: re-hardcode the FC-065 P4 resolver | `test_uncovered_days_resolver_is_gated_in_replay` | FAILED as required |
| M3 | simulator must PASS the gate: build the scanner with the production default | `test_the_simulator_builds_its_scanner_with_the_gate_shut` | FAILED as required |
| M4 | production default must stay open: flip the scanner's default to `False` | `test_scanner_bigquery_stays_enabled_by_default` | FAILED as required |
| M5 | premium-netted basis: revert `_assign_put`'s netting to the bare strike | `test_assignment_basis_is_premium_netted` | FAILED as required |
| M6 | the netted basis must reach the adapter's `avg_entry_price` | `test_the_adapter_reports_the_netted_basis_as_avg_entry_price` | FAILED as required |
| M7 | double-count guard A: net the premium into `event.price`, as a naive builder would | `test_the_cash_ledger_still_moves_at_the_strike` | FAILED as required |
| M8 | double-count guard B: net the premium into the assignment **cash delta** (attribution conservation over a full replay) | `test_attribution_conserves_through_a_full_netted_cycle` | FAILED as required |
| M9 | sanity floor: allow a non-positive basis through, silently disabling the covered-call floor | `test_a_premium_at_or_above_the_strike_falls_back_to_the_strike` | FAILED as required |
| M10 | taxonomy, the rev-1 mapping: restore dead `no_suitable_puts`, unmap the scanner-path chain-empty event | `test_an_empty_put_chain_becomes_a_named_put_side_reason` | FAILED as required |
| M11 | taxonomy: leave the CALL leg's chain-empty event unmapped (the gap the plan refused to accept) | `test_an_empty_call_chain_becomes_a_named_call_side_reason` | FAILED as required |
| M12 | taxonomy: remove `selection_dropped` reason bucketing — the deciding stage goes invisible | `test_selection_drop_reasons_are_tallied` | FAILED as required |
| M13 | taxonomy: leave a dead entry in the table (reads as coverage while counting nothing) | `TestEveryBlockingStageIsNameable` | FAILED as required |
| M14 | roller tripwire: pretend the Friday roll executed | `test_the_friday_roll_seat_is_occupied_and_still_a_no_op` | FAILED as required |
| M15 | dead-vocabulary tripwire: resurrect a dead event name at the unusable-quote site | `test_no_dead_path_events_in_replay` | **STILL PASSED** — see below |
| M15b | …retried at a site the golden fixture actually reaches (`stage_1_complete`, which fires every simulated day) | `test_no_dead_path_events_in_replay` | FAILED as required |
| M16 | chokepoint census: give `CallSeller` a resolver back, so the inventory test tracks the real instance list | `test_the_hermeticity_guard_covers_every_resolver_instance` | FAILED as required |
| M17 | producer vocabulary: drop the scanner's `type` key on the call side (the FC-048 misroute, restated at the sole surviving producer) | `test_scanner_call_opportunity_declares_its_type` | FAILED as required |
| M18 | the deletion itself: re-add `run_strategy_cycle` to `WheelEngine` (a half-deletion) | `test_the_deleted_path_is_really_gone` | FAILED as required |
| M19 | remove the per-day `clear_failed_symbols()` | whole `TestDayLoop` class | **STILL PASSED** — see below |
| M19b | …after commit C added a test for it | `test_failed_symbols_are_cleared_each_simulated_day` | FAILED as required |
| M19d | delete the snapshot-restore in the `finally` | `test_the_live_failed_symbol_set_is_restored_after_a_replay` | FAILED as required |

**The two survivors, and what was done about each — reviewers should weigh these, not the
final all-green count:**

- **M15 was an unreachable mutation, not a toothless guard.** The `dip_then_recovering`
  fixture always has a usable quote, so the `call_scan_skipped_quote_unavailable` line the
  mutation edited never executes. Retried at `stage_1_complete` (fires every simulated day)
  the guard kills it. No code change; the finding is that a mutation site must be reachable
  in the fixture to be evidence of anything.
- **M19 was a real gap.** Deleting the per-day `clear_failed_symbols()` left the entire suite
  green, and so did deleting the snapshot-restore. Both are rev-2 requirements the plan took
  from both plan reviewers, and **neither had a test**. Commit C adds two, and M19b/M19d
  confirm they fire. This was found by mutation testing, not by review.

---

## Deleted-symbol grep gate

```
grep -rnE 'run_strategy_cycle|_find_new_opportunities|_manage_existing_positions|
_can_open_new_positions|evaluate_covered_call_opportunity|_calculate_call_position\b|
_resolve_cost_basis_floor|find_put_opportunity|no_suitable_puts|
covered_call_drawdown_pause|max_stocks_evaluated_per_cycle|max_new_positions_per_cycle' \
  src/ deploy/ main.py tests/ tools/ docs/ | grep -v '^docs/plans/'
```

**116 hits, triaged. Zero are live references to deleted code.** `deploy/` is clean — no hit
at all, which is the production-path no-op check in another form.

| where | hits | classification |
|---|---:|---|
| `src/**` (7 files) | 13 | **FC-068's own explanatory comments and docstrings**, naming what was deleted and why. `src/strategy/{wheel_engine,call_seller}.py` class docstrings, `src/utils/config.py` (the orphaned-knob note + the two deletion comments), `src/api/market_data.py:410` (repointed comment), `src/backtesting/engine/{simulator,rejections}.py` |
| `main.py` | 1 | the comment explaining why `--command run` is gone |
| `tests/**` (6 files) | 16 | **the deletion tests themselves** — `test_the_deleted_path_is_really_gone`'s symbol list, `test_no_dead_path_events_in_replay`'s dead-event set, `RETIRED_EVENTS` in the rejections suite, and the module docstrings recording each disposition |
| `docs/logging/**` (3 files) | 19 | inside or below the **stale banners this PR added** |
| `docs/investigations/**` (7 files) | 22 | historical studies, each **annotated by this PR** with a non-comparability header |
| `docs/releases/**` (4 files) | 7 | release notes — immutable historical record, correct as written |
| `docs/archive/**` | 1 | archived Oct-2025 test report |
| `docs/operations/TRADE_EXECUTION_ENABLED.md` | 4 | operator doc — **annotated by this PR**; its advice to set the two deleted knobs is now marked obsolete |
| `docs/FUTURE_CONSIDERATIONS.md` | 17 | the FC index. Per the no-FC-edits-before-execution rule these are updated at **merge bookkeeping** (see post-merge steps) |
| `tools/diagnostics/fc002_gap_filter_ab.py` | 6 | **stale-header added by this PR**, which explicitly calls out that its `verify` mode asserts source properties of deleted code and will now fail |
| `tools/diagnostics/fc034_premium_floor_study.py` | 3 | a **self-contained** local mapping over *historical* Cloud Logging events. Correct for the logs it reads; wrong as a description of a scan today. Noted in the FC-034 investigation's new header rather than edited, because editing it would falsify a historical study |

Two hits worth a reviewer's eye specifically:

1. `tools/diagnostics/fc002_gap_filter_ab.py:652` — `"calls_run_strategy_cycle": "run_strategy_cycle(" in server`. This `verify` mode **will now fail**; the stale header says so. Fixing or retiring the tool belongs with FC-069 item 5 (the `GapDetector` disposition), not here.
2. `tests/test_position_sizing.py` matches `_calculate_call_position` only as a **substring** of `test_calculate_call_position_size_*`, a different symbol in a different module. Not a hit. (`src/risk/position_sizing.py` is separately import-orphaned — verified, zero importers outside its own test file — and belongs on FC-069's inventory.)

---

## Test accounting vs the plan's §9 table

**992 → 988 collected (−4 net; −60 deleted, +56 added/migrated). Full suite green at every
commit boundary, `__pycache__` cleared before each run.**

| file | pre | post | Δ | what happened |
|---|---:|---:|---:|---|
| `test_wheel_engine.py` | 17 | 5 | −12 | 16 deleted with the path; `test_wheel_engine_initialization` rewritten for the slimmed constructor; **+4 new** pinning that the deletion is total (`test_the_deleted_path_is_really_gone`, no sellers/gap detector, survivors present, roller gate still carried) |
| `test_wheel_engine_injection.py` | 6 | 7 | +1 | `test_injected_client_reaches_every_component` rewritten (components are market data + the roller now); `test_injected_state_is_used_and_shared_with_call_seller` → `…_with_the_roller`; **+1** pinning the client reaches the roller at call time; the storage-bucket tests stand |
| `test_call_seller.py` | 47 | 27 | −20 | `TestCallSellerEvaluateOpportunity` (6) deleted with mapping; `TestCallSellerCostBasisFloorFC065` (14 collected) deleted — **6 pause tests per OQ-3, 8 floor tests as duplicates** with named scanner equivalents |
| `test_put_seller.py` | 20 | 15 | −5 | the 5 `test_find_put_opportunity_*` |
| `test_cost_basis.py` | 64 | 60 | −4 | `TestCallSellerDelegationIsBehaviourPreserving` (4) dies with the object it pinned; the chokepoint census **drops the seller leg and keeps the roller leg**; the mutation-marked BQ-gate contract **transfers** to `test_scanner_cannot_query_bigquery_during_a_replay`, which carries the same mutation obligation (M1) |
| `test_execution_engine.py` | 87 | 88 | +1 | `TestProducerVocabulary` **restated against the scanner**, not deleted: both emitted-dict tests now drive `_create_{call,put}_opportunity` and assert on the real dicts; the source-literal test repoints to `options_scanner.py` |
| `test_options_scanner.py` | 57 | 60 | +3 | **§9 mapping-table build steps, both executed:** `'nonsense'` added to `test_unresolved_cost_basis_emits_nothing`'s params (parity with the deleted `[0.0/None/nonsense]`); **+`test_multiple_round_lots_size_to_every_lot`** (the scanner test only ever used one round lot, so a `max_contracts=1` regression would have been invisible); **+`test_a_chain_exception_emits_no_opportunity`** (P4's test pinned only that decision rows survive, not that the scan emits nothing) |
| `test_backtest_simulator.py` | 38 | 43 | +5 | `TestStage4ExecutionGapGate` (3) deleted — the gate exists nowhere. **+8 new:** the two scanner BQ gates, the simulator-passes-the-gate test, the decision-rows test, the roller tripwire, the dead-vocabulary test, and commit C's two failed-symbol tests. `test_no_call_is_sold_below_cost_basis` re-based onto `detail['basis']`; `test_attribution_conserves_through_a_full_netted_cycle` added |
| `test_backtest_rejections.py` | 11 | 32 | +21 | rewritten against the live vocabulary: `STAGE_EVENTS` now names each emitter, `RETIRED_EVENTS` asserts the dead entries are gone, plus the `stage_7/8_complete_not_found` and `selection_dropped`-reason classes |
| `test_backtest_metrics.py` | 42 | 42 | 0 | 3 `TestRejectionTally` tests re-based off gap-filter events (deleted) onto live ones. The `(day, reason)` dedup contract is unchanged; the vehicle changed because **no two live events share a bucket any more** |
| `test_backtest_engine.py` | 29 | 35 | +6 | `TestAssignmentBasisIsPremiumNetted` (6). `test_put_assigned_buys_shares_at_strike` now asserts cash-at-strike **and** basis-netted |
| `test_backtest_adapter.py` | 27 | 27 | 0 | `test_assigned_shares_carry_avg_entry_price` re-based to 89.025 and extended to assert the ledger still moves at the strike |

**Kept green through the repoint, assertions unweakened** — these are the acceptance tests:
`TestTheCallLegActuallyRuns` (all 4 originals), `TestDayLoop` (all 9, incl.
`test_no_new_put_is_opened_on_the_day_a_put_is_assigned`, now enforced by the scanner's
position check instead of stage 6), `TestDividendsThroughTheDayLoop`,
`TestNoProductionSideEffects` / `TestAnalyticsIsolationIsReal`,
`TestStrikeWindowCoversAssignedPositions`, and P2's roller replay-gate tests.

**§9 mapping table, walked row by row:**

| deleted engine-path test | live-path equivalent | verified |
|---|---|---|
| `test_cost_basis_floor_is_the_brokers_avg_entry_price` | `test_the_broker_basis_filters_the_chain_and_rides_the_opportunity` | ✅ exists, green |
| `test_a_divergent_cross_check_blocks_the_call_write` | `test_a_divergent_cross_check_skips_the_symbol` + `test_a_share_count_mismatch_skips_the_symbol` | ✅ |
| `test_an_agreeing_cross_check_leaves_the_floor_alone` | `test_an_agreeing_cross_check_is_logged_with_its_verdict` | ✅ |
| `test_the_floor_works_for_a_manually_bought_position` | `test_an_unavailable_cross_check_is_logged_but_keeps_the_floor` | ✅ |
| `test_no_cost_basis_floor_resolved_blocks_call_write[0.0/None/nonsense]` | `test_unresolved_cost_basis_emits_nothing` | ⚠️ **gap found — `'nonsense'` param added** |
| `test_a_position_without_the_broker_field_at_all_blocks_the_write` | `test_a_positive_cost_basis_does_not_rescue_a_missing_avg_entry_price` | ✅ |
| `test_insufficient_shares` | `test_scan_call_skips_insufficient_shares` | ✅ |
| `test_strike_vs_cost_basis_filtering` | `TestCallScanFloorIsTheBrokerBasisCrossCheckedAgainstBigQuery` | ✅ |
| `test_no_suitable_calls_found` | `test_the_nothing_happened_case_produces_a_labelled_row` | ✅ |
| `test_api_error_returns_none` | `test_records_survive_a_scan_that_dies_partway` | ⚠️ **partial — pinned only that rows survive; `test_a_chain_exception_emits_no_opportunity` added** |
| `test_find_suitable_covered_calls` / `test_multiple_round_lots` | `test_scan_call_opportunities_with_stock_positions` | ⚠️ **gap found — one round lot only; `test_multiple_round_lots_size_to_every_lot` added** |
| the pause family (6) | — | **deleted, not migrated** (FC-065 OQ-3, binding) |

Three of twelve rows were not fully covered. Per binding constraint 3 each was **migrated**,
not dropped.

---

## Production-path no-op check

- `git diff main...HEAD -- deploy/cloud_run_server.py` → **empty**.
- The two constructor changes are additive with production-preserving defaults:
  `OptionsScanner(..., allow_bigquery=True)` and `CallSeller(...)` losing a keyword `/run`
  never passed. `test_scanner_bigquery_stays_enabled_by_default` pins the first (M4).
- Post-deploy verification (operator): one manual `/scan` + `/run` cycle — identical
  opportunity counts and shapes vs the prior revision, zero new event types on the live path.

## Rollback

A single `git revert` of the squash commit. No data migrations, no schema changes, no config
migrations old code cannot read (both deleted knobs are absent-tolerant `.get()` with `None`).
`backtest_runs` needs nothing — `engine_version` distinguishes rows written either side.

---

## Post-merge steps

1. **Re-baseline screen.** Trigger one off-cycle `backtest-screen` Cloud Run Job execution
   (~1h47m) rather than waiting for 2026-09-01, so a month of decisions does not lean on
   verdicts measured against a code path that no longer exists. Plan Open Question 1 —
   operator's call on job-vs-local. **Deliberately not run from this branch:** it writes to
   `options_wheel.backtest_runs`, and no build should mutate a canonical table.
2. **`backtest_runs` annotation.** No row is mutated. The 14 existing rows keep
   `engine_version='fc-032-phase-5'`; new rows carry `'fc-068-prod-pipeline'`. Add the
   boundary note to `docs/bigquery/backtest_runs.md` alongside FC-048's timestamp-only one.
3. **Parity re-measurement.** `parity_check.py`'s selection mirror was rewritten per leg
   (calls by `attractiveness_score`, puts by ROI, both over the scanner's top 3) but **not
   re-run**. Until it is, `BACKTEST_ENGINE.md` and both `fc-032-*` investigation docs carry
   stale-markers on 81% / 55.2% / 0.676. Plan Open Question 2 recommends both legs.
4. **FC index bookkeeping** (`docs/FUTURE_CONSIDERATIONS.md`, at merge, per the
   no-FC-edits-before-execution rule):
   - FC-068 → Completed, with plan link and commit SHAs.
   - Correct FC-068's own scope line — "migrate, not delete, the 27 FC-029 guard tests" is
     **superseded** by §9's accounting (6 deleted per OQ-3, 8 deleted-as-duplicates with a
     named mapping, remainder already rewritten by FC-065 P1).
   - FC-069 item 3's "Today" rationale cites the stage-6 block as half of the emergent
     one-position invariant. Stage 6 is gone; restate against the live-path mechanisms
     (scanner position-skip + `duplicate_underlying` + the share ledger).
   - Add `src/risk/position_sizing.py` to FC-069's inventory as a delete candidate —
     import-orphaned, verified zero importers outside its own test file.
5. **Deploy verification** — the manual `/scan` + `/run` cycle above.

## Reviewer checklist

- [ ] `deploy/cloud_run_server.py` diff is empty
- [ ] every deleted symbol's mapping row in §9 is either covered or migrated (three were migrated — see the table)
- [ ] the ledger contract in commit B is unchanged (`price=strike`, `cash_delta=-strike×shares`) and the three `event.price` readers are unaffected
- [ ] the decomposition memo's claim that **commit A carries the change** holds against the tables
- [ ] the two surviving mutations (M15, M19) are dispositioned honestly, not explained away
