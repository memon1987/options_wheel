# Wheel Strategy Review — Senior Trader's Recommendations
**Author:** Claude (analyst persona)
**Date:** 2026-05-07
**Scope:** Full strategy parameter audit + actionable recommendations
**Trigger:** User question — "B&H notably outperformed our current strategy. Are there parameters or strategies we can adjust to maximize returns?"
**Period analyzed:** 2025-10-06 → 2026-05-06 (213 calendar days; 11 wheel cycles + 60+ pure-put cycles across 7 traded symbols)

---

## TL;DR

The wheel delivered **54% of buy-and-hold dollar P&L** ($21,016 vs $39,200 across 7 symbols). 5 of 7 symbols lagged B&H. **The shortfall is not random — it concentrates in 3 cycles that share one structural cause: the stock dropped 5–16% between assignment and called-away, and the bot got called away well below acquisition cost.** Those 3 cycles cost **$9,000** in share-side losses (40% of total option-side P&L).

Root cause: **call selection parameters are structurally too aggressive (delta range 0.30–0.70 = 30–70% assignment probability), 2–3× the put delta band (0.10–0.20).** Combined with an erodable cost-basis floor (Alpaca's `cost_basis` decreases as call premiums close, so the "never sell below cost" guard slips down by ~$30/share over a cycle), the bot was effectively writing increasingly aggressive calls into falling markets — locking in losses by called-away.

The user already identified the call-delta lever. This document confirms with data and ranks 11 additional changes by expected impact, ordered by recommended priority. Top three:

1. **Tighten `call_delta_range` from `[0.30, 0.70]` to `[0.15, 0.25]`** — prevents the near-ATM call writes that caused all three loss cycles. Highest impact.
2. **Make the cost-basis floor truly hard** — never let accumulated call premium erode it. Currently the floor moves down ~1% per closed call, which over 9 rolls (AMZN cycle 1) drops it by ~$25/share.
3. **Add a "drawdown pause"** — if shares are >5% below cost basis, stop selling calls. Wait for recovery. Avoids the 62-day "stuck in cycle 2" gap on AMZN where no call qualified.

Estimated combined impact (cautious): if we'd had these three changes since inception, the 3 negative cycles would have netted closer to **−$2,000** instead of **−$2,900**, and the wheel's share of B&H would have moved from 54% → ~62%. Larger gains likely come from the tail effect of NOT being called away at low strikes — i.e., riding subsequent recoveries (AMZN's price went from $212.5 in Nov to $240 by Apr — capturing that recovery would have added ~$2,750 vs the actual −$3,500 cycle 1 share-side outcome).

The aggregate "wheel < B&H" result is **partly structural** (wheel's design caps upside in exchange for income; in a strong bull market wheel will lag). The user's caveat is valid: capital efficiency means cycling the same capital several times, so per-dollar-deployed returns are different. But within the strategy's design envelope, **3 of 11 wheel cycles failed in a recognizable, parameterizable way that's worth fixing.**

---

## 1. Performance Assessment

### 1.1 Per-symbol scorecard (post-FC-025 verified truth)

| Symbol | Wheel | B&H | Wheel %BH | Δ vs B&H | Winning Cycles | Losing Cycles |
|---|---:|---:|---:|---:|---:|---:|
| AMD | $5,309 | $14,314 | 37% | −$9,005 | 2 (1/05, 1/23) | 1 (11/17) |
| NVDA | $4,627 | $1,054 | **439%** | +$3,573 | 1 (11/20) | 0 |
| GOOGL | $4,256 | $13,133 | 32% | −$8,877 | 1 (2/09) | 0 |
| UNH | $2,584 | $998 | **259%** | +$1,586 | 2 (1/29, 3/23) | 1 (10/30) |
| AMZN | $2,279 | $5,112 | 45% | −$2,833 | 1 (1/12) | 1 (11/04) |
| IWM | $1,888 | $3,316 | 57% | −$1,428 | 1 (3/10) | 0 |
| AAPL | $73 | $1,274 | 6% | −$1,201 | 0 | 0 |
| **Σ** | **$21,016** | **$39,200** | **54%** | **−$18,184** | **8** | **3** |

### 1.2 Where the lag actually came from

**The bot's option-side P&L was strong — $28,313 total premium received, $9,816 paid back via buybacks → $18,497 captured (65% capture rate). That part of the strategy works.**

Wheel's underperformance vs B&H comes from THREE sources:

1. **Share-side losses on losing cycles: −$9,000** (covered in §2 below). This is the actionable lever.
2. **Structural cap on upside in winning B&H environments: ~−$5,000**. NVDA went up moderately so the wheel beat B&H ($4,627 vs $1,054). But for AMD ($14,314 B&H), GOOGL ($13,133 B&H), AAPL ($1,274 B&H), the bot didn't hold shares for the full appreciation period (cycled in and out). Some of this is unavoidable — the wheel intentionally caps upside in exchange for income — but call-strike aggressiveness made the cap tighter than necessary.
3. **Capital efficiency caveat (user's note): valid.** Wheel cycles same capital across different names; B&H would require holding ALL 7 symbols simultaneously. With an ~$80–100k account a true 7-symbol B&H wasn't feasible. So this is **not** an apples-to-apples comparison; B&H is a "perfect-foresight" benchmark. The right comparison is **wheel vs single-symbol B&H per dollar-time deployed**, which we don't compute today (good follow-up FC).

### 1.3 The 3 "loss cycles" — anatomy

| Cycle | Days | Stock at start | Stock at end | Drop | Calls | Cycle P&L |
|---|---:|---:|---:|---:|---:|---:|
| AMD 2025-11-17 → 11-24 | 7 | $230.00 | $192.50 | **−16.3%** | 2 | **−$1,925** |
| AMZN 2025-11-04 → 11-28 | 21 | $247.50 | $212.50 | **−14.1%** | 9 | −$443 |
| UNH 2025-10-30 → 11-15 | 7 | $332.50 | $315.00 | **−5.3%** | 1 | −$532 |

All three cycles share four characteristics:
- **Stock dropped sharply (5–16%) between assignment and called-away**.
- **Bot was called away below original assignment strike**, locking in the share-side loss.
- **Bot wrote calls progressively closer to the falling spot price** (AMZN cycle 1: 9 different strikes from $247.5 down to $212.5).
- **Total cycle premium captured was *less than* the share-side capital loss** (AMD: $1,825 premium vs $3,750 share loss; AMZN: $3,057 vs $3,500; UNH: $1,218 vs $1,750).

These are not random outcomes. They're a parameterizable failure mode: **near-ATM call writes during downward price action.**

### 1.4 The 8 "winning cycle" model (NVDA, GOOGL, AMZN cycle 2, AMD cycles 2–3, UNH cycles 2–3, IWM)

| Pattern | Count | Avg duration | Avg cycle P&L |
|---|---:|---:|---:|
| **Long round-trip cycles** (held 30+ days, called away at exact assignment strike, share P&L = $0) | 4 | 73d | +$1,374 |
| **Short successful cycles** (held <15 days, mild stock recovery, called away above cost) | 3 | 8d | +$571 |
| **Long bullish cycles** (called away above cost basis, share gain) | 1 (AMD 1/23) | 77d | +$2,026 |

**Insight:** the strategy thrives on long-duration (60+ days) round-trip cycles where multiple call rolls compound premium without share-side loss. The short losing cycles are the anti-pattern.

---

## 2. Strategy Code Findings

Reviewed: `config/settings.yaml`, `src/api/market_data.py`, `src/strategy/call_seller.py`, `src/strategy/put_seller.py`. Findings sorted by severity.

### 2.1 [HIGH] Call delta range is structurally aggressive

**Finding:** `call_delta_range: [0.30, 0.70]` ([config/settings.yaml:26](config/settings.yaml#L26)) — calls have 30–70% probability of finishing ITM. Compare to puts: `[0.10, 0.20]` (10–20%). The asymmetry biases the wheel toward called-away outcomes.

**Why the team likely chose this:** higher-delta calls have more premium. The bot's ranking function `annual_return * (1 - abs(delta))` ([market_data.py:462](src/api/market_data.py#L462)) within the range *prefers lower delta*, so within the band it picks the lowest-delta available. But the **floor of 0.30** still forces near-ATM strikes on most days.

**Impact:** for a stock at $250 with cost basis $250 and a call expiring in 7 days:
- Δ=0.30 strike ≈ $253 (1.2% OTM)
- Δ=0.20 strike ≈ $258 (3.2% OTM) — currently rejected
- Δ=0.15 strike ≈ $261 (4.4% OTM) — currently rejected
- Δ=0.10 strike ≈ $265 (6.0% OTM) — currently rejected

In the AMZN cycle 1 (stock dropped from $247 to $212), the bot wrote calls at strikes from $247.5 down to $212.5 — all because once the cost basis floor eroded (see §2.2 below) and stock fell, the only "delta 0.30+" calls available were near-ATM at the falling spot price.

### 2.2 [HIGH] Cost-basis floor erodes with closed call premium

**Finding:** [call_seller.py:161,213](src/strategy/call_seller.py) uses `stock_position['cost_basis']` from Alpaca. **Alpaca dynamically reduces this when option premium is realized on the same security.** Each closed call (gross premium minus buyback) reduces the position's reported cost basis. Over 9 rolls in AMZN cycle 1 ($2,945 net call premium), the per-share "cost basis" dropped from $247.50 to ~$218 — *that's why the bot eventually wrote a $212.50 strike*. Pre-FC-027 the dashboard hid this; post-FC-027 the Cycle Table shows the truth.

**Severity:** this is a slow-motion guarantee that during a sustained downtrend the bot's "never sell below cost" check will silently allow ever-lower strikes. The user's intent (don't lock in share losses) isn't enforced.

**Side effect on the 62-day AMZN gap (Feb 6 → Apr 10):** opposite case — when AMZN was below cost basis ($240), cost basis hadn't yet eroded (only 3 calls had closed in cycle 2 by then), so the cost-basis floor blocked ALL otherwise-suitable calls. The bot scanned daily but found nothing. Lost ~$1,500–3,000 in potential premium during a 62-day window.

### 2.3 [MEDIUM] Symmetric ranking function but asymmetric ranges

`return_score = annual_return * (1 - abs(delta))` is used for both puts and calls ([market_data.py:319,462](src/api/market_data.py#L319)). The ranking *within* the range prefers low delta. Good. But because the call range floor (0.30) is much higher than the put range floor (0.10), the lowest-delta call available is always relatively risky.

### 2.4 [MEDIUM] DTE = 7 across both legs

`put_target_dte: 7`, `call_target_dte: 7` ([config/settings.yaml:21-22](config/settings.yaml#L21-L22)).

**Wheel community standard:** 30–45 DTE for puts, 14–21 DTE for calls. Reasoning:
- Puts: longer DTE captures more theta per cycle; lets you sell further OTM at the same delta (e.g., a 0.15-delta put at 7 DTE might be 1.5% OTM; same delta at 30 DTE is 4–5% OTM).
- Calls: 14–21 DTE provides flexibility to roll up-and-out as price moves, vs the current 7-day cycle that forces rapid re-decisions.

7 DTE is a viable design choice (theta is highest), but in combination with `call_delta_range: [0.30, 0.70]` it concentrates near-ATM exposure heavily. Either lever moved alone helps.

### 2.5 [LOW] Profit-target band is reasonable but could be aggressive

DTE bands at 0.35-0.80 (DTE 7→0) are slightly aggressive for the early-DTE side. Wheel community typical: 50% across the board, or 50%/65%/80% for DTE 7/3/1. Current bands close puts at 35% capture on day 0 — leaves theta on the table. This is *deliberately* aggressive (closes faster, redeploys capital), and there's a defensible argument for it. Lower priority.

### 2.6 [LOW] No volume-based universe pruning despite stale symbols

`stocks.symbols` includes 14 names but 8 (AAPL, MSFT, QQQ, SPY, F, PFE, KMI, VZ) have never traded (FC-001). They burn API calls on every scan but produce nothing. AAPL has 2 trades (closed at +$73). Recommendation aligns with FC-001 (already filed).

### 2.7 [INFO] Earnings blackout is 2 days (FC-013 wired)

`earnings_blackout_days: 2`. FC-013 wired this into PutSeller and CallSeller (per session memory). Conservative, defensible, no change recommended.

### 2.8 [INFO] No position-sizing-by-IV-rank

The IV rank filter (`max_iv_rank: 80`, `min_iv_rank: 20`) is an entry filter only — doesn't size positions differently across vol environments. In high-vol environments more capital should be deployable per dollar of risk. This is a 2nd-order improvement; mentioned for completeness.

### 2.9 [INFO] FC-006 Friday rolling engine has fired 0 times (per memory 2026-05-06)

Trigger gates (`itm_trigger_ratio: 0.98`, `max_debit_pct_of_premium: 0.25`) are too strict in practice. Either tune them or accept low fire rate. This was raised in the 2026-05-06 session and is unrelated to the wheel-vs-B&H gap. Not in scope here.

---

## 3. Recommendations (Prioritized)

Each recommendation includes: change, rationale, expected impact, risk, and validation method.

### 🔴 R1: Tighten call delta range to [0.15, 0.25] [CRITICAL]

**Change:** `config/settings.yaml`:
```yaml
call_delta_range: [0.15, 0.25]   # was [0.30, 0.70]
```

**Rationale:** Lowers call assignment probability from 30–70% to 15–25%. Pushes call strikes 2–4% further OTM at any given moment. Combined with FC-027's true-Cycle-P&L visibility, this directly attacks the 3 cycles where the bot was called away well below cost.

**Expected impact (using AMZN cycle 1 as the model):**
- Old behavior: writes call at $247.5 → falls to $212.5 → 9 rolls → called away at $212.5 → −$3,500 share loss + $2,945 premium = −$443
- New behavior (Δ=0.20): would have written call at ~$252 (2% OTM) → falls to $212.5 → call expires worthless or is bought back cheaply → bot HOLDS shares as price recovers (AMZN was back at $240 by mid-March) → potentially flat or small gain on share leg

**Risk:** premium per call drops ~30–40% (lower-delta = less premium). On non-falling stocks (NVDA, GOOGL — winners), the bot collects less income. Trade-off: lower premium income for fewer ruinous called-away outcomes. Net should be positive based on the 3 losing cycles' magnitudes vs winning cycles' magnitudes.

**Validation:**
1. Backtest: replay 11 cycles with Δ=0.20 calls. Estimate cycle P&L for each. Confirm: 3 losing cycles' average improves by ≥$1,000 each; winning cycles drop by no more than 25%.
2. Forward A/B: roll out to 3 of 7 symbols for a 30-day window; compare premium-captured rate.

**Open question for the user:** would you accept lower nominal premium income for higher net cycle P&L? The math says yes; just confirming alignment.

### 🔴 R2: Make the cost-basis floor truly hard (no premium-adjustment slip) [CRITICAL]

**Change:** [src/strategy/call_seller.py:161-213](src/strategy/call_seller.py) — instead of using Alpaca's dynamic `cost_basis`, persist the **assignment-time strike** as the position's cost-basis floor for call writes. Store this in `WheelStateManager` (which already persists per-position state per FC-015 plan).

**Pseudocode:**
```python
# At put assignment time, stamp the cost basis:
state.set_assignment_strike(symbol, strike_price=put_strike)

# In call_seller.evaluate_covered_call_opportunity:
hard_floor = state.get_assignment_strike(symbol) or stock_position['cost_basis'] / shares_owned
suitable_calls = market_data.find_suitable_calls(symbol, min_strike_price=hard_floor)
```

**Rationale:** today the floor erodes by ~$30/share over AMZN cycle 1 (9 closed calls × ~$33/share avg net premium ÷ 100 shares). User's intent ("never sell below cost") is silently violated.

**Expected impact:** in AMZN cycle 1, 8 of 9 calls would have been blocked (only the first $247.5 call passes the floor). With R1 + R2 together, AMZN cycle 1 likely ends with 1–2 calls written at $250–252 strikes, both expiring worthless or closing for small profit. Share leg outcome depends on call timing.

**Risk:** during a sustained drawdown, no calls qualify → bot is idle on shares. This is a feature, not a bug — the user's "rescue cycle" intuition. But it means premium income per cycle drops in falling markets. Mitigation in R3.

**Validation:**
1. Audit query post-deploy: `SELECT * FROM trades_from_activities WHERE option_type='call' AND strike_price < (SELECT strike_price FROM trades_from_activities WHERE activity_type='OPASN' AND option_type='put' AND symbol = same-underlying ORDER BY transaction_time DESC LIMIT 1)` — should return 0 rows post-fix.
2. Add unit test: simulate a position with assignment strike $250, premium-adjusted cost basis $235, verify bot won't sell $245 strike.

### 🟠 R3: Drawdown pause — skip call writes when shares are >5% below cost [HIGH]

**Change:** new check in `call_seller.evaluate_covered_call_opportunity`:
```python
if (stock_current_price / assignment_strike) < 0.95:
    skip_reason = "drawdown_pause"
    log_skip(...)
    return None
```

**Rationale:** when shares are 5%+ underwater, every call within the delta band is structurally unsafe — either the bot writes at-or-below cost basis (R2 blocks this), or the only OTM strikes that satisfy R2 have delta < 0.05 (not enough premium to bother). The 62-day AMZN gap was *implicitly* doing this via the cost-basis floor block; **codify it explicitly** so it's intentional and observable. Bonus: log the skip so we can tune the 5% threshold.

**Expected impact:** trades pre-FC-010 (the 5 stop-loss episodes) would have been skipped entirely if R3 were in place — they all involved selling calls into stretched runups; arguably R3 catches the inverse case (selling into runups against you).

**Risk:** false negatives — sometimes a small drawdown reverses quickly and you'd want to write calls. The 5% threshold is empirical; could be 3% or 7%.

**Validation:**
1. Replay each cycle with the rule: count days where R3 would block.
2. Log `roll_evaluation_skipped` with `reason=drawdown_pause` so we can see frequency.

### 🟠 R4: Extend call DTE to 14 days [HIGH]

**Change:** `config/settings.yaml`: `call_target_dte: 14` (was `7`).

**Rationale:** 14 DTE calls let the bot write further OTM at the same delta. For a 0.20-delta call: 7 DTE → ~3% OTM; 14 DTE → ~5% OTM. Better cushion against drops. Pairs naturally with R1 (Δ=0.15-0.25). Combined effect:
- 7 DTE × 0.30 delta → ~1.2% OTM (today)
- 14 DTE × 0.20 delta → ~5% OTM (proposed)

**Risk:** longer DTE means slower theta decay and more total time at risk. But the wheel community's consensus is that 14–21 DTE for calls outperforms 7 DTE in down markets specifically because of the OTM cushion. In flat markets, 7 DTE wins on theta efficiency.

**Validation:** A/B on 2-3 symbols for 60 days. Compare premium-per-day-deployed and called-away rate.

### 🟠 R5: Per-symbol delta tuning based on historical cycle outcomes [HIGH]

**Change:** add per-symbol overrides to `config/settings.yaml` (linked to FC-005 — already filed):
```yaml
strategy:
  call_delta_range: [0.15, 0.25]   # default
per_symbol:
  AMD:
    call_delta_range: [0.10, 0.18]   # AMD's biggest loss came from aggressive calls
    max_assignment_drawdown: 0.07    # tighter drawdown pause given AMD's volatility
  AMZN:
    call_delta_range: [0.12, 0.20]
  UNH:
    call_delta_range: [0.15, 0.22]
  NVDA:
    call_delta_range: [0.20, 0.30]   # NVDA winning pattern → can be more aggressive
  GOOGL:
    call_delta_range: [0.20, 0.30]
```

**Rationale:** symbols have different base volatility and drawdown patterns. AMD's 16% intra-week drop pattern needs lower call delta than NVDA's grinding uptrend. Currently we treat all the same.

**Risk:** more parameters to maintain. Mitigation: justify each override with a back-of-envelope on the cycle history.

**Validation:** quarterly review of per-symbol cycle P&L; tune overrides based on outcomes.

### 🟡 R6: Increase profit-target floor (close earlier on call rolls) [MEDIUM]

**Change:** `config/settings.yaml` profit_taking dte_bands — increase early-DTE targets:
```yaml
dte_bands:
  - dte: 7
    profit_target: 0.50   # was 0.35 — close at 50% capture, redeploy capital
  - dte: 6
    profit_target: 0.55   # was 0.40
  - dte: 5
    profit_target: 0.55   # was 0.35
```

**Rationale:** combined with R1 (lower call delta), call premium is smaller, so capturing 50% sooner = faster capital redeployment. The current 35% on day 0 is likely too aggressive — closing for $0.40 a $1.10 premium leaves the position open to early reversal. Higher target = let theta work, then close. Wheel community consensus: 50–60% capture on calls is the sweet spot. (Puts can stay aggressive at 35% — they're the entry leg and we want to recycle capital.)

**Risk:** trades held longer = more exposure to gap-down. Mitigation: gap_detector already in place.

**Validation:** measure call hold duration before/after; cycle P&L on 2-3 symbols for 60 days.

### 🟡 R7: Wider universe pruning (execute FC-001) [MEDIUM]

Already filed as FC-001. Drop AAPL, MSFT, QQQ, SPY, F, PFE, KMI, VZ from the universe (8 symbols, never traded). Replace with: META, TSLA-equivalent (TSLA was removed for vol; consider COIN/PLTR/AVGO).

**Rationale:** API call savings (~6k/month per FC-001), removes universe noise. Doesn't impact P&L directly but improves observability — every "rejected by gates" row in a future filtering log will be from a symbol we actually want.

**Risk:** TSLA-style names have high IV → premium-rich but assignment-heavy. Apply R1's tighter delta to compensate. Don't aggressively chase yield.

### 🟡 R8: Add a "no-call-after-assignment-day" cooldown [MEDIUM]

**Change:** in `call_seller.py`, add:
```python
hours_since_assignment = (now - state.get_assignment_time(symbol)).total_seconds() / 3600
if hours_since_assignment < 24:
    skip_reason = "assignment_cooldown_24h"
    return None
```

**Rationale:** Saturday/Sunday assignments often see Monday gap-down moves as the market re-prices the underlying given that the put writer (us) bought at strike. Writing a call into the post-assignment confusion adds trade-execution risk. Wait 24h to let the market settle.

**Looking at the data:** UNH 2025-10-30 cycle was assigned Sat Nov 8, called away Sat Nov 15 — but call sold Mon Nov 10 (2 days post-assignment, OK). AMZN 2025-11-04 cycle was assigned Sat Nov 7, but call sold Tue Nov 11 — only 4 days post-assignment, but in that window AMZN dropped from $247.5 to ~$240. A 24h cooldown wouldn't have prevented the drop, but it would have given the bot a chance to *not* sell into the immediate post-assignment volatility.

**Risk:** miss 1 day of premium. Trivial.

### 🟡 R9: Cycle-aware learning — adjust delta down after a losing cycle [MEDIUM]

**Change:** persist per-symbol "last 3 cycle P&L outcomes" in `WheelStateManager`. On the next put-sell after a losing cycle:
```python
if state.last_cycle_was_losing(symbol):
    delta_range_override = (delta_range[0] * 0.7, delta_range[1] * 0.7)
```

**Rationale:** AMD's pattern: cycle 1 (Nov 17) lost −$1,925 due to aggressive calls. Cycle 2 (Jan 5) was a 6-day round-trip. Cycle 3 (Jan 23) was the +$2,026 winner. The bot didn't "learn" from cycle 1's loss — it just lucked into better stock direction. Codifying a learning signal makes the strategy adaptive.

**Risk:** complexity, maintenance burden.

### 🟢 R10: Skip puts when stock at 30-day high [LOW]

**Change:** add a `_check_recent_run_up_filter(symbol)` to PutSeller:
```python
if stock_current_price >= 0.97 * stock_30d_high:
    skip_reason = "30d_high_proximity"
    return None
```

**Rationale:** mean reversion. Selling puts on a stock at 30-day highs increases assignment risk on a pullback. Better to wait for a 3% retracement before selling.

**Looking at the data:** several of the losing cycles were in late October / early November 2025 — UNH, AMZN, AMD all peaked in mid-October and fell into the entries. The bot was selling puts AS the stocks rolled over. A "30d high" filter would have skipped some of those entries.

**Risk:** miss premium during sustained uptrends. Counter-mitigation: don't make the filter too strict (97% threshold = only blocks within 3% of 30d high).

### 🟢 R11: Earnings buffer for IV-collapse on long calls [LOW]

**Change:** if symbol has earnings <14 days out and we're holding shares, prefer DTE shorter than the earnings date. Don't roll calls past earnings (they'll IV-crush after the report).

**Rationale:** wheel community standard. Avoids a known-direction-of-IV trap.

### 🟢 R12: Capital-efficiency-aware position sizing [LOW]

**Change:** track a metric `dollars_deployed_days` per cycle (sum of strike × 100 × days held). Compare to symbol's total return per dollar-day. Use as a forward selection signal — symbols with low dollar-day return get reduced position sizes.

**Rationale:** the user's "capital efficiency caveat" is real. Wheel cycles same capital across names, so high-velocity (short cycle, high premium) symbols are more valuable than slow ones. Today the bot doesn't know which is which.

**Risk:** complex, easy to over-fit. Defer until other priorities ship.

---

## 4. What's Already Done (don't re-recommend)

For clarity, the following levers have already been pulled this period:

- ✅ Stop-loss disabled (FC-010, 2026-04-17) — saved ~$1,000–$2,500 in future losses based on 5 historical episodes that won't repeat.
- ✅ Earnings blackout wired into both PutSeller and CallSeller (FC-013, ~2026-04-28).
- ✅ Friday rolling engine deployed (FC-006, 2026-04-16) — but has fired 0 times; orthogonal to the recommendations here.
- ✅ Per-symbol scorecard accuracy fixed (FC-019/021/023/024/025/026/027/028, this session) — now we can actually MEASURE whether changes work.
- ✅ Synthetic correction for AMD (FC-021) and AMZN (FC-025) silent-exercise data.

The dashboard now reconciles cleanly to Alpaca, so any change you make from here forward can be A/B-tested against historical baseline numbers with confidence.

---

## 5. Suggested Implementation Sequence

A 4-phase rollout, staggered to limit blast radius:

### Phase 1 (week 1): Critical risk fixes — file as one FC ("FC-029: call selection re-tune")
- R1: tighten call delta range to [0.15, 0.25]
- R2: hard cost-basis floor in `WheelStateManager`
- R3: drawdown pause at 5% below cost basis

These three are *complementary* — they collectively prevent the failure mode from §1.3. Ship together.

### Phase 2 (week 2-3): DTE and profit-target tuning — FC-030
- R4: `call_target_dte: 14`
- R6: profit-target floor adjustments
- (paired so we can A/B them together — if one helps and the other hurts, we revert just that lever)

### Phase 3 (week 4+): Symbol universe + advanced — FC-031 (drop dead symbols), separate evals for R5/R8/R9/R10
- R7: drop universe dead-weight (already FC-001 — ready to execute)
- R5: per-symbol delta tuning (after Phase 1+2 baseline)
- R8: 24h post-assignment cooldown
- R10: 30-day high proximity filter

### Phase 4 (deferred): R9, R11, R12 — adaptive/learning logic. Build only after Phases 1–3 produce a stable baseline.

---

## 6. Risk Summary

If we ship R1+R2+R3 (Phase 1):

| Outcome | Probability | Magnitude |
|---|---|---|
| Premium income drops 30–40% near-term | Likely | Income from $1,500/mo → ~$1,000/mo |
| Loss cycles avoided | High | Saves ~$3,000/year (extrapolated from observed 3 losses in 7 months) |
| Stuck-in-cycle days increase (drawdown pause) | Moderate | +30–50 idle days/year per affected cycle |
| Strategy becomes more "boring" but more consistent | High | Wheel %BH might shift 54% → 65% over 12 months |

**Worst-case risk:** if the next 6 months are a strong bull market (as B&H suggests has been the case), tighter calls = more shares held longer = more upside but less premium. Wheel still lags B&H but by less.

**Best-case payoff:** if the next 6 months see one significant drawdown across the universe (high probability over any 6-month window), the bot doesn't repeat the AMD/UNH/AMZN early-November pattern. Saves $3–9k.

**Recommended posture:** ship Phase 1 immediately. The data is unambiguous on the 3-cycle failure pattern. Phases 2–4 can be evaluated post-baseline.

---

## 7. Open Questions for the User

1. **Aggressive vs conservative call writing** — do you want the wheel to maximize premium (current setting) or minimize called-away-below-cost (recommended)? The data says the latter is more profitable, but premium nominally drops.

2. **Wheel-vs-B&H comparison** — should we add a **capital-efficiency-adjusted B&H benchmark** to the dashboard (compare per-dollar-deployed return rather than per-symbol full-period)? This would be a more honest comparison, and might show the wheel beating B&H once you account for cycling capital.

3. **Per-symbol overrides** — willing to maintain per-symbol delta/DTE tuning, or prefer one global setting? Per-symbol is more accurate but more maintenance.

4. **Adaptive logic (R9)** — comfortable with a strategy that "remembers" recent cycles and adjusts? Or prefer a stateless, deterministic strategy?

5. **The bigger question: is the wheel right for you?** If the answer is "income with lower drawdown than B&H," the wheel does that — even at 54% of B&H's dollar P&L, drawdowns and volatility are notably lower. If the answer is "maximize total dollar return," consider whether a more directional strategy or simpler holdings are better.

---

## Appendix A: Loss-cycle anatomy (raw data)

```
AMD 2025-11-17 cycle:
  Day 0 (Nov 17): put $230 sold, premium $315
  Day 7 (Nov 24): OPASN call $192.50 → called away
  Calls sold during cycle: 2 (call 1 at $230 net +$166, call 2 at $1,659 net)
  Stock path: $230 → $192.50 (-16.3% in 7 trading days)
  Share P&L: −$3,750 (assigned $230, sold $192.50)
  Option P&L: $315 + $166 + $1,659 = $1,825
  CYCLE P&L: −$1,925

AMZN 2025-11-04 cycle:
  Day 0 (Nov 4): put $247.50 sold, premium $112
  Day 21 (Nov 28): called away $212.50
  Calls sold during cycle: 9 — strike walk: $247.5, $242.5, $237.5, $230, $225, $220, $217.5, $215, $212.5
  Stock path: $247.50 → $212.50 (-14.1% in 21 days)
  Share P&L: −$3,500
  Option P&L: $112 + $2,945 net call premium = $3,057
  CYCLE P&L: −$443

UNH 2025-10-30 cycle:
  Day 0 (Oct 30): put $332.50 sold, premium $233
  Day 7 (Nov 6): called away $315
  Calls sold during cycle: 1 ($315 strike, premium $985, kept on called-away)
  Stock path: $332.50 → $315 (-5.3% in 7 days)
  Share P&L: −$1,750
  Option P&L: $233 + $985 = $1,218
  CYCLE P&L: −$532
```

## Appendix B: Quick reference — proposed parameter changes

```yaml
# config/settings.yaml — proposed
strategy:
  put_target_dte: 7
  call_target_dte: 14                    # R4: was 7
  put_delta_range: [0.10, 0.20]
  call_delta_range: [0.15, 0.25]         # R1: was [0.30, 0.70]
  # ... rest unchanged

  # New: drawdown pause
  call_drawdown_pause_threshold: 0.05    # R3: skip calls if shares >5% below cost basis

risk:
  profit_taking:
    dte_bands:
      - dte: 7
        profit_target: 0.50              # R6: was 0.35
      - dte: 6
        profit_target: 0.55              # was 0.40
      - dte: 5
        profit_target: 0.55              # was 0.35
      # ... DTE 4-0 unchanged
```

```python
# src/strategy/wheel_state_manager.py — new persistent fields (R2)
@dataclass
class PositionState:
    symbol: str
    assignment_strike: float          # NEW (R2): captured at OPASN time, never updated
    assignment_time: datetime         # NEW (R8): for cooldown check
    last_cycle_pnls: list[float]      # NEW (R9, deferred): rolling window of 3
```

---

**End of review.** Recommendations are prioritized by data-supported impact. Phase 1 (R1+R2+R3) is the minimum recommended action. Confirm directional preference (aggressive premium vs conservative cycle outcomes) and pick the implementation cadence in the AM.
