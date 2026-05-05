# Cloud Scheduler job for FC-018 stock-history ingest

`POST /ingest-stock-history` pulls daily OHLC bars from Alpaca for every
underlying that has been traded, into `options_wheel.stock_history_from_alpaca`.
Powers the FC-018 vs-buy-and-hold view. Idempotent by `(date, symbol)`.

Runs once a day at 5pm ET (after market close + portfolio history finalization).

## Prereqs

Same as FC-012 scheduler jobs. See `deploy/scheduler/fc012_activities_ingest.md`.

```bash
PROJECT=gen-lang-client-0607444019
REGION=us-central1
SERVICE_URL=https://options-wheel-strategy-omnlacz6ia-uc.a.run.app
INVOKER_SA=799970961417-compute@developer.gserviceaccount.com
```

## Create the job

```bash
gcloud scheduler jobs create http stock-history-ingest-daily \
  --project=${PROJECT} \
  --location=${REGION} \
  --schedule="0 17 * * 1-5" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/ingest-stock-history" \
  --http-method=POST \
  --oidc-service-account-email="${INVOKER_SA}" \
  --oidc-token-audience="${SERVICE_URL}" \
  --attempt-deadline=600s \
  --description="FC-018: daily Alpaca stock bars to BQ for vs-buy-and-hold view"
```

Note `attempt-deadline=600s` (10 min) because the first invocation backfills
365 days of bars across the full traded universe; subsequent daily runs are
short.

## First run / backfill

Trigger manually after creating the job:

```bash
gcloud scheduler jobs run stock-history-ingest-daily \
  --project=${PROJECT} --location=${REGION}
```

Expect ~14 symbols × 1 chunked API call each on the first run; check the
response in Cloud Run logs:

```bash
gcloud logging read \
  'resource.type=cloud_run_revision AND jsonPayload.event_type=stock_history_ingest_completed' \
  --project=${PROJECT} --limit=5 --format=json
```

A successful first run looks like:

```json
{
  "status": "ok",
  "symbols_processed": 14,
  "rows_inserted": 3500
}
```

Subsequent daily runs:

```json
{
  "status": "ok",
  "symbols_processed": 14,
  "rows_inserted": 14   // one row per symbol per trading day
}
```

## Rollback

```bash
gcloud scheduler jobs delete stock-history-ingest-daily \
  --project=${PROJECT} --location=${REGION} --quiet
bq rm -f -t ${PROJECT}:options_wheel.stock_history_from_alpaca   # if you also want to drop data
```
