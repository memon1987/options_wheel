# FC-078 — Minimal roller revival: credit-only defensive rolls, daily evaluation

**Plan:** `docs/plans/fc-078.md` (rev 2, two adversarial plan reviews dispositioned)
**Branch:** `fc-078/roller-revival`
**Base:** `origin/main @ ec53933`
**Status:** built, validated, mutation-checked, **two adversarial code reviews dispositioned**. **No PR opened; nothing merged.** Confirmation pass still required (fixes landed in code).

> ⚠️ **This code places live orders on the paper account the moment it merges.**
> The operator explicitly waived a log-only launch gate, so build correctness is
> the only line of defense. Post-merge steps below are ordered deliberately:
> alert policies exist *before* the first cycle, and the Friday job is paused
> *before* the deploy.

---

## What changed, by section

### 1. `src/strategy/call_roller.py` — rewritten

The roller has never executed a roll in production. FC-066 found four stacked
causes; all four are fixed here, and the design is changed so the most expensive
failure mode is structurally impossible rather than merely gated.

**The credit invariant.** `STO_limit − BTC_limit ≥ rolling.min_net_credit_per_contract / 100`,
enforced on the limit prices *actually placed*, at four sites: the candidate
screen, a pre-BTC re-check, order construction, and every ladder rung. Both legs
are limit orders, so fills can only improve on it — a filled roll can never net
a debit. The two aggression pads (`btc_limit_over_ask_pct`,
`stc_limit_under_bid_pct`) are deleted: a pad *above* ask makes the placed-limit
worst case a debit, and an under-bid discount gives away the credit the
invariant needs.

**Order lifecycle** (the part both plan reviews spent their findings on):

| Behaviour | As-built | Now |
|---|---|---|
| Leg order | BTC first | BTC first, pinned by test (STO-first holds two short calls against 100 shares) |
| BTC timeout | returned `btc_unfilled` with the DAY order **still live** | cancel → **re-fetch** → three-way disposition. A cancel that fails *because it filled* is a fill |
| BTC partial | passed the **requested** qty to the STO leg | STO sized to the **filled** qty; remainder canceled; position keeps the unclosed old contracts |
| STO ladder | each timed-out rung left working, next rung placed on top | **cancel-then-verify** between every rung; at most one live STO order at any instant |
| Ladder candidates | re-queried the chain unfiltered | reuses the evaluation's span/profile/floor-filtered list; per-rung quote re-fetch + full re-validation |

The as-built ladder is worth stating plainly: two live sells against one covered
lot, and a late fill on rung 1 while rung 2 works is a genuine **naked short
call**. That is the single most dangerous thing this PR removes.

**Eligibility (DD-2).** Daily. The DTE ≤ 1 gate, the max-rolls gate (which
counted wheel-state rolls that have never persisted, so it always read 0 and
never bound) and the fail-open earnings blackout are deleted. ITM ratio ≥ 0.98
stays. An **open-order guard** is added: `/monitor` places fire-and-forget DAY
buy-to-close limits that outlive its 14:55 slot, so at 15:30 the roller can see
a short call with a live BTC working against it — rolling it can fill both buys.
We skip rather than cancel; the working order belongs to the profit-taker, which
has precedence by design.

**Selection (DD-3).** Maximum **net credit** among legal candidates, ties toward
the higher strike. Every legal candidate already improves the strike strictly,
so credit is the honest maximand; paying certain credit for contingent strike
value is the roll-up chasing this FC excludes.

**Imminence override (DD-2).** `extrinsic ≤ $0.20` switches both legs to
mid ± $0.05. It relaxes the invariant, the floor and the span gate by exactly
nothing, requires a two-sided option quote, and is best-effort by construction —
its failure mode is the pre-existing default outcome (assignment, at or above
the floor).

**Quote handling.** `bid`/`ask` everywhere (the `last_price`/`ask_price` reads
that killed every evaluation are gone). The stock quote must be two-sided **and**
`ask/bid ≤ 1.05`; the rev-1 "whichever side is positive" fallback is deleted.
`get_stock_quote` *raises* on failure, so the unreachable `if not quote` branch
is replaced with a try/except.

**State (DD-6).** The wheel-state dependency is **deleted, not repaired**.
`CallRoller` loses the `wheel_state` parameter; `_check_debit_tolerance`,
`debit_pct_of_premium` and `call_roll_blocked_debit` are gone.

**Observability (DD-5).** Exactly one terminal event per evaluated position, on
every path — including the three that used to `return None` silently.

### 2. `src/risk/risk_manager.py` — `validate_roll`

Entry delta band → bare upper rail `rolling_max_replacement_delta` (0.60). DTE
cap → **expiry-relative** date bound via a required `max_expiry` argument.
`min_call_premium` check deleted. `validate_new_position` untouched.

### 3. `src/api/market_data.py` — `find_suitable_calls`

Two new parameters, both inert by default: `include_expiry_on_or_before` (the
roll-out horizon ceiling, symmetric with FC-013's span floor) and
`criteria_profile` (`'entry'` | `'roll'`). One filter site, no duplicated chain
logic. STAGE 8 log lines gain `criteria_profile` and
`rejected_expiry_beyond_horizon`.

### 4. `src/strategy/wheel_engine.py` — `run_rolling_cycle`

Stops passing `wheel_state`. Fetches open option orders once per cycle. Adds the
**cycle time budget guard**: a position is never *started* without the full
per-position worst case (600 s) of the 1500 s budget remaining, because a kill
between a filled BTC and an unplaced STO is the worst seam there is. Per-position
try/except so one bad symbol cannot kill the cycle — and the except still emits a
terminal.

### 5. `deploy/cloud_run_server.py` — `/roll`

Friday-only weekday guard deleted. Market-open guard, `strategy_lock`,
`@require_api_key`, `@require_account_match` all kept and pinned by test.

### 6–7. `src/utils/config.py`, `config/settings.yaml`

Four knobs added (`max_extension_days` 14, `max_replacement_delta` 0.60,
`min_net_credit_per_contract` 0.00, `imminence_extrinsic_threshold` 0.20), eight
deleted, four kept. `ROLLER_ENABLED` env override mirrors `EARNINGS_ENABLED`
exactly; `ROLLER_DRY_RUN` is env-only and defaults off. Config validation gains
bounds checks on all four new knobs.

### 8. `deploy/monitoring/`

New `roll_executed_alert_policy.json` (conditions: `call_roll_completed`,
`call_roll_naked_exposure`; both `jsonPayload` and `textPayload` clauses; no
severity constraint — the FC-030 gotcha; `notificationRateLimit: 300s` so a
second same-day roll still notifies). `cost_basis_alert_policy.json` gains the
two roll-path skip events in both clauses. Both documentation blocks are well
under the 4000-char cap (2250 / 2201).

### 9. `src/backtesting/engine/simulator.py`

Roll cycle runs **daily**, mirroring production; `roll_weekday` deleted.
`SimulationResult` gains `roll_records` so the golden replay can assert what now
matters. **The FC-068 tripwire flips by design** — see "Plan deviations" below.

### 10–11. Docs

`tools/backtesting/fetch_earnings_table.py` stale docstring corrected.
`docs/BACKTEST_ENGINE.md` staleness paragraph notes the roller folding into the
same re-baseline. `docs/gates.md` roll-path table rewritten (it described the
deleted gates). `tests/test_backtest_earnings.py` module docstring corrected for
the same reason.

**No `dashboard/` changes. `earnings_avoidance_days` untouched (FC-069's).**

---

## Validation

| Check | Result |
|---|---|
| Full suite, baseline `ec53933` | **1125 passed** |
| Full suite, this branch | **1237 passed** (+112; 1223 pre-review, +14 from the review fixes) |
| Working tree after mutation runs | clean; `git diff` empty |
| Entry-profile byte-identical pin | **proven** — 400 randomized chains diffed against the `ec53933` implementation; results *and* published rejection stats identical (harness run then removed) |
| Deleted-knob grep across `src/ tools/ deploy/ tests/ config/ docs/` | only intentional hits remain: the deletion-assertion tests, `docs/gates.md`'s explicit "Deleted by FC-078" list, and the historical FC-066 diagnosis in `FUTURE_CONSIDERATIONS.md` |
| `dashboard/` diff | empty |
| `earnings_avoidance_days` | untouched |

### Five-terminal taxonomy — confirmed

Eighteen scenarios, one per branch that can end a position's evaluation, each
asserting **exactly one** terminal event, plus a source-level check that no
`call_roll_*` event escapes classification:

`stock_quote_unavailable` (raise) · `stock_quote_unavailable` (empty) ·
`stock_quote_unusable` · `open_order_conflict` · `not_itm_enough` ·
`cost_basis_unresolved` · `cost_basis_divergent` · `btc_quote_unavailable` ·
`earnings_unknown` · `no_suitable_replacement` · `no_credit_candidate` ·
`invalid_expiry` · `credit_gone_at_execution` · `btc_rejected` ·
`btc_timeout_canceled` · `naked_exposure` · `completed` · `dry_run`

Cycle-level paths (`cycle_budget_exhausted`, `open_orders_unavailable`,
`evaluation_error`, `execution_error`) are covered in `test_wheel_engine.py`.

---

## Mutation record — 44 mutations, **44 killed, 0 survived**

Round 1 (31, pre-review) + round 2 (10, the review fixes) + 3 round-1 mutations
re-anchored because the H-1 fix rewrote their target code. Two mutations
survived at some point and both were then closed:

- **M39** (anchor rungs 3+ on `btc_limit` instead of the actual fill) — the
  trader's finding L-3. Survived because every prior test filled the BTC exactly
  at its limit, where the two numbers coincide. Now killed.
- **M21'** (set the shipped settle bound to 0 — one read, no polling: the H-1
  defect restored) — survived because the autouse test fixture drives that
  constant to 0 so tests don't sleep, which made the *production* value
  invisible to the entire suite. Closed by asserting the literal from source.

Procedure per mutation: apply to source → clear `__pycache__` → run targeted
tests → record → `git checkout --` the file → clear `__pycache__`. The stale-`.pyc`
lesson from FC-032's review is why the cache is cleared on both sides.

| # | Plan test | Mutation | File | Result |
|---|---|---|---|---|
| M1 | T-1 | allow a $0.01 debit on the candidate screen | call_roller | KILLED (1 failed) |
| M2 | T-2a | drop `exclude_expiry_on_or_after` from the roller's chain query | call_roller | KILLED (1) |
| M3 | T-2b | re-query the chain in the STO ladder instead of reusing the filtered list | call_roller | KILLED (1) |
| M4 | T-3a | reintroduce the `ask_price` key on the BTC quote | call_roller | KILLED (41) |
| M5 | T-3b | reintroduce the `last_price` key on the stock quote | call_roller | KILLED (48) |
| M6 | T-4 | drop `cost_basis_per_share` from the `min_strike` max() | call_roller | KILLED (1) |
| M7 | T-5a | drop the invariant recomputation from the fallback path | call_roller | KILLED (1) |
| M8 | T-5b | drop `validate_roll` from the fallback path | call_roller | KILLED (1) |
| M9 | T-6a | reintroduce a `max_current_dte ≤ 1` eligibility gate | call_roller | KILLED (46) |
| M10 | T-6b | invert the imminence comparison | call_roller | KILLED (12) |
| M11 | T-7a | restore entry-band reuse in `validate_roll` | risk_manager | KILLED (41) |
| M12 | T-7b | re-anchor the roll horizon to the **evaluation** date | call_roller | KILLED (33) |
| M13 | T-7c | apply the premium floor in `validate_roll` | risk_manager | KILLED (1) |
| M14 | T-7d | apply the premium floor in the roll criteria profile | market_data | KILLED (1) |
| M15 | T-7e | re-apply the entry DTE cap in the roll criteria profile | market_data | KILLED (6) |
| M16 | T-7f | drop the horizon ceiling from the shared filter | market_data | KILLED (3) |
| M17 | T-7b | first-past-the-post instead of max net credit | call_roller | KILLED (10) |
| M18 | T-8 | let the roll profile leak into the entry path | market_data | KILLED (17) |
| M19 | T-9 | place the STO leg before the BTC leg | call_roller | KILLED (14) |
| M20 | T-10a | drop the cancel on BTC timeout | call_roller | KILLED (3) |
| M21 | T-10b | drop the post-cancel re-fetch (report the timeout blind) | call_roller | KILLED (2) |
| M22 | T-15 | restore the Friday-only guard in the simulator | simulator | KILLED (1) |
| M23 | T-16 | let dry-run place orders anyway | call_roller | KILLED (1) |
| M24 | T-17 | drop the open-order guard | call_roller | KILLED (1) |
| M25 | T-18 | drop the inter-rung cancel-then-verify | call_roller | KILLED (2) |
| M26 | T-19 | pass the **requested** qty to the STO leg | call_roller | KILLED (1) |
| M27 | T-20 | drop the pre-position cycle budget check | wheel_engine | KILLED (1) |
| M28 | T-21 | drop the pre-BTC invariant re-check | call_roller | KILLED (1) |
| M29 | T-22 | restore the whichever-side-is-positive stock quote fallback | call_roller | KILLED (4) |
| M30 | T-11 | swallow a per-position exception without a terminal event | wheel_engine | KILLED (2) |
| M31 | T-17b | fail **open** when the open-order book is unreadable | wheel_engine | KILLED (1) |

### Round 2 — the review fixes

| # | Finding | Mutation | File | Result |
|---|---|---|---|---|
| M32 | H-1 | revert cancel-and-settle to a **single** post-cancel re-read | call_roller | KILLED (6) |
| M33 | H-1 | treat `pending_cancel` as a **terminal** status | call_roller | KILLED (4) |
| M34 | H-1 | let the STO ladder continue after an unsettled rung | call_roller | KILLED (1) |
| M35 | H-1 | treat an unsettled BTC cancel as a verified zero fill | call_roller | KILLED (2) |
| M36 | H-1 | swallow order-refetch failures silently (no breadcrumb) | call_roller | KILLED (2) |
| M37 | H-2 | restore the **mixed-quantity** `net_credit` | call_roller | KILLED (1) |
| M38 | H-2 | drop the uncovered-remainder terminal (report `completed`) | call_roller | KILLED (2) |
| M39 | L-3 | anchor rungs 3+ on `btc_limit` instead of the **actual fill** | call_roller | KILLED (1) — *survived pre-fix* |
| M40 | L-2 | report a post-placement rejection as a timeout-cancel | call_roller | KILLED (1) |
| M41 | L-1 | silently drop short calls with no covering shares | wheel_engine | KILLED (1) |

### Re-anchored round-1 mutations (target code rewritten by the H-1 fix)

| # | Plan test | Mutation | Result |
|---|---|---|---|
| M20' | T-10a | drop the cancel entirely from cancel-and-settle (both legs) | KILLED (4) |
| M21' | T-10b | settle with a **zero** bound (one read, no polling) | KILLED (1) — *survived until the source-literal assertion* |
| M25' | T-18 | drop the inter-rung settle (assume every rung is dead) | KILLED (4) |

Parenthesised numbers are failing tests under the mutation.

---

## Two-review disposition

Both reviews returned **REQUEST_CHANGES**. They were strongly convergent and
**there were no reviewer-vs-reviewer disagreements** — two findings were the
same defect reached from different directions (exec H-2 = trader M-1; exec H-3 =
trader M-2). The trader re-derived DD-8 against live marks and re-ran the round-1
mutation harness independently.

**Core money path verified clean by both.** The credit invariant, BTC-first
ordering, the span gate, the floor routing and max-credit selection were
confirmed against live data. The trader's re-derivation put **GOOGL C375 8/21 at
exactly +$248/contract, ranked 14th of 170 by `return_score`** — direct
confirmation that the `[:5]` truncation would have hidden it and that the
deviation was necessary. **Sign-off granted on that deviation.**

| # | Finding | Sev | Disposition |
|---|---|---|---|
| Exec H-1 | Cancel-then-verify did a single re-read and dispatched on `filled_qty` ignoring a non-terminal status. Alpaca cancels are **queued**; `pending_cancel` is a real intermediate state and such an order can still fill. Probe: STO ladder placed 3 sells that **all filled** while reporting `naked_exposure` "no naked position" (two genuinely naked calls); BTC reported `btc_timeout_canceled` with `order_status=pending_cancel` while the DAY order kept working | BLOCKER | **FIXED.** `_cancel_and_settle` cancels then polls to a terminal status (bound 15 s, 5 s interval). Non-terminal at the bound → fail safe: never place another sell, emit alert-wired `call_roll_unknown_disposition`, stop touching the position. Same for unreadable orders (an API blip used to mint a "verified zero fill"). Mutations M32–M36, M20', M21', M25' |
| Exec H-2 = Trader M-1 | STO partial fill: uncovered remainder invisible; `net_credit` computed across **mixed quantities** → BTC 2 / STO 1 reported `call_roll_completed` with **net_credit = −$590**, a blended debit labelled a credit, 100 shares uncovered, no naked-exposure-class event. Contradicts plan §1's own text | HIGH | **FIXED.** `net_credit` computed on the **replaced** quantity; both legs' qty × price reported explicitly; remainder raises alert-wired `call_roll_partial_naked_exposure`. Mutations M37, M38 |
| Exec H-3 = Trader M-2 | `call_roll_execution_error` and `call_roll_order_refetch_failed` not alert-wired, despite the build's own Gap-2 rationale saying execution_error carries naked-exposure weight | HIGH | **FIXED.** Both added to `roll_executed_alert_policy.json` (jsonPayload + textPayload), along with the two new terminals. Doc 2841/4000 chars |
| Exec M-1 | `strategy_lock` is in-process; Cloud Run can run 2 instances, so a manual `POST /roll` racing the 15:30 job on a different instance bypasses it — now wrapping a two-leg sequence | MEDIUM | **NOTED + runbook.** `--max-instances=1` added to the rollout as a required step, plus an explicit "manual triggers must not race the 15:30 slot" runbook line. Not enforced in code: the repo has no service-config-as-code, so the concurrency bound is a deploy-time property |
| Trader L-3 | A mutation anchoring rungs 3+ on `btc_limit` instead of `btc_filled_price` **SURVIVED** the suite (every prior test filled the BTC exactly at its limit, where the two coincide) | LOW | **FIXED.** Test added with BTC filling at 7.00 against an 8.40 limit and a fallback quoted at 8.00 — legal against the actual fill, rejected against the stale limit. Mutation M39 now KILLED |
| Trader L-2 | A broker rejection reaching terminal `rejected` reported `btc_timeout_canceled` with `disposition=terminal_no_fill` | LOW | **FIXED.** Now emits `call_roll_btc_rejected` with `rejected_after_placement=True`. Mutation M40 |
| Trader L-1 | A short call with no matching stock position was dropped silently pre-evaluation — the one shape nobody wants (a genuinely naked short call) was the one never mentioned | LOW | **FIXED.** Emits `call_roll_skipped{no_covering_shares}` and counts as evaluated. Mutation M41 |
| Exec L-1 | `settings.yaml` stale `# Call Rolling (Friday EOW) — FC-006` header | LOW | **FIXED** |
| Exec L-2 | `docs/gates.md` stale injected-calendar quirk paragraph (the rewritten roller gates span on `config.earnings_enabled`, so the quirk is gone) | LOW | **FIXED** |
| Exec L-3 + Trader L-5 | Deterministic `client_order_id` duplicate-rejection behaviour; off-tick `mid ± 0.05` limits | LOW | **NOTED in runbook** (below) |
| Trader (runbook) | A rolled position re-pins just above the money (Δ≈0.47) and is re-eligible next day → expect daily `no_credit_candidate` noise; watch `stock_quote_unusable` frequency in week 1 | — | **NOTED in runbook** (below) |

**Residual risk accepted:** exec M-1's instance race is mitigated by
configuration and procedure, not by code. If the operator wants it enforced, the
follow-up is a distributed lock (Firestore/GCS lease) — out of scope here, worth
an FC if manual triggers become routine.

---

## Plan deviations and gaps found

These are reported, not improvised around silently. Two need a reviewer's eye.

### Gap 1 — `find_suitable_calls` truncates to top-5, which defeats DD-3 (**resolved in code; needs sign-off**)

The plan's DD-3 says the roller "iterates the *legal* set" and executes the
maximum-net-credit candidate. But `find_suitable_calls` has always ended with
`return suitable_calls[:5]`, sorted by `return_score` = annualised yield ×
(1 − |delta|). That ordering prefers *low delta*, i.e. far-OTM, low-credit
strikes — so the top-5 slice systematically drops the near-money, high-credit
replacements a defensive roll wants, **before the roller ever ranks them**.

Concretely on the flagship trade: short-dated 8/07 strikes get a ~121×
annualisation multiplier against 8/21's ~21×, so a top-5-by-`return_score` slice
of GOOGL's chain is plausibly all 8/07 contracts — every one of which is a debit
against the 370 8/07 being closed. The cycle would have logged
`no_credit_candidate` while C375 8/21 sat at ≈ +$248.

This is the same failure mode DD-3 explicitly rejected ("letting an ordering
never designed for rolls silently pick the executed contract"), one layer
earlier. **Resolved by returning the full legal set on the `'roll'` profile
only**; the entry path keeps its `[:5]` slice, pinned byte-identical. Flagging it
because it is a deviation from the plan's literal text, taken to satisfy the
plan's binding intent.

### Gap 2 — the plan requires both per-position try/except and exactly-one-terminal

§Behaviour contract requires a per-position try/except so one bad symbol cannot
kill the cycle; DD-5 requires exactly one terminal per evaluated position. An
unhandled exception satisfies the first and violates the second. Added two
reasons not in the plan's list:

- `evaluation_error` — `call_roll_skipped{evaluation_error}` when
  `evaluate_roll_opportunity` raises (no order was ever placed).
- `call_roll_execution_error` — an **error**-severity terminal when
  `execute_roll` raises, deliberately *not* a skip: an exception out of
  `execute_roll` may have left a filled BTC behind, so it carries the same
  "look at this" weight as `call_roll_naked_exposure`.

### Gap 3 — `open_orders_unavailable` (new terminal reason)

The plan specifies the open-order guard but not what happens when
`get_orders` fails. Chosen: **fail closed** — without the open-order picture the
guard cannot protect against the double buy-to-close it exists for. Emits
`call_roll_skipped{open_orders_unavailable}`. Mutation M31 pins it.

### Gap 4 — `invalid_expiry` (new terminal reason)

If the old contract's expiry will not parse there is no horizon to bound the
replacement by. Fails closed with its own reason rather than being mislabelled
`invalid_strike`.

### Gap 4b — the STO partial remainder diverged from the plan (**found by review, not by me**)

Plan §1 says, of a rung's partial fill: *"the uncovered remainder falls through
to the naked-exposure terminal if no later rung covers it."* The shipped build
did not implement that — it reported `call_roll_completed` and computed
`net_credit` across mixed quantities, so a 2-contract BTC against a 1-contract
STO produced **net_credit = −$590**, a blended debit labelled a credit, with 100
shares uncovered and no naked-exposure-class event at all.

**This was a plan-contract violation I missed and did not list among my
deviations** — the original list claimed partial-fill truth was handled, which
was true for the *BTC* leg only. Latent on today's 1-lot book, but a money-path
contract violation regardless. Fixed per the disposition table; recorded here
because "the deviations list was incomplete" is itself a finding worth carrying.

### Gap 5 — fallback rungs whose natural price violates the invariant are skipped, not repriced

The plan says each rung re-passes "`validate_roll` + the invariant". A rung
whose quote-derived price is below `btc_filled_price + min_credit` could either
be *skipped* or *repriced up to the floor*. Implemented as **skip**, matching the
plan's "re-passing … the invariant" phrasing. Consequence: in a falling tape the
ladder terminates early rather than posting progressively less fillable limits —
correct under credit-only doctrine, but it is a choice, not a derivation.

### Gap 6 — `call_roll_dry_run` is a sixth terminal

DD-5's table lists it as an event; the exhaustive-taxonomy paragraph lists five
terminals and omits it. In dry-run mode it *is* the terminal (nothing is
placed). Treated as a sixth terminal; T-11 runs in normal mode.

### Deviation 7 — shared date coercion moved

`_coerce_date` moved from `market_data` to
`src/utils/option_symbols.coerce_expiry_date` so `validate_roll`'s horizon bound
uses the identical parser. `market_data._coerce_date` is kept as a module-local
alias, so every existing call site and test reference resolves unchanged. A
second copy of a date parser is how two gates end up disagreeing about what a
contract expires on.

### Deviation 8 — `docs/gates.md` updated (not in the plan's file list)

Its roll-path table documented gates 20/22/23/24 that this FC deletes. Doc-only;
left stale it would actively mislead. Historical documents (`docs/plans/fc-006.md`,
`docs/investigations/`, `docs/releases/`) are deliberately **not** rewritten.

### Note — the FC-068 tripwire flipped, as designed

`test_the_friday_roll_seat_is_occupied_and_still_a_no_op` asserted
`rolls_executed == 0`. Its authors wrote it so that reviving the roller would
flip a test rather than quietly change every backtest number. It is now
`test_the_roll_seat_is_occupied_daily_and_every_roll_nets_a_credit`, asserting
that the cadence is daily (evaluations exceed the Friday count) and that **every
executed replay roll increased the strike and netted a credit ≥ 0**. The replay
does now execute rolls end-to-end through the backtest adapter — which is also a
live integration check of the whole two-leg path.

---

## Post-merge steps (orchestrator)

Ordering is deliberate. **Pause the Friday job before deploying**, or a Friday
deploy puts new roller code live under the old trigger before alert policies and
the daily job exist — the first live roll would happen unwatched.

### Step 1 — pause the Friday job (BEFORE the deploy)

```bash
gcloud scheduler jobs pause options-wheel-roll-friday --location us-central1
```

### Step 2 — deploy, verify the request timeout, and PIN THE INSTANCE COUNT

```bash
gcloud run services describe options-wheel-strategy \
  --region us-central1 \
  --format="value(spec.template.spec.timeoutSeconds)"
# must be >= 1800; raise it if lower — the cycle budget guard assumes the
# request survives to the 1800s attempt deadline.
```

**Required (review exec M-1): `--max-instances=1`.**

```bash
gcloud run services update options-wheel-strategy \
  --region us-central1 --max-instances=1
```

`strategy_lock` is an **in-process** lock. It serialises `/roll` against
`/monitor` and `/run` only within a single container. Cloud Run will happily run
two instances, and two concurrent `/roll` requests landing on different
instances bypass the lock entirely — which now wraps a two-leg order sequence
against the same positions. `--max-instances=1` is what makes the lock mean what
the plan assumed it meant.

Env changes, if any, via `--update-env-vars` only — **never** `--set-env-vars`
(it wipes the whole env set).

### Step 3 — alert policies, BEFORE the first cycle

```bash
gcloud alpha monitoring policies create \
  --policy-from-file=deploy/monitoring/roll_executed_alert_policy.json

# Replace the existing cost-basis policy with the version that includes the two
# roll-path skip events. Get its name first:
gcloud alpha monitoring policies list \
  --filter='displayName:"Cost-basis floor blocked a covered call"' \
  --format='value(name)'

gcloud alpha monitoring policies update POLICY_NAME \
  --policy-from-file=deploy/monitoring/cost_basis_alert_policy.json

# Verify both landed:
gcloud alpha monitoring policies list \
  --format='table(displayName,enabled,conditions.len())'
```

Both policies already carry `notificationRateLimit` (300 s on the roll policy, so
a second same-day roll still notifies) and `autoClose` in the JSON — no extra
flags needed.

### Step 4 — create the daily scheduler job

`describe` the Friday job first and copy any headers/auth it carries.

```bash
gcloud scheduler jobs describe options-wheel-roll-friday --location us-central1

gcloud scheduler jobs create http options-wheel-roll-daily \
  --location us-central1 \
  --schedule "30 15 * * 1-5" \
  --time-zone "America/New_York" \
  --uri "https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/roll" \
  --http-method POST \
  --attempt-deadline 1800s \
  --oidc-service-account-email 799970961417-compute@developer.gserviceaccount.com
```

**Timing budget, explicit.** The Friday job's live `attemptDeadline` is the 180 s
default with `retryCount` unset = 0 (verified live 2026-08-04). 180 s would kill
a real roll mid-ladder — the worst seam. The daily job sets 1800 s (Scheduler's
HTTP maximum) against a worst case of ≈ 600 s/position, with the in-process cycle
budget guard capping total work at 1500 s.

**Retry posture: keep retries at 0, deliberately.** A scheduler retry after a
deadline kill would re-enter a cycle whose partial order state it cannot see. The
daily cadence *is* the retry.

### Step 5 — supervised first cycle

During market hours, trigger manually and watch logs live:

```bash
gcloud scheduler jobs run options-wheel-roll-daily --location us-central1

gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND
   (jsonPayload.event_type:"call_roll" OR textPayload:"call_roll")' \
  --limit=50 --freshness=10m --format=json
```

The next scheduled cycle is live regardless — no gate, per operator decision.

> ⚠️ **Manual triggers must not race the 15:30 slot.** Even with
> `--max-instances=1`, trigger manually only *well before* 15:30 (or after the
> scheduled run has completed). The in-process lock is the only serialisation
> there is, and a second instance — from a deploy rolling over, a scaling event,
> or a raised max-instances — would bypass it while a two-leg sequence is in
> flight. If a manual run is still executing at 15:30, let it finish and skip
> the scheduled trigger.

**Known bound:** a manual trigger plus the 15:30 scheduled run can produce **two
rolls on one position in one day**. Each is independently credit-≥ 0 and
strike-increasing, so the composite is still profitable and monotone, but "one
roll per day" is a per-*cycle* claim, not a hard invariant.

### What is NORMAL in week 1 (from the trader review — do not debug these)

- **Daily `no_credit_candidate` on a freshly rolled position.** A completed roll
  re-pins the strike just above the money (Δ≈0.47), so the position is
  **re-eligible the very next day** (ratio ≥ 0.98) and will be evaluated every
  cycle until the stock moves. Expect a steady drip of `no_credit_candidate`
  skips on it. That is the credit invariant refusing marginal rolls, working as
  designed — not a stuck position.
- **Duplicate-order rejections are benign.** `place_option_order` mints a
  deterministic `client_order_id` from (symbol, qty, side, price). A retried
  HTTP request therefore *rejects* rather than double-placing — which is the
  point — but it surfaces as a rejection in the logs. A rejection whose
  `client_order_id` matches an order already on the book is the guard working.
  This also means a rung re-priced to *exactly* the same limit within a cycle
  will be refused; the ladder treats that as a dead rung and moves on.
- **Off-tick limits from imminence mode.** `mid ± $0.05` can land off the
  contract's tick grid (many options tick at $0.05 above $3.00, $0.01 below).
  Alpaca rounds or rejects depending on the contract. A rejected STO rung is
  handled (the ladder advances); a rounded one shifts the limit by up to a tick
  — always in a direction the invariant already tested at the *unrounded* price,
  so it cannot turn a credit into a debit by more than a rounding step. Worth
  watching in week 1; if it produces noise, quantising the pad to the tick grid
  is the follow-up.
- **Watch `skip_reason=stock_quote_unusable` frequency.** The two-sided +
  spread-sanity guard reads IEX, which is thin. A symbol whose IEX book is
  chronically wide will be skipped *every* cycle and never roll — silently, as
  far as the roller is concerned, because a skip is a correct outcome. If one
  symbol dominates this reason in week 1, the fix is a better quote source for
  the gate, not a looser bound.

**Instant stop, no deploy:**
```bash
gcloud run services update options-wheel-strategy \
  --region us-central1 --update-env-vars ROLLER_ENABLED=false
```

### Step 6 — post-first-roll verification checklist

- [ ] Terminal-event contract: N short calls → N terminal events in logs/BQ.
- [ ] If executed: both fills present in `trades_from_activities` after the next
      15-minute ingest, order IDs matching the `call_roll_completed` event; **no
      residual open orders** on either leg's symbol (cancel-then-verify worked).
- [ ] Assertions on the executed pair: new strike > old; new strike ≥ Alpaca
      `avg_entry_price`; replacement expiry ≤ **old expiry + 14 days** and
      < next earnings date; **fill credit = STO fill − BTC fill ≥ 0**;
      `call_roll_completed.contracts` matches the filled quantities.
- [ ] FC-030-channel notification received for `call_roll_completed`.
- [ ] If an AMZN-class position is present: its `no_credit_candidate` skip event
      exists — that skip **is** the credit-only proof.
- [ ] No `call_roll_naked_exposure`; if one fired, confirm the alert arrived and
      the next `/run` re-covered.

### Step 7 — after the first verified week

Delete `options-wheel-roll-friday`; file the `decision_events` `roll`-stage
follow-up FC (DD-5, deferred not dismissed); update the FC index and this plan's
`## Execution` section.

---

## DD-8 — first-cycle expectation table (re-derived live by the trader reviewer)

**Mark-dependent. Re-derive again at execution time; do not treat as a promise.**

| Position | Expected outcome | Why |
|---|---|---|
| GOOGL C370 8/07 (ITM) | **the expected roll.** Re-derived live: C375 8/21 = **exactly +$248**/contract (+$5 strike), **ranked 14th of 170 by `return_score`**; C380 8/21 ≈ +$13 (+$10 strike). Both ≤ old-expiry + 14 (8/21). Max-credit selection picks **C375 8/21**; expect `call_roll_completed` | the GOOGL-class window this FC is expedited for. The rank-14-of-170 figure is the direct proof that the entry-shaped top-5 slice would have hidden it, and that an eval-relative DTE frame would have excluded it outright |
| AMZN C262.5 8/07 (deep ITM) | `call_roll_skipped {no_credit_candidate}` | every strike-improving roll is a four-figure debit; **this skip event is itself the launch verification that credit-only holds** |
| AAPL C312.5 8/05 (OTM) | `call_roll_skipped {not_itm_enough}` — or the position is already gone (expired 8/05) | profit-taker's territory |
| NVDA C220 8/10 (OTM) | `call_roll_skipped {not_itm_enough}` | same; note NVDA earnings 8/26 — any replacement expiring ≥ 8/26 would be span-blocked if it were ITM |

**Finding nothing executable is also a pass.** The pass criterion is
**4 evaluated / 4 terminal events / 0 debits**, not "a roll happened."

---

## Rollback

- **Instant:** `--update-env-vars ROLLER_ENABLED=false` (~1 min, new revision).
- **Full:** revert the squash commit — which restores the Friday-only guard,
  making the daily job a harmless no-op (`skipped: not_friday`), so the revert is
  safe even before touching the scheduler — then pause/delete
  `options-wheel-roll-daily`, resume `options-wheel-roll-friday`, and roll back
  the alert-policy edits (delete the new policy; remove the two added event types
  from the cost-basis policy).

---

## Review gate

**Both adversarial reviews: DONE.** Trader (with live re-derivation) and
execution-lifecycle, fresh contexts, different personas. Both REQUEST_CHANGES,
strongly convergent, no reviewer-vs-reviewer disagreements. Every finding is
dispositioned in the table above — all fixed in code except exec M-1
(`--max-instances=1`), which is a deploy-time property noted in the runbook.

**Still required before merge: the confirmation pass.** Fixes landed in code, so
house rules require a scoped confirmation review — Fable, fresh context, reusing
one of the original personas, handed the combined required-fix list as the
contract. Its job is narrow: verify each fix landed, and check for regressions
introduced *while* fixing. Output sections: CONFIRMED / STILL BROKEN / NEW
REGRESSIONS / VERDICT.

The execution-lifecycle persona is the right one to reuse — the H-1 fix rewrote
the two-leg state machine's disposition logic, which is where a fix-time
regression would hide. Points worth its attention:

- `_attempt_stc` now returns three shapes (success / unknown / None); every
  caller branch must handle all three.
- The unknown-disposition path returns *before* the naked-exposure path — check
  that a genuinely exhausted ladder still reaches `call_roll_naked_exposure`.
- `call_roll_partial_naked_exposure` replaced `call_roll_completed` for the
  partial case; confirm a fully-matched roll still reports `completed` with the
  right `net_credit`.
- The autouse settle-timeout fixture makes the production constant invisible to
  every other test — confirm the source-literal assertion is the only thing
  standing between that and a silent regression to one-read behaviour.
