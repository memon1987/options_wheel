# Decision records — the covered-call decision table

**Plan:** `docs/plans/fc-065.md` §Phase 4
**Table:** `options_wheel.decision_events` (BigQuery, day-partitioned on `timestamp`)
**Subsumes:** FC-044 Phase 1 (`decision_events` telemetry backbone). FC-044's
Phase 2 grid UI is still its own FC and reads this table.

---

## What it answers

For any held symbol on any cycle: **did we sell a covered call, and if not, why not.**

Before this table, the honest answer was silence. An underwater position
quietly yielded nothing — no event said so — and the structured logs that
would have told you live only in Cloud Logging's 30-day window, because the
BigQuery log sink died 2025-11-22 (FC-046). A question about last month's
decisions was already unanswerable.

## Bootstrap

**None required.** `AnalyticsWriter._ensure_all_tables()` creates the table
from its code-defined schema on the next cold start after deploy. There is no
`bq mk` step and no DDL to apply. A contract test
(`tests/test_analytics_writer.py::test_managed_table_set_is_explicit`) pins the
managed-table set so this cannot happen by accident again.

---

## Schema

| Column | Type | Notes |
|---|---|---|
| `timestamp` | TIMESTAMP | Write time; the partition field |
| `run_id` | STRING | Minted once per `/scan`, threaded to `/run` |
| `run_ts` | TIMESTAMP | Cycle start — stable across both stages |
| `stage` | STRING | `scan` \| `run` |
| `endpoint` | STRING | `/scan` \| `/run` |
| `symbol` | STRING | Underlying |
| `outcome` | STRING | **Closed enum**, below |
| `reason` | STRING | Sub-reason, scoped to the outcome |
| `shares` | INTEGER | Shares held |
| `cost_basis_per_share` | FLOAT | The floor the bot enforced (Alpaca `avg_entry_price`) |
| `current_price` | FLOAT | Broker mark (`market_value / qty`) |
| `underwater_pct` | FLOAT | `(price − floor) / floor`. **NEGATIVE is underwater** |
| `uncovered_days` | INTEGER | Trading days since the last covered call. **NULL = unknown, not zero** |
| `candidates` | INTEGER | Qualifying call contracts found |
| `option_symbol`, `strike_price`, `premium`, `contracts`, `order_id` | | Populated on `sold` |
| `reason_counts` | REPEATED RECORD `(reason, count)` | Chain-rejection breakdown |
| `dedup_key` | STRING | `run_id\|symbol\|stage`; also the streaming `insertId` |

`reason_counts` is a **REPEATED RECORD, never a JSON string.** String-ifying
arrays or structs into a BigQuery column is the 2026-04-07 lesson this project
already paid for once (it produced a dataset whose wildcard queries could not
be run at all). FC-044's sketch proposed a `metrics JSON` column; it was
deliberately not adopted.

### The outcome enum

| `outcome` | valid `reason` values |
|---|---|
| `sold` | *(empty)* |
| `no_candidates` | `no_qualifying_strikes`, `quote_unavailable` |
| `blocked` | `floor_unresolved`, `floor_divergent` |
| `not_eligible` | `insufficient_shares` |
| `dropped` | FC-038's selection enum (`insufficient_available_shares`, `insufficient_buying_power`, `duplicate_underlying`, `sizing_failed`, `positions_unavailable`) plus `execution_failed`, `already_positioned`, `previously_failed`, `not_selected` |

The enum is **closed**: an out-of-vocabulary outcome or an outcome/reason
mismatch raises `UnknownDecisionOutcome`. The recorder catches it at its own
boundary, refuses the row and emits `decision_record_invalid`. Trading must not
stop because telemetry is malformed, and telemetry must not lie because trading
continued.

There is **no `paused` outcome.** The plan's enum text predates OQ-3; the
operator removed the drawdown gate entirely, so no code path could produce one.

### One terminal row per held symbol per cycle

The `scan` stage writes the row for every symbol *it* terminates
(`not_eligible`, `blocked`, `no_candidates`). Symbols that produced candidates
are terminated by `/run` instead (`sold` / `dropped`). So a healthy cycle
yields exactly one row per held symbol — written by whichever stage decided it.

**A held symbol with zero rows for a scan-hour means the cycle did not
complete for it** — a scheduler miss, a `/scan` crash, or a `/run` that never
followed a scan that found candidates. That is the condition the fill-rate
check below exists to surface; silent non-execution is the failure mode that
hid FC-031 for 11 days and let the roller never fire.

---

## Fill-rate check

Expected: **one row per held symbol per scan-hour.** Run this to find the gaps.

```sql
-- Held symbols x scan-hours with NO decision row, last 3 days.
WITH deduped AS (
  SELECT *
  FROM `options_wheel.decision_events`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY timestamp DESC) = 1
),
cycles AS (
  SELECT DISTINCT run_id, run_ts FROM deduped
),
symbols AS (
  SELECT DISTINCT symbol FROM deduped
)
SELECT c.run_id, c.run_ts, s.symbol
FROM cycles c
CROSS JOIN symbols s
LEFT JOIN deduped d USING (run_id, symbol)
WHERE d.symbol IS NULL
ORDER BY c.run_ts DESC, s.symbol
```

The log-event form of the same check is `decision_records_written`, emitted at
every flush with `run_id`, `stage`, `row_count`, `expected_count` and
`missing_symbols`.

### Duplicate check

```sql
SELECT dedup_key, COUNT(*) AS copies
FROM `options_wheel.decision_events`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY dedup_key HAVING copies > 1
ORDER BY copies DESC
```

Non-empty is expected occasionally and is **not** a defect: `insertId` dedup is
best-effort over a short streaming window, so a Cloud Scheduler retry minutes
later inserts a second copy. **Every reading query must therefore dedup on
`dedup_key`** — see `uncovered_decisions_sql` in
`dashboard/backend/services/bigquery.py`, whose dedup is pinned by a test. An
unkeyed fire-and-forget writer is what produced 36 duplicate `wheel_cycles`
rows per assignment.

---

## Everyday queries

**Why did NVDA not get a call today?**

```sql
SELECT run_ts, stage, outcome, reason, cost_basis_per_share, current_price,
       underwater_pct, uncovered_days, reason_counts
FROM `options_wheel.decision_events`
WHERE symbol = 'NVDA' AND DATE(run_ts) = CURRENT_DATE()
QUALIFY ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY timestamp DESC) = 1
ORDER BY run_ts DESC
```

**What is blocking the book right now?**

```sql
SELECT outcome, reason, COUNT(DISTINCT symbol) AS symbols
FROM `options_wheel.decision_events`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
QUALIFY ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY timestamp DESC) = 1
GROUP BY outcome, reason ORDER BY symbols DESC
```

**In-gap-strike retro-analysis (OQ-1).** In-gap strikes on $1-grid names are a
permitted, accepted exception with no audit machinery built. Every `sold` row
carries both its floor and its strike, so the evidence to revisit that decision
already exists:

```sql
SELECT symbol, run_ts, strike_price, cost_basis_per_share,
       ROUND(strike_price - cost_basis_per_share, 2) AS above_floor
FROM `options_wheel.decision_events`
WHERE outcome = 'sold'
QUALIFY ROW_NUMBER() OVER (PARTITION BY dedup_key ORDER BY timestamp DESC) = 1
ORDER BY above_floor ASC
```

---

## The two labels

**`underwater_pct` = `(current_price − cost_basis_per_share) / cost_basis_per_share`.**
Signed, and **negative means below the floor** — the plan's own convention
("NVDA … underwater −8.9%"). `current_price` is the broker's own mark
(`market_value / qty` from the Alpaca position), not an independently fetched
quote: it costs no API call for the symbols that produced no candidates, which
is precisely the population this record exists for, and it cannot disagree with
the `avg_entry_price` on the same position dict. NULL means "not computable",
which is a different claim from 0%.

**`uncovered_days` = trading days a held symbol has gone without a covered
call.** Stateless by construction — wheel-state persistence has never worked
(`STATE_STORAGE_BUCKET` unset since inception) — and derived in two steps:

1. **Alpaca positions, already in hand.** A symbol with an open short call is
   covered *right now* → `0`, with no BigQuery round trip. Classification goes
   through `strict_option_type`, never a substring match (FC-041/043/045/048/052).
2. **BigQuery `trades_from_activities`** for the rest, batched into **one query
   per scan** for all held symbols. The anchor is the most recent **call-leg**
   activity on the underlying — a write, a close, an expiry or an exercise; any
   of them means the shares were covered that day. A lot that has never had a
   call written falls back to the **put assignment** that created it, the day
   the shares became coverable. Trading days are counted against the
   `stock_history_from_alpaca` benchmark-symbol calendar (FC-031's), not a
   hand-rolled weekday count — holidays are real and "≥ 7 trading days" is an
   alert boundary.

**NULL is not zero.** No history, BigQuery unreachable, or the lookup gated off
all yield NULL, meaning "we could not tell". The dashboard puts those symbols
in a separate `unknown_uncovered_days` list and the daily check logs
`DRAWDOWN_PAUSE_ALERT_CHECK_FAILED` for them, so an underivable label can never
read as an all-clear.

---

## Consumers

- **Dashboard card** — `GET /api/v2/bot-health/drawdown-pauses` (path kept;
  payload is the uncovered shape). Renders `UncoveredPositionsCard`.
- **Daily alert** — `POST /api/v2/bot-health/pause-alert-check`, weekdays
  17:45 ET. Fires on **"symbol uncovered ≥ N trading days"**. Marker strings,
  policy, channel, scheduler job and threshold env var are all unchanged from
  FC-030 — see `deploy/monitoring/drawdown_pause_alert.md` §Alert 2.
