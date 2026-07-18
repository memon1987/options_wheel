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

**Threshold:** 7 trading days, overridable per-revision without touching the
policy:

```bash
gcloud run services update options-wheel-dashboard --region=us-central1 \
  --update-env-vars PAUSE_ALERT_THRESHOLD_DAYS=7
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

## Alert inventory

| Alert | Signal | Threshold | Rate limit |
|---|---|---|---|
| Cloud Build failure | `resource.type="build" AND severity>=ERROR` | any failure | 5 min |
| Extended drawdown pause | `DRAWDOWN_PAUSE_ALERT` in dashboard logs | ≥7 trading days | 24 h |

Candidates to add on this channel (each a small follow-up): reconciliation
banner `warn`, `critical`-severity bot-health anomalies, ingest staleness.
