# Plan: Covered Call Rolling Engine (Friday EOW)

**FC entry:** `docs/FUTURE_CONSIDERATIONS.md` FC-006
**Status:** Draft
**Size:** L
**Author:** Claude
**Last updated:** 2026-04-16

---

## Context

GOOGL and AMD positions that were previously underwater rallied hard (Iran ceasefire + upcoming earnings), leaving existing short covered calls deep ITM at strikes well below current market price. The current system has no mechanism to roll a short call forward — positions either expire/assign or get closed via profit-target/stop-loss. This means shares get called away at a notable discount to the current trading price.

A rolling engine would buy-to-close the expiring short call and sell-to-open a new call at a higher strike for next week's expiration. This moves the effective strike closer to the current price and ideally generates a net credit (or at worst a controlled net debit). Running only on Friday maximizes theta decay on the existing contract before committing to the roll.

## Goals

- Roll short covered calls forward on Friday EOW when stock has rallied through/near the strike
- Move strike price closer to current trading price (roll-up only, never roll down)
- Apply the full existing covered-call framework to the replacement leg (cost basis protection, delta band, min premium, DTE target, risk validation)
- Use relative/percentage-based debit tolerance that scales with position economics
- Track net P&L of each roll and enforce configurable thresholds
- Persist roll history per symbol to bound total rolls (max 2 consecutive)
- Schedule as a distinct Friday-only operation at 3:30 PM ET

## Non-goals

- Put-rolling mirror (strategy takes assignment on puts by design per CLAUDE.md)
- Multi-leg spread construction (diagonals, calendars, verticals)
- Same-strike roll-out (extending time only without moving strike up)
- Rolling on non-Friday days (emergency mid-week rolls)
- Changing existing call_seller/put_seller flow for M-Th

## Proposed approach

### 1. New module: `src/strategy/call_roller.py`

`CallRoller` class with constructor mirroring `CallSeller`:

```python
CallRoller(alpaca_client, market_data, call_seller, config, wheel_state_manager)
```

**Public methods:**

- `should_roll(short_call_position, stock_position, current_stock_price) -> Tuple[bool, str]`
  Pure predicate returning (decision, reason_code). Checks all trigger gates (see section 2).

- `evaluate_roll_opportunity(short_call_position, stock_position) -> Optional[Dict]`
  Calls `should_roll`, then finds target calls via `market_data.find_suitable_calls()`,
  computes net economics, returns opportunity dict with both legs described.

- `execute_roll(roll_opportunity) -> Dict`
  Two-leg sequential execution: buy-to-close then sell-to-open.

**Private helpers:**

- `_compute_net_roll_economics(original_premium, btc_ask, new_bid, contracts) -> Dict`
  Credit/debit math with conservative pricing (btc@ask, stc@bid).

- `_check_debit_tolerance(net_debit, original_premium, notional_value) -> bool`
  Percentage-based gate: net debit must be <= X% of original premium collected
  AND <= Y% of notional exposure. Scales naturally with position size and volatility.

- `_validate_roll_target(new_call, current_strike, stock_cost_basis) -> Tuple[bool, str]`
  Ensures new_strike > current_strike, new_strike >= cost_basis, and passes risk_manager.

### 2. Decision criteria (all must pass)

| Gate | Default | Config key |
|------|---------|------------|
| It's Friday (ET) | weekday()==4 | hard-coded in endpoint |
| Current time >= 15:00 ET | 15:00 | `rolling.trigger_time_et` |
| Existing call DTE <= 1 | 1 | `rolling.max_current_dte` |
| Stock price / strike >= threshold | 0.98 | `rolling.itm_trigger_ratio` |
| New strike > current strike | always | hard rule (roll-up only) |
| Cost basis protection (new strike >= cost basis) | always | inherited from find_suitable_calls |
| New contract passes find_suitable_calls filters | always | inherited delta/DTE/premium/liquidity |
| Net debit <= % of original premium | 25% | `rolling.max_debit_pct_of_premium` |
| Net debit <= % of notional | 0.5% | `rolling.max_debit_pct_of_notional` |
| Rolls on this position < max | 2 | `rolling.max_rolls_per_position` |
| Not in earnings blackout | 2 days | `rolling.earnings_blackout_days` |
| Gap filter not triggered | existing | inherited from gap_detector |

### 3. Relative debit tolerance model

Instead of a fixed $/contract threshold, debit tolerance scales with position economics:

**Primary gate:** `net_debit <= max_debit_pct_of_premium * original_premium_collected`
- If original call sold for $2.00 and max_debit_pct is 25%, max debit = $0.50/contract
- If original call sold for $0.50 and max_debit_pct is 25%, max debit = $0.125/contract
- Higher premiums (volatile stocks) naturally allow larger debit
- Lower premiums get tighter caps

**Backstop:** `net_debit <= max_debit_pct_of_notional * (strike * 100 * contracts)`
- Hard cap on absolute debit relative to position notional size
- Prevents outsized debits on high-premium stocks

### 4. Strike selection

Use existing `market_data.find_suitable_calls(symbol, min_strike_price=max(cost_basis_per_share, current_strike + 0.01))`. This reuses the exact delta band [0.30, 0.70], DTE target (7), premium ($0.30 min), liquidity validation pipeline.

Since `call_target_dte=7` and we run Friday, next Friday's expiry surfaces naturally.

Selection: iterate sorted candidates (by return_score) and pick the first that passes the net-economics gate. Try up to `fallback_strike_attempts` (default 2) before giving up.

### 5. Execution order (sequential two-leg)

1. **Buy-to-close** existing short call:
   - `alpaca.place_option_order(symbol, qty, side='buy', order_type='limit', limit_price=round(btc_ask * 1.05, 2))` — pay up to 5% over ask for Friday PM fill
   - Poll order status for up to `btc_fill_timeout_seconds` (120s)
   - If unfilled: **abort roll**, leave existing position intact, log `call_roll_btc_unfilled`

2. **Sell-to-open** new short call:
   - `alpaca.place_option_order(new_symbol, qty, side='sell', order_type='limit', limit_price=round(new_bid * 0.98, 2))`
   - If STO fails after BTC succeeded (**naked exposure risk**):
     - Retry once at `limit=new_bid` (flat to bid)
     - Try next fallback strike from suitable-calls list
     - If all fail: emit `log_error_event(error_type="roll_naked_exposure", recoverable=False)` for alerting

3. Record paired `(btc_order_id, stc_order_id)` on WheelStateManager roll history.

### 6. Integration points

**a) New endpoint: `deploy/cloud_run_server.py` — `POST /roll`**
- Pattern matches existing `/monitor` endpoint
- `@require_api_key`, `strategy_lock`, `_is_market_open()` gate
- Friday-only guard: `if now_et.weekday() != 4: return {'skipped': 'not_friday'}`
- Body: initialize `WheelEngine(config)`, call `engine.run_rolling_cycle()`

**b) New method: `src/strategy/wheel_engine.py` — `run_rolling_cycle()`**
- Separate from `_manage_existing_positions` (testable in isolation, never runs on M-Th)
- Gets positions, filters short call positions, matches to stock positions for cost basis
- Instantiates CallRoller, evaluates each position, executes qualifying rolls

**c) Cloud Scheduler (documented, not in-repo)**
- Name: `options-wheel-roll-friday`
- Cron: `30 15 * * 5` (3:30 PM ET, `timeZone: America/New_York`)
- Target: `POST ${CLOUD_RUN_URL}/roll` with API key header

### 7. Config additions — `config/settings.yaml`

```yaml
rolling:
  enabled: true
  trigger_time_et: "15:00"
  max_current_dte: 1
  itm_trigger_ratio: 0.98
  max_debit_pct_of_premium: 0.25    # 25% of original premium collected
  max_debit_pct_of_notional: 0.005  # 0.5% of notional exposure
  max_rolls_per_position: 2
  earnings_blackout_days: 2
  btc_limit_over_ask_pct: 0.05
  stc_limit_under_bid_pct: 0.02
  btc_fill_timeout_seconds: 120
  fallback_strike_attempts: 2
```

Corresponding attributes in `src/utils/config.py` with defaults.

### 8. State tracking — `WheelStateManager` additions

Extend per-symbol state dict:

```python
'roll_history': [],              # list of roll event dicts
'total_rolls': 0,                # counter for max_rolls guard
'cumulative_roll_premium': 0.0,  # sum of net roll premiums
```

New methods: `record_call_roll(symbol, old_symbol, new_symbol, contracts, net_premium, btc_cost, stc_credit, old_strike, new_strike, roll_date)` and `get_roll_count(symbol)`.

### 9. Logging — new event_types via existing log_trade_event

- `call_roll_evaluated` — per short-call evaluation with gate decisions
- `call_roll_skipped` — gate failed with `skip_reason`
- `call_roll_btc_executing` / `call_roll_btc_filled` / `call_roll_btc_unfilled`
- `call_roll_stc_executing` / `call_roll_stc_filled` / `call_roll_stc_unfilled`
- `call_roll_completed` — both legs successful with `net_premium`, `old_strike`, `new_strike`
- `call_roll_naked_exposure` — error via `log_error_event(recoverable=False)`

## Critical files

- `src/strategy/call_roller.py` — **new**, CallRoller class
- `src/strategy/wheel_engine.py` — add `run_rolling_cycle()`, construct CallRoller in `__init__`
- `src/strategy/wheel_state_manager.py` — extend state schema, add `record_call_roll`/`get_roll_count`
- `deploy/cloud_run_server.py` — new `/roll` endpoint with Friday guard
- `config/settings.yaml` + `src/utils/config.py` — new `rolling:` section

## Reuse

- `src/api/market_data.py::find_suitable_calls` — entire filter pipeline including cost-basis min_strike_price floor
- `src/strategy/call_seller.py::_parse_option_symbol` — OCC symbol parsing (underlying, strike, DTE)
- `src/api/alpaca_client.py::place_option_order` — both legs, with existing idempotent client_order_id, circuit breaker, retries
- `src/risk/risk_manager.py::validate_new_position` — validate replacement leg
- `src/risk/gap_detector.py` — earnings and gap filter checks
- `src/utils/logging_events.py::log_trade_event, log_error_event, log_position_update` — no new functions needed

## Risks & mitigations

- **Naked exposure between BTC fill and STO fill**
  - Mitigation: pre-check STO quote freshness before submitting BTC; retry STO at bid then fallback strike; emit non-recoverable error for alerting if all fail

- **Cumulative premium erosion via repeated debit rolls**
  - Mitigation: max 2 rolls per position; relative debit tolerance caps erosion proportionally; `cumulative_roll_premium` tracked in state for monitoring

- **Cost basis corruption**
  - Mitigation: reuse same `find_suitable_calls(min_strike_price=cost_basis)` guard as fresh calls; unit test locks behavior

- **Friday-close thin liquidity / wide spreads**
  - Mitigation: aggressive BTC pricing (5% over ask), tight STO pricing (2% under bid with fallback to flat), 120s fill timeout. All tunable via config.

- **Earnings surprise within new expiry week**
  - Mitigation: `earnings_blackout_days=2` check reusing gap_detector infrastructure

- **No put-side mirror (symmetry caveat)**
  - Mitigation: rolling is an extension of covered calls; puts take assignment by design. Documented explicitly.

## Rollout

1. Deploy with `rolling.enabled: false` in prod config
2. Enable in paper-only settings; run manual `/roll` curls for 1-2 Fridays
3. After validation, create `options-wheel-roll-friday` Cloud Scheduler job
4. Monitor: `call_roll_completed` count, `net_premium` distribution, `roll_naked_exposure` count (must be 0)
5. Kill switch: `rolling.enabled: false` + redeploy = instant disable

## Verification

- [ ] Unit tests in `tests/test_call_roller.py`: trigger gates, cost basis protection, debit tolerance (percentage-based), max rolls, earnings blackout, happy path execution, BTC unfilled abort, STO failure emergency path, fallback strike selection
- [ ] Integration test in `tests/test_wheel_engine.py::test_run_rolling_cycle_end_to_end`
- [ ] Manual paper-mode test: `/roll` POST on a Friday with ITM covered call in paper account
- [ ] Negative-path test: mispriced BTC limit to verify abort without naked exposure
- [ ] Production monitoring for 4 weekly cycles after deploy

## Open questions

- Should net-economics calculation include lifetime premium (original + all rolls) for display/logging, while using immediate roll P&L for the debit-tolerance gate? **Recommendation: yes** — lifetime for observability, immediate for gating.
- Multi-contract positions (e.g., 3 short calls on AMD): roll all atomically or per-contract? **Recommendation:** all-or-nothing per symbol (single BTC + STO pair), matching CallSeller._calculate_call_position pattern.
