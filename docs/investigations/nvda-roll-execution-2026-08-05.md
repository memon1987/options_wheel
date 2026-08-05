# NVDA Roll Execution Analysis — Two STO Orders, One Canceled, Fill Above Limit (2026-08-05)

**Author:** Claude (analyst persona)
**Date:** 2026-08-05
**Scope:** Execution-path forensics of the 2026-08-05 end-of-day NVDA covered-call roll
**Trigger:** Operator observation — "the sell side submitted two orders, one of which was
cancelled. The fill price ended up being higher than the limit price which would imply
there was some volatility towards the end of the trading day."
**Evidence status:** ⚠️ Code-path reconstruction. This analysis was produced in an
environment without GCP or Alpaca credentials, so it maps the observed broker-side facts
onto the only code path that can produce them, and lists the log queries that confirm
(or falsify) each step. The discriminating observables are called out explicitly.

---

## TL;DR

**All three observations are the FC-078 roller's STO ladder behaving exactly as designed.
No anomaly, no violated invariant, and — importantly — no adverse fill.**

1. **Two sell orders** = ladder rung 1 and rung 2 of `CallRoller._attempt_stc`
   (`src/strategy/call_roller.py:885`). Rung 1 rested unfilled for the 120-second fill
   window; the ladder then moved to a lower-priced rung 2.
2. **One canceled** = the mandatory cancel-and-settle between rungs
   (`call_roller.py:1127`). The ladder's core invariant is *at most one live STO at any
   instant* — rung 1 is canceled and **verified zero-fill** before rung 2 may be placed.
   The canceled order in the Alpaca blotter is that verification succeeding.
3. **Fill above the limit** = ordinary limit-order price improvement on rung 2, not
   volatility. Rung 2 is deliberately priced *below the market* (at the invariant floor:
   BTC fill price + `min_net_credit_per_contract`), so it crosses the spread and prints
   at the standing NBBO bid — which is at or **above** the limit. A sell limit can only
   ever fill at limit-or-better; a fill through the limit in the adverse direction is
   impossible. The gap between limit and fill measures how far below the market rung 2
   was priced, not how much the market was moving.

The volatility hypothesis is at most half right: end-of-day movement is one of two
candidate explanations for why **rung 1 missed** (see §4), but the fill-above-limit on
rung 2 is structural and would occur on a dead-calm tape too.

---

## 1. The execution path, step by step

The 15:30 ET scheduled `/roll` cycle (`deploy/cloud_run_server.py:1168`, lock-serialized
against `/monitor` and `/run`) drives one pass of `CallRoller` per short call. For a roll
that reaches completion with the observed two-sells-one-cancel signature, the sequence
is:

| # | Time (approx) | Action | Code |
|---|---------------|--------|------|
| 1 | 15:30 | Evaluate: NVDA short call ITM (stock/strike ≥ 0.98), pick max-net-credit replacement from the legal set | `evaluate_roll_opportunity`, `call_roller.py:207` |
| 2 | 15:30 | Pre-BTC re-check: re-quote the replacement, recompute the STO limit, re-test the credit invariant | `call_roller.py:588-607` |
| 3 | 15:30 | **Leg 1:** BTC limit order placed on the old call | `call_roller.py:619` |
| 4 | 15:30–15:32 | Poll to terminal (5s interval, 120s bound). BTC fills — a buy limit fills at ≤ its limit, often better | `_poll_order_fill`, `call_roller.py:1085` |
| 5 | ~15:32 | **Leg 2, rung 1:** STO placed on the replacement at the step-2 limit — **this is sell order #1** | `_place_stc`, `call_roller.py:1034` |
| 6 | 15:32–15:34 | Rung 1 polls for 120s without reaching a terminal status → carried as `live` | `call_roller.py:922-927` |
| 7 | ~15:34 | Ladder advances: **cancel rung 1, then poll until the broker settles it** (≤15s). Settles `canceled`, `filled_qty=0` — **this is the canceled order** | `_settle_live_rung` → `_cancel_and_settle`, `call_roller.py:1000, 1127` |
| 8 | ~15:34 | **Rung 2:** STO placed at the floor price = BTC fill + `min_net_credit_per_contract` ($0.00) — **this is sell order #2**, priced below rung 1 by construction | `_rungs`, `call_roller.py:969-976` |
| 9 | ~15:34 | Rung 2 is marketable (limit below the standing bid) → fills immediately at the NBBO, i.e. **at or above its limit** | — |
| 10 | ~15:34 | `call_roll_completed` emitted with **actual** fill prices; `net_credit = (STO fill − BTC fill) × qty × 100` | `call_roller.py:801` |

Wall-clock: roughly 15:30–15:36 ET — "towards the end of the trading day", matching the
operator's observation and yesterday's GOOGL precedent (`call_roll_completed` at
19:32:40Z on 2026-08-04).

## 2. Why two sell orders — the ladder is the retry mechanism

`_attempt_stc` exists precisely because a single STO attempt after a filled BTC is
fragile: the BTC has already been paid for, so a sell that never fills strands the debit
(the `call_roll_naked_exposure` terminal). The ladder retries at progressively more
executable prices while never breaching the credit invariant:

- **Rung 1** — the primary candidate at the pre-BTC re-checked limit (best price).
- **Rung 2** — the *same* contract at the invariant minimum:
  `btc_filled_price + min_credit`, emitted only when that is strictly below rung 1's
  limit (`call_roller.py:975`). With `min_net_credit_per_contract: 0.00`
  (`config/settings.yaml:181`), rung 2's limit is **exactly what the BTC cost**.
- **Rungs 3+** — up to `fallback_strike_attempts: 2` alternate candidates, re-quoted and
  re-validated.

Two sell orders means the ladder stopped at rung 2 — the common case, and the *intended*
degradation: give the good price two minutes to fill, then take the market rather than
strand the BTC.

## 3. Why one was canceled — the one-live-sell invariant

The cancel is not an error or a change of mind; it is the load-bearing safety step. Two
live sells against one covered lot means a late fill on the first while the second works
creates a **genuine naked short call**. So every rung transition is
cancel-then-**settle**: cancel rung 1, then poll until the broker reports a terminal
status, because Alpaca cancels are queued (`pending_cancel` can still fill —
FC-078 review H-1). Only a verified `canceled / filled_qty=0` lets rung 2 be placed. Had
the cancel lost the race to a fill, that would have been reported as rung 1 *succeeding*
and no second order would exist.

**Observability note:** this settle outcome is silent in the event stream — the
`(None, True)` path of `_settle_live_rung` (`call_roller.py:1032`) emits nothing. The
log signature of a rung transition is just two consecutive `call_roll_stc_placed`
events; the cancel itself is only visible broker-side. See §7 item 1.

## 4. Why rung 1 didn't fill — two candidate mechanisms

Which one applies is decided by `pricing_mode` on the `call_roll_evaluated` event:

**(a) Imminence mode (`pricing_mode=imminence`) — no volatility required.** If the old
call's extrinsic was ≤ $0.20/share (likely for a deep-ITM NVDA call at 15:30), limits
are mid-based: STO at `mid − $0.05` (`call_roller.py:539`). Whenever the replacement's
spread exceeds $0.10, `mid − 0.05` sits **above the bid** — a non-marketable resting
order that needs a buyer to step up. On a quiet tape it simply sits for 120 seconds.
This is the highest-prior-probability explanation.

**(b) Base mode (`pricing_mode=base`) — staleness/movement required.** Base mode sells
at the **bid**, which is marketable and should fill near-instantly — *at the quoted
price*. But that quote is captured at the pre-BTC re-check (step 2), and the order is
placed only after the BTC poll completes — up to two minutes later
(`call_roller.py:588` vs `:722`). If the replacement call's bid dropped in that window
(NVDA fading into the close, or spread widening), rung 1's limit is above the new bid
and rests. This is the scenario where the operator's volatility intuition is genuinely
the cause.

Either way, rung 2's floor price (= BTC cost) sat below the then-current bid, crossed
the spread, and filled with price improvement.

## 5. Was the trade harmed? No — the invariant held on every placed limit

- Rung 2's limit is the invariant floor, so the worst possible completed outcome was
  net credit = `min_net_credit_per_contract` = **$0.00** on the placed limits.
- Both legs are limit orders, so fills only improve: BTC filled ≤ its limit, STO filled
  ≥ its limit. **A filled roll cannot net a debit** (module invariant,
  `call_roller.py:10-15`).
- The fill-above-limit the operator saw is that improvement materializing: the realized
  credit is `STO fill − BTC fill`, and the amount by which the fill beat rung 2's limit
  is *extra* credit above the $0 floor.

The honest caveat: with the floor at $0.00, the *guaranteed* credit on rung 2 is zero,
and the realized credit was delivered by NBBO price improvement rather than by the
placed limit. That is a config posture, not a bug — see §7 item 3.

## 6. Verification checklist (run with production access)

1. **Event sequence** — expect, in order for the NVDA option symbols:
   `call_roll_evaluated` → `call_roll_btc_placed` → `call_roll_btc_filled` →
   `call_roll_stc_placed` (×2) → `call_roll_stc_filled` → `call_roll_completed`:

   ```bash
   gcloud logging read 'jsonPayload.event_type=~"call_roll_" AND jsonPayload.underlying="NVDA"' \
     --freshness=1d --order=asc \
     --format='value(timestamp, jsonPayload.event_type, jsonPayload.symbol, jsonPayload.limit_price, jsonPayload.filled_price, jsonPayload.pricing_mode, jsonPayload.net_credit)'
   ```

2. **Discriminators:**
   - `pricing_mode` on `call_roll_evaluated` → decides §4(a) vs §4(b).
   - Second `call_roll_stc_placed.limit_price` **== `call_roll_btc_filled.filled_price`**
     → confirms rung 2 was the same-symbol floor rung (expected). If the second
     `stc_placed` has a *different symbol*, the ladder skipped to a fallback strike
     instead (rung 3), which would mean the floor condition `floor < rung-1 limit`
     failed — worth a closer look at the BTC fill.
   - Gap between the two `call_roll_stc_placed` timestamps ≈ 120s poll + ≤15s settle.
3. **Broker blotter:** canceled sell = rung 1 (`canceled`, `filled_qty=0`); filled sell
   = rung 2 with `filled_avg_price ≥ limit_price`. Confirm **no** residual open order on
   either leg's symbol (roll-alert triage step 2,
   `deploy/monitoring/roll_executed_alert_policy.json`).
4. **BigQuery:** both fills present in `options_wheel.trades_from_activities` after the
   next 15-minute ingest; assert new strike > old strike, new strike ≥ Alpaca
   `avg_entry_price`, and `STO fill − BTC fill ≥ 0`.
5. **One check that matters if the operator's comparison was against rung 1's limit:**
   if the *filled* price exceeded even the **canceled** order's (higher) limit, the
   market popped upward in the seconds between the cancel and rung 2's fill — that
   *would* be direct evidence of end-of-day volatility, and mildly unlucky sequencing
   (rung 1 would have filled had it lived seconds longer). Structurally harmless either
   way, but it distinguishes "market came up to us late" from "we crossed down to the
   market."

## 7. Findings & follow-ups (none urgent)

1. **Silent rung-cancel settle (observability gap).** A rung that cancels clean emits no
   event — the operator discovered the canceled order from the broker side, not from
   logs. A small `call_roll_stc_rung_canceled` info event (order_id, rung index, limit,
   settle latency) would make the ladder's most common transition self-describing.
   Candidate FC, size S.
2. **Rung-1 staleness window (base mode only).** The STO limit is priced before the BTC
   is placed and used up to ~2 minutes later. Re-quoting between BTC fill and rung-1
   placement (taking `max(fresh limit, floor)`) would shrink the miss rate at zero risk
   to the invariant. Only worth doing if §6's discriminator shows base mode; in
   imminence mode rung 1 is above-bid by design.
3. **Rung 2 guarantees only $0.00 with the current floor.** `min_net_credit_per_contract:
   0.00` means the ladder's fallback price concedes the entire screened credit and relies
   on price improvement for the realized gain. If repeated rolls show rung 2 doing the
   filling, consider a small positive floor (e.g. $5–10/contract) — it prices the retry
   instead of giving it away. Interacts with FC-072 (call-side pricing economics).
4. **FC-080 tie-in (duration drift).** This NVDA roll extends the expiry by ≤14 days
   from the *current* contract. NVDA trending like GOOGL did on 2026-08-04 will
   re-trigger daily roll candidates and ratchet the horizon (3→31 DTE in one day for
   GOOGL). Today's roll is another data point for the FC-080 evaluation — log it there
   as part of the "live chain as it plays out" research.

## Links

- `docs/plans/fc-078.md` — the roller rails as built (credit-only invariant, ladder,
  cancel-and-settle doctrine)
- `docs/FUTURE_CONSIDERATIONS.md` §FC-080 — duration drift bookmark (2026-08-04)
- `docs/releases/RELEASE_2026-08-04.md` — first production roll (GOOGL) and the
  execution-hazard notes this analysis leans on
- `deploy/monitoring/roll_executed_alert_policy.json` — operator triage runbook for
  every roll terminal event
