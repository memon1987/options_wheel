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

- File name: `docs/plans/<kebab-case-slug>.md` (e.g., `symbol-universe-refactor.md`)
- Slug should match the FC entry title when possible.

## Plan template

Copy `_template.md` in this directory to start a new plan.

## Index

_List active plans here as they are added._

<!--
Example:
- [symbol-universe-refactor.md](symbol-universe-refactor.md) — FC-001, status: drafted
- [dte-target-optimization.md](dte-target-optimization.md) — FC-003, status: executing
-->
