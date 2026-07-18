# Execution Plans

Published plans for changes to this codebase. **No medium or large change should land without a plan file here** — see `docs/CLAUDE.md` ("Plan-First Development") for the rule.

## How plans flow in

1. An idea starts as an entry in `docs/FUTURE_CONSIDERATIONS.md` (FC-NNN).
2. When ready to design, draft a plan file here using the template below.
3. Iterate asynchronously — update the plan over time.
4. When the plan is approved, update the FC entry's status to "Plan published" and link the plan file.
5. Execute against the plan. Reference the plan file path in commit messages and PR descriptions.
6. After merge, move the FC entry to "Completed" with a link to the plan and the commit/PR.

## Naming

- File name: `docs/plans/fc-NNN.md` matching the FC entry number (e.g., `fc-006.md` for FC-006)
- This ensures direct traceability between FC entries and their published plans.

## Plan template

Copy `_template.md` in this directory to start a new plan.

## Index

_List active plans here as they are added._

- [fc-006.md](fc-006.md) — FC-006: Covered call rolling engine, status: done
- [fc-007.md](fc-007.md) — FC-007: Earnings calendar service, status: done
- [fc-010.md](fc-010.md) — FC-010: Disable call stop-losses, status: done
- [fc-012.md](fc-012.md) — FC-012: Shift dashboard logging to Alpaca queries, status: done
- [fc-013.md](fc-013.md) — FC-013: Gate health audit & earnings blackout symmetry, status: draft
- [fc-018.md](fc-018.md) — FC-018: Wheel-centric dashboard rebuild (frontend only), status: draft
- [fc-019.md](fc-019.md) — FC-019: True P&L reconciliation (JNLC + OPTRD ingest), status: done
- [fc-020.md](fc-020.md) — FC-020: FIFO cycle pairing for overlapping share lots, status: draft
- [fc-030.md](fc-030.md) — FC-030: Drawdown-pause alerting (operator notification for extended pauses), status: done
- [fc-031.md](fc-031.md) — FC-031: Dashboard metrics overhaul (vetted portfolio metrics + bot execution health), status: done
- [fc-032.md](fc-032.md) — FC-032: Backtesting engine overhaul (symbol wheel-fitness evaluation), status: draft
