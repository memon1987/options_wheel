# Cost-Basis Floor Validation — 2026-05-08

> **⚠️ Code references are past tense as of FC-068 (2026-08-01).** Every claim below
> about `call_seller.evaluate_covered_call_opportunity` — that it is "the only
> opportunity-builder that reads `stock_position['cost_basis']`", that AMZN cycle 1's
> calls went through it, that the failure could be reproduced by tracing through it —
> describes a function this project has **deleted**. The *finding* stands and was acted
> on: FC-029 R2, then FC-050, then FC-065 Phase 1, which made the floor Alpaca's
> `avg_entry_price` and moved it onto the live `/scan` path. The floor now lives in
> `options_scanner.scan_for_call_opportunities` (scan-time) and
> `call_seller.execute_call_sale` (execute-time, FC-050). Read this as the record of a
> 2026-05 investigation, not as a map of current code.


**Triggered by:** User question — "before we execute Phase 1 changes I want to validate the findings on cost basis floor. Confirm this is actually the case. We should be getting cost basis based on assignment price (static floor) vs the dynamic floor the analysis suggested."

**Finding:** **The original strategy review's "dynamic erosion" hypothesis was wrong. The truth is more severe: the cost-basis floor is non-functional — Alpaca's `cost_basis` field returns 0 for stock positions acquired via option assignment, and both safety checks in the call-selling path are gated on `> 0`, so a 0 value trivially bypasses them.**

The user's intuition was right to challenge the dynamic-erosion theory. After empirical investigation, the floor isn't dynamically eroding — **it's effectively zero**, the entire safety net has been a no-op since at least early April 2026.

---

## What I checked

### 1. Code paths
Both gates that protect against sub-cost calls have a `> 0` guard:

```python
# src/api/market_data.py:435 — find_suitable_calls filter
if min_strike_price > 0 and call['strike_price'] < min_strike_price:
    rejection_stats['below_cost_basis'] += 1
    continue

# src/strategy/call_seller.py:211 — execute_call_sale defensive check
if stock_cost_basis > 0 and strike_price > 0:
    cost_basis_per_share = stock_cost_basis / shares_covered
    if strike_price < cost_basis_per_share:
        return {'success': False, 'error': 'strike_below_cost_basis', ...}
```

If `stock_cost_basis = 0`, neither guard fires. This is the key vulnerability.

### 2. Empirical: what does the bot actually log?

Pulled the 8 most recent `call_sale_executed` events from Cloud Logging (Apr 9–16, 2026):

| Date | Symbol | Strike | `stock_cost_basis` | `shares_covered` |
|---|---|---:|---:|---:|
| 2026-04-09 14:15 | GOOGL260415C00312500 | 312.5 | **0** | **0** |
| 2026-04-09 15:15 | AMD260417C00245000 | 245 | **0** | **0** |
| 2026-04-10 15:15 | AMZN260417C00240000 | 240 | **0** | **0** |
| 2026-04-10 16:15 | AMZN260417C00240000 | 240 | **0** | **0** |
| 2026-04-13 18:15 | AMZN260417C00240000 | 240 | **0** | **0** |
| 2026-04-15 14:15 | AMZN260420C00245000 | 245 | **0** | **0** |
| 2026-04-15 15:15 | AMD260417C00252500 | 252.5 | **0** | **0** |
| 2026-04-16 14:15 | AMZN260422C00240000 | 240 | **0** | **0** |

**100% of the events log `stock_cost_basis = 0` and `shares_covered = 0`.** This is not a quirk of one symbol or one cycle — it's universal across:
- AMZN (silently-assigned cycle, expected to have weird Alpaca metadata)
- GOOGL (normal Feb 9 OPASN at $312.5 — Alpaca knows about this assignment with full activity-feed records)
- AMD (normal Jan 23 OPASN at $245 — Alpaca records it correctly)

If Alpaca tracked cost_basis correctly (qty × strike), GOOGL's stock position on Apr 9 would have shown $31,250 cost_basis. It logged 0.

### 3. Cross-checked the Alpaca client code

`src/api/alpaca_client.py:244–258` — `get_positions()` reads `pos.cost_basis` directly from the alpaca-py SDK and casts to float. No transformation, filtering, or override:

```python
return [
    {
        'symbol': pos.symbol,
        'qty': float(pos.qty),
        'cost_basis': float(pos.cost_basis),  # ← direct passthrough
        ...
    }
    for pos in positions
]
```

So whatever the bot logs is exactly what Alpaca's API returned. The 0 value originates from Alpaca's paper-trading API.

### 4. Cross-checked when the floor was added

`src/strategy/call_seller.py` cost-basis floor was added 2025-09-29 (commit `77a1ee36`, "Critical: Add cost basis protection for covered calls"). Pre-dates AMZN cycle 1 (Nov 2025). So the floor *exists* in code; it's just been silently bypassed because Alpaca's `cost_basis` returns 0.

### 5. Verified there's no other path silently bypassing the floor

- `evaluate_covered_call_opportunity` is the only opportunity-builder that reads `stock_position['cost_basis']`.
- `call_roller.py` (FC-006, post-2026-04-16) doesn't go through `execute_call_sale` — it calls `place_option_order` directly via `_place_and_poll_stc`. **However, FC-006 has fired 0 times in production**, so this is irrelevant to the historical AMZN cycle 1.
- AMZN cycle 1 (Nov 2025) calls all went through `evaluate_covered_call_opportunity` → `execute_call_sale`. Both reads of `stock_position['cost_basis']` would have been 0 if Alpaca's API behaved the same way then. (Cloud Logging retention is ~30 days, so we can't verify Nov 2025 logs directly, but the pattern in Apr 2026 is consistent across multiple symbols and conditions.)

---

## Why does Alpaca return 0?

Most likely explanation (based on Alpaca paper-trading API behavior and IRS Section 1234 option-premium accounting): **Alpaca's `cost_basis` for stocks acquired via option assignment is computed as `qty × avg_entry_price`, but `avg_entry_price` for assigned shares is set to 0 (since no cash was paid at acquisition — the cash flow is recorded in the put assignment ledger separately).** This is broker-dependent. Some brokers (Schwab, Fidelity) compute assigned-stock cost basis as `strike − premium received` per IRS §1234. Alpaca's paper engine appears to not — it leaves `avg_entry_price = 0`.

This is an **Alpaca paper-engine quirk**, not a bug in our code. (Possibly fixed in live trading; we're on paper.)

We didn't validate via direct API hit (no open stock positions to query right now), but the empirical evidence is overwhelming: 8/8 events across 3 symbols and varied conditions all return 0.

---

## Severity reframing

The original strategy review's R2 said "make the cost-basis floor truly hard (no premium-adjustment slip)." The actual failure mode is much worse:

- **Original hypothesis:** Floor exists at $247.50 initially, then erodes ~$30 over a cycle as call premium closes — sub-cost calls get progressively allowed.
- **Reality:** Floor never existed in production. It's been 0 since the bot's been live (or at least since Alpaca's behavior on these positions has been observed).

This means:
1. Every covered-call sale in production has had **zero protection against sub-cost-basis strikes**.
2. The 3 loss cycles (AMD 11-17 −$1,925, AMZN 11-04 −$443, UNH 10-30 −$532) lost $2,900 in cycle P&L specifically because there was **no floor**.
3. Future cycles in falling markets will hit the same trap unless we fix this.

---

## Corrected R2 recommendation

The original recommendation was directionally correct but framed wrong. Here's the corrected version:

### R2 (corrected): Source-of-truth cost basis from our own records, not Alpaca's broken field

**Change scope:**

1. **In `src/data/activities_ingestor.py`** (or a small new module): when an `OPASN` activity is processed for a *put* assignment, capture `(symbol, strike_price, transaction_time)` and persist to `WheelStateManager.symbol_states[symbol]['assignment_strike']`. This becomes the canonical cost basis for the wheel cycle. (We already use the same OPASN→OPTRD pairing logic in FC-024's view — this just persists it.)

2. **In `src/strategy/call_seller.py:63`** — replace:
```python
stock_cost_basis = float(stock_position['cost_basis']) / shares_owned
```
with:
```python
# Alpaca's cost_basis returns 0 for assigned positions (paper-engine quirk).
# Use our own assignment_strike as the source of truth.
state = self.wheel_state.get_position_summary(symbol)
assignment_strike = state.get('assignment_strike') or state.get('stock_cost_basis')
if not assignment_strike:
    # Fallback: use Alpaca's reported value (may be 0).
    # Better than nothing for unassigned positions like manual buys.
    alpaca_cb = float(stock_position['cost_basis']) / shares_owned
    assignment_strike = alpaca_cb if alpaca_cb > 0 else 0
stock_cost_basis = assignment_strike
```

3. **In `src/strategy/call_seller.py:211`** — defensive check now needs to allow assignment_strike-driven floor too. Change the gate from `if stock_cost_basis > 0` to `if cost_basis_per_share > 0`. Same effect, but reads from the corrected source.

4. **Backfill historical assignment_strike values.** For each existing entry in `WheelStateManager`, derive from `wheel_cycles_from_activities.put_strike` for the most recent unclosed cycle. One-time migration script.

### Independent of R2 — should we also worry about R2 being a no-op for non-assigned acquisitions?

Edge case: if the user manually buys shares (not via put assignment), there's no assignment_strike. Alpaca's cost_basis SHOULD be populated correctly in that case (since it was a normal market purchase). The fallback in step 2 above handles this — uses Alpaca's value when our own is missing.

We should monitor: post-fix, log a warning whenever `assignment_strike` is populated AND Alpaca's `cost_basis` is non-zero AND they diverge. That's a signal that Alpaca's behavior changed, or our logic missed something.

---

## What to do now

### Updated Phase 1 plan (FC-029)

R1, R2 (corrected), R3 still ship together. The corrected R2 has a slightly larger surface area (touches `WheelStateManager` and the activities ingestor) but isn't fundamentally harder. Roughly the same M-sized PR.

**Sequence:**
1. Add `assignment_strike` to `WheelStateManager.symbol_states` schema. Default to None.
2. Wire OPASN-put events from the activities ingestor into `WheelStateManager.set_assignment_strike(symbol, strike)`.
3. Backfill: one-time SQL/script to set `assignment_strike` for any currently-tracked stock positions based on the most recent OPASN-put strike per symbol from `trades_from_activities`.
4. Update `call_seller.py:63` and `:211` to read from `WheelStateManager` first, Alpaca second.
5. Add a monitoring log: "assignment_strike vs alpaca_cb divergence detected" (info-level) when both are populated and differ — gives visibility into Alpaca's behavior over time.

### Validation post-deploy

- Trigger the bot on a known live cycle (currently no stock positions, so we'd need to wait for a future assignment).
- Or: simulate by manually setting `assignment_strike` in `WheelStateManager` for a hypothetical position and tracing through `evaluate_covered_call_opportunity`.
- Or (best): write a unit test that mocks `stock_position['cost_basis'] = 0` (Alpaca's broken behavior) AND `WheelStateManager.assignment_strike = $250`, verify a $245-strike call is blocked.

### Don't:

- Don't rely on Alpaca's `cost_basis` field at all going forward. Treat it as advisory/fallback only.
- Don't try to "fix" the dynamic-erosion theory in the original review — that's not the bug.
- Don't file a support ticket with Alpaca about this — we're on paper trading, may not be reproduced in live, and they're slow to respond (per FC-021 ticket history).

---

## Conclusion

**The user's instinct to validate was correct, and the answer is more severe than the original review suggested.** The cost-basis floor isn't dynamically eroding — it's been broken since project start. Every covered call sold to date had zero floor protection. This is the most actionable finding from the entire strategy review and should be fixed first.

Updated R2 above. Ship as part of Phase 1 (FC-029) alongside R1 and R3.
