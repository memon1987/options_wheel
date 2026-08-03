# FC-013 — Earnings blackout gate on the live sell path

**Plan:** `docs/plans/fc-013.md` (rev 2.2 — twice adversarially reviewed, operator
window decision binding)
**Branch:** `fc-013/earnings-gate` off `origin/main` @ `32a856c`
**Investigation:** `docs/investigations/earnings-pop-callaway-2026-08-03.md`

---

## What this is

Three incidents on record, one root cause: **no earnings gate has ever existed on
any path that opens a position.** The `earnings.*` knobs read as live and gated
nothing. This wires one gate, at the scanner, covering both legs, in production
and in replays.

- **GOOGL cash-secured put**, filled 2026-04-28, earnings 04-29 — `days_until = 1`.
- **AAPL covered call C347.5**, filled 2026-07-30 15:15 ET, hours before the AMC
  report — `days_until = 0`, expiry 08-03 ≥ 07-30, **spanning**. Profited $165
  because AAPL gapped **down** 8.5%.
- **AMZN covered call C262.5**, filled 2026-07-30 10:15 ET, morning of the AMC
  report — `days_until = 0`, expiry 08-07 ≥ 07-30, **spanning**. AMZN gapped
  **+12.3% through the strike**: **$2,308 of upside surrendered against $222
  collected.** Same trade shape as AAPL's, coin the other way.

The shipped configuration blocks all three. Encoded executable as
`test_the_incident_geometry_is_blocked`, and pinned in the recurring audit
script so a future run that cannot locate one stops rather than restating the
criterion against new numbers.

### Full-book economics — the number the operator decided with

The July-window counterfactual above is a *sample*, and a small one. Against the
**whole fill history (341 option sell-to-open fills)** the shipped configuration
blocks **20 fills, 5.9% of the book**:

| Leg | Predicate | Fills blocked | Realized on those fills |
|---|---|---|---|
| Puts | `days_until <= 2` | 12 | $2,150 |
| Calls | SPAN | 8 | $2,841 |
| **Total** | | **20 (5.9%)** | **$4,991** |

**On realized history alone this gate is net negative: ~$4,991 of realized
premium forgone against one ~$2,308 tail event.** That is the honest arithmetic
and it is not close.

The case for shipping it anyway is *not* the backward-looking P&L — it is:

1. **The tail prior.** Realized history contains exactly one gap-through-strike
   event because the sample is ten months long, not because the frequency is
   1-in-341. The $4,991 is spread across every earnings cycle; the $2,308 landed
   in one morning. One AMZN-scale gap-up every few seasons pays for permanent
   span gating, and the gap-down cushions that make up most of the forgone
   premium only *stay* cushions while gap-downs outnumber gap-ups.
2. **Killing the adverse selection (FC-073).** Earnings IV is what pushes
   marginal strikes over the premium floor — the AMZN 10.9%-OTM trade existed
   *at all* only because IV was 0.68. The scorer is structurally attracted to
   the highest-risk day of the cycle. The gate removes that selection pressure,
   which is a benefit no P&L-on-realized-history calculation captures.

**The operator made the window decision with these numbers on the table**
(2026-08-03, binding). Recording them here so the record shows the trade-off was
priced, not overlooked.

---

## Per-leg semantics (DD-3 — operator decision 2026-08-03, binding)

**The legs diverge deliberately. Their exposures are mirror images; their costs
are not.**

| Leg | Predicate | Granularity | Knob |
|---|---|---|---|
| Puts | `0 <= (next_earnings_date − today) <= 2`, calendar days, inclusive | symbol-level | `earnings.blackout_days: 2` |
| Calls | `expiration_date >= next_earnings_date` | **per candidate** | none — span is a predicate, not a tunable |
| Unknown | calendar cannot answer | symbol-level, **both legs** | — |

- **Puts, N=2:** put-side realized-loss risk concentrates in immediate pre-event
  *entries* (the GOOGL shape), while wide-window pre-earnings put income was the
  book's best bucket — 100% win rate, $301 average. A wide put window would
  forfeit the best trades to block a risk that lives in the last two days.
- **Calls, true span:** any call whose expiry covers the report carries the full
  gap. A days-until N is only a proxy. The operator explicitly rejected both
  alternatives — hardcoding 7 manufactures a silent disconnect the day trading
  parameters extend past 7 DTE; deriving N from DTE over-blocks progressively at
  longer DTE, making a 30-DTE call that expires *before* the event illegal. Span
  is DTE-invariant by construction. `>=` is inclusive: assignment on an expiry
  landing on the report date resolves after the report.
- **No symbol-level blackout skip on the call leg.** A symbol reporting in three
  days may legally sell a call expiring in two.
- **Unknown is symbol-level on both legs** because a span test needs a date.

**Residual accepted, on the record.** Span also blocks the spanning calls that
*profit* on gap-downs (AAPL's C347.5 made $165; GOOGL's two July spanners made
$584 combined). Accepted because the asymmetry is ~10:1 the other way — one
gap-up pop costs ~$2,300 gross (~$1,500–2,100 re-arm-adjusted) against a
~$100–200 cushion per gap-down — and the cushion trades are exactly the
earnings-IV bait the scorer over-selects (cross-ref FC-073).

---

## Per-section summary

### §1 — Service layer (`src/api/earnings_calendar.py`, `src/utils/config.py`)

- **Constructor fix (required by both plan reviewers).** Every attribute is now
  set on every path. The old early `return` on a missing key exited before
  `_enabled` / `_cache_ttl_hours` / `_lookahead_days` were assigned, so every
  later method call raised `AttributeError` — which the scanner's broad `except`
  misfiled as `scan_failure`, producing zero opportunities **and zero gate
  telemetry**, indistinguishable from a broken scanner. Enabled-but-unusable now
  logs one `earnings_gate_unusable` error event and leaves `_client = None`;
  disabled-and-unusable logs a warning instead. *Disabled* and *broken* are
  different states with different behaviour, by design.
- **Tri-state surface (DD-2).** `next_earnings_info() -> (status, date)` with
  known / clear / unknown, and `earnings_within() -> Optional[bool]` derived from
  it. `None` is "could not tell" and is **not** `False`. Rev 1 tried to make the
  existing boolean surface fail closed by flipping its error paths; that method's
  `None` branch conflates "Finnhub failed" with "nothing in the next 90 days", so
  the flip would have blocked every known-clear symbol — an account-wide brick on
  a normal day. The roller's three methods are untouched and still fail open.
- **Two-layer cache.** L1 moves instance → module scope: `/scan` builds a fresh
  scanner (and service) per request, so the instance cache never survived one
  request and `cache_ttl_hours` governed nothing. L2 is a small GCS blob in the
  opportunity bucket, read once per process and written through after each
  successful fetch, because min-instances=0 leaves L1 cold nearly every scan
  (~84 Finnhub calls/day and +2–6s per scan without it; ~14/day with it).
  **Every GCS failure mode is a cache miss, never a block.** Eviction uses
  `.pop(symbol, None)`.
- **`EARNINGS_ENABLED` env override (DD-7).** The yaml value is baked into the
  image, so a config rollback rides Cloud Build — the pipeline that once sat
  silently red for 11 days (FC-031). An unparseable value is ignored (yaml wins)
  rather than read as false: a typo must not disable a risk control.
- **DD-3 lookahead invariant** asserted in `_validate_config`:
  `earnings.lookahead_days >= call_target_dte + 7`, so a future DTE extension
  cannot silently outrun the calendar.

### §3 — The gate (`src/data/options_scanner.py`, `src/api/market_data.py`)

- Put leg gated before `_has_existing_position`, so the event count reads as the
  earnings exposure of the post-stage-1 candidate set, held or not.
- `find_suitable_calls` gains `exclude_expiry_on_or_after`, counted under a new
  **`expires_into_earnings`** key in the published stage-8 rejection stats. The
  counter is incremented **last** in the criteria chain, so it means "a strike
  that otherwise qualified was taken by the event" — which is what makes the
  emptied-set test precise. A candidate rejected for delta is attributed to
  delta, not to earnings.
- An **unparseable expiry is rejected** when a span floor is set. Structurally
  unreachable today, which is exactly why it must not be the one path where
  "could not tell" resolves to "sell it".
- Call-leg unknown skip sits **before** cost-basis resolution: an unanswerable
  symbol spends neither a resolver call nor a BigQuery cross-check.
- Span-emptied symbol → `call_scan_skipped_earnings_blackout` + decision row
  `blocked{earnings_blackout}` carrying basis/underwater. Empty **with zero span
  rejections** stays the ordinary `no_candidates` path, untouched.
- **Config wins over injection (DD-8):** `earnings_enabled` falsy means no gate
  even when a calendar is injected, so a live rolloff cannot leave replays gated.

### §2 / §4 / §5 — Replay seam

- `HistoricalEarningsCalendar` grows the same tri-state surface. It **never
  returns unknown**, and that asymmetry with live is deliberate: a replay
  "outage" is a table gap, and blocking would silently zero out that symbol's
  entire replay — a pessimistic bias corrupting the verdict rather than
  protecting anything. It fails open and **reports**.
- New: `horizon_for()` + `symbols_past_horizon`. A symbol *present* in the table
  with only *past* dates previously answered exactly like genuinely-clear —
  silent fail-open at the table's edge, and the 2026-07-18 table had most
  reporters' last dates already behind us by 08-01. Both sets surface in the run
  report's data-quality block.
- Simulator passes the calendar to the scanner — the one-line obligation FC-068
  created. Same instance the roller already had: one point-in-time truth per
  replay.
- Tally: both `*_earnings_blackout` events mapped. The `*_earnings_unknown` pair
  is deliberately **unmapped** (the historical calendar cannot emit it), and a
  test pins that so a future reader does not "fix" it.

### §7 / DD-6 — Alerting and docs

- `deploy/monitoring/earnings_gate_alert_policy.json` — matches three event types
  on `jsonPayload` **and** `textPayload`, **no severity clause** (Cloud Run
  captures stderr as plain text with empty severity; a `severity>=WARNING` clause
  matches nothing — FC-030 fire drill, 2026-07-18). Existing verified email
  channel, 24h rate limit. Rev 2's claim that these events "flow through the
  existing FC-030 baseline" was **verified false**, which is why this is a
  required deliverable, not a follow-up.
- Runbook Alert 4 with transient-vs-persistent triage, gcloud commands, the
  emergency lever, and a fire drill.
- `docs/gates.md` — the FC-069 items 3/14 cross-reference target: every gate
  across three stages plus the roll path, config keys and env overrides, event
  names, decision-record outcomes, rejection-stat keys, alert coverage, replay
  parity, the detective layer, and test anchors. Carries item 3's emergent
  one-position invariant **with its open-order caveat verbatim**.
- Step-0 audit script committed at `tools/diagnostics/fc013_earnings_exposure_audit.py`
  (cherry-picked from `fc-013/step0-audit` with the refreshed earnings table).

### §9 — Hermeticity

`_no_finnhub` autouse fixture: `FINNHUB_API_KEY` pinned **unconditionally**,
`_fetch_earnings` chokepointed on the class, both L2/GCS helpers no-op'd, L1
cleared before **and** after every test. `real_finnhub_fetch` is the escape
hatch. Also added `_build_client` as a patchable seam — without it the suite's
default gate behaviour would hinge on whether `finnhub-python` happens to be
installed, which is the ambient-environment defect class this suite has been
bitten by three times.

---

## Validation

- **Full suite: 1125 passed** (main baseline 1025, +100; 1115 at build, +10 from
  the review fixes). `__pycache__` cleared before the final run — stale `.pyc`
  from mutation testing has made correct code misbehave on this repo before.
- **Frontend untouched:** the branch diff contains no `dashboard/` files.
  DD-4's cascading-impact check was performed instead: `uncovered_decisions_sql`
  selects `reason` as a free string and `DrawdownPauseCard.tsx` renders it
  free-form (`{p.outcome}{p.reason ? ' · ' + p.reason : ''}`), so the two new
  reasons are additive-safe. No display-label mapping exists, so none was added.
- **`deploy/cloud_run_server.py` and `main.py` diffs are empty** (reviewer
  checklist item, FC-068's pattern) — both construct through the default path.
- **`earnings_avoidance_days` untouched** (FC-069's sweep owns it): still present
  in `config/settings.yaml:148` and `src/utils/config.py:589`.

---

## Mutation record

Every mutation was applied on top of the committed code, run, then reverted; the
tree was verified clean and the full suite re-run green afterwards.

| # | Mutation | Test | Result |
|---|---|---|---|
| 1 | Put-leg gate reverted (`_put_leg_blocked_by_earnings` call disabled in the loop) | `test_put_scan_skips_symbol_in_earnings_blackout` | **FAILED** ✓ |
| 3 | Span → days-until ≤ 2 (`market_data`) | `test_call_candidate_spanning_earnings_is_rejected` | **FAILED** ✓ (9 failures across the two files) |
| 4a | Hardcoded N=7 symbol-level block replaces span (scanner) | `TestCallLegEarningsSpanGate::test_call_candidate_expiring_before_earnings_is_allowed` | **FAILED** ✓ |
| 4b | N derived from `call_target_dte` replaces span (scanner) | same test | **FAILED** ✓ |
| 4c | Span → days-until ≤ 7 (`market_data`, the chain-level form of the same mistake) | `TestCallSpanFilter::test_call_candidate_expiring_before_earnings_is_allowed` | **FAILED** ✓ |
| 7 | Span reverted — no floor threaded into the chain | `test_the_incident_geometry_is_blocked` | **FAILED** ✓ (4 failures in the file) |
| 15a | Simulator stops passing `earnings_calendar` to the scanner | `test_replay_uses_the_point_in_time_calendar_never_finnhub` | **FAILED** ✓ — with `AssertionError: a replay must never construct the live Finnhub service` |
| 15b | Both gates reverted (put call disabled + span floor `None`) | same test | **FAILED** ✓ |
| **PD** | **Past-date guard removed** from `_is_stale` (the review fix) | 6 of the 9 new past-date tests | **FAILED** ✓ — see below |

**Past-date guard mutation (required by the review), run on commit `0d49eba`:**

Removing the three-line guard failed **6 tests across both layers**:

- `test_a_within_ttl_cached_yesterday_date_is_not_served_as_known` — regression (a)
- `test_the_stale_past_entry_is_evicted`
- `test_a_failed_refetch_reports_unknown_not_the_past_date`
- `test_a_past_dated_l2_entry_is_not_hydrated`
- `test_candidates_are_emitted_on_the_day_after_earnings` — regression (b)
- `test_no_false_blackout_row_is_written`

Three tests **correctly kept passing**, which is the control that the guard did
not over-fire: `test_todays_date_is_still_served` and
`test_the_still_future_date_is_honoured_the_same_day` (day-of must still block —
the incident geometry) and `test_parity_with_the_replay_calendar` (the replay
calendar was already correct). Guard restored, tree verified clean, full suite
re-run green.

Notes on the record:

- **Test 4 required two mutations by the plan and got three.** 4a/4b are the
  scanner-level forms the operator explicitly rejected; 4c is the same mistake
  made one layer down, added because the scanner-level test cannot see a
  `market_data`-level regression. The `market_data`-level test 4 correctly
  *passed* under 4a/4b (different layer) and *failed* under 4c.
- **Test 15 fails two distinct ways, as the plan specifies**, and both were
  exercised separately: 15a proves the seam, 15b proves the gate.
- **The replay test is protected against vacuity**: its two earnings dates are
  chosen against the fixture's verified ungated trade schedule (a call sold
  06-10 expiring 06-14 spans 06-12; a put sold 07-15 is one day from 07-16), and
  `test_replay_honors_earnings_enabled_false` runs the *same* table with the gate
  config-disabled and asserts both violations DO occur there.

---

## Review disposition

**Two adversarial reviews, both REQUEST_CHANGES. No reviewer-vs-reviewer
disagreements** — the two verdicts were disjoint in content and consistent in
direction, so nothing needed to be surfaced for adjudication.

Both reviewers independently re-ran the mutation set above and added their own;
**all were caught**. The `>=` span boundary was actively **VALIDATED** rather
than merely accepted: for an AMC reporter, a contract expiring on the report
date settles that afternoon and contrary exercise lands before the ~5:30pm ET
cutoff — after the report — so expiry-day-equals-event-day genuinely carries
the gap and the inclusive comparison is correct. The trade path verified clean.

### Required fixes — all addressed in code (`0d49eba`)

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | A cached **past** date was servable; the durable cache made it newly reachable. A date fetched on AMC report day survives the 24h TTL into D+1, threads as `exclude_expiry_on_or_after=yesterday`, span-rejects the entire chain, and produces a false `blocked{earnings_blackout}` on the IV-crush day the plan wants to sell into. Recurs every earnings cycle whenever the fetch anchor sat late on day D. Also a tri-state parity break with `HistoricalEarningsCalendar`, which has always filtered `>= today`. | **HIGH** | **Fixed.** Past-date check added to `_is_stale`, covering the L1 read and L2 hydration alike: evict + refetch. A failed refetch reports `unknown` (fail closed), the honest state. Day-of still blocks. Six new tests; mutation-verified below. |
| 2 | The broken-GCS test's `monkeypatch.setitem(sys.modules, "google.cloud.storage", …)` does not intercept `from google.cloud import storage` once the real module is imported — attribute binding on the package wins — so on any machine with the package installed it built a **real** client against `test-bucket`. | Medium | **Fixed.** Added `_storage_client()` as a patchable seam mirroring `_build_client`; both `_l2_read` and `_store_to_l2` use it, and the test patches the seam. `conftest` now hard-fails *any* GCS client construction, so even a test restoring the real `_l2_read` cannot reach one. Symmetric write-side test added. |
| 3 | The audit script pinned 2 incidents while the plan's fail-loudly contract names 3 — the flagship $2,308 AMZN C262.5 was not locatable by the recurring detective run. | Medium | **Fixed.** AMZN added, plus `expect_days_until` / `expect_spans` assertions on all three so a drifting join stops the run instead of quietly restating the acceptance criterion. |

**Environment drift disclosed (finding 2).** This venv is **missing
`google-cloud-storage`**, which `requirements.txt` declares
(`google-cloud-storage>=2.10.0,<3.0.0`). That drift is the only reason the
defective test looked hermetic locally — on CI or any correctly-provisioned
machine it would have constructed a real client. The seam fix removes the
dependence on that accident, but **the venv should be reconciled against
`requirements.txt` independently of this PR.**

### Non-blocking findings — all addressed in code, none deferred

| # | Finding | Disposition |
|---|---|---|
| 4 | PR body stated only the July-window economics. | **Fixed** — full-book economics added above: 20/341 fills (5.9%), $4,991 forgone vs one $2,308 tail, and the explicit statement that the gate is net negative on realized history alone. |
| 5 | `earnings_hour` unused by both predicates; kill-switch blast radius wider than the scanner. | **Fixed** in `docs/gates.md` — both recorded, including that `EARNINGS_ENABLED=false` also darkens `run_rolling_cycle`'s gate (moot per FC-066, stated for whoever revives it). |
| 6 | Runbook's persistent-case dichotomy was wrong: a revoked key / lapsed plan does **not** fire `earnings_gate_unusable` (the client builds fine). | **Fixed** in the runbook and in the alert policy's documentation content — the dichotomy is now event-shape *plus* `earnings_fetch_failed` error text (401/403 → key, 429 → quota, 5xx/timeout → outage). |
| 7 | Two undocumented deviations. | **Recorded** — see the two new entries in the plan's Execution §Deviations (L2 write-per-fetch vs the plan's per-batch; the unparseable-expiry labeling nit). |
| 8 | Rollout did not make the key check mandatory or same-window. | **Fixed** — mandatory pre-flight added to the runbook and to post-merge step 2 below. |

### Confirmation pass

Fixes landed in code for every required finding, so a **scoped confirmation
review is required before merge** (Fable, fresh context, one of the original
personas, contract = the three required fixes plus regression check on the
clock-seam change that rode along with fix 1).

---

## Post-merge steps

### 1. Deploy the alert policy (FC-065 P1 pattern — REST, not `gcloud alpha`)

`gcloud alpha` is not installed on the operator machine and invoking it silently
prompts for component installation (it looks like a hang). Use the Monitoring
REST API:

```bash
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @deploy/monitoring/earnings_gate_alert_policy.json \
  "https://monitoring.googleapis.com/v3/projects/gen-lang-client-0607444019/alertPolicies"
```

Then confirm the policy is ACTIVE and its channel is the verified email:

```bash
gcloud alpha monitoring policies list --format="value(name,displayName,enabled)" 2>/dev/null \
  || curl -sS -H "Authorization: Bearer $TOKEN" \
       "https://monitoring.googleapis.com/v3/projects/gen-lang-client-0607444019/alertPolicies" \
       | python -c "import json,sys; [print(p['displayName'], p.get('enabled'), p.get('notificationChannels')) for p in json.load(sys.stdin)['alertPolicies']]"
```

### 2. Deploy the code — outside market hours, key verified FIRST

**MANDATORY, and in this order.** This PR converts a missing `FINNHUB_API_KEY`
from *invisible* (no gate existed; a missing key changed nothing) into
*full-book fail-closed* (every symbol unknown, every open blocked, both legs).
So:

1. **Verify the key is on the live revision** — not in `.env`, not in Secret
   Manager, on the revision that will serve traffic — **before the first
   market-hours scan**:

   ```bash
   gcloud run services describe options-wheel-strategy --region=us-central1 \
     --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep -i finnhub
   ```

   If this returns nothing, do **not** let a market-hours scan run. Set the key
   first, or ship with `EARNINGS_ENABLED=false` and enable once the key is in.
2. **Deploy the alert policy in the same maintenance window as the code**, not
   after. An unalerted fail-closed gate is the failure this FC exists to end,
   pointed the other way.
3. Deploy after FC-068's deploy, outside market hours. The first scan pays up to
   ~14 Finnhub fetches against a cold L1 **and** a cold L2 blob; a transient
   hiccup then blocks symbols as unknown. Deploying outside market hours means
   the verification scan populates the blob before the next scheduled scan.

**The pre-merge live check could not run** — there is no Finnhub key available
in this environment (tests are hermetic by construction, `_no_finnhub` pins a
fake key). So the **post-deploy Finnhub-vs-table cross-source scan in step 3c is
mandatory, not optional**: it is the first and only opportunity to confirm the
live provider agrees with the committed yfinance table on the dates the gate
will act on.

### 3. Post-deploy verification, in order

```bash
# a. One scan. Confirm duration is within expectations and NO unknown events.
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type:"earnings"' \
  --limit=20 --freshness=1h \
  --format="value(timestamp,jsonPayload.event_type,jsonPayload.symbol)"

# b. Confirm the L2 blob exists.
gsutil ls -l gs://options-wheel-opportunities/earnings_cache.json

# c. Confirm decision rows are normal (no earnings reasons on a clear day).
#    Expect the usual mix; blocked{earnings_*} should be absent.
```

**3c. Cross-source check — MANDATORY, and only possible post-deploy.** The live
gate reads **Finnhub**; the replay and the audit script read the committed
**yfinance** table. Two independent providers is what makes the audit
meaningful, but it also means they can disagree, and a disagreement on a date
the gate acts on is a silent wrong answer in either direction. Compare what
Finnhub actually returned against the table:

```bash
# What the live service cached, per symbol:
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type="earnings_date_fetched"' \
  --limit=30 --freshness=1d \
  --format="value(jsonPayload.symbol,jsonPayload.earnings_date,jsonPayload.calendar_empty)"

# Against the committed table:
python3 -c "
import json; d=json.load(open('src/backtesting/data/earnings_dates.json'))['earnings']
for s in ('AAPL','AMZN','GOOGL','MSFT','NVDA'):
    print(s, [x for x in d.get(s,[]) if x >= '2026-08-01'][:2])
"
```

Any symbol where Finnhub says `calendar_empty=True` but the table has an
upcoming date is the accepted empty-200 fail-open landing live — investigate
before trusting the gate on that symbol.

### 4. Live-fire verification — **the split matters**

**Near-term (immediately post-deploy, before 08-19): a NEGATIVE check only.**
Every universe symbol is currently clear of its next report by a wide margin —
per the investigation, GOOGL `days_until = 89`, AAPL `87`, NVDA `23` with a
7-DTE chain that does not reach 08-26. So the only thing verifiable now is that
**the gate is inert on clear symbols**:

- clear symbols still produce opportunities and decision rows read normally;
- `expires_into_earnings` is present in the stage-8 stats and **equal to 0**;
- zero `*_skipped_earnings_*` events of any kind;
- the L2 blob is populated and the next scan is fast.

This does **not** prove the gate blocks anything. Do not read it as such.

**08-19 onward: the POSITIVE check, both legs, on NVDA.** NVDA reports
**2026-08-26**. From **08-19** every ~7-DTE NVDA call candidate spans the event,
and from **08-24** the put leg is inside N=2. Verify:

- span-rejected NVDA call candidates appear in `expires_into_earnings` — or, if
  the chain empties, a `(blocked, earnings_blackout)` decision row plus a
  `call_scan_skipped_earnings_blackout` event;
- from 08-24, a `put_scan_skipped_earnings_blackout` event for NVDA;
- NVDA absent from the opportunity blob on those days;
- **and the gate does not over-block**: a known-earnings symbol still sells a
  call expiring *before* its event. If NVDA's chain offers a pre-08-26 expiry in
  that window, that is the allowed case, live.

If any other universe symbol enters its own window before 08-19, it substitutes.

### 5. Alert fire drill (day one)

Emit one synthetic `earnings_gate_unusable`-matching log line (the FC-030 drill
pattern, documented in the runbook) and confirm the email arrives. Untested
alerting is worse than none — and this alert is the only bound on the
persistent-failure case.

### 6. Monitor one trading week

Re-run `tools/diagnostics/fc013_earnings_exposure_audit.py` and confirm zero
option sell-to-open fills violated either predicate. Confirm
`earnings_fetch_failed` events stay at baseline and no unknown-state alerts
fired. (The script needs `db-dtypes` installed for BigQuery→dataframe reads.)

---

## Rollback

- **Emergency (runtime-atomic, ~1 min, no Cloud Build):**
  `gcloud run services update options-wheel-strategy --region=us-central1
  --update-env-vars EARNINGS_ENABLED=false`. `--update-env-vars`, **never**
  `--set-env-vars` — the latter wipes the whole env set, which is itself one of
  this gate's persistent-failure scenarios.
- **Durable:** flip `earnings.enabled: false` in yaml through the normal
  pipeline. Honest latency: commit → Cloud Build → deploy.
- **Full code rollback:** single revert of the squash commit. No schema, no data
  migrations — the two enum reasons are additive strings, old rows are
  unaffected, and the L2 blob is inert to old code.

`test_gate_absent_when_earnings_disabled` proves config-off restores pre-gate
behaviour byte-identically.

---

## Known residual risks

- **Persistent fail-closed blocks all opens indefinitely.** Bounded only by the
  DD-6 alert and the DD-7 lever. Both ship here; the alert must actually be
  deployed and fire-drilled (post-merge steps 1 and 5) or this risk is unbounded.
- **Finnhub empty-200 is cached as known-clear.** Correct for ETFs and quiet
  windows; a coverage regression on Finnhub's side would read as *permanently
  clear* for that symbol — an accepted fail-open. The fetch log carries
  `calendar_empty=True`, and the audit script (independent yfinance table) is the
  retrospective detector.
- **A blocked symbol every scan through an earnings week reads as "scanner
  broke"** to a future reader. Mitigated by the decision rows, the events, the
  `expires_into_earnings` stat, and `docs/gates.md`.
- **The roller's earnings gate is untouched and still fails open** — operator
  decision. Unification is FC-066's pre-revival checklist, along with the roller
  seam's injected-calendar-bypasses-`enabled` quirk (both recorded in
  `docs/gates.md`).
