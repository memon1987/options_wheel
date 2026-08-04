# Documentation index

An automated options wheel trading strategy deployed to Google Cloud Run with
continuous integration.

## Start here
- [`CLAUDE.md`](CLAUDE.md) — the architecture that actually runs, the control
  layer, and the conventions this repo enforces. Read this first.
- [`gates.md`](gates.md) — every gate on the live sell path: where it lives,
  what config drives it, what it emits, whether it fails open or closed.
- [`BACKTEST_ENGINE.md`](BACKTEST_ENGINE.md) — the single home of every measured
  backtest figure, and what not to trust.

## Operating facts
- Cloud Scheduler drives everything: `/scan` at :00 (10:00–15:00 ET), `/run` at
  :15, `/monitor` at :55, `/roll` daily at 15:30 ET, `/regression` at :45.
- Paper trading is the default, and every trading endpoint refuses to act unless
  the live Alpaca account matches `alpaca.expected_account_number`.
- Gap-risk management was removed in FC-069 — gap risk is absent by decision.

## Also here
- [`deployment/DEPLOYMENT_SUMMARY.md`](deployment/DEPLOYMENT_SUMMARY.md) — setup details
- [`deployment/GITHUB_DEPLOYMENT_SETUP.md`](deployment/GITHUB_DEPLOYMENT_SETUP.md) — CI/CD pipeline
- [`operations/MAINTENANCE.md`](operations/MAINTENANCE.md) — ongoing operations
- [`plans/`](plans/) — published execution plans (`fc-NNN.md`)
- [`FUTURE_CONSIDERATIONS.md`](FUTURE_CONSIDERATIONS.md) — pre-plan ideas
- [`releases/`](releases/) — release notes
- [`investigations/`](investigations/) — committed investigation write-ups
