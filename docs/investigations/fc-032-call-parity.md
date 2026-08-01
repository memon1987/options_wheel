# Call-side parity: the first measurement of the engine's other half

> **⚠️ Method predates FC-068 (2026-08-01); 55.2% / 0.676 are STALE.** This measured
> `find_suitable_calls(...)[0]`, mirroring the since-deleted
> `CallSeller.evaluate_covered_call_opportunity`. Production ranks the scanner's top 3
> by `attractiveness_score` and lets the best available-shares candidate win.
> `parity_check.py` now mirrors that per leg, but **has not been re-run**. The strike
> figure is the one at risk; the premium ratio depends on the chain model, not the
> selection rule.


**Date:** 2026-07-29
**Tool:** `python tools/diagnostics/parity_check.py --side call` (re-runnable)
**Companion:** `docs/investigations/fc-032-parity-check.md` (the put side)

## Why this did not exist before

The headline fidelity claim — **81% strike reproduction over 204 real decisions** — is
**put-only by construction**. Its decisions are defined as "every (date, underlying) with
a put sell-to-open fill."

That was not a scoping choice. Until FC-048, covered calls were misrouted in the engine
and rejected, so **the replay could not produce a call to compare against**. The call leg
became measurable only after `ea5cfa5`.

## Method

Identical to the put side, one real decision at a time: rebuild that day's chain, wrap it
in `BacktestAlpacaClient`, run the *live* selection path, compare against the contract
that actually filled.

One thing the call side needs that the put side does not: a **cost-basis floor**. Live
called `find_suitable_calls(symbol, min_strike_price=cost_basis)`, so comparing without it
would answer a different question than the bot answered. Basis is resolved per FC-029 R2 —
the strike of the most recent prior **put** assignment (OPASN) on that underlying. Call
OPASN rows are excluded: they end a position, they do not establish a basis. A decision
whose basis cannot be resolved is reported as `no_basis` and **excluded from the rate**
rather than silently compared against a floor of zero.

## Results — 80 live call decisions

| outcome | n | share |
|---|---:|---:|
| exact strike | 14 | 17.5% |
| close (within 2%) | 23 | 28.7% |
| diverged | 30 | 37.5% |
| no candidate | 13 | 16.2% |

| metric | call leg | put leg (for comparison) |
|---|---:|---:|
| **strike reproduced** (exact or ≤2%) | **55.2%** (37/67) | **81%** |
| **delta band accuracy** | **100%** (67/67) | 100% |
| median \|strike diff\| | 1.61% | — |
| **premium ratio on IDENTICAL contracts** | **0.676** | ~0.93 |

### The call leg is materially less faithful than the put leg

Two findings, and the second is the important one.

**1. Selection is looser.** 55.2% strike reproduction against the put side's 81%. Delta-band
accuracy is perfect (100%, median 0.207 inside `call_delta_range` [0.15, 0.25]), so the
engine is choosing *a* correct-risk contract every time — it just lands on a different
strike far more often than on the put side. Per-symbol, this is concentrated: GOOGL 15/18
and NVDA 9/19 reproduce well; **AMD 0/9 and AMZN 1/17 barely reproduce at all.**

**2. Pricing is ~32% low on the same contract.** Decomposed to separate pricing from
selection:

| comparison | n | median sim/live premium |
|---|---:|---:|
| **identical strike** | 14 | **0.676** |
| within 2% | 23 | 0.500 |
| different strike | 30 | 0.243 |

On the *identical contract* the engine marks a call at **68% of what live received**. The
put side's equivalent figure is ~93% (a ~7% shortfall). **The call leg's pricing error is
roughly five times the put leg's.**

### A hypothesis tested and disconfirmed

The obvious explanation was DTE mix: **28% of live call fills are at DTE 8** (22 of 80),
while the sim caps at `call_target_dte: 7`, so it would pick a shorter, cheaper contract.

Split on exact-strike matches:

| | n | median sim/live |
|---|---:|---:|
| live DTE ≤ 7 (sim *can* match the expiry) | 8 | **0.644** |
| live DTE > 7 (sim capped shorter) | 6 | 0.723 |

The shortfall is **slightly worse where the sim can match the expiry**. DTE mix does not
explain it. Cause unknown — filed as **FC-056** rather than guessed at.

## What this means for using the engine

**Direction is conservative, magnitude is material.** The engine understates call premium
by about a third, so it **understates wheel returns on the call leg**. Combined with the
put side (~7% conservative) and the spread model (proven 2.46× wider than real intraday),
every known bias points the same way: **reported returns are a floor, not a forecast.**

That is the safe direction for a demotion tool — it will not flatter a symbol into looking
tradeable. But it means:

- **Do not read an absolute call-leg return as accurate.** It is low by roughly a third on
  the premium component.
- **Cross-symbol comparison is safer than absolute levels**, except where reproduction is
  poor (AMD, AMZN).
- **A `marginal` verdict driven by the call leg deserves scepticism** — the true figure is
  probably better than reported.

## Reproduce

```bash
python tools/diagnostics/parity_check.py --side call            # this measurement
python tools/diagnostics/parity_check.py --side call --out parity_call.json
python tools/diagnostics/parity_check.py                        # the put side
```

## Fixed while running this

`_summarize` hard-coded the **put** delta band `[0.10, 0.20]`. The first call-side run
therefore reported "delta in band: 37.3%" when the correct band for calls is
`[0.15, 0.25]` (FC-029 R1) and the true figure is **100%**. The band is now taken from
config per leg. A wrong-band statistic understating the engine's own fidelity is exactly
the kind of number that gets quoted later.
