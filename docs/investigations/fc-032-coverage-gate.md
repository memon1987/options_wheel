# FC-032 Phase 1 — Data Coverage Gate: results and decision

**Date:** 2026-07-09
**Plan:** [docs/plans/fc-032.md](../plans/fc-032.md)
**Raw data:** [fc-032-coverage-gate.json](./fc-032-coverage-gate.json)
**Command:** `python tools/backtesting/coverage_report.py --out coverage.json`
**Window:** 2024-02-01 → 2026-07-09 (Alpaca options-history floor → today), every 5th trading day (~weekly), 122 decision days per symbol.
**Strategy parameters used:** `max_dte=7`, `put_delta_range=[0.10, 0.20]`, `min_put_premium=$0.50` — read from `config/settings.yaml`, matching the live filter chain in `market_data._check_put_criteria_detailed`.

## Decision

**Do not buy ThetaData/ORATS. Phase 3 proceeds on free Alpaca data.**

The gate exists to answer one question: *can Alpaca's trade-derived option history support our decisions, or must we pay a vendor?* The answer is unambiguous — **zero of 14 symbols are data-limited**, and not one symbol had a single decision day lacking same-day option bars.

## Results

| symbol | days | w/bar | in-band | in-band % | usable | usable % | verdict | limited by |
|--------|-----:|------:|--------:|----------:|-------:|---------:|---------|------------|
| AAPL   | 122 | 122 | 112 |  91.8% |  75 |  61.5% | poor     | premium |
| MSFT   | 122 | 122 | 120 |  98.4% | 109 |  89.3% | marginal | premium |
| GOOGL  | 122 | 122 | 115 |  94.3% |  72 |  59.0% | poor     | premium |
| AMZN   | 122 | 122 | 117 |  95.9% |  86 |  70.5% | marginal | premium |
| NVDA   | 122 | 122 | 121 |  99.2% | 103 |  84.4% | marginal | premium |
| AMD    | 122 | 122 | 119 |  97.5% |  96 |  78.7% | marginal | premium |
| QQQ    | 122 | 122 | 122 | 100.0% | 122 | 100.0% | good     | none    |
| SPY    | 122 | 122 | 122 | 100.0% | 122 | 100.0% | good     | none    |
| IWM    | 122 | 122 | 122 | 100.0% | 113 |  92.6% | good     | premium |
| UNH    | 122 | 122 | 122 | 100.0% | 115 |  94.3% | good     | premium |
| F      | 122 | 122 |  69 |  56.6% |   0 |   0.0% | poor     | premium |
| PFE    | 122 | 122 |  89 |  73.0% |   0 |   0.0% | poor     | premium |
| KMI    | 122 | 122 |  83 |  68.0% |   0 |   0.0% | poor     | premium |
| VZ     | 122 | 122 | 110 |  90.2% |   2 |   1.6% | poor     | premium |

Tally: 4 good, 4 marginal, 6 poor. **Data-limited: 0. Premium-limited: 12.**

## Why the headline verdict column is misleading on its own

The gate as originally written computed one number — the fraction of decision days with a put that was *both* in the 0.10–0.20 delta band *and* paying ≥ $0.50 — and mapped it to good/marginal/**poor**, where "poor" was wired to "buy ThetaData/ORATS."

That conflates two unrelated failures:

- **No priced put at our deltas.** A real data gap. A vendor with true historical quotes would fix it.
- **A priced put that pays less than our floor.** A fact about the symbol. **No vendor can change what a contract paid.**

Read naively, this run says 6 symbols are "poor" and we should spend $99/mo. Read correctly, **the data was never the problem for any of them.** AAPL is the clearest case: 91.8% of decision days had a priced, in-band put; of its 47 unusable days, 37 had that put sitting right there below the $0.50 floor. Only 10 were a genuine gap.

`quality.py` now reports `in_band_fraction` (the true data-coverage number), `premium_shortfall_days`, and `limiting_factor() -> data | premium | none`, and `coverage_report.py` recommends a vendor purchase only for `data`-limited symbols.

## The load-bearing number

`days_with_bar = 122/122` on **every symbol, including the thinnest names.** The plan's flagship data risk —

> *"Alpaca bar sparsity at 0.10–0.20-delta weeklies makes chains unusable for some symbols"*

— did not materialize. Weekly options on these 14 underlyings trade every session across the strike range we care about.

## Independent validation against production

The gate makes a falsifiable prediction: F, PFE, KMI (0 usable days) and VZ (2) are structurally unsellable under the current config, so **the live bot should never have sold a put on them.**

Checked against 588 `FILL` activities from the Alpaca account (2024-01-01 →):

| underlying | live put legs | live call legs |
|---|---:|---:|
| NVDA | 155 | 31 |
| AMD | 88 | 15 |
| GOOGL | 51 | 32 |
| UNH | 50 | 5 |
| AMZN | 49 | 32 |
| IWM | 39 | 15 |
| AAPL | 15 | 5 |
| MSFT | 3 | 3 |
| **F, PFE, KMI, VZ** | **0** | **0** |

Confirmed. The bot has traded exactly the symbols the gate rates usable, and has never touched the four it rates unsellable. The rebuilt data layer reproduces production behavior it was never shown — evidence that the chain builder, the Black-Scholes greeks, and the delta band are sound.

SPY and QQQ score 100% usable yet were never traded. This is not a contradiction: a SPY cash-secured put reserves ~$60k of collateral. The gate measures *chain usability*, not *affordability* — the simulator's cash ledger (`BacktestBroker`, Phase 2) is what will reproduce that constraint.

## Findings worth acting on separately

1. **Four of the 14 universe symbols are structurally untradeable under `min_put_premium: 0.50`.** F, PFE, KMI and VZ produced 0, 0, 0 and 2 usable days in 2.4 years. They occupy universe slots and screening budget while being incapable of generating a trade.

2. **A fixed dollar premium floor is not scale-free.** `min_put_premium: $0.50` is a much harsher filter on a $12 stock (F) than on a $600 one (SPY). A 15-delta weekly put on F is worth pennies and can never clear $0.50 — not because F is a bad wheel candidate, but because the threshold is denominated in dollars rather than as a fraction of strike or of collateral. Whether to re-express the floor (e.g. as % of strike, or as annualized return on collateral) is a live-strategy question and belongs in its own FC, not in FC-032.

Neither finding blocks Phase 3.

## Caveat: this gate measured *availability*, not *fidelity*

Alpaca has no historical option quotes at any price. That is unchanged by this result. Bars are trade prints, so:

- **bid/ask is modeled** (`spread_model.py`), not observed;
- **IV and delta are computed** via Black-Scholes inversion from the bar close, not published.

A paid vendor would still improve *fidelity* — real bid/ask, real greeks — even though it would improve *availability* not at all. The plan's mitigations stand: every run reports the bid-fill worst case alongside the mid-fill result, and every modeled field is labeled as such in output. If fitness verdicts flip between mid-fill and bid-fill, that is the signal to revisit the vendor decision on fidelity grounds.

## Sampling note

Coverage was sampled every 5th trading day (122 of ~610 sessions), matching the strategy's ~weekly decision cadence. Bar availability was 100% at every sampled point; an exhaustive `--sample 1` pass would tighten the bound but is unlikely to change the decision given no sampled day missed a bar.
