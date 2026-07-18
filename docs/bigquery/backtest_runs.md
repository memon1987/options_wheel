# `options_wheel.backtest_runs`

One row per **symbol per screening run** (FC-032 Phase 5). Written by
`src/backtesting/reporting/bq_writer.py` via the `/backtest/screen` endpoint or
`python main.py --command screen`.

Day-partitioned on `timestamp`.

## What this table is for

Answering "which symbols we currently trade have stopped being a fit?" — and
keeping a queryable audit trail of *why*, under *which* configuration.

**`demote` is a recommendation, not an action.** Nothing in the pipeline changes
the trading universe. The plan requires two observed screening cycles before any
automation is considered, and the engine's known biases are the reason.

## Reading a row honestly

Three columns exist specifically to stop the headline number being misread:

| column | why it matters |
|---|---|
| `config_hash` | A verdict is uninterpretable without the thresholds that produced it. Two runs with different hashes are not comparable — a changed premium floor looks identical to a changed symbol. |
| `option_pnl_share` | Fraction of gross P&L from premium rather than the stock leg. Published wheel studies find 94–99% comes from the stock; a "profitable" symbol at a low share is mostly a long position. `NULL` when the legs have opposite signs, because a percentage would mislead. |
| `days_in_position_fraction` | Time occupancy. A symbol that cannot clear the premium floor shows a flattering return on the handful of days it traded — KMI scored +138% annualized on one 8-day cycle in 273 days. |

Also: `reconciliation_gap` should be ~0. A non-zero value means a cash flow
escaped the attribution columns, and the split between `option_pnl` and the
stock columns should not be trusted for that row.

And `verdict_flips_on_fill` — if true, the verdict depends on whether fills come
at mid or at the bid, which means it is not a verdict.

## Schema

### Run identity
| column | type | notes |
|---|---|---|
| `run_id` | STRING | Shared by every row of one screening run |
| `timestamp` | TIMESTAMP | Partition key |
| `symbol` | STRING | |
| `window_start` / `window_end` | DATE | Evaluation window |
| `config_hash` | STRING | 16-char hash of the strategy thresholds |
| `engine_version` | STRING | |

### Verdict
| column | type | notes |
|---|---|---|
| `verdict` | STRING | `fit` / `marginal` / `unfit`; NULL when the symbol errored |
| `demote` | BOOL | `verdict == 'unfit'`. Recommendation only |
| `verdict_reasons` | STRING[] | Ordered, prefixed `BLOCK:` / `WARN:` / `OK:` |
| `binding_constraint` | STRING | Which filter blocked the most days |

### Performance
`starting_cash`, `final_equity`, `total_return`, `annualized_return`,
`annualized_return_on_collateral`, `benchmark_return`, `excess_return` — all FLOAT.

Prefer **`annualized_return_on_collateral`**. `total_return` divides by the whole
account, so it is dominated by the arbitrary per-symbol notional and mostly
measures idle cash.

### Attribution
`option_pnl`, `stock_pnl_realized`, `stock_pnl_unrealized`, `option_pnl_share`,
`reconciliation_gap` — all FLOAT. Realized and unrealized are separate because
counting only realized understates the stock leg whenever a cycle is still open.

### Activity and risk
`decision_days`, `days_in_position`, `days_in_position_fraction`,
`cycles_completed`, `cycles_open`, `puts_sold`, `calls_sold`, `win_rate`,
`assignment_rate`, `max_drawdown`, `days_underwater`, `avg_collateral`.

`win_rate` is high by construction at 0.10–0.20 delta — read it beside
`max_drawdown` and `days_underwater`, never alone.

### Fill sensitivity and provenance
`bid_fill_return`, `verdict_flips_on_fill`, `known_biases` (STRING[]), `error`.

A symbol that failed still gets a row with `error` set and a NULL verdict.
**A NULL verdict does not mean the symbol is fine — it means it was never
checked.** Filter explicitly.

## Queries

Current demotion candidates from the most recent run:
```sql
WITH latest AS (
  SELECT run_id FROM `options_wheel.backtest_runs`
  ORDER BY timestamp DESC LIMIT 1
)
SELECT symbol, verdict, total_return, annualized_return_on_collateral,
       days_in_position_fraction, ARRAY_TO_STRING(verdict_reasons, '; ') AS reasons
FROM `options_wheel.backtest_runs`
WHERE run_id IN (SELECT run_id FROM latest) AND demote
ORDER BY total_return;
```

Symbols that were never actually checked (do not mistake these for passes):
```sql
SELECT symbol, error FROM `options_wheel.backtest_runs`
WHERE verdict IS NULL
  AND run_id = (SELECT run_id FROM `options_wheel.backtest_runs`
                ORDER BY timestamp DESC LIMIT 1);
```

Verdict drift for one symbol — only meaningful within a single `config_hash`:
```sql
SELECT DATE(timestamp) AS run_date, config_hash, verdict,
       total_return, option_pnl_share
FROM `options_wheel.backtest_runs`
WHERE symbol = 'NVDA'
ORDER BY timestamp DESC;
```

Rows whose attribution does not reconcile (treat their split as unreliable):
```sql
SELECT run_id, symbol, reconciliation_gap
FROM `options_wheel.backtest_runs`
WHERE ABS(IFNULL(reconciliation_gap, 0)) > 0.01;
```

## Known biases carried in every row

`known_biases` lists them by title; the full text is in each run's markdown
report and in `src/backtesting/reporting/report.py`. The two that most affect a
demotion decision:

- **Dividends are not modeled**, and this *flatters the wheel* — the buy-and-hold
  benchmark holds shares every day and forgoes the entire dividend stream, while
  the wheel holds them only intermittently (~15 points on a 6.5% yielder over
  2.4 years). Weigh `excess_return` accordingly on income names.
- **Early assignment is not modeled**, also optimistic, and concentrated on the
  same dividend payers.
