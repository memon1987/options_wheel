# Future Considerations

A running list of things we want to **research and write a plan for** before coding. This file is a **precursor to todos**, not a todo list itself. Entries here are ideas and open questions — they become actionable only after a plan file is published in `docs/plans/`.

## Lifecycle

```
1. Consideration  →  added here, loosely scoped, questions open
2. Research        →  investigation, data gathering, comments, alternatives
3. Plan published  →  a file in docs/plans/<slug>.md with the agreed approach
4. Execution       →  code changes are made against the plan
5. Archived        →  moved to "Completed" below with a link to the plan + PR
```

**Rule of thumb:** nothing graduates from this file into code until step 3 is done. See `docs/CLAUDE.md` ("Plan-First Development") for the enforcement rule.

---

## Entry template

Copy this when adding a new consideration. Keep it short — detail belongs in the eventual plan file, not here.

```markdown
### FC-NNN: <short title>

**Status:** Consideration | Researching | Plan drafted | Plan published | Executing | Done
**Size estimate:** S | M | L  (M/L require a plan file before code changes)
**Owner:** <who is thinking about this>
**Plan file:** `docs/plans/<slug>.md` (once published)

**Problem / opportunity:** 1–3 sentences on what prompted this.

**Open questions:**
- ...
- ...

**Links:** related evals (`PERFORMANCE_EVAL_CATALOG.md#EVAL-XXX`), issues, PRs, logs.
```

---

## Active Considerations

### FC-001: Symbol universe optimization

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Several configured symbols never trade — they burn ~6k API calls/month and slow scans. Before removing them or adding replacements, we need a plan covering rollout, monitoring, and reversion.

> **Premise corrected 2026-07-18.** The original entry listed 8 never-traded symbols including AAPL and MSFT. **Both now trade**: AAPL 11 trades since 2026-04-28 (assigned at $305 on 6/13), MSFT 6 trades since 2026-06-16 (assigned at $382.50 on 6/23) — they were below the price filter when this entry was written and have since come into range. The actual dead weight is **6 symbols: QQQ, SPY, F, PFE, KMI, VZ** (zero trades ever). FC-032's coverage work separately found F/PFE/KMI/VZ **structurally** untradeable (0 usable days — the $0.50 premium floor, not a data gap), which is a stronger argument for removal than "hasn't traded yet". Note SPY now appears in `stock_history_from_alpaca` as the FC-031 benchmark/trading-calendar symbol — that is ingest-only and does not make it a trading candidate.

**Open questions:**
- Remove the 6 dead-weight symbols in one change or stage it? (F/PFE/KMI/VZ have a structural justification; QQQ/SPY are price-filter exclusions.)
- Which replacement candidates (META, TSLA, COIN, PLTR) clear our filters in a backtest?
- Do we raise `max_stock_price` from $400 to bring QQQ/SPY into range? (AAPL/MSFT resolved themselves without a config change.)
- How do we validate the change hasn't reduced premium throughput?
- Should this merge into FC-032's wheel-fitness evaluation rather than stand alone? The backtesting overhaul is building exactly the machinery to answer "which symbols deserve capital".

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-010; FC-032 (wheel-fitness evaluation — overlapping scope).

---

### FC-002: AMD gap-risk filter re-tuning

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** AMD is our top premium generator but is gap-filtered on 47% of scans (262 of 553). Filter thresholds may be over-conservative for this symbol. A plan needs to weigh actual realized overnight gaps against the threshold and consider per-symbol tuning vs. a global change.

**Updated 2026-07-18 (FC-032 engine walkthrough):** the binding constraint is broader than AMD and broader than gap *frequency*. NVDA was blocked on 18 of 20 decision days in Jun–Jul 2026 by the **40% realized-vol cap** (`max_historical_vol`) — its 30-day vol sat at 40–42%, so trading was noise around one hard line; the single day vol dipped to ~40% it traded. Validated against live: production also sold zero NVDA puts that window. Structural critique: the filter double-counts risk that delta-band strike selection already prices (IV rises → strikes auto-walk OTM → richer premium), is a binary cliff with no graduated response, and embargoes the top premium generators exactly when compensation is highest. **The A/B study to answer this empirically is Track B1 of `docs/plans/fc-042.md`** (filter off / vol-cap sweep / vol-relative percentile / half-size-instead-of-ban); any threshold change then gates on this FC's own plan + two reviewers. Note stage-4's execution gap check is dead (FC-036), so this filter is currently the *only* functioning gap control — do not simply disable it.

**Updated 2026-07-29 — B1 study published, and it reframes this entry. See
`docs/investigations/fc-002-gap-filter-ab.md`.** Four corrections, in order of consequence:

1. **The filter is not wired into the live trading path and has never gated a live trade**
   (filed as **FC-048**). Every block rate quoted above — this entry's and FC-036's —
   describes the *backtest engine*. Whether to gate at all is now the prior question;
   tuning a threshold nothing reads is a no-op.
2. **"47% of scans" is stale.** Reconstructed over the same bars, AMD is blocked on **94.4%**
   of sessions 2024-02→2026-07 and **100% of the 201 sessions in the live-fills window** —
   all by the gap-**frequency** leg, not the vol cap. AMD's median 34-session vol there is
   0.735.
3. **The vol-cap diagnosis is half right.** Confirmed for NVDA in Jun–Jul 2026 (35 of 38
   sessions blocked, all by the vol cap, vol 0.387–0.459 against a 0.400 line). But over the
   full window NVDA's two legs bind almost equally (52.9% vol-alone vs 51.3% frequency-alone),
   and on AMD frequency is the binding leg. A vol-only sweep would leave AMD untradeable.
4. **`vol_lookback_days: 252` is dead config** — nothing reads it. Both legs are computed
   over `gap_lookback_days + 20` = 50 **calendar** days ≈ 34 sessions.

**On the evidence, the filter is anti-selective in this window:** of 327 real entries, the
123 it would have blocked earned **$70.66/entry** against **$55.94** for the 204 it would
have allowed ($8,691 forgone, 43% of net realized); on 2,329 synthetic daily entries blocked
days out-earn allowed days on 4 of 4 symbols, both IV models, ±20% premium. Caveats stated
prominently in the study: one bull-market regime, no vol shock, and — per **FC-048** — the
study's *engine* arms are put-only and are therefore supporting evidence at most. The real-fills
and overlay layers, which carry the conclusion, are unaffected by FC-048. **Recommendation:
do not re-tune thresholds; resolve FC-049 first.** The one arm worth carrying forward is
graduated response (delta band → [0.10, 0.15] instead of a ban), **contingent on a re-run
after FC-048 is fixed** — its support is engine-only, and its "half size" variant is
impossible at `put_seller.py`'s hard-coded `contracts = 1`.

**Open questions:**
- ~~What's the distribution of AMD's actual overnight gaps vs the current filter?~~ Answered.
- Do we support per-symbol gap thresholds, or keep one global? *Still open — and now
  secondary to FC-048.*
- How do we avoid over-fitting to AMD's recent history? *Partly addressed: the study's
  pre-registration requires any proposal to hold its sign on 3 of 4 symbols.*
- **New:** should the gap-frequency leg exist at all? A >2% overnight move on a 40-vol name
  is a typical day, not a tail, and that leg is what makes AMD permanently untradeable.

**Links:** `docs/investigations/fc-002-gap-filter-ab.md`, `tools/diagnostics/fc002_gap_filter_ab.py`,
FC-048, FC-036, `PERFORMANCE_EVAL_CATALOG.md` EVAL-010, `docs/analysis/AMD_GAP_RISK_ANALYSIS_2025.md`.

---

### FC-003: DTE target optimization (7 → 2–3?)

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Current 7 DTE target may be suboptimal. Shorter DTE has higher per-trade ROI but potentially higher assignment risk. A change here touches strategy config, risk thresholds, profit-target DTE bands, and scan cadence.

**Open questions:**
- Does 2–3 DTE net ROI (after assignment losses) actually beat 7 DTE?
- Do profit-target bands need to be re-tuned for the new DTE?
- Do we ramp via A/B (some symbols at 3 DTE, others at 7) or flip the whole universe?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-004, EVAL-002.

---

### FC-004: Autonomous eval-driven parameter tuning

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `PERFORMANCE_EVAL_CATALOG.md` describes a scheduled runner + results storage + threshold checker + config proposer + human-in-the-loop gate. This is a multi-component build that needs a plan before any code lands.

**Open questions:**
- What's the minimum viable first eval to automate (EVAL-011 share-commitment verification is the highest-safety candidate)?
- Where does the scheduled runner live (Cloud Scheduler + Cloud Run job, or inline with the strategy?)
- What schema for the `eval_results` audit table?
- What are the hard per-parameter safety bounds?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` "Future Automation Architecture" section.

---

### FC-005: Per-symbol strategy parameters

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Low-priced symbols (F, PFE, KMI, VZ) fail the global `min_put_premium` because their option premiums are structurally smaller. Either remove them or support per-symbol DTE/premium overrides. Touches config schema, filter code, docs, tests.

**Open questions:**
- Do we actually want these low-priced symbols, or is it simpler to drop them (see FC-001)?
- Config shape: per-symbol overrides map, or a tier system?
- How does this interact with the gap-risk controls (FC-002)?

**Links:** `PERFORMANCE_EVAL_CATALOG.md` EVAL-007, EVAL-010.

---

### FC-009: Duplicate early_close_executed (revised 2026-04-24 post-FC-012)

**Status:** Consideration (scope clarified, not narrowed)
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Original problem:** The bot logs `early_close_executed` multiple times (4-10 duplicates) for the same position when the close order doesn't fill quickly. The `_closed_today` dedup set in `cloud_run_server.py` is in-memory and resets on Cloud Run cold starts. Each monitor invocation on a fresh instance re-evaluates the position, finds it still meets the close criteria, and places another close order.

**What FC-012 changed:** the dashboard no longer reads from the structlog-sourced `options_wheel.trades` table. Dashboard counts are from `trades_with_outcomes` (Alpaca FILLs, deduped on `activity_id`). So duplicate log entries no longer corrupt dashboard numbers. **But the bug is about duplicate *orders*, not logs — the dashboard migration doesn't fix the underlying mechanism.**

**What FC-010 did NOT change:** FC-010 only disabled the call **stop-loss** branch. Call profit-target early-closes and put profit-target early-closes still flow through the same shared code path (`deploy/cloud_run_server.py:694-776`) with the same in-memory dedup. FC-010 reduced the *frequency* of vulnerable events but not the *mechanism*.

**Paths currently exposed to the bug:**
- Put profit-target early-closes (never touched by prior fixes)
- Call profit-target early-closes (stop-loss portion was silenced by FC-010, profit-target portion unchanged)

**Why duplicate orders can actually happen:**
1. Monitor fires → `should_close_*_early()` returns True → check `_closed_today` (empty on cold start) → place buy-to-close order → add symbol to `_closed_today`.
2. Before the order fills, Cloud Run scales to zero.
3. Next monitor fires on a new instance → `_closed_today` is empty again → position still exists at Alpaca (short option) → `should_close_*_early()` still returns True (position still meets profit-target threshold based on mark) → second close order placed.
4. Both orders sit in Alpaca's queue. Depending on timing, one or both may fill.

**Remaining work:**
1. **Verify** via BQ query against `trades_from_activities`:
   ```sql
   SELECT symbol, COUNT(*) AS close_fills, COUNT(DISTINCT order_id) AS close_orders
   FROM `options_wheel.trades_from_activities`
   WHERE side = 'buy_to_close'
     AND transaction_time >= '2026-04-01'
   GROUP BY symbol
   HAVING COUNT(DISTINCT order_id) > 1
   ```
   If the query returns rows where `close_orders > 1` on the same symbol on the same day → real duplicate orders confirmed.
2. **Fix** the dedup so it survives cold starts. Two viable options:
   - Persist `_closed_today` to GCS alongside the existing wheel state.
   - Before placing a close order, check Alpaca for open buy-to-close orders on the same option symbol. Skip if one is already pending.

The second option is more robust — it handles the "Cloud Run instance crashed mid-cycle" case that even GCS persistence wouldn't catch cleanly. Small M-sized change.

**Links:** FC-010, FC-012. Relevant code: `deploy/cloud_run_server.py:694-776`, `src/strategy/put_seller.py:523` (`should_close_put_early`), `src/strategy/call_seller.py:536` (`should_close_call_early`).

---

### FC-013: Gate health audit & earnings blackout symmetry

**Status:** Plan published
**Size estimate:** M
**Owner:** Claude
**Plan file:** `docs/plans/fc-013.md`

**Problem / opportunity:** A GOOG put executed 2026-04-28 the day before Google's 2026-04-29 earnings. The FC-007 `EarningsCalendarService` exists and works, but is only wired into `CallRoller.should_roll()` — never into `PutSeller.find_put_opportunity()` or `CallSeller.evaluate_covered_call_opportunity()`. The FC-007 execution note acknowledged this deferral. A holistic gate audit also surfaced that `config.earnings_blackout_days`, `config.earnings_avoidance_days`, and `RiskManager.validate_new_position()` are all defined but never read/invoked. FC-013 wires earnings into both sellers, flips fail-open → fail-closed, removes the dead `earnings_avoidance_days` knob, and publishes `docs/gates.md` as a single source of truth for all gates.

**Open questions:** see plan file.

**Links:** FC-006, FC-007, `docs/CLAUDE.md` Wheel Strategy Symmetry Principle. Sibling FCs spun off from the audit: FC-014, FC-015, FC-016.

---

### FC-014: Wire RiskManager.validate_new_position() into sellers (or retire it)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `RiskManager.validate_new_position()` (risk_manager.py:23) is defined but **never invoked**. It contains portfolio-level checks — max total positions, max positions per stock, max exposure per ticker, min cash reserve, portfolio allocation — that today are partially duplicated in `wheel_engine._can_open_new_positions` and partially absent. Only `validate_roll()` is wired (from `CallRoller`). Either consolidate the put/call seller paths through `validate_new_position` (and dedupe the engine-level checks) or formally retire the method and document where each portfolio-level check actually lives.

**Open questions:**
- Consolidate (route puts/calls through `validate_new_position`) or retire (delete the method, ensure engine-level checks cover everything)?
- If consolidating, do the engine-level early checks stay as a fast-fail before scanning, with the seller-level call as the authoritative gate?
- Are `max_exposure_per_ticker` and `min_cash_reserve` actually checked anywhere today, or are they silently disabled?

**Links:** FC-013 Phase-1 audit, `risk_manager.py:23-120`, `wheel_engine.py:220-249`.

---

### FC-015: Centralize hold-period state in WheelStateManager (cold-start safe)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Both `PutSeller._entry_times` (put_seller.py:30) and `CallSeller._entry_times` (call_seller.py:32) are local in-memory dicts that do not survive Cloud Run cold starts. The `profit_taking_min_hold_hours` gate inside `should_close_*_early()` silently fails open when the dict is empty (no `entry_time` → loop falls through). This is the same class of bug as FC-009 (the `_closed_today` cold-start dedup issue). Persist `_entry_times` to GCS alongside the existing wheel state so the hold-period gate enforces correctly across cold starts and parallel cycles.

**Open questions:**
- Persist to GCS (existing `WheelStateManager` GCS layer) or query Alpaca for fill timestamps?
- Should this share infrastructure with FC-009's `_closed_today` fix or stay independent?
- What's the migration path for currently-held positions whose entry times are unknown?

**Links:** FC-009, `put_seller.py:30,378,544`, `call_seller.py:32,300,557`.

---

### FC-016: Test coverage for orchestration & account-level gates

**Status:** Consideration
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** The Phase-1 gate audit for FC-013 found ~0 unit-test coverage for orchestration STAGES 3/4/5/6/9 in `wheel_engine._find_new_opportunities` (max stocks evaluated per cycle, execution gap check, wheel state phase guard, existing position blocking, max new positions per cycle) and account-level gates (`_can_open_new_positions`: max total positions, minimum buying power). These gates run on every cycle but no test asserts they fire when their conditions are met. Add unit-test coverage for each gate's positive and negative paths.

**Open questions:**
- Test directly against `WheelEngine` with mocked Alpaca, or extract the gates into pure helpers first?
- Does coverage of the Cloud-Run-server market-open / strategy-lock gates belong here too, or in a separate FC?

**Links:** FC-013 Phase-1 audit, `wheel_engine.py:220-400`.

---

### FC-020: FIFO cycle pairing in wheel_cycles_from_activities

**Status:** Plan published
**Size estimate:** S-M
**Owner:** Claude
**Plan file:** `docs/plans/fc-020.md`

**Problem / opportunity:** After FC-019 landed, the per-symbol scorecard reconciles correctly to actual cash flow (sum of Total P&L ~= account growth, modulo small Alpaca-side data anomalies). But the per-cycle drilldown still has a pairing bug: when multiple put assignments happen on the same underlying before any are called away (overlapping share lots), the view pairs each assigned put to the earliest subsequent called_away, so two puts can both pair to the same called_away. The result: OPTRD events get summed into the wrong cycle window, inflating one cycle's `capital_gain` and treating another cycle as still open.

**Concrete example (AMD):**
- 2025-11-22: put assigned at $230 (Lot A starts)
- 2025-11-29: called away at $192.50 (Lot A ends)
- 2026-01-10: put assigned at $212.50 (Lot B starts)
- 2026-01-31: put assigned at $245 (Lot C starts — concurrent with Lot B)
- 2026-04-17: called away at $252.50 (one lot ends)

The view shows:
- Cycle 1 (correct): put $230 → call $192.50, cap_gain -$3,750
- Cycle 2 (WRONG): put $212.50 → call $252.50, cap_gain -$20,500 — sums OPTRDs from the second assignment too
- Cycle 3 (WRONG): put $245 → call $252.50 — pairs to same called_away as Cycle 2

**Fix:** FIFO pairing. For each underlying:
1. Sort all OPTRD-buy events by `transaction_time` ascending → assigned-put queue.
2. Sort all OPTRD-sell events by `transaction_time` ascending → called-away queue.
3. Walk the events in time order. Each OPTRD-buy opens a lot; each OPTRD-sell closes the oldest open lot.
4. Each lot pair = one cycle. `capital_gain = sell_price − buy_price` × shares (using actual OPTRD prices, not put_strike/call_strike).
5. Lots without a matching sell remain open.

This requires a stateful walk over events, which BigQuery can express via `ARRAY_AGG` + `OFFSET` tricks or a JavaScript UDF. Alternative: do the walk in Python in the backend's `BigQueryService.get_wheel_cycles_for_symbol` method.

**Open questions:**
- SQL-only or Python-side walk? Python is simpler to write but harder to test against the view abstraction; SQL keeps the view as source of truth.
- How to handle the AMD-style data anomaly where OPTRDs net to non-zero shares but Alpaca reports zero? Surface as an "unaccounted_shares_loss" column in the per-symbol scorecard, computed as `current_shares (from OPTRD net) − live_alpaca_shares`?

**Links:** FC-018 (dashboard), FC-019 (the OPTRD ingest that exposed this).

---

### FC-017: Option chain snapshots at decision points (for retrospective decision-quality analysis)

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** The dashboard rebuild (proposed FC-018) would benefit from retrospective decision-quality analysis: "could I have rolled to a higher-strike call instead of closing?", "was there a same-DTE put at a similar delta with better premium I should have picked instead?", "how does my close-time strike compare to the strike chain that existed at that moment?". These questions are not retrospectively computable from current data — they require a snapshot of the option chain at decision time. EOD prices are not enough; we need the strikes/premiums that existed *when the close or open decision was made*.

**Scope:** capture option chain snapshots at three decision points:
1. **Close decision** — when `should_close_*_early()` returns True. Snapshot the chain near the position being closed (same expiry, ±5 strikes), plus next-week's chain (±5 strikes near current price) so a "should I have rolled?" counterfactual is possible.
2. **Open decision** — when an opportunity is selected for execution. Snapshot the chain wider for the selected symbol (±10 strikes, all available expirations within target DTE band) so a "was there a better strike?" counterfactual is possible.
3. **Skip decision** — when the scanner had a candidate but skipped it for a gate reason. Just the candidate's chain row (so we can later validate "was the gate right?").

**Storage:** new BQ table `options_wheel.option_chain_snapshots` partitioned by `snapshot_date`, clustered by `underlying`. Schema captures `snapshot_id`, `decision_type`, `decision_id` (FK to the trade/scan/close event), `underlying`, `snapshot_time`, `chain` (REPEATED RECORD with strike, expiration, type, bid, ask, mid, delta, theta, iv, volume, oi). Append-only, idempotent by `snapshot_id`.

**Open questions:**
- Storage cost — option chains can be 50-200 rows each. If we snapshot every scan + every close, that's potentially 5-10k chain rows/day. At BQ pricing this is trivial ($X/month) but worth a back-of-envelope check.
- Alpaca rate limits — pulling chains adds API load. Are we already pulling them for these decisions and just not persisting? (Yes for opens — `find_suitable_*` already calls the chain. Closes likely don't pull a wider chain — would be net-new API calls.)
- Decision-id schema — how does a close-decision row in this table link back to the actual close FILL? Use `order_id` of the buy-to-close as the natural FK.
- Retention — do we want this forever or roll off after 1 year?

**Why deferred from FC-018 (dashboard rebuild):** counterfactual analysis is high-value but expensive to build correctly. FC-018 ships v1 of the new dashboard with retrospective views that *don't* require chain snapshots (closed-trade % of max profit, vs-buy-and-hold per symbol, ACB walk). FC-017 unlocks a follow-up dashboard iteration that adds the harder counterfactual surfaces.

**Links:** FC-018 (dashboard rebuild — depends on this for full decision-quality views); `src/strategy/put_seller.py:should_close_put_early`, `src/strategy/call_seller.py:should_close_call_early`, `src/api/market_data.py:find_suitable_puts/find_suitable_calls`.

---

### FC-033: Drawdown-pause escalation — permit a below-cost-basis call after an extended pause

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Split out of FC-030 (2026-07-18). When a symbol sits paused for a long stretch, the shares are dead capital — AMZN's 62-day pause cost an estimated $1,500–3,000 in foregone premium. One candidate response: after N days paused (14? 21?), allow a single far-OTM call whose strike is *below* the assignment-strike floor, harvesting some premium while accepting a capped share loss if called away.

**Why this is not FC-030:** it deliberately reverses part of FC-029 R2's hard cost-basis floor — the guard built specifically because the eroding floor caused the $9k of loss cycles. That makes it a strategy change (two-reviewer, high-stakes calibration per `~/CLAUDE.md`), not observability.

**Prerequisite:** empirical pause-duration data. FC-030's alerting starts collecting it; AMZN and GOOGL entered pauses 2026-07-17. Decide only after seeing whether pauses typically resolve in days (escalation unnecessary) or drag for weeks (escalation valuable).

**Open questions:**
- Day threshold to permit escalation, and how far OTM must the strike be?
- Operator-approval-in-the-loop, or automatic once configured?
- Does a called-away-below-cost outcome here beat continued waiting, measured over the observed pause distribution?
- Interaction with the FC-006 rolling engine (which has fired 0 times)?

**Links:** FC-029 R2/R3 (hard floor + pause), FC-030 (alerting; source of the duration data), `docs/investigations/strategy-review-2026-05-07.md` §R3.

---

### FC-011: Support non-Friday option expirations (daily/weekly rolling expirations)

**Status:** Consideration
**Size estimate:** L
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Some high-volume symbols (e.g., GOOGL, AMZN, SPY, QQQ) now have options expiring every trading day, not just Fridays. The current system assumes Friday-only expirations in multiple places:

1. **FC-006 rolling engine** — hardcoded Friday guard (`weekday()==4`) in both the `/roll` endpoint and Cloud Scheduler (`30 15 * * 5`). Positions expiring on a Wednesday won't be evaluated for rolling.
2. **DTE bands** — the 7→0 bands assume a Monday-sell, Friday-expire cadence. A position sold Monday with a Wednesday expiry has DTE=2 at open, hitting different (later) bands than intended.
3. **`call_target_dte: 7` / `put_target_dte: 7`** — assumes next-Friday expiry. With daily expirations available, shorter DTE targets (2-3 days) become viable, potentially improving theta capture per calendar day.
4. **Strike selection** — `find_suitable_calls/puts` filters by `dte <= target_dte` which works, but may miss better opportunities at non-Friday expirations.

**Open questions:**
- Which symbols in our universe have daily expirations vs Friday-only? Need to audit Alpaca's option chain data.
- Should the rolling engine run daily (not just Fridays) for symbols with daily expirations?
- Do DTE bands need to be reparameterized for shorter-DTE strategies (see FC-003)?
- Should we support mixed strategies — daily expirations for some symbols, weekly for others?
- How does this interact with FC-003 (DTE target optimization from 7 to 2-3)?

**Links:** FC-003 (DTE target optimization), FC-006 (rolling engine)

---

### FC-032: Backtesting engine overhaul — symbol wheel-fitness evaluation

**Status:** Phases 0–4 **Done** (PR #35, merged 2026-07-18) — evaluate mode ships; **Phase 5 (screen mode) still open**, tracked in the plan's Rollout section
**Size estimate:** L
**Owner:** zeshan
**Plan file:** `docs/plans/fc-032.md`

**Problem / opportunity:** The original backtesting engine has never produced a single trade in any saved run (all `backtest_results/` artifacts show 0 trades). Root causes: it requests Alpaca option bars with `feed='iex'` (options come from OPRA) so chains are always empty; the covered-call scan crashes on a nonexistent `portfolio.positions` attribute; `_calculate_summary_metrics` is called but never defined; and it reimplements — and diverges from — the live strategy rules instead of replaying them. Separately, `tools/backtesting/scheduled_backtest.py` emits fabricated performance numbers when its (nonexistent-module) imports fail. We want a rebuilt engine whose purpose is **symbol wheel-fitness evaluation**: given a symbol, replay our live strategy rules over a 1–2 year lookback with real historical options data and report how the full wheel (CSP → assignment → covered calls → called away) would have performed — both on-demand for candidate symbols and on a cadence to flag risky symbols for demotion.

**Open questions:**
- Data budget: free Alpaca bars (Feb 2024+, no bid/ask/greeks) vs a paid vendor (ThetaData/ORATS) — decide after the Phase 1 data-quality report?
- Reuse live strategy components via an adapter vs standalone reimplementation with parity tests?
- One decision point per simulated day (EOD) vs mimicking the live 9/12/3 ET schedule?
- Is the scheduled screening/demotion job part of this FC or a follow-up?

**Links:** FC-017 (chain snapshots at decision points — same storage need, forward-looking), FC-001 (symbol universe optimization — this engine answers its backtest question), `docs/plans/fc-032.md`.

---

### FC-037: Synthetic pre-2024 premium extension for backtests

**Status:** Consideration — explicitly deferred out of FC-032 v1
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** Alpaca's historical options data starts 2024-02-01, so FC-032 can only backtest ~2.4 years — a single, calm vol regime. Fitness verdicts risk overfitting to it. Extending backward requires *synthesising* option premiums from underlying price history, which is dangerous: Black-Scholes with trailing realized vol badly underprices seller premiums (IV exceeds RV ~85% of days; VIX/RV ≈ 1.18; the variance risk premium concentrates at short maturities — worst exactly for our weeklies; OTM put skew adds 3–5 vol points). Naive BS-with-RV understates a 30-delta weekly put premium by ~50–60%.

If ever built, the recipe and its error bars are already written down in the FC-032 plan appendix: Yang-Zhang 21d realized vol × a per-symbol IV/HV factor calibrated from our real 2024+ chains, plus a skew bump; binomial with discrete dividends for ITM/dividend cases. Synthetic-regime results must be **labeled as such and never silently mixed** with real-data results.

**Open questions:**
- Is a wider, lower-fidelity window actually more informative than a narrow, high-fidelity one for a *fitness* verdict (which is comparative vs buy-and-hold, not absolute)?
- Cheaper alternative: buy ThetaData/ORATS history (2012+/2007+, real quotes) — $25–99/mo or $599 one-time. That buys real data instead of modeled data for less engineering risk.
- Would a multi-start-date ensemble on the real 2024+ window capture most of the timing-luck benefit at a fraction of the cost?

**Links:** `docs/plans/fc-032.md` (non-goals + research appendix), FC-032.

---

### FC-034: Premium floor is not scale-free — four universe symbols can never trade

**Status:** Consideration
**Size estimate:** M (changes live trading behavior → requires a plan file)
**Owner:** unassigned
**Plan file:** not yet

**Problem / opportunity:** `min_put_premium: 0.50` is a **fixed dollar** floor applied identically to a $12 stock and a $600 one. The FC-032 coverage gate measured every decision day from 2024-02-01 to 2026-07-09 and found **F, PFE and KMI have zero usable decision days, and VZ has two** — a 0.10–0.20 delta weekly put on a low-priced underlying is worth pennies and can never clear $0.50. Independently confirmed against production: across 588 live Alpaca `FILL` activities and `options_wheel.trades_from_activities`, the bot has **never sold a put on any of the four**. They occupy 4 of 14 universe slots, consume screening API budget, and are structurally incapable of generating a trade.

This is not a data problem (bar coverage was 122/122 for all 14 symbols) and not a bug — the filter is doing exactly what it says. The question is whether a dollar-denominated floor is the right *threshold shape*.

**Open questions:**
- Re-express the floor as a fraction of strike (e.g. ≥ 0.5% of strike), as annualized return on collateral, or keep a dollar floor with a per-symbol override?
- A return-on-collateral floor is the economically meaningful one (it's what the wheel actually earns) — but it changes which contracts pass on *every* symbol, not just the cheap ones. Needs a backtest before it ships. FC-032's engine is exactly the tool; sequence this after FC-032 Phase 4.
- Or simply demote F/PFE/KMI/VZ from the universe and leave the floor alone. Cheapest fix, but leaves the threshold mis-shaped for any future low-priced candidate.
- Does `min_call_premium: 0.30` have the same defect on the call side? (Almost certainly — same shape, and calls are only sold post-assignment so the blast radius differs.)

**A/B study complete (2026-07-29) — recommendation is DEMOTE.** `docs/investigations/fc-034-premium-floor-ab.md`. Three arms (flat $0.50 / 0.40%-of-strike / 8% annualized return-on-collateral) over 275 decision days plus a read-only join against the 330 real sell-to-open fills. The pre-registered rules return DEMOTE: the cohort's *richest* in-band put pays a median $0.03–$0.08 a share (controls: $0.51–$0.53), so no floor admits them without admitting $3-per-contract trades; a 0.40%-of-strike floor would have retroactively blocked **47 of 330 real fills and $2,235 of realized option P&L**; and an 8%-annualized floor only helps the cohort by taking AAPL from 50% to 94% of usable days. The threshold shape is not the defect — the premium is not there. **Open question 4 (the call-side floor) is still open**: no covered call executed in any replay (see the study's New findings §1). Change still requires its own plan + two reviewers.

**Links:** `docs/investigations/fc-034-premium-floor-ab.md` (the A/B study), `docs/investigations/fc-032-coverage-gate.md` (the measurement + production validation), FC-032, FC-001 (symbol universe optimization). **A/B study = Track B2 of `docs/plans/fc-042.md`.**

---

### FC-035: delete the dead `poll_order_statuses` path and the `order_statuses` table

**Status:** Done — code merged (PR #54, `ceaae16`); **`bq rm` still outstanding (owner)**
**Size estimate:** M (multi-file deletion in live paths + a BigQuery table drop)
**Owner:** zeshan + Claude
**Plan file:** `docs/plans/fc-035.md`

**Re-scoped 2026-07-29:** originally "fix a one-line `NameError`." Investigation showed the whole path should be **deleted, not revived** — it has never executed, nothing reads its output, and FC-012 already scheduled the exact `bq rm` this performs. Step 0 gate verified live: **0 rows**, **no views** in `options_wheel` or `options_wheel_logs` reference the table, **no scheduled queries**. PR #47 (which revived it) is closed unmerged. Original problem statement retained below for history.

**Problem / opportunity:** `src/strategy/wheel_engine.py` (~line 698, in `poll_order_statuses`) calls:

```python
closed_orders = self.alpaca.trading_client.get_orders(
    filter=alpaca.trading.requests.GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100))
```

The module `alpaca` is **never imported** in that file — only `QueryOrderStatus`, in a local import on the line above. So this raises `NameError: name 'alpaca' is not defined` on every invocation. The surrounding `except Exception` swallows it and logs a debug line, "Could not fetch closed orders directly, using all_orders". Found by pyflakes while seaming the clock for FC-032; confirmed pre-existing (predates the FC-032 branch).

**Consequence:** the closed-orders path has never once executed. Order-status polling sees only whatever `self.alpaca.get_orders()` returns (the SDK default), so `order_filled` / `order_expired` events may be under-reported. Worth checking whether the dashboard's order-status accuracy has been quietly leaning on the activities ingestor instead.

**Open questions:**
- Fix is one import (`from alpaca.trading.requests import GetOrdersRequest`). But this *enables* a code path that has never run in production — what does it start doing, and does it double-log `order_filled` events against the activities-derived ones?
- Does `get_orders()` (no filter) already return closed orders, making the whole block dead code worth deleting instead?
- Add a test that would have caught this: pyflakes/flake8 `undefined name` in CI. There are other pre-existing lint findings; a clean-then-gate pass is probably warranted.

**Links:** FC-032 (found during the Phase 3 clock seam), `src/strategy/wheel_engine.py`.

---

### FC-036: Stage-4 execution gap check is dead in production

**Status:** Done — fix merged unarmed (PR #52, `44159d5`); **arming rejected on evidence**, see `docs/investigations/fc-036-gap-gate-study.md`
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not needed (single-file fix) — but it changes runtime behavior, so branch + PR

**Problem / opportunity:** Found by the FC-032 backtest, which reproduced it faithfully — the replay is behaving correctly; **production is not**.

`GapDetector._get_previous_close` (`src/risk/gap_detector.py`) does `df[df.index < current_time]` and takes `.iloc[-1]`. Alpaca stamps daily stock bars at **midnight ET** (04:00 UTC under EDT, 05:00 under EST), far before any of our decision times (9:35am ET = 13:35 UTC). So today's own bar satisfies the filter and "previous close" returns **today's close**.

Verified against the live client on 2026-07-17: at a simulated 9:35am ET decision, `_get_previous_close` returned **202.81** while the latest bar in the frame was also **202.81** (dated the same day).

**Consequence — note the precise failure, it is not "the gap reads zero".** Alpaca returns a *partial* bar for the current session, and `can_execute_trade` compares a real-time IEX quote against it, so what the gate actually measures is the **~20-minute pre-market drift** (the partial bar's last print ~9:15 ET vs the 9:35 quote), not the overnight gap. Observed drifts ran −0.967% to +1.212% — **nonzero**, so anyone spot-checking `gap_percent` in the logs would wrongly conclude the gate is working.

Today's bar was returned in **10/10 live trials** across NVDA and AAPL. The real overnight gaps on five sampled NVDA days were −2.295%, −1.096%, +0.076%, +2.295%, −1.147%; against `execution_gap_threshold = 1.5`, **3 of 5 should have blocked execution and none did.** The gate can also fire *spuriously* on a violent 9:15→9:35 move unrelated to any overnight gap.

Note this is *not* true of the Stage-2 gap-risk analysis (`_detect_current_gap`, gap_detector.py:214), which compares `df_dates < target_date` — a **date** comparison rather than a timestamp one. That is the fix pattern, and it means one of our two gap controls works while the other does not, with nothing surfacing the disagreement.

**Open questions:**
- Fix by excluding the current session's bar (`df.index.date < current_time.date()`), or by requesting bars with an explicit end of yesterday?
- Enabling a gate that has never fired changes live behavior. How much would it have blocked historically? The FC-032 engine can now answer this directly — run it with the gate fixed and compare.
- Does the same 04:00-stamp assumption leak into any other windowed statistic?

**Links:** FC-032 (`docs/plans/fc-032.md`), found during its two-reviewer pass; `docs/investigations/fc-032-parity-check.md`. **Fix + would-have-blocked study = Track E1 of `docs/plans/fc-042.md`.**

---

### FC-039: Wheel state persistence has never worked in production

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet — changes runtime behavior of the live wheel, so a plan is required

**Problem / opportunity:** `WheelStateManager` has been running with `storage_bucket=None` since inception. Its GCS save/load are therefore unconditional no-ops (`src/strategy/wheel_state_manager.py:60-62, 84-86`), and wheel state is in-memory per Cloud Run instance — lost on every scale-to-zero.

Verified four independent ways on 2026-07-18:

1. `src/strategy/wheel_engine.py:40` resolves the bucket as `getattr(config, 'state_storage_bucket', None) or os.getenv('STATE_STORAGE_BUCKET')`.
2. `Config` has **no** `state_storage_bucket` property — `grep` over all of `src/utils/config.py` returns nothing, so the `getattr` yields `None`.
3. `STATE_STORAGE_BUCKET` is **not set** on the live Cloud Run service. `gcloud run services describe options-wheel-strategy` shows the env is exactly `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `FINNHUB_API_KEY`, `ALPACA_PAPER_TRADING`, `GCP_PROJECT`. `cloudbuild.yaml:75` sets only the last two, and `--set-env-vars` is replace-semantics, so any hand-added value is wiped on the next deploy.
4. **No `wheel_state/current_state.json` object exists in any bucket in the project** — checked all three (`...-options-data`, `..._cloudbuild`, `options-wheel-opportunities`).

**Consequence — this silently disabled a control we believe is running.** Source #1 of the FC-029 R2 cost-basis chain is `wheel_state.symbol_states[symbol]['stock_cost_basis']` (`src/strategy/call_seller.py:429-441`), documented as *canonical*. It never resolves. The chain has been running on source #2 (BigQuery OPASN lookup) and source #3 (Alpaca `cost_basis`, empirically broken for assigned positions — that finding is what motivated FC-029 R2 in the first place). The cost-basis floor is therefore weaker in production than the FC-029 plan claims, on exactly the path FC-029 was written to harden.

Same family as FC-035 (`poll_order_statuses` latent `NameError`) and FC-015 (`_entry_times` is in-process, so the 4h min-hold gate is dead): code that has never executed in production while appearing healthy.

**Open questions:**
- Enable persistence, or accept in-memory state and delete the dead code? `reconcile_positions` rebuilds state from Alpaca each cycle, so persistence may be genuinely unnecessary — in which case the fix is removing the illusion, not the bucket.
- If we enable it: this is a **behavior change**, not a config fix. Cost-basis floors would begin resolving from source #1 and change which strikes are sellable. Needs its own canary and rollback.
- Add `state_storage_bucket` to `Config`, or set `STATE_STORAGE_BUCKET` in `cloudbuild.yaml`? The former is testable; the latter is one line.
- Should there be a startup assertion that any configured-but-unresolvable persistence target is fatal rather than silently no-op? This bug class keeps recurring.

**Links:** found during the FC-038 two-reviewer plan pass — `docs/investigations/fc-038-plan-review-2026-07-18.md` (BLOCKER B2). Related: FC-029 (R2 cost-basis chain), FC-035, FC-015.

---

### FC-040: Unit tests make live BigQuery calls against production data — ALREADY FIXED, entry withdrawn

**Status:** Withdrawn 2026-07-18 — the bug was real but had already been fixed on `main` before this entry was filed.

**What happened.** This entry was filed on 2026-07-18 during the FC-038 review, claiming the bug existed on `main`. It did not. `tests/conftest.py` on `main` already carries an autouse `_no_production_bigquery` fixture that stubs `CallSeller._lookup_last_opasn_put_strike`, with a `@pytest.mark.real_bq_lookup` escape hatch for the one test that genuinely exercises the fallback.

That fixture's own docstring documents the identical finding — same mechanism, same AAPL `$305` value, same drawdown-pause symptom — so the diagnosis here was a rediscovery, not a new bug.

**Why the false positive.** The verification was run in the FC-038 worktree, which is based on `main` from before PR #35 merged and therefore predates the fixture. The lesson is procedural and worth keeping: **verify a claimed `main` bug against `main`, not against a feature branch's base.** Every other finding in that review pass was re-checked against `main` afterward; FC-039 and FC-041 survived, this one did not.

**Links:** `tests/conftest.py` (`_no_production_bigquery`); `docs/investigations/fc-038-plan-review-2026-07-18.md`.

---

### FC-041: Naked-call share guard misparses OCC symbols and can fail open

**Status:** Consideration
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not needed (single-file fix), but it changes runtime behavior of a risk control, so branch + PR

**Problem / opportunity:** `ExecutionEngine`'s committed-share accounting (`src/strategy/execution_engine.py:333` (on `main`)) identifies short calls with a hand-rolled parser:

```python
for ch in opt_sym:
    if ch.isdigit(): break
    opt_underlying += ch
if opt_underlying == underlying and 'C' in opt_sym:
    committed_shares += abs(int(float(pos.get('qty', 0)))) * 100
```

Two defects:

1. **`'C' in opt_sym` is a substring test over the whole OCC symbol, including the ticker.** `CRWD250718P00150000` contains a `C`, so a short *put* on any C-containing ticker is counted as committing 100 shares to calls — over-blocking legitimate call sales. The current wheel universe (AAPL, MSFT, GOOGL, AMZN, NVDA, AMD, QQQ, SPY, IWM, UNH, F, PFE, KMI, VZ) contains no `C` ticker, so the wheel is safe **by luck, not by design**. Adding CSCO, CVX, KO-adjacent names, or C itself would trigger it.
2. **The digit-break underlying parser breaks on class shares.** `BRK.B` has position symbol `BRK.B` but OCC symbol `BRKB250718C...`, which parses to `BRKB` ≠ `BRK.B`. No match → `committed_shares = 0` → `available_shares = owned` → **the guard fails open and the bot writes calls against already-committed shares. That is a naked call.**

`src/utils/option_symbols.py` already exists and should be used instead; the option type is at a fixed offset in the OCC layout, not a substring.

**Consequence.** Defect (1) is currently latent and costs premium when triggered. Defect (2) is a genuine naked-call path — an uncovered short call has unbounded upside risk. Both become materially more likely under FC-038, which introduces a covered-call account with **no configured symbol universe by design**, where the operator buys arbitrary tickers through the Alpaca UI. FC-038's Phase 2 explicitly relies on this guard as the primitive for committed-share accounting.

**Open questions:**
- Replace the parser with `src/utils/option_symbols.py`, or is that module's coverage incomplete for class-share tickers too? Check before assuming.
- Add a hard pre-submit assertion that `short_calls × 100 ≤ shares_owned` per underlying, independent of the parser, so a parsing bug cannot produce a naked call?
- Are there other places that infer option type or underlying by substring? Sweep for `'C' in` / `'P' in` over option symbols.
- Regression tests must include a short put on a C-containing ticker and a `BRK.B`-style class-share position.

**Links:** found during the FC-038 two-reviewer plan pass — `docs/investigations/fc-038-plan-review-2026-07-18.md` (HIGH H1); flagged independently by both reviewers. Related: FC-038 (Phase 2 depends on this guard).

---

### FC-042: Backtest engine follow-on — performance, fidelity, and the filter studies

**Status:** Done — all tracks closed (PRs #49/#50/#48/#52/#54/#55/#56). **Surfaced FC-048 + FC-049, both blocking.**
**Size estimate:** L (tracks are individually S/M)
**Owner:** zeshan + Claude
**Plan file:** `docs/plans/fc-042.md`

**Problem / opportunity:** FC-032 shipped a working engine; three things separate it from answering the money questions. (1) Runs cost ~25 min/symbol — `ChainStore` is never constructed and contract discovery fetches ~70% unusable strikes. (2) Dividends/early assignment are unmodeled, blocking any verdict on income names. (3) The Jun–Jul 2026 walkthrough found NVDA blocked ~90% of the month by the gap filter's **40% vol cap** (not gap frequency), with NVDA's 30-day vol oscillating 40–42% against the hard line — trading was threshold noise on the symbol that is 155/241 lifetime put legs. The plan wires the cache + strike window (Track A), models dividends/early assignment (Track C), runs the gap-filter and premium-floor A/B studies feeding FC-002/FC-034 (Track B), and fixes FC-036/FC-035 behind quantifying studies (Track E). Includes a parallel-agent execution map. **No live thresholds change under this FC** — studies produce evidence; changes gate on FC-002/FC-034 plans.

**Open questions:**
- Vol-relative gate percentile (80th?) and graduated-response shape for B1.
- Dividend source: yfinance vs Alpaca corporate-actions endpoint (both validated reachable).

**Links:** `docs/plans/fc-042.md`, FC-002, FC-034, FC-035, FC-036, `docs/investigations/fc-032-parity-check.md`, `docs/investigations/fc-032-coverage-gate.md`.

---

### FC-043: `AlpacaClient.get_orders` status filter has never worked

**Status:** Done — merged (PR #51, `7e71f69`)
**Size estimate:** S (one wrapper function; live-behavior change)
**Owner:** zeshan + Claude
**Plan file:** `docs/plans/fc-043.md`

**Problem:** `AlpacaClient.get_orders(status=...)` (`src/api/alpaca_client.py:632`) has two independent defects: it never passes a `GetOrdersRequest`, so Alpaca's `status=open` REST default always applies (closed orders never fetched); and it value-filters `order.status.value == status`, but callers pass *query* tokens (`'open'`) that are never status *values* (`'open' not in [s.value for s in OrderStatus]`, verified). Net: the `status` argument has never selected the orders the caller asked for. **Three live callers broken:** the Stage-6 duplicate-order guard's Check 2 (`wheel_engine.py:496`, `status='open'`) returns `[]` unconditionally — and Check 2 is the *only* duplicate backstop that survives a Cloud Run cold start, i.e. the exact FC-009 window is currently unguarded; `wheel_engine.py:497` (`'pending_new'`); and `portfolio_tracker.py:315` (`'filled'`, "last 10 filled orders" — also always empty). Verified against live paper (500 closed orders; all four wrapper calls return 0).

**Fix:** map the `status` string to the correct `QueryOrderStatus` bucket, fetch with an explicit `GetOrdersRequest(limit=500)`, value-filter only for specific status values. Fixes all three callers at the root. Live trading logic → two reviewers.

**Links:** `docs/plans/fc-043.md`, FC-009 (confirmed duplicate-order bug this contributes to), FC-035/PR #47 (adjacent poll path, does not overlap — calls `trading_client` directly).

---

### FC-044: Daily execution grid — per-run decision telemetry + at-a-glance day view

**Status:** Consideration
**Size estimate:** L (two phases: telemetry backbone, then dashboard view)
**Owner:** zeshan
**Plan file:** not yet

**Problem / opportunity:** Day-to-day troubleshooting of the hourly engine is currently archaeology: to answer "what did the bot do today and was it the desired behavior?" you have to grep Cloud Run logs across three endpoints. We want a dashboard view for a single day — a grid with symbols as rows and hourly executions as columns — where each cell shows at a glance what happened to that symbol in that run: which gate stopped it (and why), whether an opportunity was found, whether a trade was placed, or whether the run never happened at all. The goal is visual deviation-detection: a normal day has a recognizable shape, and an abnormal one (a gate suddenly blocking everything, a missing scheduler run, a symbol silently skipped for weeks) should be visible without reading a single log line.

**The hard prerequisite — the data doesn't exist yet (surveyed 2026-07-25):** the grid cannot be built from BigQuery today; the finest live granularity is one `executions` row per endpoint invocation with **no symbol column**. Specifically:
- All per-symbol gate/skip reasons (stage 1 stock filter, stage 7/8 chain criteria with rejection breakdowns, batch dedup, naked-call block, drawdown pause) are `logger.info` → Cloud Run logs only. The `options_wheel_logs` sink dataset technically retains them, but nothing normalized reads it and the dashboard was deliberately repointed off it in FC-012.
- Two skips produce **zero telemetry anywhere**: insufficient-collateral drop in `select_batch` (`src/strategy/execution_engine.py:226` has no `else`) and the scanner's existing-position skip (`src/data/options_scanner.py:53`, bare `continue`).
- **No run identifier joins one hour together.** `request_id` is bound per HTTP request (so a `/scan` at :00 and its `/run` at :15 get different ids) and — despite `executions`/`errors` having a `request_id` column — is never passed to `write_execution`/`write_error`, so the column is always `""`. The only scan→run correlator is the 20-min-TTL GCS opportunity blob.
- **`options_wheel.scans` is a dead table with live readers.** Its writer was deleted in FC-012, yet the dashboard's Bot Health gate heatmap (`dashboard/backend/services/bigquery.py:303`) and the `gate_full_block_streak` anomaly flag (`:1393`) still query it — both presumably render empty today. No FC covered this until now.
- The documented 9-stage funnel (`docs/logging/FILTERING_STAGES_LOGGING.md`) describes the CLI/backtest path, not production: stages 2–6 and 9 never execute in the live `/scan`→`/run` path, while the gates that *do* fire live (scanner position skip, batch collateral fit, batch dedup) have no stage number at all. A grid must be built on the **live** gate sequence, not the documented one.
- `log_filtering_event()` (`src/utils/logging_events.py:421`) — the one helper defining a normalized `stage`/`status`/`symbol` contract — is dead code with zero call sites; it's a natural starting point for Phase 1.

**Rough shape (detail belongs in the plan):**
- *Phase 1 — decision telemetry:* a `run_id` minted at `/scan` and threaded through the GCS opportunity blob into `/run`; a new BQ `decision_events` table (run_id, run_ts, endpoint, symbol, gate, outcome, reason, metrics JSON) written at every gate verdict including the currently-silent skips; retire or repoint the dead `scans` readers.
- *Phase 2 — the grid:* symbols × hourly runs for a selected day; cell encodes furthest-stage-reached / terminal outcome, click-through to the full decision trail for that symbol-run; a column that never happened (scheduler miss, endpoint 500) must render as visibly distinct from "ran, nothing tradeable" — silent non-execution is exactly the failure mode that has bitten before (FC-031 sat undeployed 11 days; roller never fired).

**Open questions:**
- Write-time events to a new table vs. a normalized view over the existing `options_wheel_logs` sink? (Sink is free and already flowing, but wildcard-table parsing per event type is brittle and the two zero-telemetry skips still need code changes either way.)
- Cell semantics: terminal outcome only, or furthest-stage + reason? How to encode multi-contract evaluation (stage 7 rejects 40 contracts, accepts 1) without drowning the at-a-glance read?
- What defines "expected behavior" for deviation highlighting — static schedule (6 runs/day × universe), or a learned baseline?
- Volume/cost: ~14 symbols × ~4 gates × 6 runs/day is trivial (<500 rows/day), but per-contract stage-7 detail could be 100×; keep contract-level breakdown as aggregate counts in the metrics JSON?
- Does Phase 1 subsume FC-030's pause-observability metric (drawdown pause becomes just another gate event)?
- Retention: decision events are diagnostic, not canonical — partition + expire after N months?

**Links:** FC-030 (pause alerting — overlapping telemetry), FC-036 (dead stage-4 gate — grid would have made this visible immediately), FC-014 (RiskManager never invoked live — same class of "documented gate doesn't fire"), FC-002 (gate-hit-rate analysis wants the same data), FC-012 (`scans` writer removal), `docs/investigations/dashboard-metrics-audit-2026-07-07.md` §Bot Health.

---

### FC-045: `/monitor` misroutes covered calls to put-close logic (`'P' in symbol`)

**Status:** Consideration
**Size estimate:** S (one expression + test; live behavior path)
**Owner:** unassigned
**Plan file:** not yet

**Problem:** `deploy/cloud_run_server.py:688-689` classifies an option position by substring:

```python
is_put = 'P' in symbol      # evaluated FIRST
is_call = 'C' in symbol
```

`symbol` is a full OCC symbol (e.g. `AAPL250815C00185000`), so the ticker's own letters are tested. Any underlying containing `P` matches `is_put`, and because `is_put` is checked first, **every covered call on those symbols is evaluated by `should_close_put_early()` instead of `should_close_call_early()`** and tagged `position_type='PUT'`.

**Affected: 3 of 14 universe symbols — `AAPL`, `SPY`, `PFE`** (two are core holdings). Verified against `config/settings.yaml` 2026-07-28.

**Actual impact today is telemetry, not money — verified, not assumed.** `should_close_put_early` and `should_close_call_early` currently converge: both call `_get_profit_target_for_dte`, which reads the *same* shared config (`profit_taking_dte_bands` / `profit_taking_static_target`) in both classes, and both stop-loss branches are gated off (`use_put_stop_loss: false`, `use_call_stop_loss: false` — FC-010). So the close *decision* is presently identical; what differs is the emitted event (`put_profit_target_reached`) and `position_type`, which mislabels call closes as put closes in the analytics/dashboard attribution for those symbols.

**Latent severity is higher.** The moment `use_call_stop_loss` is re-enabled, or the two profit-target implementations diverge, this becomes a real behavioral bug — misrouted calls would silently consult the *put* stop-loss flag and never trigger call protection. It is a landmine, not just a label.

**Fix:** use the canonical parser — `parse_option_symbol(symbol)['option_type']` (`src/utils/option_symbols.py`, fully-anchored OCC regex). Do not re-implement OCC parsing. Lower-stakes copies of the same substring pattern in `tools/testing/*` can ride along.

**Why filed now:** surfaced during FC-035's plan verification. PR #47 fixed this same defect class inside the (now deleted) poll path via `_classify_order_strategy()`; that fix dies with the branch, but the live `/monitor` instance remains. Same bug family as FC-041 (naked-call guard OCC misparse) and the FC-043 Stage-6 substring over-block — **the third occurrence of substring-matching an OCC symbol**, which argues for a lint/grep guard rather than another one-off fix.

**Links:** `docs/plans/fc-035.md` (where it was found), FC-041, FC-043, `src/utils/option_symbols.py`.

---

### FC-046: `options_wheel_logs.trades_executed` view is unqueryable

**Status:** Consideration
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not yet

**Problem:** every query against the live view fails:

```
Cannot read field of type FLOAT64 as STRING  Field: jsonPayload.symbols
Cannot read repeated field of type STRING as optional STRING  Field: jsonPayload.symbols
```

The view selects across the `run_googleapis_com_stderr_*` day-sharded log tables and does `TO_JSON_STRING(jsonPayload)`. `jsonPayload.symbols` has been emitted with **three different shapes** over time (FLOAT64, STRING, REPEATED STRING), so the wildcard union cannot resolve a single type. Reproduced live 2026-07-29: `SELECT COUNT(*) FROM options_wheel_logs.trades_executed` errors.

**Why it matters:** this view is treated in plan docs as a live ad-hoc analysis surface (FC-035's behavior contract reasoned carefully about not polluting it). It has in fact been broken — how long is unknown. Any analysis that assumed it works has been silently unavailable, and the schema-collision class is the same one recorded in the 2026-04-07 session memory ("never string-ify arrays").

**Fix direction:** pin the wildcard union to a consistent projection (extract `symbols` with `JSON_VALUE`/`JSON_QUERY` rather than `TO_JSON_STRING` over the whole payload), or exclude the offending shards. Decide first whether the view is still wanted at all, given the dashboard reads `trades_from_activities`.

**Found:** during FC-035's two-reviewer pass, by a reviewer verifying the deletion had no consumers.

**Links:** `docs/plans/fc-035.md`, FC-012.

---

### FC-047: `log_system_event` never sets `event_type`, so system events are unqueryable by it

**Status:** Consideration
**Size estimate:** S
**Owner:** unassigned
**Plan file:** not yet

**Problem:** `src/utils/logging_events.py` `log_system_event()` does:

```python
logger.info(event_type, event_category="system", status=status, ...)
```

`event_type` is passed as structlog's **positional message**, so it lands in `jsonPayload.event` and `jsonPayload.event_type` is **never set** for any system event. The function's own docstring advertises the opposite, showing `SELECT event_type ... GROUP BY event_type` — a query that returns NULL for every row it produces.

**Confirmed live (2026-07-29):** `pre_trade_reconciliation_completed` has 492 rows, all under `jsonPayload.event`. Two independent FC-035 reviewers each hit this and had to correct their queries mid-review; one nearly concluded the pre-trade housekeeping block had never run.

**Why it matters:** every consumer that filters system events on `event_type` silently matches nothing. This is a monitoring/observability trap of exactly the kind that hid FC-030's alerting problem (an alert filtering `severity>=WARNING` that matched nothing). Any future post-deploy verification keyed on `event_type` will look like a regression.

**Fix direction:** pass `event_type=event_type` as a kwarg (and keep the message for readability). **Check for downstream breakage first** — some views may already compensate by reading `jsonPayload.event`, and setting both could double-count or change existing query results. Contrast with `log_risk_event` / `log_order_status_update`, which set the kwarg correctly; the inconsistency is the real defect.

**Links:** `docs/plans/fc-035.md`, FC-030.

---

### FC-048: every backtest runs only half a wheel — covered calls are misrouted to the put path

**Status:** Consideration — **high priority, affects the credibility of every backtest verdict**
**Size estimate:** S to fix, M to re-validate downstream conclusions
**Owner:** unassigned
**Plan file:** not yet

**Problem:** `ExecutionEngine.execute_batch` routes on `opp.get('type', 'put')` (`src/strategy/execution_engine.py:286`) — defaulting to **put**. There are two producers of opportunities and only one of them sets that key:

| producer | sets `type`? | routes to |
|---|---|---|
| `options_scanner.py:340` (production `/scan` path) | **yes** (`'type': 'call'`) | call path — correct |
| `call_seller.evaluate_covered_call_opportunity` (used by `wheel_engine._find_new_opportunities` and `_manage_existing_positions`) | **no** — emits `'strategy': 'sell_call'` instead | **put path — misrouted** |

The backtest replays `run_strategy_cycle()`, which uses the second producer. So **every covered-call opportunity in every backtest is handed to `put_seller`**, which rejects it. Verified three ways: the code trace above; a direct routing simulation (engine-shaped dict → `'put'`, scanner-shaped dict → `'call'`); and empirically — a 2-year NVDA replay reports **30 puts sold, 0 calls**, and a B2 study run found **293 call opportunities on AAPL, 0 sold**.

**Production is NOT affected.** It executes from the scanner path, which types calls correctly; 84 real covered calls appear in `trades_from_activities`. This is a backtest-fidelity defect, not a live trading bug.

**Why it went unnoticed:** the golden test is named `test_the_wheel_actually_turns`, but it only asserts put-sold → assignment → shares-held. **No test has ever asserted that a covered call is sold in replay.** The suite covers exactly the half that works.

**What it means for existing conclusions:**
- **Every backtest to date models a put-only strategy.** Assigned shares are never called away, so cycles never complete, call premium is never earned, and returns are understated on any symbol that gets assigned.
- This plausibly explains an FC-032 Phase 5 finding previously blamed on window length: **7 of 14 symbols — including SPY and QQQ — were flagged for demotion purely for not closing a cycle.** A cycle cannot close without the call leg.
- Affects the engine-A/B layers of `fc-036-gap-gate-study.md` and the Track B studies. It does **not** overturn their headline conclusions, both of which rest on real-fills layers rather than the engine (FC-036's DO-NOT-ARM; FC-034's DEMOTE) — but the engine tables in those docs should be read as put-only.

**Fix direction:** set `'type': 'call'` in `evaluate_covered_call_opportunity` (and audit the put side for symmetry, per the repo's wheel-symmetry rule). Then add the test that was missing: a replay assertion that a covered call is sold after assignment. Re-run the affected verdicts afterwards — the fix is small, but re-validating what it changes is the real work.

**Found:** by the FC-034 (B2) premium-floor study while investigating why enabled symbols showed no call activity.

**Links:** `docs/plans/fc-042.md`, `docs/plans/fc-032.md`, `docs/investigations/fc-034-premium-floor-ab.md`, FC-015 (same family: a gate that has never fired while looking healthy).

---

### FC-049: The stage-2 gap-risk filter is not wired into the live trading path

*(Renumbered from FC-048 at merge: FC-048 was concurrently allocated on main to the covered-call misroute found by the B2 study. Independent findings — but the same species: a control that looks active and is not.)*

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Problem:** `GapDetector.filter_stocks_by_gap_risk` is called from exactly one place —
`WheelEngine._find_new_opportunities`. The deployed Cloud Run trading path is
`/scan` → `OptionsScanner` → `OpportunityStore` → `/run`, and `src/data/options_scanner.py`
never constructs a `GapDetector`. Commit `842dcce` (2025-10-03, "Implement Cloud Storage
scan-to-execution architecture") removed `wheel_engine.run_strategy_cycle()` from `/run`;
the live account's first fill is **2025-10-06**. **No live trade has ever been evaluated by
stage 2.** The server does build a `WheelEngine`, but only for `reconcile_positions()` and
`run_rolling_cycle()` — neither reaches `_find_new_opportunities`.

**Confirmed four ways (2026-07-29)**, all reproducible via
`tools/diagnostics/fc002_gap_filter_ab.py verify`:
1. Source inspection: no module on the live scan path references `GapDetector`.
2. `git log -S "run_strategy_cycle" -- deploy/cloud_run_server.py` → `842dcce`, three days
   before the first fill.
3. Cloud Logging (40d): all 18 request_ids emitting `stage_2_complete` /
   `stock_passed_gap_filter` / `stock_filtered_by_gap_risk` are **backtest** requests.
4. On 2025-10-06, `docs/analysis/AMD_GAP_RISK_ANALYSIS_2025.md` records the filter returning
   "Suitable for Trading: NO" for AMD; BigQuery shows `AMD251010P00192500` sold short that
   same day for $223.

**Why it matters:** this is the mirror of FC-036 (a control that ran but measured the wrong
thing) — a control that measures correctly and never runs. It also invalidates the framing
of **FC-002**, whose block rates describe the backtest engine, not production. Reconstructed
over the same bars, the filter would have refused **123 of 327** real entries.

**Decision required before any threshold work:** wire it in, or delete it. What it must not
remain is a control that exists in `config/settings.yaml`, in the backtest, and in the FC
index, but not in the thing that trades. **Wiring the current rule in unchanged would be the
largest behaviour change in the project's history and, on the evidence, a costly one** — see
the study. Same class of latent defect as FC-035 (dead poll) and FC-039 (state persistence
never worked); worth a sweep for others.

**Links:** `docs/investigations/fc-002-gap-filter-ab.md`, FC-002, FC-036, FC-039.

---

### FC-050: production's below-basis protection for covered calls is plausibly nil

**Status:** Consideration — **potential live money bug, verify before acting**
**Size estimate:** S to fix, but needs live verification first
**Owner:** unassigned
**Plan file:** not yet

**Problem:** the covered-call cost-basis floor — the guard that stops us writing a call below what we paid, i.e. locking in a guaranteed loss — appears to be **non-functional on the path production actually executes**. Two independent halves both fail, and they fail in the same direction.

**Half 1 (confirmed by code inspection).** `execute_call_sale` gates its floor check on `stock_cost_basis` (`src/strategy/call_seller.py:319-325`):

```python
stock_cost_basis = opportunity.get('stock_cost_basis', 0)
if stock_cost_basis > 0 and strike_price > 0:   # gate self-disables at 0
```

Scanner-produced opportunities — the ones production executes — carry **`cost_basis_per_share`**, not `stock_cost_basis` (`src/data/options_scanner.py:~350`). So the key lookup returns the `0` default and **the execute-time floor never runs in production**. Only `call_seller.evaluate_covered_call_opportunity` sets `stock_cost_basis`, and production never calls it (same scanner-vs-wheel_engine path split that caused FC-048).

**Half 2 (rests on FC-029's prior validation; could NOT be re-confirmed today).** The scanner's own floor uses `float(position['cost_basis']) / shares` (`options_scanner.py:128`). FC-029 (2026-05-08) empirically established that **Alpaca returns `cost_basis = 0` for assigned positions** — which is why FC-029 R2 built the `wheel_state → BigQuery → Alpaca` resolution chain. If that still holds, the scanner passes `min_strike_price=0` and applies no floor either. *Not re-verified: the account currently holds zero equity positions, so there was nothing to observe. Confirm against a live assigned position before acting.*

**Consequence if both hold:** covered calls can be written below cost basis in production on exactly the positions the floor exists to protect — assigned shares. That is the guaranteed-loss scenario `docs/CLAUDE.md` calls out as CRITICAL.

**The deeper issue — FC-029 R2 may be dead code in production.** FC-029's headline fix (the cost-basis source-order chain) lives in `evaluate_covered_call_opportunity`. If production only ever runs the scanner path, that fix has never executed in production, for the same structural reason FC-048 existed. **Worth checking whether other FC-029 remediations landed on the unused path too.**

**Verification before any fix:**
1. Wait for (or create) an assigned equity position; read `cost_basis` and `avg_entry_price` from the live API.
2. Query `trades_from_activities` for historical covered calls whose strike was below the assigning put's strike — direct evidence of whether this has already cost money.
3. Confirm which path `/run` executes for calls end to end.

**Fix direction:** make the scanner use the same FC-029 resolution chain, and have `execute_call_sale` read whichever key is actually present (or normalize the opportunity shape — the boundary-dataclass idea rejected as out-of-scope in `docs/plans/fc-048.md` would prevent this whole class).

**Found:** by an FC-048 adversarial reviewer probing whether the newly-live call path could write below basis. In the backtest it cannot (both guards work there); production is the gap.

**Links:** `docs/plans/fc-048.md`, FC-029 (R2 cost-basis chain), FC-038, `docs/CLAUDE.md` (Risk Management Philosophy).

---

### FC-051: the spread model needs per-symbol calibration, not a pooled fit

**Status:** Consideration
**Size estimate:** M
**Owner:** unassigned
**Plan file:** not yet

**Context — FC-042 Track C3 is now closed on its measurement half.** The RTH sample that C3 was blocked on has been taken (2026-07-29 11:39 ET, market confirmed open via Alpaca's clock, `--require-rth`): **n=524 OTM puts across AAPL/AMD/IWM/NVDA, median real half-spread $0.0250 vs $0.0614 modeled — 2.46x wider, wider on 86% of contracts.** That **retires** the long-standing caveat: the earlier after-hours sample (2.12x) warned the gap might close intraday, leaving "the model is conservative" unproven. It does not close — intraday the model is *more* conservative, not less. The report footer now states the RTH figure.

**What remains — the model's shape, not its level.** Fitting `SpreadModel` on that same RTH sample yields:

| | value |
|---|---|
| R² | **0.027** |
| samples used | 256 of 524 (121 excluded cheap, 147 at the $0.02 floor) |
| pooled `base_frac` | 0.0251 (default 0.05) |
| per-symbol `base_frac` | **AMD 0.0050 · IWM 0.0232 · NVDA 0.0159 · AAPL 0.0773** |

That is a **15x spread across four symbols**, and moneyness explains ~3% of the variance. The tool's own verdict is `NOT USABLE — DO NOT COMMIT`, and no parameters were committed.

**Why a pooled fit cannot work here:** a single `base_frac` averages a $290 ETF (IWM) against a $440 single name (AMD). Half-spread as a *fraction of mark* is not the same quantity across those. Two structural facts the fit surfaces: 28% of contracts sit at the **$0.02 exchange floor** — a constant, not a fraction — and 23% are "cheap" contracts where `cheap_widening` is already applied at eval, so fitting them double-counts it.

**Fix direction:** calibrate per symbol (or per liquidity tier / price bucket), and model the $0.02 floor explicitly rather than letting it distort a proportional fit. Re-check R² per symbol; NVDA already scores `[OK]` alone while the other three do not.

**Why it matters:** every backtest premium is a modeled bid/ask. The *level* is now known to be conservative, so verdicts are not being flattered — this is about narrowing an honest but coarse error bar, not correcting a bias. Lower priority than the FC-048 re-validation.

**Links:** `docs/plans/fc-042.md` (Track C3), `tools/diagnostics/spread_model_check.py`, PR #48.

---

### FC-052: oversell guard counted short PUTs as committed calls (5th OCC-substring instance)

**Status:** Done — fixed in the same PR that filed it
**Size estimate:** S
**Owner:** zeshan + Claude
**Plan file:** not needed (single-file, latent bug, no behavior change for the current universe)

**Problem:** `ExecutionEngine.execute_batch`'s covered-call oversell guard decided "is this short option a call on my underlying?" with two heuristics stacked:

```python
opt_underlying = ''
for ch in opt_sym:              # hand-rolled: chars up to the first digit
    if ch.isdigit(): break
    opt_underlying += ch
if opt_underlying == underlying and 'C' in opt_sym:   # substring
```

A short **put** on any ticker containing a `C` matches `'C' in opt_sym`, so it was counted as a committed call. That over-reports committed shares, under-reports available shares, and **silently starves the call side** — refusing legitimate covered calls with no error, the same signature as the covered-call starvation investigated on 2026-07-18.

**Latent, not firing:** no configured symbol contains a `C` (AAPL, MSFT, GOOGL, AMZN, NVDA, AMD, QQQ, SPY, IWM, UNH, F, PFE, KMI, VZ). It fires the moment one is added — and the failure mode is silence, not an error.

The hand-rolled underlying parser is separately wrong on adjusted roots: `1AAPL250815C00190000` yields `''` (first char is a digit).

**Fifth instance of the OCC-substring family** — FC-041 (naked-call guard), FC-043 (Stage-6 over-block), FC-045 (`/monitor` misroute), FC-048 (execution routing), and now this. FC-048 added the shared `strict_option_type()` primitive precisely so these stop recurring; this converts the last known site.

**Fix:** parse the contract once with the canonical parsers — `parse_option_symbol` for the underlying, `strict_option_type` for the side.

**Tests:** a short put on a C-containing ticker no longer consumes call capacity; a real short call still does (guard not over-corrected into overselling). Mutation-verified — reverting to the substring form fails the first test.

**Links:** FC-041, FC-043, FC-045, FC-048, `docs/investigations/covered-call-starvation-2026-07-18.md`.

---

## Completed

_Move entries here once a plan has been published, executed, and merged. Include plan file + PR/commit link._

### FC-006: Covered call rolling engine (Friday EOW)
- Plan: `docs/plans/fc-006.md`
- PR: https://github.com/memon1987/options_wheel/pull/5 (merged 2026-04-16)
- Commit: `08fb876`
- Notes: Deployed with `rolling.enabled: false`. Pending paper testing on Fridays before enabling Cloud Scheduler job.

### FC-007: Earnings Calendar Service (Finnhub)
- Plan: `docs/plans/fc-007.md`
- PR: https://github.com/memon1987/options_wheel/pull/5 (merged 2026-04-16)
- Commit: `0ccf852`
- Notes: Finnhub API key in Secret Manager, injected into Cloud Run. Log enrichment active; PutSeller/CallSeller integration deferred.

### FC-010: Disable call stop-losses (assignment is profitable by design)
- Plan: `docs/plans/fc-010.md`
- PR: https://github.com/memon1987/options_wheel/pull/7 (merged 2026-04-17)
- Commit: `737db8a`
- Notes: Single config change (`use_call_stop_loss: false`). Deployed to Cloud Run revision `00142-vz6`.

### FC-012: Shift dashboard logging to Alpaca queries wherever authoritative
- Plan: `docs/plans/fc-012.md`
- PR: https://github.com/memon1987/options_wheel/pull/8 (merged 2026-04-24)
- Commit: `8b31a1b`
- Notes: All phases (2.1-2.7) shipped in one PR after user dropped the parity gate. New tables: `trades_from_activities` (465 rows backfilled) and `equity_history_from_alpaca` (124 rows). New views: `trades_with_outcomes`, `wheel_cycles_from_activities`. Three Cloud Scheduler jobs ingest on a split schedule. V1 tables (trades, wheel_cycles, position_snapshots, order_statuses) left inert pending manual `bq rm` — a follow-up remote routine on 2026-05-01 opens a cleanup PR. Follow-up fix PR #9 preserves `GCP_PROJECT` env var across bot deploys.

### FC-008: Stop-loss events mislabeled as profit_target_reached (superseded)
- No dedicated PR — superseded by FC-010 + FC-012.
- Closed: 2026-04-24
- Notes: Two independent mechanisms neutralized this. (1) FC-010 disabled call stop-losses, so `should_close_call_early` no longer returns True for losses — the mislabeling trigger is gone. (2) FC-012 cut dashboard reads over to `trades_with_outcomes` (Alpaca-sourced), so the corrupted `event_type=early_close_executed` + `reason=profit_target_reached` rows in the v1 `trades` table no longer affect analytics. Historical rows remain dirty but unread; the v1 table itself is scheduled for drop on 2026-05-01 via the FC-012 cleanup routine. If put early-closes ever start showing the same mislabel in structlog events, re-file as a new FC focused on the put-side path only.

### FC-018: Wheel-centric dashboard rebuild (frontend only)
- Plan: `docs/plans/fc-018.md`
- PRs: #12 (skeleton), #13 (backend), #14 (pages), #15-#18 (review fixes), #22 (Trade Log), #23 (gap-closing), #24 (PR F cutover), #25 (PR G cleanup) — final merge 2026-05-05
- Commits: `b7b9184` → `4eb74d2` (PR G)
- Notes: 3-page dashboard (Overview / By Symbol / Bot Health) shipped via strangler migration. Canonical paths are now bare (`/overview`, `/symbol`, `/bot-health`); `/v2/*` and legacy `/positions`, `/trades`, `/performance`, `/cycles` redirect for bookmark compatibility. Legacy frontend preserved under `dashboard/frontend.archive/` with emergency-revert README — recommend deletion after ~2 weeks of bake time. Mid-execution the gross-vs-net premium audit triggered FC-019; FIFO cycle pairing for overlapping share lots was scoped out as FC-020.

### FC-022: Trade Log contract IDs + ET timezone + By-Symbol summary table
- Plan: `docs/plans/fc-022.md`
- PR: https://github.com/memon1987/options_wheel/pull/26 (merged 2026-05-06)
- Commit: `cd1d47d`
- Notes: Trade Log gains OCC symbol + expiration + Alpaca order ↗ link per row. All date helpers (`fmtDate`, `fmtDateShort`, `fmtDateTime`) now ET-anchored with explicit `timeZone: 'America/New_York'` and `fmtDateTime` shows the EST/EDT marker. `/symbol` landing page replaces the pill grid with a sortable summary table (`SymbolUniverseTable`) backed by existing scorecard data. Backend `fc018_acb_timeline_per_symbol` view extended with `occ_symbol`, `order_id`, `expiration` columns. `positionState`/`stateColor` extracted from SymbolScorecard into a shared util. 4 new vitest tests assert ET-stability across system locales.

### FC-021: Synthetic activity correction for Alpaca paper-engine silent settlements
- Plan: `docs/plans/fc-021.md`
- Commit: `133ebb0` (no PR — data-only correction)
- Date: 2026-05-06
- Notes: Inserted two synthetic rows into `options_wheel.trades_from_activities` (`activity_id LIKE 'synthetic-fc-021-%'`) to reconcile the dashboard for `AMD260116C00212500`'s silent 2026-01-16 paper-engine exercise. Discovered during reconciliation diving (see `docs/investigations/amd-reconciliation.md`) — Alpaca's paper engine settled the deep-ITM call without logging OPASN/OPEXP/OPTRD; daily-P&L hypothesis fit confirmed only one silent event occurred, no second discrepancy. Effect on AMD scorecard: `share_pnl` −$24,250 → −$3,000, `total_pnl` −$17,319 → +$5,309, Cycle 2 `cap_gain` −$20,500 → $0 (clean wash). Headline Total Return remains pinned to NLV − sum(deposits) so it's unaffected; per-symbol sum across symbols ($44.9k) no longer ≈ headline ($20.1k) — accepted divergence reflecting the off-book silent settlement. Audit query: `WHERE activity_id LIKE 'synthetic-%'`. Rollback: `DELETE` same predicate.

### FC-023: Per-symbol Realized P&L reconciliation — single canonical number across drilldown
- Plan: `docs/plans/fc-023.md`
- PR: https://github.com/memon1987/options_wheel/pull/27 (merged 2026-05-07)
- Commit: `83bbd57`
- Notes: Top-of-page "Realized P&L" card and Wheel-vs-B&H "Wheel" total now both display canonical `total_realized_pnl` (option leg + share leg, FC-019) instead of two different disagreeing numbers. UNH pre-fix: top $4,334, wheel $10,222 (double-counted premium). UNH post-fix: both $2,584. View `fc018_vs_buy_and_hold_per_symbol.wheel_minus_bh` formula corrected from `realized_pnl + total_premium` to `total_realized_pnl`. B&H labeled "(price only)" — dividend-reinvested B&H is a deferred concern (FC-017's neighborhood).

### FC-024: ACB walk view rewrite — restore missing event types and ACB computation
- Plan: `docs/plans/fc-024.md`
- PRs: https://github.com/memon1987/options_wheel/pull/30 (merged 2026-05-07; replaces auto-closed [#28](https://github.com/memon1987/options_wheel/pull/28) which lost its base on FC-023's merge)
- Commit: `1a4e401`
- Notes: `fc018_acb_timeline_per_symbol` rewritten to source from `trades_from_activities` directly via four UNION-ALL blocks (opens / closes / OPASN with QUALIFY-guarded OPTRD pairing / OPEXP). Pre-fix every symbol had `rows_w_acb=0`; post-fix all 6 event types render correctly with ACB transitions during share-holding windows. Reference-dot positioning fixed (`dotAxisFor()` helper rides ACB axis when shares held, premium axis otherwise). Incidentally fixed Phase Timing observation #4 (UNH state machine now returns 4-phase split: cash 124d / short_put 61d / long_stock 10d / covered 17d). Surfaced AMZN silent-exercise data anomaly as a side discovery, filed as FC-025.

### FC-026: Decision Quality — surface Premium Received / Captured / Foregone macro stats
- Plan: `docs/plans/fc-026.md`
- PR: https://github.com/memon1987/options_wheel/pull/29 (merged 2026-05-07)
- Commit: `1b5559c`
- Notes: Capture-ratio math validated as correct against raw activities (no data fixes shipped). Three new dollar-magnitude aggregates rendered in the chart card: Received / Captured / Foregone (buybacks). UNH macros: **$5,888 / $4,334 (73.6%) / $1,554 (26.4%)** (verified 2026-05-07 against raw Alpaca activity feed). "Foregone" is qualified "(buybacks)" to disambiguate from the counterfactual reading (which would require option-chain snapshots — FC-017). Frontend-only; no view, no backend, no payload change.

### FC-027: Cycle Table — separate "Total Premium" from "Cycle P&L"
- Plan: `docs/plans/fc-027.md`
- PR: https://github.com/memon1987/options_wheel/pull/31 (merged 2026-05-07)
- Commit: `9928db8`
- Notes: Surfaced mid-trace during the FC-023/024/026 manual reconcile when the user noticed the Cycle Table column labeled "Cycle P&L" actually displayed `total_premium` only (option-side net), silently excluding `capital_gain` (share-side cash flow). For UNH Cycle 1 the column read +$1,218 but the true cycle outcome was $1,218 − $1,750 = −$532. Fix: rename existing column → "Total Premium" (matches the data), add new "Cycle P&L" column = `total_premium + capital_gain`. Same class of bug as FC-023 at cycle granularity. Peer review caught one defect (Cap Gain tooltip leaked internal nomenclature `Post-FC-019`/`OPTRD` — reverted to user-readable copy) and two test-strength suggestions (cell-position assertions) — all addressed pre-merge.

### FC-028: fmtDate calendar-date off-by-one (TZ shift on pure dates)
- PR: https://github.com/memon1987/options_wheel/pull/32 (merged 2026-05-07)
- Commit: `0c4d20d`
- Notes: Plan-exempt (single-file utility bug fix). User caught on Trade Log: OCC `UNH260424P00302500` (Apr 24 expiry) rendered "Apr 23" in the Expiration column. Root cause: `fmtDate()` parsed pure-date strings as UTC midnight then converted to ET (UTC−4) — rolled back to prior day. Same bug affected `event_date` Date column. Fix detects `YYYY-MM-DD`-shaped inputs and renders from year/month/day directly with no TZ conversion. Full ISO 8601 timestamps still ET-anchor per FC-022. 4 new vitests pin the contract; FC-022's ISO behavior verified preserved.

### FC-025: AMZN silent-exercise correction (paper-engine, Jan 16 2026)
- Plan: `docs/plans/fc-025.md`
- Investigation: `docs/investigations/amzn-reconciliation.md`
- Commit: `15625ce` (no PR — data-only correction direct to `main`, mirroring FC-021)
- Date: 2026-05-07
- Notes: Twin of FC-021's AMD silent-exercise bug. AMZN $240 put `AMZN260116P00240000` (sold 2026-01-12 at $0.73, expired 2026-01-16 with AMZN at $239.09 = $0.91 ITM) was auto-exercised silently — no OPASN/OPTRD ingested. Confirmed by behavioral evidence (Jan 23 covered call written, Apr 22 called-away at exact $240 strike). Inserted two synthetic rows into `options_wheel.trades_from_activities` (`activity_id LIKE 'synthetic-fc-025-%'`). Effect on AMZN scorecard: `share_side_pnl` +$20,500 → **−$3,500**, `total_realized_pnl` $26,206 → **$2,279**, `cycles_completed` 1 → 2, `wheel_minus_bh` +$21,094 → **−$2,833** (sign reversal — wheel actually lagged B&H on AMZN). Audit query: `WHERE activity_id LIKE 'synthetic-%'` (returns 4 rows: 2 FC-021 + 2 FC-025). Rollback: `DELETE WHERE activity_id LIKE 'synthetic-fc-025-%'`.

### FC-029: Wheel strategy Phase 1 risk re-tune (call delta + cost-basis floor + drawdown pause)
- Plan: `docs/plans/fc-029.md`
- Investigations: `docs/investigations/strategy-review-2026-05-07.md`, `docs/investigations/cost-basis-floor-validation-2026-05-08.md`
- PR: https://github.com/memon1987/options_wheel/pull/34 (merged 2026-05-08)
- Commit: `692f64e`
- Notes: Three complementary changes addressing the 3-loss-cycle pattern (-$9k share losses) found in the senior-trader strategy review. **R1**: tightened `call_delta_range` from `[0.30, 0.70]` to `[0.15, 0.25]` (calls 2-4% further OTM, 30-70% → 15-25% assignment probability). **R2**: cost-basis floor source-order rewrite — Alpaca's `cost_basis` returns 0 for assigned paper positions (both safety guards were gated on `> 0` and silently bypassed), now `CallSeller._resolve_cost_basis_floor` reads `wheel_state.stock_cost_basis` (canonical, populated from put strike at OPASN) → BQ lookup of last 90-day OPASN-put strike (handles silent assignments + cold starts; back-fills wheel_state) → Alpaca (last-resort fallback for non-wheel positions); when ALL three fail with shares > 0 the call write is blocked with `event_type=cost_basis_floor_unresolved` (operator intervention). **R3**: drawdown pause — skip covered call writes when shares ≥ 5% below cost basis with `event_type=covered_call_drawdown_pause`. Bad/missing quote now defers (`event_type=covered_call_quote_missing`) instead of failing-open. Two-reviewer process (new ~/CLAUDE.md rule for high-stakes changes) caught 4 HIGH + 3 MEDIUM the first review missed — see PR comments. Tests 27 in `TestCallSellerCostBasisFloorFC029`; 253/253 pytest green. Follow-up FC-030 filed for drawdown-pause observability metric.

### FC-019: True P&L reconciliation — JNLC + OPTRD ingest, share-side P&L
- Plan: `docs/plans/fc-019.md` (written retroactively)
- PR: https://github.com/memon1987/options_wheel/pull/19 (merged 2026-05-05)
- Commit: `78acf92` (preceded by `4862159` — interim env-var-baseline fix that this PR replaces with the real JNLC sum)
- Notes: Per-symbol scorecard now reconciles to actual account growth (sum of Total P&L = $21,808 vs account growth $20,080, with the ~$1,600 unexplained gap concentrated entirely on AMD's Alpaca-side data anomaly). New scorecard columns: Option P&L (renamed from Net P&L), Share P&L (FC-019), Total P&L (sum). `wheel_cycles_from_activities.capital_gain` now uses real OPTRD cash flow within the cycle window. `BASELINE_DEPOSITS` env var becomes a fallback only — primary source is `SUM(net_amount) WHERE activity_type='JNLC'`. Per-cycle pairing for overlapping share lots is filed as **FC-020** for follow-up.

### FC-031: Dashboard metrics overhaul — vetted portfolio metrics + bot execution health
- Plan: `docs/plans/fc-031.md`
- Investigations: `docs/investigations/dashboard-metrics-audit-2026-07-07.md` (per-metric methodology audit), `docs/investigations/fc-031-adversarial-review-2026-07-07.md` (adversarial PM review of the plan — 7 blockers incorporated pre-implementation)
- Merge: direct merge commit `1e8f622` to main (2026-07-07) — no PR: GitHub App not connected for the org this session; branch `claude/dashboard-metrics-review-k1ze5g`, commits `5fa2e48` (plan+audit), `7b5a718` (implementation), `14f299d` (adversarial code-review fixes)
- Notes: One accounting convention everywhere (net cash P&L + market value of holdings — the PM review caught that the draft's `(price − basis) × shares` add-back would have double-subtracted held-share cost, ~$24k error on AMD). Headline KPIs: Total P&L (realized cash / open value split), max drawdown (% + flow-adjusted $), XIRR labeled "annualized (single deposit)". TWR-indexed equity curve vs SPY; vs-B&H made symmetric (wheel MTM); FIFO open-lot basis + breakeven columns; cycle table RoC + $/day/$1k; separate put/call trade stats with held-to-expiry exercise-rate calibration vs live config delta bands (Symmetry Principle); net option cash flow bars. Bot Health: decision funnel, anomaly flags on the SPY-bar calendar, run reliability, drawdown-pause card (absorbs FC-030's dashboard half), falsifiable reconciliation banner (residual vs known gaps, share-count mismatch tracking). Removed: dead `win_rate`/`return_30d`, option-leg-only `/api/metrics/pnl-by-symbol`, fake freshness stamp, CAGR tile. Post-implementation 8-angle code review found + fixed 3 defects (cycle-stats fallback crash, unpopulated mismatch badge, /config not exposing threshold/bands) before merge. Tests 293 pytest + 72 vitest. **Post-merge manual steps pending:** re-apply `fc018_views.sql` + `fc031_views.sql` via bq, `POST /ingest-stock-history?backfill_days=400` (SPY), `POST /ingest-activities?after=2025-10-01` (FEE).

### FC-030: Drawdown-pause alerting — operator notification for extended pauses
- Plan: `docs/plans/fc-030.md`
- Runbook: `deploy/monitoring/drawdown_pause_alert.md`
- PRs: [#38](https://github.com/memon1987/options_wheel/pull/38) (endpoint + tests), [#40](https://github.com/memon1987/options_wheel/pull/40) (CI fix — FastAPI-free service module), [#41](https://github.com/memon1987/options_wheel/pull/41) + [#42](https://github.com/memon1987/options_wheel/pull/42) (alert-filter fix + closeout, **duplicate fixes — see note**)
- Date: 2026-07-18
- Notes: Scope was alerting only — the observability half shipped in FC-031. `POST /api/v2/bot-health/pause-alert-check` runs weekdays 17:45 ET and logs a single `DRAWDOWN_PAUSE_ALERT` line when any symbol is paused >= 7 trading days (threshold declared in `cloudbuild.yaml`); a Cloud Monitoring log-based policy emails the operator via the project's **first notification channel**. Built as a strict consumer of FC-031's `get_drawdown_pauses` — one implementation of pause state, not two. Degraded paths are loud: a live-positions outage logs `DRAWDOWN_PAUSE_ALERT_CHECK_FAILED` rather than reporting "nothing paused". **Cloud Build failure alerting shipped on the same channel** and was prioritized ahead of the pause alert — FC-031 had sat undeployed 11 days behind an unnoticed red build; the new alert then caught three real failures the same session. **The mandatory fire drill caught a fatal defect:** the policy's `severity>=WARNING` clause matched zero entries, because Cloud Run only assigns severity to structured JSON logs while Python's `logging.warning()` writes plain text — the alert would have been silent forever, discoverable only as a missing notification. Pure logic lives in `services/pause_alert.py` (the bot CI image has no FastAPI); a module-level `pytest.importorskip` was rejected after verifying it silently skips the pure tests too.
- Note on duplicate PRs: two parallel sessions independently found and fixed the same severity-filter defect (#41 and #42). The same collision duplicated this file's entire Completed section, repaired in `fix/dedupe-fc-ledger`. No code conflict resulted; the fixes were equivalent.
- **Operator action outstanding:** confirm the alert email lands (Cloud Monitoring channels may need one-time verification).
