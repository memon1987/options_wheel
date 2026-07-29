# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an algorithmic trading solution that executes an options wheel strategy. The options wheel is a systematic approach to generating income from stocks through selling cash-secured puts and covered calls. All trade execution is handled through the Alpaca.py APIs.

## Plan-First Development

Plan-First Development rules are defined in the parent `CLAUDE.md` and apply to this project. Project-specific plan files live in `docs/plans/`.

## Development Setup

Install dependencies:
```bash
pip install -r requirements.txt
```

Set up environment:
```bash
cp .env.example .env
# Edit .env with your Alpaca API credentials
```

## Commands

**Run Strategy:**
```bash
python main.py --command run --dry-run  # Test mode
python main.py --command run            # Live execution
```

**Analysis Commands:**
```bash
python main.py --command scan    # Scan for opportunities
python main.py --command status  # Portfolio status  
python main.py --command report  # Performance report
```

**Testing:**
```bash
pytest tests/ -v                 # Run all tests
pytest tests/test_config.py -v   # Run specific test file
```

**Code Quality:**
```bash
black src/ tests/                # Format code
flake8 src/ tests/               # Check style
mypy src/                        # Type checking
```

## Architecture

**Core Strategy Flow:**
1. `WheelEngine` orchestrates the complete strategy
2. `MarketDataManager` analyzes stocks and options chains  
3. `OptionsScanner` identifies and ranks opportunities
4. `PutSeller`/`CallSeller` execute strategy-specific trades
5. `RiskManager` validates all positions against limits
6. `PortfolioTracker` monitors performance and generates reports

**Key Integration Points:**
- All market data flows through `AlpacaClient` wrapper
- Configuration centralized in `Config` class with YAML + env vars
- Risk validation required before any trade execution
- Structured logging throughout for debugging and audit trails

## Trading APIs

- **Alpaca API**: Primary API for all trade execution via custom AlpacaClient wrapper
- **Paper Trading**: Enabled by default at https://paper-api.alpaca.markets/v2
- **Options Trading**: Full support for cash-secured puts and covered calls
- **Real-time Data**: Stock quotes, options chains, and portfolio positions

## Key Components (Implemented)

- **WheelEngine** (`src/strategy/wheel_engine.py`): Core orchestrator for wheel strategy
- **PutSeller** (`src/strategy/put_seller.py`): Cash-secured put selling logic
- **CallSeller** (`src/strategy/call_seller.py`): Covered call selling logic  
- **AlpacaClient** (`src/api/alpaca_client.py`): API wrapper for trading operations
- **MarketDataManager** (`src/api/market_data.py`): Options chain analysis and filtering
- **RiskManager** (`src/risk/risk_manager.py`): Position validation and risk controls
- **PortfolioTracker** (`src/data/portfolio_tracker.py`): Performance monitoring
- **OptionsScanner** (`src/data/options_scanner.py`): Opportunity identification
- **Config** (`src/utils/config.py`): Centralized configuration management

## Strategy Configuration

**Short-Term Focus**: 7-day maximum expiration for rapid theta decay
**Conservative Deltas**: 0.10-0.20 range for ~10-20% assignment probability
**Assignment Strategy**: Take assignment on puts (no stop losses), protect calls
**Position Sizing**: Maximum 1 contract per new position, 10% portfolio allocation

## Wheel Strategy Symmetry Principle

**CRITICAL DEVELOPMENT RULE**: The options wheel has two phases that must be treated symmetrically:

1. **Put Selling Phase** - Initial entry via `find_suitable_puts()` and `put_seller.py`
2. **Call Selling Phase** - Position management via `find_suitable_calls()` and `call_seller.py`

**When making changes to one side (puts OR calls), ALWAYS apply equivalent changes to the other side:**
- Logging enhancements → Apply to both puts and calls
- Filtering improvements → Apply to both puts and calls
- Error handling → Apply to both puts and calls
- Performance metrics → Apply to both puts and calls

**Why**: The wheel is a complete lifecycle (sell put → assignment → sell call → called away → repeat). Both phases need equal observability, consistent logging, and symmetric filtering for effective debugging and analysis.

**Key Files**:
- Filtering: `src/api/market_data.py` (find_suitable_puts/calls, _check_put/call_criteria_detailed)
- Execution: `src/strategy/put_seller.py` and `src/strategy/call_seller.py`

## Risk Management Philosophy

**Puts**: No stop losses - designed to take assignment on quality stocks
- Assignment probability ≈ |Delta| (10-20% for our range)
- Keep full premium on 80-90% of positions
- Take assignment on remaining 10-20% at favorable prices

**Calls**: Protected with stop losses adjusted for time decay
- 75% loss threshold (50% base × 1.5 multiplier) accounts for theta
- Delta > 0.5 triggers immediate exit (likely ITM)
- Prevents unlimited upside risk on covered positions

## Data Analysis Policy

**IMPORTANT: Cloud-First Data Analysis**
- For ALL analysis of *what the bot actually did*, use data on Google Cloud Platform — not local files or caches.
- Primary sources:
  - BigQuery `options_wheel.trades_from_activities` — real fills, the source of truth for realized behavior
  - BigQuery `options_wheel.backtest_runs` — screening results (see `docs/bigquery/backtest_runs.md`)
  - Google Cloud Storage: `gs://gen-lang-client-0607444019-options-data/`
  - Cloud Run dashboard endpoints
- This ensures analysis reflects production-ready, persistent, centralized data.

**Backtests are the exception, and the distinction matters.** The old
`/backtest`, `/backtest/results`, `/backtest/history` and `/cache/*` endpoints
were **deleted in FC-032** — the engine behind them had never produced a single
trade and one component emitted fabricated numbers. Do not reference them.

The rebuilt engine (FC-032) runs **locally by design**: it replays live strategy
code over historical Alpaca data and needs no cloud round-trip.

**Read `docs/BACKTEST_ENGINE.md` before quoting any backtest number.** It states what
the engine measures well, what it does not, and the six things that mislead readers who
don't know them. Two worth knowing here: the headline "81% strike reproduction" is the
**put leg only** (the call leg is 55.2%, and prices calls at 0.676 of live), and a symbol
showing 0% days in position is a **filter** result — 8 of 14 configured symbols currently
cannot trade at all, for reasons unrelated to symbol quality.

```bash
python main.py --command backtest --symbol NVDA --start 2025-10-01 --end 2026-07-01
python main.py --command screen            # whole universe -> options_wheel.backtest_runs
```

Screening results *are* persisted to BigQuery and are cloud-first like everything
else. A local `--command backtest` run is a simulation, never evidence of what
the bot did — for that, always go to `trades_from_activities`.

**Read backtest output with its stated biases.** Every report carries a
known-bias footer. Two of them favour the wheel over its own benchmark
(dividends and early assignment are unmodeled), so `excess_return` is optimistic
on dividend payers. Never quote a backtest number without them.

## Dashboard & Backend Cascading Impact Analysis

**CRITICAL: Before making changes to the dashboard or backend, ALWAYS perform a cascading impact analysis.**

The dashboard architecture has multiple interconnected layers. Changes to one layer can break functionality in others. Always trace data flow end-to-end:

### Data Flow Architecture
```
Trading Bot (Cloud Run) → Cloud Logging → BigQuery Views → Dashboard Backend → Dashboard Frontend
```

### Pre-Change Checklist

Before modifying ANY dashboard or backend component, analyze:

1. **Data Source Changes (BigQuery Views/Tables)**
   - Which backend queries use this data?
   - What fields does the frontend expect?
   - Are there aggregations that depend on specific field values?

2. **Backend API Changes (FastAPI endpoints)**
   - Which frontend hooks consume this endpoint?
   - What TypeScript types need updating?
   - Are there caching considerations?

3. **Frontend Component Changes**
   - What API data does this component expect?
   - Are there shared components (e.g., RecentTrades used in multiple places)?
   - Does the status/display logic match backend data format?

4. **Logging Event Changes (logging_events.py)**
   - Which BigQuery views depend on this event_type?
   - Will existing queries still work?
   - Do frontend status mappings need updating?

### Key Files by Layer

| Layer | Key Files | Impact When Changed |
|-------|-----------|---------------------|
| Bot Logging | `src/utils/logging_events.py` | BigQuery views, dashboard status displays |
| BigQuery | `dashboard/backend/services/bigquery.py` | All dashboard endpoints |
| Backend API | `dashboard/backend/routers/*.py` | Frontend hooks, data types |
| Frontend Hooks | `dashboard/frontend/src/hooks/useApi.ts` | All consuming components |
| Frontend Components | `dashboard/frontend/src/components/*.tsx` | UI display, user experience |
| Frontend Pages | `dashboard/frontend/src/pages/*.tsx` | Feature functionality |

### Example: Order Status Display

Order status (filled / expired / assigned) is **not** derived from bot logs. It
comes from Alpaca's account-activities feed, which is authoritative and
idempotent. Trace a change through these five layers:

1. **Ingest Layer**: `src/data/activities_ingestor.py` pulls Alpaca activities
   (`FILL`, `OPASN`, `OPEXP`, ...) and dedupes on `activity_id`
2. **BigQuery Layer**: rows land in `options_wheel.trades_from_activities`;
   `trades_with_outcomes` joins them into per-position outcomes
3. **Backend Layer**: `dashboard/backend/services/bigquery.py` queries those
   views — confirm any new field is selected and returned
4. **Frontend Hooks**: add the field to the TypeScript interface in
   `dashboard/frontend/src/hooks/useApi.ts`
5. **Frontend Components**: update the status mapping that renders it
6. **Verify**: premium calculations and other aggregates are unaffected

**Do not add a bot-side order-status poller.** One existed
(`poll_order_statuses`) and was deleted in FC-035. It *ran* on every `/run`
cycle for ~4 months, but produced nothing — 0 events and 0 rows across ~490
invocations — because it only ever inspected open orders, which are never in
a final state. Nothing read its output, and it would have been a second,
non-idempotent writer of facts the activities feed already carries. See
`docs/plans/fc-035.md`.

### Verification Steps

After any change:
1. Check that existing features still work (premium tracking, trade history, etc.)
2. Verify TypeScript compiles without errors
3. Test the full data flow from bot to dashboard display
4. Confirm metrics and aggregations are unaffected by display-only changes

## Development Notes

**Alpaca Setup**: Requires options trading approval and paper trading endpoint
**Testing**: Comprehensive test suite in `/tests` directory
**Logging**: Structured logging with structlog for trade audit trails
**Configuration**: YAML-based settings with environment variable substitution