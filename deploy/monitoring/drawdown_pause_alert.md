# Operator alerting — setup & runbook

**Plans:** `docs/plans/fc-030.md` (drawdown-pause alerting)
**Created:** 2026-07-18

This is the project's **first and only notification path**. Both alerts below
share one email notification channel; future alerts (reconciliation `warn`,
critical bot-health anomalies) should reuse it rather than create new channels.

> `gcloud alpha` is **not installed** on the operator machine, and invoking it
> silently prompts for component installation (it looks like a hang). Use the
> Monitoring REST API with `gcloud auth print-access-token`, as below.

---

## Shared notification channel

```bash
gcloud beta monitoring channels create \
  --display-name="Options Wheel — operator email" \
  --type=email \
  --channel-labels=email_address=zeshan@tkzmgroup.com \
  --description="Primary operator notification channel for the options-wheel bot."
```

Current channel:
`projects/gen-lang-client-0607444019/notificationChannels/10474915111056992031`

List channels:

```bash
gcloud beta monitoring channels list --format="value(name,type,labels.email_address)"
```

---

## Alert 1 — Cloud Build failure

**Why it exists:** the FC-031 dashboard overhaul sat undeployed for **11 days**
(2026-07-07 → 2026-07-18) because a red build went unnoticed. Deploys do not
happen on a red build, so merged code silently is not live. Historical failure
rate at time of writing: 2 of the last 19 builds (~10%).

**Policy:** `Cloud Build failure — options-wheel`
(`projects/gen-lang-client-0607444019/alertPolicies/12432709964222363712`)

**Match filter** (verified against the two real 2026-07-07 failures — Cloud
Build failures land as `cloudaudit.googleapis.com/activity` entries; there is
no `jsonPayload.status` field to match on):

```
resource.type="build" AND severity>=ERROR
```

**Triage when it fires:**

```bash
gcloud builds list --limit=5
gcloud builds log <BUILD_ID>
# Confirm what is actually live:
gcloud run revisions list --service=options-wheel-dashboard --region=us-central1 --limit=1
gcloud run revisions list --service=options-wheel-strategy  --region=us-central1 --limit=1
```

---

## Alert 2 — Extended drawdown pause (FC-030)

**Why it exists:** FC-029 R3 stops covered-call writes when shares sit >5%
below their assignment strike. Correct short-term, expensive if it persists
silently — AMZN's 62-day implicit pause (Feb 6 → Apr 10, 2026) cost an
estimated $1,500–3,000 in foregone premium and was only found post-hoc.

**Threshold:** 7 trading days, declared in `cloudbuild.yaml`'s dashboard
deploy step.

> **Change it in `cloudbuild.yaml`, not with `--update-env-vars`.** The deploy
> uses `--set-env-vars`, which **replaces the entire env set** — an
> out-of-band `--update-env-vars` value is silently wiped on the next deploy.
> (Observed 2026-07-18: the fire-drill override vanished on the following
> build. Harmless only because the code default matched.)

For a temporary override (e.g. a fire drill), `--update-env-vars` is fine as
long as you know it lasts only until the next deploy:

```bash
gcloud run services update options-wheel-dashboard --region=us-central1 \
  --update-env-vars PAUSE_ALERT_THRESHOLD_DAYS=1
```

**Match filter** — the marker string is `ALERT_MARKER` in
`dashboard/backend/services/pause_alert.py`. **Renaming it breaks the alert**;
a unit test pins the literal
(`tests/test_dashboard_pause_alert.py::test_carries_marker_and_is_single_line`).

> Selection/formatting live in `services/pause_alert.py`, not the router, so
> they are testable in the **bot CI image**, which does not install FastAPI —
> only the dashboard image does. Endpoint tests are class-scoped-skipped there.
> Do not use a module-level `pytest.importorskip`: it aborts collection of the
> whole file and silently skips the pure tests too (CI goes green testing
> nothing — this was caught during FC-030 implementation).

```
resource.type="cloud_run_revision"
AND resource.labels.service_name="options-wheel-dashboard"
AND (textPayload:"DRAWDOWN_PAUSE_ALERT" OR jsonPayload.message:"DRAWDOWN_PAUSE_ALERT")
```

**Do not add a `severity>=WARNING` clause.** The first version of this policy
had one and would never have fired: Cloud Run captures the app's stderr as
plain text with an **empty** severity field, so `logging.warning()` does *not*
produce a WARNING-severity log entry. Verified in the 2026-07-18 fire drill —
the severity-constrained filter matched **0** entries while the alert line was
sitting in Cloud Logging. This is exactly why the fire drill is mandatory.

Both payload shapes are matched so structured logging can be adopted later
without breaking the alert. The filter also matches the `_CHECK_FAILED` marker
— a check that cannot evaluate is itself worth knowing about (a silent
evaluator is the FC-006 failure mode).

### Create the policy

```bash
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @deploy/monitoring/pause_alert_policy.json \
  "https://monitoring.googleapis.com/v3/projects/gen-lang-client-0607444019/alertPolicies"
```

### Create the scheduler job

Runs weekdays 17:45 ET — after the 17:00 ET stock-history ingest refreshes the
closes that pause state is computed from.

```bash
gcloud scheduler jobs create http drawdown-pause-alert-daily \
  --location=us-central1 \
  --schedule="45 17 * * 1-5" \
  --time-zone="America/New_York" \
  --uri="https://options-wheel-dashboard-omnlacz6ia-uc.a.run.app/api/v2/bot-health/pause-alert-check" \
  --http-method=POST \
  --oidc-service-account-email=799970961417-compute@developer.gserviceaccount.com \
  --oidc-token-audience="https://options-wheel-dashboard-omnlacz6ia-uc.a.run.app"
```

The compute SA needs invoker on the **dashboard** service (existing jobs all
target the bot service):

```bash
gcloud run services add-iam-policy-binding options-wheel-dashboard \
  --region=us-central1 \
  --member=serviceAccount:799970961417-compute@developer.gserviceaccount.com \
  --role=roles/run.invoker
```

---

## Fire drill (do this on day one — untested alerting is worse than none)

Do **not** wait weeks for a natural ≥7-day pause to discover the email never
arrives.

```bash
# 1. Temporarily lower the threshold so currently-paused symbols qualify
gcloud run services update options-wheel-dashboard --region=us-central1 \
  --update-env-vars PAUSE_ALERT_THRESHOLD_DAYS=1

# 2. Trigger the check
TOKEN=$(gcloud auth print-identity-token)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  "https://options-wheel-dashboard-omnlacz6ia-uc.a.run.app/api/v2/bot-health/pause-alert-check"

# 3. Confirm the marker was logged
gcloud logging read \
  'resource.type="cloud_run_revision" AND textPayload:"DRAWDOWN_PAUSE_ALERT"' \
  --limit=3 --freshness=10m --format="value(timestamp,textPayload)"

# 4. Confirm the email arrived, then restore
gcloud run services update options-wheel-dashboard --region=us-central1 \
  --update-env-vars PAUSE_ALERT_THRESHOLD_DAYS=7
```

**If no email arrives:** email notification channels may require one-time
verification — check for a "Verify this notification channel" message from
Google Cloud Monitoring (including spam) and click through. Re-run the drill.

---

## Alert 3 — Cost-basis floor blocked a covered call (FC-065)

**Why it exists:** since FC-065 Phase 1 the covered-call floor is a *single*
broker field — Alpaca's `avg_entry_price` for the equity position. Two events
mean the bot is holding shares and deliberately writing no calls on them:

| Event | Meaning |
|---|---|
| `call_scan_skipped_cost_basis_unresolved` | no usable `avg_entry_price`. Every wheel position is an assigned position, so a recurrence of FC-029's reported `cost_basis = 0` would starve the whole book |
| `call_scan_skipped_cost_basis_divergent` | the broker's number disagrees with the basis reconstructed from BigQuery assignment history by more than `max($0.10, 0.1%)` — presence with a *wrong* value, which fail-closed-on-zero cannot catch |

Fail-closed is the correct behaviour in both cases. The alert exists because
the *consequence* — idle capital, indefinitely, with no other signal — is
exactly the FC-030 failure mode.

**Policy:** `deploy/monitoring/cost_basis_alert_policy.json`, created the same
way as Alert 2 (Monitoring REST API, `gcloud alpha` is not installed):

```bash
TOKEN=$(gcloud auth print-access-token)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @deploy/monitoring/cost_basis_alert_policy.json \
  "https://monitoring.googleapis.com/v3/projects/gen-lang-client-0607444019/alertPolicies"
```

**Match filter** — note this one targets the **bot** service, not the
dashboard, and matches on `jsonPayload.event_type` because the bot renders
structlog as JSON to stderr (`src/utils/logger.py`), which Cloud Run parses
into `jsonPayload`. `textPayload` is matched too, for the same
future-proofing reason as Alert 2. **No `severity>=` clause** — see Alert 2.

```
resource.type="cloud_run_revision"
AND resource.labels.service_name="options-wheel-strategy"
AND (jsonPayload.event_type="call_scan_skipped_cost_basis_unresolved"
  OR jsonPayload.event_type="call_scan_skipped_cost_basis_divergent"
  OR textPayload:"call_scan_skipped_cost_basis_unresolved"
  OR textPayload:"call_scan_skipped_cost_basis_divergent")
```

**Fire drill** (do it on day one — untested alerting is worse than none). The
guard fires naturally only on a real defect, so provoke it from the logs side
and confirm the policy matches:

```bash
# 1. Confirm the events are being emitted at all (they should be absent in
#    a healthy book — absence here is the expected steady state).
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type:"call_scan_skipped_cost_basis"' \
  --limit=5 --freshness=2d --format="value(timestamp,jsonPayload.event_type,jsonPayload.symbol)"

# 2. Confirm the healthy-path counterpart IS present, which proves the scan is
#    reaching the cross-check. Every held symbol with >=100 shares that was
#    NOT skipped emits one of these per scan.
gcloud logging read \
  'resource.labels.service_name="options-wheel-strategy" AND jsonPayload.event_type="cost_basis_cross_check"' \
  --limit=10 --freshness=1d \
  --format="value(timestamp,jsonPayload.symbol,jsonPayload.status,jsonPayload.basis_delta)"
```

If step 2 returns nothing, the alert is watching a path that never runs —
treat that as a broken alert, not a quiet book (the FC-006 failure mode).

**Read the `status`, not just the presence of the row.** Every held symbol
should show `status=ok` with a non-null `basis_delta`. A row saying
`status=unavailable` means the cross-check did not actually compare anything —
see "Blind spot" below. A book of `unavailable` rows looks identical to a
healthy book if you only check that the event exists.

**Triage when it fires:** compare the logged `broker_basis` / `expected_basis`
against the Alpaca UI position and the symbol's OPASN rows in
`options_wheel.trades_from_activities`. Do **not** lower the floor to unblock
writing — the floor blocking a write is the control working.

### Divergence triage: "the broker is right, the history is wrong"

A divergence does **not** imply the broker's number is wrong. Three benign
causes are known, and all three present as a standing divergence on one symbol:

- **(a) Multi-lot partial call-away — the most likely one.** Alpaca's
  `avg_entry_price` is an *entry* average and is **not recomputed when shares
  are partially disposed of**, while the cross-check's reconstruction prices
  the newest remaining lots (FIFO-shaped). After a partial call-away out of a
  multi-lot position the two therefore measure different things, and the gap is
  roughly the **spread between the lot bases** — persisting until the position
  fully cycles out. Expected, safe in direction (the broker's average is the
  looser number; blocking is conservative), and a false alarm. Pinning the
  exact semantics is **FC-070**.
- **(b) A stock split Alpaca adjusted correctly** while the OPASN strikes in
  `trades_from_activities` remain unadjusted. The reconstruction is then
  pre-split and the broker post-split, so the ratio between `broker_basis` and
  `expected_basis` is the split ratio — a clean tell.
- **(c) Multi-fill sell-to-open.** The derivation uses the **last** fill's
  price as the put premium (plan-specified); a lot opened across fills at
  materially different prices can exceed tolerance. Zero instances in the 640
  historical fills at the time of writing, so treat this as the last hypothesis,
  not the first.

**If the broker is confirmed right** (verified against the position in the
Alpaca UI), the sanctioned unblock is to fix the *history*, never the floor:

1. Write synthetic corrective rows into `trades_from_activities` under the
   repo's prefix-tagging discipline — a stable `synthetic-fc-NNN-` identifier,
   an audit query, and a rollback recipe, all documented in a plan file (see
   `~/CLAUDE.md` §"Synthetic / corrective data writes", and FC-021 / FC-025 for
   precedents); **or**
2. Accept the divergence in writing as an FC entry, if the correction is not
   worth making.

**Never** lower the tolerance, bypass the cross-check, or hand-edit the floor in
code to clear a divergence. That converts a working control into a silent one,
which is the failure mode this whole layer exists to end.

**If ALL held symbols diverge at once**, do not triage four symbols
individually — suspect a **systemic netting-semantics change**: a broker-side
change to how `avg_entry_price` is reported, or a live-account cutover with a
different convention. One cause, one fix; per-symbol data corruption does not
arrive simultaneously across the book.

### Blind spot: a broken cross-check is silent

A cross-check that cannot run — BigQuery schema drift, revoked permissions, a
SQL error, an outage — degrades **every** scan to `status=unavailable`, which
keeps the broker's floor and lets trading continue. That is deliberate
(availability of the check must not gate the book), but it means the *control*
can be dead while the *alert* stays quiet: the failure is logged as
`cost_basis_cross_check_unavailable` / `cost_basis_cross_check_lookup_failed`
and **is not alerted on**.

Until an alert on *persistent* `unavailable` exists (a follow-up, deliberately
not in FC-065 Phase 1), check it by hand periodically — the fire-drill query in
step 2 above is the check: every held symbol should show `status=ok`, not
`unavailable`.

---

## Alert inventory

| Alert | Signal | Threshold | Rate limit |
|---|---|---|---|
| Cloud Build failure | `resource.type="build" AND severity>=ERROR` | any failure | 5 min |
| Extended drawdown pause | `DRAWDOWN_PAUSE_ALERT` in dashboard logs | ≥7 trading days | 24 h |
| Cost-basis floor blocked a call | `call_scan_skipped_cost_basis_{unresolved,divergent}` in bot logs | any occurrence | 24 h |

Candidates to add on this channel (each a small follow-up): reconciliation
banner `warn`, `critical`-severity bot-health anomalies, ingest staleness.
