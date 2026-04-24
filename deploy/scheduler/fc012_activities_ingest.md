# Cloud Scheduler jobs for FC-012 activities ingest

Manual `gcloud` commands to create the two scheduler jobs that drive
`POST /ingest-activities`. There is no Terraform/IaC in this repo today,
so these commands are the source of truth — keep them in sync with any
changes made via the GCP console.

## Prereqs

- Cloud Run service `options-wheel-strategy` already deployed.
- Service URL and `STRATEGY_API_KEY` secret already provisioned.
- A service account (e.g., `scheduler-invoker@PROJECT.iam.gserviceaccount.com`)
  with `roles/run.invoker` on the Cloud Run service.

Set shell variables before running:

```bash
PROJECT=gen-lang-client-0607444019
REGION=us-central1
SERVICE_URL=https://options-wheel-strategy-omnlacz6ia-uc.a.run.app
INVOKER_SA=scheduler-invoker@${PROJECT}.iam.gserviceaccount.com
API_KEY=$(gcloud secrets versions access latest --secret=strategy-api-key --project=${PROJECT})
```

## Job 1 — market hours (15-minute cadence)

Fires every 15 minutes between 9:00am and 4:45pm Eastern Time, Mon–Fri.
The schedule is expressed in the scheduler's timezone.

```bash
gcloud scheduler jobs create http activities-ingest-market-hours \
  --project=${PROJECT} \
  --location=${REGION} \
  --schedule="30,45 9 * * 1-5; 0,15,30,45 10-15 * * 1-5; 0 16 * * 1-5" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/ingest-activities" \
  --http-method=POST \
  --headers="X-API-Key=${API_KEY},Content-Type=application/json" \
  --oidc-service-account-email="${INVOKER_SA}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --attempt-deadline=300s \
  --description="FC-012: pull Alpaca activities to BQ (market hours)"
```

Cloud Scheduler does not accept multiple schedule expressions in a
single job. Use three jobs (9:30–9:45, 10:00–15:45, 16:00) or, more
practically, one job at `*/15 9-16 * * 1-5` and let the off-hours job
cover the gap. The simpler setup:

```bash
gcloud scheduler jobs create http activities-ingest-market-hours \
  --project=${PROJECT} \
  --location=${REGION} \
  --schedule="*/15 9-16 * * 1-5" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/ingest-activities" \
  --http-method=POST \
  --headers="X-API-Key=${API_KEY},Content-Type=application/json" \
  --oidc-service-account-email="${INVOKER_SA}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --attempt-deadline=300s \
  --description="FC-012: pull Alpaca activities to BQ (market hours)"
```

This fires at 9:00, 9:15, ..., 16:45 on weekdays (some pre-market
invocations will be no-ops since `/v2/account/activities` returns empty
when nothing new has happened — that is the intended idempotent
behaviour).

## Job 2 — off hours (hourly cadence)

Hourly outside market hours. Covers overnights, weekends, and the OPASN
/OPEXP events that Alpaca posts around 8am ET the next morning.

```bash
gcloud scheduler jobs create http activities-ingest-off-hours \
  --project=${PROJECT} \
  --location=${REGION} \
  --schedule="0 0-8,17-23 * * 1-5; 0 * * * 0,6" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/ingest-activities" \
  --http-method=POST \
  --headers="X-API-Key=${API_KEY},Content-Type=application/json" \
  --oidc-service-account-email="${INVOKER_SA}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --attempt-deadline=300s \
  --description="FC-012: pull Alpaca activities to BQ (off hours)"
```

If the `;`-joined schedule is rejected, split into two jobs
(`off-hours-weekday` with `0 0-8,17-23 * * 1-5` and `off-hours-weekend`
with `0 * * * 0,6`).

## Verify

```bash
# List jobs
gcloud scheduler jobs list --project=${PROJECT} --location=${REGION}

# Trigger one manually to prove wiring
gcloud scheduler jobs run activities-ingest-market-hours \
  --project=${PROJECT} --location=${REGION}

# Tail the Cloud Run logs for the run
gcloud logging read \
  'resource.type=cloud_run_revision AND jsonPayload.event_type=activities_ingest_completed' \
  --project=${PROJECT} --limit=5 --format=json
```

Successful run signature:

```json
{
  "status": "ok",
  "fetched": 3,
  "inserted": 3,
  "skipped": 0
}
```

Repeated runs with no new activity return:

```json
{"status": "ok", "fetched": 0, "inserted": 0, "skipped": 0}
```

## Rollback

```bash
gcloud scheduler jobs delete activities-ingest-market-hours \
  --project=${PROJECT} --location=${REGION} --quiet
gcloud scheduler jobs delete activities-ingest-off-hours \
  --project=${PROJECT} --location=${REGION} --quiet
```

Deleting the jobs halts ingest immediately. The raw
`options_wheel.trades_from_activities` table persists; to discard it:

```bash
bq rm -t ${PROJECT}:options_wheel.trades_from_activities
bq rm -f ${PROJECT}:options_wheel.trades_with_outcomes   # view
```
