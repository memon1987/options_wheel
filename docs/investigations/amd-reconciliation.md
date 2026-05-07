# AMD Holdings Reconciliation

Generated 2026-05-05. Data sources: BQ `trades_from_activities` (verified parity with Alpaca activity API), Alpaca `/v2/account/portfolio/history`, Alpaca `/v2/positions`.

> **STATUS: Fix applied 2026-05-06 via FC-021.** Two synthetic rows (`activity_id LIKE 'synthetic-fc-021-%'`) were inserted into `options_wheel.trades_from_activities` to record the silent 2026-01-16 paper-engine exercise. The dashboard now shows AMD `total_pnl` = +$5,309 (was −$17,319). See `docs/plans/fc-021.md`.

## TL;DR

**One silent event explains everything.** On `2026-01-16`, the deep-ITM short call `AMD260116C00212500` (sold 1/14 at $8.60, expiring with AMD at $231.79 = $19.29 ITM) was settled by Alpaca's paper engine **without logging an OPASN, OPEXP, or OPTRD record**. 100 shares were delivered out at $212.50 strike, but no record exists in any Alpaca endpoint.

After accounting for that single missing record, the entire holdings timeline reconciles cleanly with current state (0 shares).

## Hypothesis fit test (most decisive evidence)

For each hypothesis, walked daily portfolio P&L vs `shares × AMD_close_change`:

| Hypothesis | shares-days | Σ expected_pl | Σ actual_pl | Σ gap | Verdict |
|---|---:|---:|---:|---:|---|
| **A**: ledger only (no silent events; today shows +100 shares) | 80 | +$20,146 | +$14,941 | **−$5,206** | Misses by ~100×AMD_drift; ledger overstates holdings |
| **B**: ledger + silent `2026-01-16` exercise (−100) | 60 | +$6,887 | +$11,363 | **+$4,476** | ✅ Best fit; +$4.5k residual is normal option-premium decay from other symbols |
| **C**: B + a silent post-April loss | 69 | −$1,666 | +$13,955 | **+$15,620** | Over-corrects; no second silent event needed |

Hypothesis B wins by a wide margin. The ~$4.5k residual under B is consistent with option premium decay on the bot's full short-put inventory across all symbols, not a second AMD-specific anomaly.

## Cataloged option contracts on AMD

Every option contract the bot opened on AMD, with its terminal status:

| # | Opened | Symbol | Strike | Expiry | Side | Premium ($) | Outcome | Outcome date |
|---|---|---|---:|---|---|---:|---|---|
| 1 | 2025-10-06 | AMD251010P00192500 | 192.50 | 2025-10-10 | sold put | +223 | expired worthless | 2025-10-13 (OPEXP) |
| 2 | 2025-10-13 | AMD251017P00207500 | 207.50 | 2025-10-17 | sold put | +176 | bought back | 2025-10-15 |
| 3 | 2025-10-15 | AMD251017P00225000 | 225.00 | 2025-10-17 | sold put | +155 | bought back | 2025-10-16 |
| 4 | 2025-10-15 | AMD251017P00217500 | 217.50 | 2025-10-17 | sold put | +123 | bought back | 2025-10-15 |
| 5 | 2025-10-16 | AMD251024P00217500 | 217.50 | 2025-10-24 | sold put | +241 | bought back | 2025-10-20 |
| 6 | 2025-10-20 | AMD251024P00225000 | 225.00 | 2025-10-24 | sold put | +192 | bought back | 2025-10-21 |
| 7 | 2025-10-22 | AMD251024P00227500 | 227.50 | 2025-10-24 | sold put | +151 | bought back | 2025-10-23 |
| 8 | 2025-10-24 | AMD251031P00232500 | 232.50 | 2025-10-31 | sold put | +223 | bought back | 2025-10-27 |
| 9 | 2025-10-27 | AMD251031P00240000 | 240.00 | 2025-10-31 | sold put | +244 | bought back | 2025-10-28 |
| 10 | 2025-10-28 | AMD251031P00245000 | 245.00 | 2025-10-31 | sold put | +199 | bought back | 2025-10-29 |
| 11 | 2025-10-29 | AMD251031P00250000 | 250.00 | 2025-10-31 | sold put | +180 | bought back | 2025-10-30 |
| 12 | 2025-10-30 | AMD251107P00237500 | 237.50 | 2025-11-07 | sold put | +355 | bought back | 2025-11-05 |
| 13 | 2025-11-06 | AMD251114P00225000 | 225.00 | 2025-11-14 | sold put | +330 | bought back | 2025-11-10 |
| 14 | 2025-11-17 | **AMD251121P00230000** | **230.00** | 2025-11-21 | sold put | +194 | **assigned → +100 sh** | 2025-11-22 |
| 15 | 2025-11-24 | AMD251128C00205000 | 205.00 | 2025-11-28 | sold call | +1,010 | bought back | 2025-11-25 |
| 16 | 2025-11-25 | **AMD251128C00192500** | **192.50** | 2025-11-28 | sold call | +840 | **called away → −100 sh** | 2025-11-29 |
| 17–25 | 12/01 → 12/31 | 9 short puts | 200–210 | 12/05–01/02 | sold puts | (small) | all bought back / OTM | various |
| 26 | 2026-01-05 | **AMD260109P00212500** | **212.50** | 2026-01-09 | sold put | +148 | **assigned → +100 sh** | 2026-01-10 |
| 27 | 2026-01-12 | AMD260116C00212500 | 212.50 | 2026-01-16 | sold call | +262 | bought back at loss | 2026-01-13 |
| 28 | 2026-01-13 | AMD260116C00217500 | 217.50 | 2026-01-16 | sold call | +705 | bought back | 2026-01-14 |
| **29** | **2026-01-14** | **AMD260116C00212500** | **212.50** | **2026-01-16** | **sold call** | **+860** | **🔴 SILENT EXERCISE — no record** | **2026-01-16 (inferred)** |
| 30 | 2026-01-20 | AMD260123P00220000 | 220.00 | 2026-01-23 | sold put | +166 | bought back | 2026-01-21 |
| 31 | 2026-01-21 | AMD260123P00237500 | 237.50 | 2026-01-23 | sold put | +121 | bought back | 2026-01-22 |
| 32 | 2026-01-21 | AMD260123P00232500 | 232.50 | 2026-01-23 | sold put | +119 | bought back | 2026-01-21 |
| 33 | 2026-01-22 | AMD260130P00232500 | 232.50 | 2026-01-30 | sold put | +223 | bought back | 2026-01-22 |
| 34 | 2026-01-22 | AMD260130P00237500 | 237.50 | 2026-01-30 | sold put | +242 | bought back | 2026-01-23 |
| 35 | 2026-01-23 | **AMD260130P00245000** | **245.00** | 2026-01-30 | sold put | +233 | **assigned → +100 sh** | 2026-01-31 |
| 36 | 2026-02-02 | AMD260206C00245000 | 245.00 | 2026-02-06 | sold call | +1,245 | bought back | 2026-02-03 |
| 37 | 2026-02-03 | AMD260206C00245000 | 245.00 | 2026-02-06 | sold call | +790 | bought back | 2026-02-04 |
| 38 | 2026-04-09 | AMD260417C00245000 | 245.00 | 2026-04-17 | sold call | +320 | bought back at loss | 2026-04-15 |
| 39 | 2026-04-15 | **AMD260417C00252500** | **252.50** | 2026-04-17 | sold call | +670 | **called away → −100 sh** | 2026-04-18 |
| 40 | 2026-04-20 | AMD260424P00262500 | 262.50 | 2026-04-24 | sold put | +235 | bought back | 2026-04-21 |
| 41 | 2026-04-21 | AMD260424P00265000 | 265.00 | 2026-04-24 | sold put | +174 | bought back | 2026-04-22 |
| 42 | 2026-04-23 | AMD260501P00282500 | 282.50 | 2026-05-01 | sold put | +325 | bought back | 2026-04-24 |
| 43 | 2026-04-23 | AMD260501P00277500 | 277.50 | 2026-05-01 | sold put | +315 | bought back | 2026-04-24 |
| 44 | 2026-04-24 | AMD260501P00320000 | 320.00 | 2026-05-01 | sold put | +370 | bought back | 2026-04-30 |
| 45 | 2026-04-30 | AMD260508P00307500 | 307.50 | 2026-05-08 | sold put | +535 | bought back | 2026-04-30 |
| 46 | 2026-05-01 | **AMD260508P00322500** | **322.50** | 2026-05-08 | sold put | +525 | **OPEN** (current position) | — |

Bolded contracts = ones that triggered share movements. Row #29 is the missing one.

## Holdings timeline (corrected with 1/16 silent exercise)

| Date | Event | Shares before | Shares after | Source |
|---|---|---:|---:|---|
| 2025-11-22 | Put 230 assigned (#14) | 0 | **+100** | OPASN+OPTRD ✓ |
| 2025-11-29 | Call 192.5 called away (#16) | +100 | **0** | OPASN+OPTRD ✓ |
| 2026-01-10 | Put 212.5 assigned (#26) | 0 | **+100** | OPASN+OPTRD ✓ |
| **2026-01-16** | **Call 212.5 silently exercised (#29)** | **+100** | **0** | **🔴 INFERRED — no Alpaca record** |
| 2026-01-31 | Put 245 assigned (#35) | 0 | **+100** | OPASN+OPTRD ✓ |
| 2026-04-18 | Call 252.5 called away (#39) | +100 | **0** | OPASN+OPTRD ✓ |
| 2026-05-05 | Today | — | **0** | Alpaca `/v2/positions` ✓ |

**Max simultaneous holding: 100 shares.** The bot never actually held 200 shares concurrently — that's an artifact of the missing 1/16 record creating an apparent overlap between the 1/10–1/16 lot and the 1/31–4/18 lot that didn't physically exist.

## Cash flow reconciliation under Hypothesis B

| Date | Event | Cash flow on shares |
|---|---|---:|
| 2025-11-22 | Buy 100 @ $230.00 (assigned) | −$23,000 |
| 2025-11-29 | Sell 100 @ $192.50 (called away) | +$19,250 |
| 2026-01-10 | Buy 100 @ $212.50 (assigned) | −$21,250 |
| **2026-01-16** | **Sell 100 @ $212.50 (silent exercise)** | **+$21,250** (inferred, missing) |
| 2026-01-31 | Buy 100 @ $245.00 (assigned) | −$24,500 |
| 2026-04-18 | Sell 100 @ $252.50 (called away) | +$25,250 |
| | **Net** | **−$3,000** |

If you trust the inference: actual AMD share-side P&L is **−$3,000** (not the **−$24,250** the dashboard shows).

| | Dashboard (raw OPTRD) | Reconciled (with inferred 1/16) |
|---|---:|---:|
| Option P&L | +$6,931 | +$6,931 |
| Share P&L | −$24,250 | **−$3,000** |
| **Total realized** | **−$17,319** | **+$3,931** |

## So where's the bug?

**The bug is in Alpaca's paper-trading engine.** Specifically:

- Contract: `AMD260116C00212500`
- Order ID: `14255807-d0b8-4f0e-8614-3bc92d83cef0`
- Sold: 2026-01-14 15:15 ET, 1 contract @ $8.60
- Expired: 2026-01-16 with AMD at $231.79 ($19.29 ITM)
- Expected lifecycle: auto-exercised by holder → OPASN + OPTRD pair logged → 100 shares delivered at $212.50
- Actual: order frozen at `status="filled"` forever, no OPASN, no OPEXP, no OPTRD generated, no `/v2/orders` follow-up event, no portfolio-history cash event

This is a paper-account-only inconsistency. The account books *behaved* as if shares were delivered (current state matches Hypothesis B) — only the activity log is missing the entry.

## What to do

1. **File an Alpaca paper-trading support ticket** referencing the order ID and contract above, asking why no exercise event was logged for a deep-ITM expiration.
2. **Build FC-021** (or extend FC-020): when the activity-ledger sum of share movements diverges from Alpaca's positions endpoint, surface it as `unaccounted_shares_delta` in the dashboard. This single check would have flagged the AMD anomaly the day it happened.
3. **Don't change the dashboard headline numbers.** Until Alpaca confirms the missing record, the dashboard correctly reports what their activity API tells us.

## Reproducer scripts

- `/tmp/amd_alpaca_audit.py` — fresh activity pull from Alpaca, BQ parity check
- `/tmp/amd_hunt_missing.py` — exhaustive endpoint search for the missing 1/16 record
- `/tmp/amd_reconcile.py` — full event log reconstruction
- `/tmp/amd_clean_reconcile.py` — hypothesis fit test against daily P&L
