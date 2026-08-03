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
`test_the_incident_geometry_is_blocked`.

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

- **Full suite: 1115 passed** (main baseline 1025, +90). `__pycache__` cleared
  before the final run — stale `.pyc` from mutation testing has made correct code
  misbehave on this repo before.
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

### 2. Deploy the code — outside market hours

Deploy after FC-068's deploy. The first scan after deploy pays up to ~14 Finnhub
fetches against a cold L1 **and** a cold L2 blob; a transient hiccup then blocks
symbols as unknown. Deploying outside market hours means the post-deploy
verification scan populates the blob before the next scheduled scan.

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
