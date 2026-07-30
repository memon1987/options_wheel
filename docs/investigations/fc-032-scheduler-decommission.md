# Scheduler decommission record — Track D, 2026-07-30

Full configuration of the three Cloud Scheduler jobs deleted in Track D, recorded
**before** deletion so the action is reversible in practice. All three were PAUSED and
targeted endpoints deleted in FC-032 Phase 0 — they were live 404s if resumed.

The fourth paused job, `monthly-performance-review`, was NOT deleted: it is re-pointed
at the new `backtest-screen` Cloud Run Job.

## `daily-quick-backtest`
```yaml
attemptDeadline: 180s
description: Daily quick backtest analysis for strategy optimization
httpTarget:
  body: ewogICAgICAgICJhbmFseXNpc190eXBlIjogInF1aWNrIiwKICAgICAgICAic3ltYm9sIjogIlNQWSIsCiAgICAgICAgImxvb2tiYWNrX2RheXMiOiA3LAogICAgICAgICJhdXRvX3N5bWJvbHMiOiB0cnVlLAogICAgICAgICJzdHJhdGVneV9wYXJhbXMiOiB7CiAgICAgICAgICAgICJkZWx0YV9yYW5nZSI6IFswLjEwLCAwLjIwXSwKICAgICAgICAgICAgImR0ZV90YXJnZXQiOiA3CiAgICAgICAgfQogICAgfQ==
  headers:
    Content-Type: application/json
    User-Agent: Google-Cloud-Scheduler
  httpMethod: POST
  oidcToken:
    audience: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/backtest
    serviceAccountEmail: 799970961417-compute@developer.gserviceaccount.com
  uri: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/backtest
name: projects/gen-lang-client-0607444019/locations/us-central1/jobs/daily-quick-backtest
retryConfig:
  maxBackoffDuration: 3600s
  maxDoublings: 5
  maxRetryDuration: 0s
  minBackoffDuration: 5s
schedule: 0 13 * * 1-5
  code: -1
timeZone: Etc/UTC
```

## `weekly-comprehensive-backtest`
```yaml
attemptDeadline: 180s
description: Weekly comprehensive backtest across multiple symbols
httpTarget:
  body: ewogICAgICAgICJhbmFseXNpc190eXBlIjogImNvbXByZWhlbnNpdmUiLAogICAgICAgICJzeW1ib2wiOiAiQUFQTCIsCiAgICAgICAgImxvb2tiYWNrX2RheXMiOiAzMCwKICAgICAgICAiYXV0b19zeW1ib2xzIjogdHJ1ZSwKICAgICAgICAic3RyYXRlZ3lfcGFyYW1zIjogewogICAgICAgICAgICAiZGVsdGFfcmFuZ2UiOiBbMC4xMCwgMC4yMF0sCiAgICAgICAgICAgICJkdGVfdGFyZ2V0IjogNwogICAgICAgIH0KICAgIH0=
  headers:
    Content-Type: application/json
    User-Agent: Google-Cloud-Scheduler
  httpMethod: POST
  oidcToken:
    audience: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/backtest
    serviceAccountEmail: 799970961417-compute@developer.gserviceaccount.com
  uri: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/backtest
name: projects/gen-lang-client-0607444019/locations/us-central1/jobs/weekly-comprehensive-backtest
retryConfig:
  maxBackoffDuration: 3600s
  maxDoublings: 5
  maxRetryDuration: 0s
  minBackoffDuration: 5s
schedule: 0 11 * * 1
  code: -1
timeZone: Etc/UTC
```

## `daily-cache-maintenance`
```yaml
attemptDeadline: 180s
description: Daily cache cleanup and optimization
httpTarget:
  body: ewogICAgICAgICJjbGVhbnVwX29sZF9kYXRhIjogdHJ1ZSwKICAgICAgICAib3B0aW1pemVfc3RvcmFnZSI6IHRydWUsCiAgICAgICAgIm1heF9jYWNoZV9hZ2VfZGF5cyI6IDMwCiAgICB9
  headers:
    Content-Type: application/json
    User-Agent: Google-Cloud-Scheduler
  httpMethod: POST
  oidcToken:
    audience: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/cache/maintenance
    serviceAccountEmail: 799970961417-compute@developer.gserviceaccount.com
  uri: https://options-wheel-strategy-omnlacz6ia-uc.a.run.app/cache/cleanup
name: projects/gen-lang-client-0607444019/locations/us-central1/jobs/daily-cache-maintenance
retryConfig:
  maxBackoffDuration: 3600s
  maxDoublings: 5
  maxRetryDuration: 0s
  minBackoffDuration: 5s
schedule: 0 7 * * *
  code: -1
timeZone: Etc/UTC
```

