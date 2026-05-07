# AMZN End-to-End Reconciliation — 2026-05-07

**Triggered by:** User question — "wheel P&L on AMZN really high, please reconcile against raw Alpaca." Dashboard shows AMZN total_realized_pnl = **$26,206** (top of all 7 symbols), but FC-025 (filed 2026-05-07) had already identified that AMZN has the same Alpaca paper-engine silent-exercise bug as AMD (FC-021). This document reconciles every dashboard surface against a fresh activity-feed pull.

**Scope:** 76 raw activities from `/v2/account/activities` for AMZN (paper account), 2025-10-13 → 2026-05-06.

**TL;DR:** Dashboard's $26,206 is **inflated by ~$24,000** because the Jan 16, 2026 silent-assignment leg of Cycle 2 isn't ingested. True realized P&L is **$2,279** = option +$5,779 + share −$3,500. AMZN went from "best symbol" ($26.2k) to mid-pack ($2.3k) once silent-assignment is corrected. Wheel lagged B&H by ~$2,833 on this name once the bug is fixed (currently overstated as +$21,094).

---

## Activity Inventory (76 events from Alpaca)

| Phase | Window | Events | Description |
|---|---|---:|---|
| 0 | Oct 13 – Oct 31 | 8 | Pre-cycle 1: 4 puts sold, all closed early |
| **Cycle 1** | Nov 4 – Nov 28 | 21 | Put assigned $247.5 → 9 covered calls (8 rolled, 1 called away at $212.5) |
| 1.5 | Dec 4 – Jan 6 | 14 | 7 puts sold, all closed early (no assignments) |
| **Cycle 2 (silent)** | Jan 12 – Apr 22 | 19 | Put silently assigned $240 (Jan 16) → 8 covered calls (7 rolled, 1 called away at $240). **NO OPASN/OPTRD ingested for Jan 16.** |
| Post-cycle | Apr 23 – May 6 | 14 | 7 puts sold, all closed early |

Activity-type breakdown: **27 sell_shorts** (20 puts + 7 calls — wait, recount: 4 pre + 1 cycle-1-put + 7 phase-1.5 + 1 cycle-2-put + 7 post = 20 puts; 9 cycle-1 calls + 8 cycle-2 calls = 17 calls; total 37). **33 buybacks** (puts + calls closed early). **2 OPASN puts** wait — only 1 OPASN put (Cycle 1 Nov 7) is in the raw feed; Cycle 2 Jan 16 is the missing one. **2 OPASN calls** (Nov 28, Apr 22). **2 OPTRD events** (Nov 7 +100 / Nov 28 −100 / Apr 22 −100 — actually 3 OPTRDs, but only 1 is "buy" direction). Let me reconcile: Cycle 1 OPTRD-in (+100) + Cycle 1 OPTRD-out (−100) + Cycle 2 OPTRD-out (−100, no matching OPTRD-in) = **3 OPTRDs total.**

Confirmed counts via dashboard:
- `trade_count = 37` ✓ (sell_shorts; matches my 20 puts + 17 calls)
- `early_close_count = 33` ✓
- `put_assignment_count = 1` (should be 2 after FC-025)
- `called_away_count = 2` ✓ (the orphan Apr 22 called-away that has no matching put_assigned in BQ)
- `open_count = 1` ✓ (the Jan 12 $240 put with `outcome='open'` despite expiring 4 months ago — the smoking gun)

---

## Phase 0: Pre-Cycle 1 Pure Puts (Oct 13 – Oct 31)

| # | Sold | Strike/Exp | Premium in | Bought back | Cost out | **Net** |
|---|---|---|---:|---|---:|---:|
| 1 | Oct 13 | $210 / Oct 17 | +$78 | Oct 15 @ $0.47 | −$47 | **+$31** |
| 2 | Oct 22 | $212.5 / Oct 24 | +$75 | Oct 23 @ $0.15 | −$15 | **+$60** |
| 3 | Oct 23 | $205 / Oct 31 | +$230 | Oct 24 @ $1.35 | −$135 | **+$95** |
| 4 | Oct 27 | $212.5 / Oct 31 | +$205 | Oct 31 @ $0.02 | −$2 | **+$203** |

**Phase 0 net: +$389** (premium in $588, buybacks $199)

---

## Cycle 1: Nov 4 – Nov 28 (AMZN tanks $247.5 → $212.5)

### Entry
- Nov 4: Sold $247.5 put @ $1.12 → +$112
- Nov 7: OPASN put → assigned. **Cash out: −$24,750.** Premium $112 kept.

### 9 Covered Calls (rolling lower as price falls)
The 8-roll sequence below shows the bot chasing the falling stock — each call is bought back at a loss-or-near-breakeven and a new lower-strike call sold.

| Call # | Sold | Strike | Sell prem | Buy-back | Buy prem | Net |
|---|---|---:|---:|---|---:|---:|
| 1 | Nov 11 | $247.5 | $410 | Nov 12 | $144 | +$266 |
| 2 | Nov 12 | $242.5 | $390 | Nov 13 | $194 | +$196 |
| 3 | Nov 13 | $237.5 | $805 | Nov 13 | $660 | +$145 |
| 4 | Nov 14 | $230 | $810 | Nov 17 | $420 | +$390 |
| 5 | Nov 17 | $225 | $745 | Nov 18 | $410 | +$335 |
| 6 | Nov 18 | $220 | $725 | Nov 19 | $297 | +$428 |
| 7 | Nov 19 | $217.5 | $585 | Nov 20 | $315 | +$270 |
| 8 | Nov 20 | $215 | $750 | Nov 21 | $595 | +$155 |
| 9 | Nov 21 | $212.5 | $760 | (called away Nov 28) | — | +$760 |

**Cycle 1 call sums:** Sells $5,980, buybacks $3,035 → Net $2,945

### Termination
- Nov 28: OPASN call $212.5 → called away. **Cash in: +$21,250.** Premium $760 kept.

### Cycle 1 P&L
- **Option leg:** $112 (put kept) + $2,945 (calls net) = **+$3,057**
- **Share leg:** −$24,750 + $21,250 = **−$3,500**
- **Cycle 1 net: −$443**

(AMZN's price drop overwhelmed the option premium take.)

---

## Phase 1.5: Inter-cycle Pure Puts (Dec 4 – Jan 6)

7 puts sold; all closed early; 1 (Jan 12) opens Cycle 2.

| # | Sold | Strike | Premium in | Bought back | Cost out | Net |
|---|---|---:|---:|---|---:|---:|
| 1 | Dec 4 | $220 | $130 | Dec 4 | −$101 | +$29 |
| 2 | Dec 4 | $220 | $103 | Dec 5 | −$63 | +$40 |
| 3 | Dec 5 | $222.5 | $106 | Dec 10 | −$28 | +$78 |
| 4 | Dec 10 | $225 | $62 | Dec 11 | −$26 | +$36 |
| 5 | Dec 12 | $220 | $103 | Dec 18 | −$25 | +$78 |
| 6 | Dec 18 | $220 | $96 | Dec 19 | −$64 | +$32 |
| 7 | Jan 6 | $232.5 | $80 | Jan 6 | −$38 | +$42 |

**Phase 1.5 net: +$335** (premium in $680, buybacks $345)

---

## Cycle 2: Jan 12 – Apr 22 — **THE SILENT-EXERCISE CYCLE** (FC-025)

### Entry (and the smoking gun)
- **Jan 12: Sold `AMZN260116P00240000` @ $0.73 → +$73 premium.** Expires Jan 16, 2026.
- **Jan 16: AMZN closes at $239.09 — $0.91 ITM.** Standard option settlement auto-exercises ITM puts at expiry.
- **NO OPASN/OPTRD ingested for Jan 16.** Per `trades_with_outcomes` the put is still `outcome='open'` four months later — impossible since the contract has expired.

### Behavioral evidence the silent assignment occurred
- Jan 23: Bot sells $240C `AMZN260130C00240000` @ $2.83. Could not have done this without holding shares — the bot's `wheel_engine` requires shares ≥ 100 before selling covered calls.
- Apr 22: OPTRD `AMZN −100 @ $240, net = +$24,000` followed by OPASN call. Strike-to-strike round-trip suggests cost basis was $240 — **exactly the strike of the missing assignment**.

This is the same Alpaca paper-engine bug as FC-021's AMD silent exercise. Cross-symbol detector query (`outcome='open' AND expiration < CURRENT_DATE()`) returned ONLY this row across all 7 symbols.

### 8 Covered Calls (during silent share-holding)

| Call # | Sold | Strike | Sell prem | Buy-back | Buy prem | Net |
|---|---|---:|---:|---|---:|---:|
| 1 | Jan 23 | $240 | $283 | Jan 29 | $109 | +$174 |
| 2 | Jan 29 | $240 | $790 | Feb 5 | $450 | +$340 |
| 3 | Feb 5 | $240 | $475 | Feb 6 | $11 | +$464 |
| (gap Feb 6 – Apr 10: ~62 days no call activity, shares held idle) | | | | | | |
| 4 | Apr 10 | $240 | $430 | Apr 10 | $340 | +$90 |
| 5 | Apr 10 | $240 | $335 | Apr 13 | $224 | +$111 |
| 6 | Apr 13 | $240 | $291 | Apr 14 | $1,155 | **−$864** |
| 7 | Apr 15 | $245 | $530 | Apr 16 | $310 | +$220 |
| 8 | Apr 16 | $240 | $725 | (called away Apr 22) | — | +$725 |

The Apr 14 buy at $11.55 (call #6) is a **−$864 single-position loss** — AMZN spiked through the $240 strike and the bot bought to close at deep ITM before letting it get assigned. Note this didn't actually prevent assignment — it just rolled into a higher strike ($245) which then also got bought back, ending at $240 (call #8) which was called away anyway.

**Cycle 2 call sums:** Sells $3,859, buybacks $2,599 → Net $1,260

### Termination
- Apr 22: OPTRD `AMZN −100 @ $240, net = +$24,000`. OPASN call $240 → called away. Premium $725 kept.

### Cycle 2 P&L
- **Option leg:** $73 (put kept on silent assignment) + $1,260 (calls net) = **+$1,333**
- **Share leg (true):** −$24,000 (silent assignment) + $24,000 (Apr 22 called away) = **$0** (clean round-trip)
- **Share leg (current dashboard, missing the silent OPTRD-in):** $0 + $24,000 = **+$24,000**
- **Cycle 2 net (true): +$1,333**

This cycle was **profitable** despite a 96-day duration through significant AMZN volatility (Apr 14 −$864 day notwithstanding).

---

## Post-Cycle: Apr 23 – May 6 Pure Puts

7 puts sold; all closed early.

| # | Sold | Strike | Premium in | Bought back | Cost out | Net |
|---|---|---:|---:|---|---:|---:|
| 1 | Apr 23 | $237.5 | $283 | Apr 24 | $184 | +$99 |
| 2 | Apr 27 | $242.5 | $264 | Apr 30 | $18 | +$246 |
| 3 | Apr 30 | $250 | $141 | Apr 30 | $65 | +$76 |
| 4 | May 1 | $260 | $135 | May 4 | $69 | +$66 |
| 5 | May 4 | $262.5 | $118 | May 4 | $62 | +$56 |
| 6 | May 4 | $265 | $117 | May 5 | $47 | +$70 |
| 7 | May 5 | $267.5 | $126 | May 6 | $74 | +$52 |

**Post-cycle net: +$665** (premium in $1,184, buybacks $519)

---

## Grand Reconciliation

### Total option-side P&L (closed positions only — excludes the still-"open" Jan 12 put per dashboard's view)

| Phase | Net | Running |
|---|---:|---:|
| Phase 0 (pre-cycle 1 puts) | +$389 | +$389 |
| Cycle 1 option leg ($112 put + $2,945 calls) | +$3,057 | +$3,446 |
| Phase 1.5 (inter-cycle puts) | +$335 | +$3,781 |
| Cycle 2 option leg — **excludes Jan 12 $73** (still "open") | +$1,260 | +$5,041 |
| Post-cycle puts | +$665 | **+$5,706** |

Confirmed against dashboard's `realized_pnl`: **$5,706** ✓

### Add the Jan 12 put if it were properly recorded as assigned (FC-025 impact)
- Jan 12 put kept on silent assignment: **+$73**
- **Truth-side option leg: $5,706 + $73 = $5,779**

### Total share-side P&L

| Event | Cash flow | Status |
|---|---:|---|
| Nov 7 OPTRD (Cycle 1 acquisition) | −$24,750 | ✓ ingested |
| Nov 28 OPTRD (Cycle 1 disposition) | +$21,250 | ✓ ingested |
| **Jan 16 OPTRD (Cycle 2 acquisition, SILENT)** | **−$24,000** | **❌ missing** |
| Apr 22 OPTRD (Cycle 2 disposition) | +$24,000 | ✓ ingested |

- **Currently ingested net: −$24,750 + $21,250 + $24,000 = +$20,500** (matches dashboard's `share_side_pnl`)
- **Truth (with the missing Jan 16 leg): −$24,750 + $21,250 − $24,000 + $24,000 = −$3,500**
- **Bug magnitude: +$24,000** (the missing OPTRD-in)

### Per-cycle truth

| Cycle | Option leg | Share leg | Cycle P&L |
|---|---:|---:|---:|
| Cycle 1 (Nov 4 → Nov 28) | +$3,057 | −$3,500 | **−$443** |
| Cycle 2 (Jan 12 → Apr 22) — silent | +$1,333 | $0 | **+$1,333** |
| Σ wheel cycles | +$4,390 | −$3,500 | **+$890** |
| Σ pure-put cycles (Phase 0 + 1.5 + post) | +$1,389 | $0 | **+$1,389** |
| **GRAND TOTAL** | **+$5,779** | **−$3,500** | **+$2,279** |

---

## Dashboard Surface Comparison (Current vs. Truth vs. Post-FC-025)

| Surface | Current dashboard | True (Alpaca) | After FC-025 correction | Δ vs truth |
|---|---:|---:|---:|---:|
| `realized_pnl` (option leg) | $5,706 | $5,779 | $5,779 | dashboard −$73 |
| `share_side_pnl` | **+$20,500** | **−$3,500** | −$3,500 | **dashboard +$24,000** |
| `total_realized_pnl` | **$26,206** | **$2,279** | $2,279 | **dashboard +$23,927** |
| `total_premium` (gross) | $12,476 | $12,476 | $12,476 | unchanged |
| Top "Realized P&L" card | $26,206 | $2,279 | $2,279 | inflated $23,927 |
| Wheel-vs-B&H "Wheel" total | $26,206 | $2,279 | $2,279 | inflated $23,927 |
| Wheel-vs-B&H "Δ vs B&H" | **+$21,094** | **−$2,833** | −$2,833 | inflated $23,927; **flips sign** |
| Cycles Completed | 1 | 2 | 2 | dashboard −1 |
| `cycles_completed` count | 1 | 2 | 2 | missing Cycle 2 |
| `put_assignment_count` | 1 | 2 | 2 | missing Jan 16 |
| `open_count` | 1 (the orphan Jan 12) | 0 | 0 | should be 0 |
| Cycle Table rows | 1 | 2 | 2 | only shows Cycle 1; Cycle 2 invisible |
| ACB Walk yellow line segments | 1 (Cycle 1 only) | 2 | 2 | Cycle 2 line missing |
| ACB Walk reference dots | 73 | 75 | 75 | missing Jan 16 OPASN+OPTRD-folded dot |
| Trade Log row count | 73 | 75 | 75 | (or 76 if OPTRD rendered separately) |
| Phase Timing share-holding days | ~21 (Cycle 1 only) | ~117 (21 + 96) | ~117 | missing ~96 days |
| Decision Quality Received | $12,403 (excludes open $73) | $12,476 | $12,476 | dashboard −$73 |
| Decision Quality Captured | $5,706 | $5,779 | $5,779 | dashboard −$73 |
| Decision Quality Foregone | $6,697 | $6,697 | $6,697 | unchanged |
| Decision Quality capture rate | 46.0% | 46.3% | 46.3% | barely changes |

### The big picture
- **Direction reversal on "Δ vs B&H":** currently shows AMZN's wheel beat buy-and-hold by **+$21,094** (looks great). True direction is wheel **lagged** B&H by **$2,833** (a real but small loss to a passive strategy).
- **AMZN's "best-in-portfolio" status is illusory.** The dashboard ranks AMZN #1 by total_realized_pnl ($26,206). Post-correction it drops to mid-pack ($2,279) and ranks behind UNH ($2,584).

---

## Sanity-checks against raw data

- **Total premium received** (gross, all 37 sells): $12,476 ✓ matches `total_premium` exactly
- **Put premium**: 4 pre-cycle ($588) + 1 Cycle 1 entry ($112) + 7 phase 1.5 ($680) + 1 Cycle 2 entry ($73) + 7 post-cycle ($1,184) = **$2,637** ✓ matches dashboard
- **Call premium**: 9 Cycle 1 ($5,980) + 8 Cycle 2 ($3,859) = **$9,839** ✓ matches dashboard
- **Total buybacks** (foregone): 4 ($199) + 7 ($345) + 8 Cycle 1 ($3,035) + 7 Cycle 2 ($2,599) + 7 post ($519) = **$6,697** ✓ matches Decision Quality Foregone
- **Sells − Buys = Realized + Open**: $12,476 − $6,697 = $5,779 (= realized $5,706 + open $73) ✓

Every aggregated number on the dashboard maps exactly to a sum I can derive from the 76 raw activities. **There is no math error.** The error is one missing pair of activities (Jan 16 OPASN put + Jan 16 OPTRD-in), which propagates into ~$24k of mis-attribution across multiple surfaces.

---

## Conclusion & recommendation

**Conclusion:** AMZN's headline number is wrong by ~$24,000. The bug is data-completeness, not math. The `wheel_cycles_from_activities` view and all derivative surfaces are working correctly given the data they're fed; they're just being fed an incomplete activity stream.

**Recommendation:** Execute FC-025 (`docs/plans/fc-025.md` not yet drafted — but the plan template is FC-021's `docs/plans/fc-021.md`). Insert two synthetic rows into `options_wheel.trades_from_activities`:

```sql
-- Synthetic OPASN put for the silent Jan 16 assignment
INSERT INTO `options_wheel.trades_from_activities` ...
  (activity_id = 'synthetic-fc-025-opasn-AMZN260116P00240000',
   activity_type = 'OPASN', symbol = 'AMZN260116P00240000',
   underlying = 'AMZN', option_type = 'put', strike_price = 240,
   qty = 1, transaction_time = '2026-01-16 21:00:00 UTC', ...)

-- Synthetic OPTRD for the corresponding share acquisition
INSERT INTO `options_wheel.trades_from_activities` ...
  (activity_id = 'synthetic-fc-025-optrd-AMZN-2026-01-16',
   activity_type = 'OPTRD', symbol = 'AMZN', underlying = 'AMZN',
   qty = 100, price = 240, net_amount = -24000,
   transaction_time = '2026-01-16 21:00:00 UTC', ...)
```

Audit query: `SELECT * FROM trades_from_activities WHERE activity_id LIKE 'synthetic-fc-025-%'`
Rollback: `DELETE WHERE activity_id LIKE 'synthetic-fc-025-%'`

Predicted post-fix dashboard values are in the table above (the "After FC-025 correction" column).

**Effort:** ~30 minutes. Same shape as FC-021. Plan-driven (data-only correction).

---

## Appendix: raw activity dump

Saved at `/tmp/amzn-alpaca-raw.json` (76 records, full `/v2/account/activities` response payload). Re-pull with:

```bash
python3 -c "..."  # see session 2026-05-07 walkthrough for the full puller
```
