# FC-037 plan review — 2026-07-18

Two-reviewer adversarial pass on `docs/plans/fc-037.md` before any Phase 1 code,
per the stakes-calibration rule in `~/CLAUDE.md` (Phase 1 refactors live-wheel
code paths). Personas: senior options trader / Python dev, and production
reliability engineer.

**Both verdicts: REQUEST_CHANGES.** Neither reviewer saw the other's output.

Findings below are the merged, deduplicated list. Claims marked **[verified]**
were independently re-checked by the author after the reviews came back — the
reviewers' own evidence was not taken at face value.

---

## Independently re-verified before acceptance

| Claim | Check | Result |
|---|---|---|
| 3 tests failing in `test_call_seller.py` | `pytest tests/ -q` | **[verified]** 3 failed, 290 passed |
| Failures pre-date this branch | `git diff --stat main...HEAD` | **[verified]** 7 files, +436 lines, docs/tooling only — zero production code. Failures exist on `main`. |
| `opportunity_store` bucket is hardcoded, blob path has no strategy scoping | read `src/data/opportunity_store.py:18,329-340` | **[verified]** `bucket_name: str = "options-wheel-opportunities"`, path `opportunities/{date}/{time}.json` |
| 17 bare `Config()` calls in the Cloud Run server | `grep -c 'Config()' deploy/cloud_run_server.py` | **[verified]** 17 |
| `Config` has no `state_storage_bucket` property | `grep state_storage_bucket src/utils/config.py` | **[verified]** absent |
| `STATE_STORAGE_BUCKET` unset on live Cloud Run | `gcloud run services describe` | **[verified]** env is exactly `ALPACA_API_KEY, ALPACA_SECRET_KEY, FINNHUB_API_KEY, ALPACA_PAPER_TRADING, GCP_PROJECT` |
| No wheel state blob exists in GCS | `gcloud storage ls` across all 3 project buckets | **[verified]** no `wheel_state/` object anywhere |

---

## BLOCKERS

### B1 — Shared GCS opportunity store cross-fires orders between accounts
`src/data/opportunity_store.py:18` hardcodes bucket `options-wheel-opportunities`;
`_get_blob_path` (`:329-340`) returns `opportunities/{YYYY-MM-DD}/{HH-MM}.json`
with no strategy scoping. Both call sites (`deploy/cloud_run_server.py:182` writes
in `/scan`, `:308` reads in `/run`) pass only `config`.

Two services from the same image share the blob keys. The covered-call service's
`/run` would read the **wheel's** scan output and execute wheel cash-secured puts
in the covered-call account against $4M of margin buying power — and vice versa.

This directly falsifies the plan's rollback claim ("own account, own state, own
dataset — nothing shared to unwind"). Orders placed in the wrong account cannot
be unwound by deleting a service.

**Fix:** strategy-key the blob prefix as a sixth Phase 1 seam. No second service
may deploy before this lands.

### B2 — Wheel state persistence has never worked in production
`wheel_engine.py:40` resolves the bucket via
`getattr(config, 'state_storage_bucket', None) or os.getenv('STATE_STORAGE_BUCKET')`.
Neither source exists **[verified]**, so `WheelStateManager(storage_bucket=None)`
makes `_save_state`/`_load_state` unconditional no-ops
(`wheel_state_manager.py:60-62, 84-86`). No state blob exists in any bucket.

Wheel state has been in-memory-per-instance since inception. Consequences:

1. Phase 1 seam #3 (path parameterization + "legacy shim" + "one-time copy
   script") is **dead work** — there is nothing to migrate. The corresponding
   risk-register entry is built on a false premise.
2. Source #1 of the FC-029 R2 cost-basis chain (`wheel_state.stock_cost_basis`,
   `call_seller.py:429-441`) **never resolves in production**. The chain runs on
   BQ and the known-broken Alpaca fallback only. This is a live correctness gap
   the plan should have surfaced.
3. If Phase 1 wires up `STATE_STORAGE_BUCKET` for the first time, that is a
   **behavior change to the live wheel**, not the "behavior-preserving by
   construction" refactor the plan claims — cost-basis floors would start
   resolving from source #1 and change which strikes are sellable.

This is the same class of latent-dead-code bug as FC-035 (`poll_order_statuses`
`NameError`) and FC-015 (`_entry_times` in-process only).

### B3 — 17 bare `Config()` sites; one missed conversion trades the wrong account
`deploy/cloud_run_server.py` has 17 `Config()` calls with no argument
**[verified]**. `Config.__init__` defaults to `config/settings.yaml` (`config.py:46`)
and resolves credentials via the hardcoded `_SECRET_MANAGER_MAP` → the **wheel's**
keys. Same image, both services. Any unconverted endpoint silently authenticates
as the wheel and acts on it.

Account isolation — this plan's entire thesis — would be enforced by nothing but
17 hand-edits, with no compile-time or runtime check.

**Fix:** one module-level `get_config()` resolving `STRATEGY_CONFIG` once, **plus**
a startup assertion that `get_account().account_number` matches an
`expected_account_number` pinned in the YAML (`PA37XLNWDLB3` / `PA3D36DVXSZ2`,
both captured in Phase 0). Refuse to serve on mismatch.

### B4 — Inherited drawdown pause makes the covered-call strategy inert
`call_seller.py:123-134` + `config.py:283` default `call_drawdown_pause_threshold:
0.05` (FC-029 R3). If `(cost_basis - price)/cost_basis >= 0.05`,
`evaluate_covered_call_opportunity` returns `None`.

That is a **wheel** rule — the wheel is assigned stock it did not pick, and
pausing lets it recover toward the put strike. A covered-call book is the
opposite: the operator chose the stock, and premium collection during a drawdown
is the economic point. Inherited as-is, the strategy stops writing calls on any
name down >5% from `avg_entry_price` — most of the book in any correction, and
permanently on anything bought near a local high.

Stacked with the `min_strike_price = avg_entry_price` floor (`:136`), two
independent gates hard-block on the same condition.

**This is why the 3 tests fail** — all three error with
`drawdown pause cost_basis=305.0 current_price=175.0 drawdown_pct=0.4262`.
The plan's own gate ("full pytest suite green on each phase") is violated at
Phase 1 start, in the exact module Phase 1 refactors.

Suggested policy: a **net** floor — `strike + premium_received >= cost_basis` —
which is the economically correct rule and which the wheel does not implement.

---

## HIGH

### H1 — Naked-call guard's OCC parser is wrong and can fail open
`execution_engine.py:322-338`. Two defects:
- `'C' in opt_sym` matches 'C' **anywhere** in the OCC symbol including the
  ticker. `CRWD250718P00150000` → a short *put* counts as committing 100 shares
  to calls. The current wheel universe contains no 'C' ticker — safe by luck.
- The digit-break underlying parser breaks on class shares: `BRK.B` position
  symbol vs `BRKB...` OCC symbol → no match → `committed_shares = 0` →
  **guard fails open → naked calls written against committed shares.**

The covered-call account has no configured universe *by design*, so this goes
from theoretical to operator-triggerable. Use `src/utils/option_symbols.py` and
match the option-type character at its fixed offset.

### H2 — The plan's Phase 2 sizing mechanism does not exist
Plan says "sell up to `floor(uncommitted_shares/100)` contracts — the existing
`ExecutionEngine` share guard already computes committed-share accounting."
It does not size. `call_seller._calculate_call_position:215` computes
`max_contracts = shares_owned // 100` from **owned**, never uncommitted, shares.
`ExecutionEngine:339-359` then rejects the whole opportunity — binary, no partial
sizing.

Modal covered-call workflow breaks: hold 300 shares with 3 calls open, buy 100
more → seller proposes 4 → guard sees `available=100 < 400` → blocked. **The
incremental lot is never covered, forever.** Sizing must move into the seller.

### H3 — No earnings gate on *opening* covered calls
`EarningsCalendarService` is injected only into `CallRoller`
(`call_roller.py:39,45,78-79,108-109`); `CallSeller` has no earnings check at all.
The plan lists `EarningsCalendar` under "Reuse," implying coverage that does not
exist for new writes. A book with no symbol universe will write short-dated calls
straight into earnings prints on names nobody vetted.

### H4 — `CallRoller`'s wheel coupling understated by ~an order of magnitude
Plan: "decouple its `wheel_state.record_call_roll` hooks." Actual: `wheel_state`
is a **required positional** (`call_roller.py:37`) used at 8 sites — and two are
*decision gates*, not bookkeeping: `get_roll_count` (`:73,:340`) enforces the
max-roll limit, `get_active_call_details` (`:147`) supplies the strike/premium the
roll is computed against. Phase 2's "simple state: HOLDING_STOCK → SELLING_CALLS"
state manager cannot support this. Either scope it properly or drop rolling from
Phase 2.

### H5 — Blanket adoption has no opt-out, contradicting the operator model
Phase 2 adopts every equity position as call-writing inventory. But "operator
discretion over holdings" is not discretion over what gets *written against*.
There is no exclusion list, no per-symbol enable, no minimum-hold flag. A
long-term hold gets called away; a large unrealized gain gets called away,
forcing an unauthorized taxable event.

**Fix:** an `excluded_symbols` list, or write the invariant into the plan as an
operator contract: *this account holds nothing you are unwilling to have called
away.* Currently it has neither.

### H6 — New BigQuery dataset will 403 on first write
Runtime SA `799970961417-compute@developer.gserviceaccount.com` has
`bigquery.dataViewer` + `bigquery.jobUser` but **no `dataEditor`** and no
project Editor. Writes to `options_wheel` work only via a dataset-level WRITER
grant. A new `covered_call` dataset gets no such grant, and the SA cannot
`datasets.create`. Covered-call service would trade fine but silently lose all
journaling. Phase 3 says "dataset `covered_call`" with no IAM step.

### H7 — "Check both formats for one day" describes code that does not exist
Idempotency is entirely broker-side: `alpaca_client.py:521-523` hands the id to
Alpaca; there is **one** call site, no local order registry, no
reconciliation-by-id. On a mid-day deploy a retry rehashes to a new prefixed id,
Alpaca sees it as new, and **fills a second contract**. With 6 `/run` + 6 `/scan`
schedules during market hours and a confirmed duplicate-order history (FC-009),
this is not theoretical.

**Fix:** keep the unprefixed id for `strategy_id == "wheel"` permanently and
prefix only new strategies — zero deploy-boundary risk. Or make "deploy after
close" a mandatory single option.

### H8 — Scheduler cloning is ~5x larger than stated
Plan: "clone the jobs (`/run`, `/monitor`, `/roll`, activities ingest)." Live
inventory in `us-central1`: **29 jobs, ~20 enabled and wheel-bound** — 6×
`execute-*`, 6× `scan-*`, 6× `monitor-*`, `options-wheel-roll-friday`, 2×
activities-ingest, plus portfolio/stock history and `regression-hourly`. Two
different URL conventions in use with no documented reason. Hand-cloning will
drift; script it.

---

## MEDIUM

- **M1 — Credential indirection won't work as designed in Cloud Run.**
  `_load_secret` (`config.py:33`) reads `GOOGLE_CLOUD_PROJECT` / `GCP_PROJECT_ID`;
  Cloud Run sets neither, `cloudbuild.yaml:75` sets `GCP_PROJECT` — a third name.
  The Secret Manager fallback has never executed in production; it works only
  because `--set-secrets` injects values as env vars. If seam #1 makes runtime
  Secret Manager calls, it returns `""` and `_validate_config:126-129` crashes the
  service on boot. Keep env-var injection; make the seam only about *which env var
  names* the YAML references. Also `_validate_config:126` names `ALPACA_API_KEY_ID`
  while the map keys on `ALPACA_API_KEY` — wrong error message today.
- **M2 — No dividend / early-exercise handling anywhere in production.**
  `grep -rni "dividend|ex-div|CDIV" src/` (excl. `backtesting/`) → zero hits. The
  *backtest* broker models it (`broker.py:299 assign_call_early(reason="ex_dividend")`,
  `:308 credit_dividend`), so the simulator models a risk production is blind to.
  Early assignment before ex-dividend is the classic covered-call blowup, and far
  likelier here than in the wheel's low-yield mega-cap universe.
- **M3 — `avg_entry_price` is not exposed by `AlpacaClient.get_positions()`**
  (`alpaca_client.py:248-256` returns `symbol, qty, side, market_value, cost_basis,
  unrealized_pl, asset_class`). `StockEntryCostBasisProvider` is not a drop-in;
  existing code approximates it as `cost_basis / shares` (`call_seller.py:488`).
- **M4 — The 4x-margin mitigation targets the wrong code.**
  `position_sizing.py:38-39,63,396-399` reads `buying_power` unconditionally —
  there is no config knob to "assert on"; adding one is a change to shared risk
  code. And it sizes *puts*; covered-call contract count comes from
  `shares_owned // 100` and never touches it. The real exposure is that the
  *operator* can buy $4M of stock on $1M equity. Correct mitigations: set
  `max_portfolio_allocation` against equity, and alert on
  `long_market_value > equity`.
- **M5 — Three ingestors missing from Phase 1 scope**: `activities_ingestor.py:92`,
  `portfolio_history_ingestor.py:66`, `stock_history_ingestor.py:75` all default to
  `options_wheel`. `activities_ingestor` ingests OPASN/OPTRD — every assignment and
  call-away in the covered-call book. The plan's own verification checklist tests
  it while never scoping it. Also `call_seller.py:522` hardcodes
  `` FROM `options_wheel.trades_from_activities` `` **inside a SQL string literal**,
  contradicting seam #4's "nothing is hardcoded."
- **M6 — Schema-aware validation needs a golden-file test.** `_validate_config`
  (`config.py:110-231`) hard-requires `['alpaca','strategy','risk','stocks','monitoring']`
  and validates ~20 fields, several wheel-only. `stocks.symbols` is required and
  non-empty (`:209-212`) but Phase 2 derives the CC universe from holdings, so it
  must become optional — unstated, and a boot-time crash. Require a test that loads
  the **unmodified** `config/settings.yaml` and asserts a byte-identical parsed
  config plus an identical set of raised validation errors, before/after.
- **M7 — `client_order_id` prefix is a net-negative trade at Phase 1.** The
  "latent collision" the plan cites is the deterministic idempotency the docstring
  (`alpaca_client.py:118-123`) explicitly promises; Alpaca rejecting the duplicate
  is the feature working. Uniqueness is scoped per account, and the strategies are
  in separate accounts — so the prefix has value only under the consolidation the
  plan defers indefinitely, in exchange for rotating a live idempotency key on the
  money-making wheel.

## LOW

- **L1 — Stale line references throughout**: `simulator.py:226`→243, `:332,337`→349,354,
  `config.py:115`→109, `wheel_engine.py:1267`→1262. Individually trivial, but the
  plan's persuasive force rests on its citations.
- **L2 — `_generate_client_order_id` has exactly one call site** (`alpaca_client.py:523`),
  not "every call site" as the plan states.
- **L3 — Secret IAM policies are empty** (`{"etag":"ACAB"}`) — access is project-level,
  so the covered-call service can read the wheel's credentials and vice versa.
  Acceptable at paper, not at live.
- **L4 — Credential rotation is an unenforced comment.** Both `-cc` secrets have
  exactly one enabled version, created 2026-07-18T07:28 — the transcript-exposed
  keys are live. Move rotation into the Rollout checklist as a hard gate with a
  version-count assertion.

---

## Structural critique (both reviewers, independently)

**The plan is structured as an *extensibility* project when the risk is
concentrated in a *strategy* it treats as solved.** Phase 1's seams are ~200 lines
of mechanical plumbing; Phase 2 — "reuse `CallSeller`, `CallRoller`,
`ExecutionEngine`" — is one paragraph, and is where six of the findings above
live. Each is a case where wheel semantics are silently wrong for a covered-call
book:

| Wheel semantics | Covered-call reality |
|---|---|
| Cost basis = assigning put strike (exogenous) | = purchase price the operator chose |
| 5% drawdown → pause and wait for recovery | drawdown is exactly when you want premium |
| One call per assigned lot, flat→flat cycle | inventory grows/shrinks by hand; needs incremental coverage |
| Low-yield tech universe, dividends ignorable | discretionary book; dividend payers likely |
| 14 vetted symbols | **no universe, no selection criteria** |
| Earnings gated on roll only | same gap, on names nobody vetted |

The plan's load-bearing reuse claim — "`call_seller.py` is ~70% reusable, the one
wheel assumption is `_resolve_cost_basis_floor`" — is false. The drawdown pause
(`:123`), the sizing basis (`:215`), the absent earnings gate, and the hardcoded
BQ dataset (`:522`) are four more wheel assumptions in the same file. The 70%
figure was estimated, not measured, and on the dimension that matters — decision
policy, not line count — the reusable fraction is much lower.

**The reviewers also disagreed with the plan's own consistency on consolidation.**
The universe guard was dropped because consolidation is hypothetical; the
`client_order_id` prefix was kept *for* consolidation — and it costs a live
idempotency-key rotation. Same hypothetical, opposite reasoning. Pick one.
Recommendation: drop both, and add an inventory *validator* (optionability,
liquidity, spread width) on its own merits — the guard was the only mechanism
that ever inspected what the CC book was allowed to touch, and dropping it left
that hole unnoticed.

**Correct framing for Phase 1** is not "five seams" but: *enumerate every piece of
process-global or externally-shared state and prove each is strategy-keyed or
strategy-agnostic.* `grep -rn "options_wheel\|wheel_state\|opportunities/" src/ deploy/`
turned into a checklist would have caught the opportunity store.

### Design alternatives neither considered nor recorded

1. **A separate `CoveredCallSeller` class** rather than injecting a
   `CostBasisProvider` into `CallSeller`. Given six divergent policies, two classes
   sharing a small sizing helper is likely less total code and removes the risk
   that a future wheel tweak silently changes covered-call behavior. The
   "fork-in-disguise" risk applies to *services*, not two sellers in one tree.
2. **A read-only shadow phase** where the CC engine observes a hand-managed book
   and logs what it *would* have done — the cheapest way to surface all six policy
   mismatches before any order is submitted.
3. **A per-symbol opt-in file** — the middle ground between "configured universe"
   and "adopt everything" that the plan never considered.
4. **Defer Phase 1's live-wheel refactor until Phase 2 is proven.** Phase 1's only
   consumer is Phase 2; building Phase 2 against a hardcoded second config first
   avoids touching production wheel code for a strategy that may change shape.
5. **A separate `CoveredCallConfig`** sharing only the YAML/env/secret loading
   machinery, leaving the live wheel's 600-line wheel-shaped validation path
   literally untouched. For a change whose #1 stated risk is "refactors regress the
   live wheel," that trade looks favorable.

### Missing entirely

- **Monitoring/alerting**: no alert policy for the CC service; nobody paged.
  Worse, Phase 3's verification gate is "both services' bot-execution-health
  dashboards clean" — but Phase 5 defers multi-strategy dashboard support, so
  **that dashboard does not exist at Phase 3 time.** Circular dependency.
- **Runbook**: the plan invents the operator rule "never manually sell shares
  while short calls are open" and only "document"s it. No `docs/operations/`
  runbook, no answer to "the naked-call alert fired, what do I do."
- **Rollback rehearsal**: "redeploy previous image" is untested, and rolling back
  the image does not roll back GCS blobs or BQ rows.
- **Cost / shared Finnhub quota**: `finnhub-api-key` is a single secret shared by
  both services — two services on one rate limit, no quota-headroom discussion.

---

## What both reviewers affirmed

- The **separate-account recommendation is correct and well-argued**; all four
  anti-tagging grounds check out against real code, and #3
  (`reconcile_positions` adopting foreign positions, `wheel_engine.py:1262`) is
  decisive on its own.
- **Phase 0's empirical verification** against the live API — rather than
  assuming — is the right methodology.
- **The Phase 4 rewrite** (recognizing the backtest rebuild deliberately replays
  production code, and that a `Strategy` protocol with one implementor is
  premature) reverses the plan's own earlier position and is correct.
- The **honest downward re-scoping of seam #4** and the flagging of credential
  rotation as mandatory.
