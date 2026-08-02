# PR body draft — FC-071: at-floor scoring bonus aligned to the gate (`>=`)

> Draft only. **Do not open this PR until after the Monday 2026-08-03 merge train**
> (PR #76 → P4 → FC-068). See *Merge slot* below. Paste the body below the line when opening.

---

Plan: docs/plans/fc-071.md

## Summary

FC-065 Phase 2 (PR #76) moved the `assignment_above_cost_basis` **flag** to `>=`, matching all
three floor gates — `market_data`'s chain filter, `call_seller`'s execute-time check, and
`risk_manager.validate_roll` — each of which rejects only `strike < floor`. An at-floor call is
therefore admitted and sold; GOOGL's 370C on a 370.00 floor was the live example.

The **scoring** input was deliberately left on strict `>` for an operator decision (PR #76
review, INFO finding). The result: an at-floor candidate was *flagged* at-or-above basis while
being *scored* as below-basis — 15 points versus 5, a 10-point swing in a 0–100 score that
ranked a genuinely profitable write below its peers. Operator decided 2026-08-02: **align.**

This PR makes gate, flag, and score all agree that at-floor is good.

## The change

One functional line, in `_create_call_opportunity` (`src/data/options_scanner.py`). The plan
preferred a single source of truth if the code shape allowed it — it did:

```python
assignment_above_cost_basis = strike >= cost_basis_per_share
```

computed once, above the scoring call, and feeding **both**:

- the `above_cost_basis` argument to `_calculate_call_attractiveness_score` — **this is the
  change**; it was `strike > cost_basis_per_share`
- the `assignment_above_cost_basis` key on the opportunity dict — was a second,
  separately-written `strike >= cost_basis_per_share`

Two predicates became one, so they cannot drift apart again. The FC-065 P2 comment block moved
up with the hoisted comparison and gained the FC-071 rationale.

## Behavior

- **At-floor** (`strike == floor`): scoring input now True → +15 instead of +5. Ranks 10 points
  higher, consistent with its flagged status.
- **Above-floor:** unchanged (was True, stays True).
- **Below-floor:** unchanged (False → +5), and still blocked at the gates regardless of score.
  The parameter contract is preserved even though scoring such a candidate is moot in practice.
- **Unchanged:** floor gates, the flag's own value, `attractiveness_score` for every non-at-floor
  candidate, opportunity dict shape, blob schema.

Exact equality is near measure-zero with premium-netted floors (e.g. 368.34) against $2.50
strike grids, so this is consistency hygiene rather than a shift on today's book. No at-floor
candidate is expected on the current book; the verified consequence is confined to future
exact-equality candidates.

**Explicitly out of scope:** scoring weights (FC-073's territory), the gates, put-side scoring
(no basis component to symmetrize). Also untouched: the `strike > cost_basis_per_share` branch
at `:595` splitting capital gain from capital loss — at exact equality both arms compute
`total_return_if_assigned == premium_income` (gain and loss are each 0), so it is already
equality-correct and outside the one-predicate scope.

## Tests

Three new tests (6 cases with parametrization) in
`tests/test_options_scanner.py::TestAtFloorStrikesAreScoredTheWayTheyAreFlagged`, reusing the
GOOGL 368.34-floor fixture from the FC-065 P2 flag class directly above it:

1. **`test_a_strike_exactly_at_the_floor_earns_the_above_basis_bonus`** — re-scores the emitted
   opportunity from its own published components with the basis input forced True and False,
   asserts the spread is exactly 10 points and that the opportunity carries the with-bonus
   score. Derives the 10 rather than hardcoding 15, so it stays honest if FC-073 moves weights.
2. **`test_an_at_floor_strike_scores_the_same_as_one_cent_above`** — the boundary is no longer a
   scoring cliff: 368.34 and 368.35 score within 1 point (residual is the OTM/return effect of
   the extra cent), not 10 apart.
3. **`test_the_flag_and_the_scoring_input_are_the_same_value`** — the anti-drift pin. Spies on
   the scoring call and asserts the recorded `above_cost_basis` argument **is the same value**
   as the emitted `assignment_above_cost_basis` flag, parametrized across
   `[360.00, 368.34, 368.35, 375.00]` (below / at / just-above / above). Fails the moment
   anyone re-derives either surface from its own comparison.

**Full suite: 996 passed** (990 baseline + 6 new). No existing assertion moved.

## Mutation record

Per plan §Tests, the predicate was reverted to strict `>` to prove the new tests actually bite.
The mutation recreated the exact pre-FC-071 drift — flag on `>=`, scoring input on `>` — then
every `__pycache__` was cleared and the suite re-run with `-p no:cacheprovider` (stale `.pyc`
has burned a prior mutation exercise on this repo).

| | Result |
|---|---|
| Mutated (`strike > cost_basis_per_share` into scoring) | **3 failed, 3 passed** |
| Failing | Test 1; test 2; test 3's `[368.34]` case **only** |
| Still passing under mutation | Test 3's `[360.00]`, `[368.35]`, `[375.00]` |
| Predicate restored | **6/6 pass**, full suite 996 green |

The failure is confined precisely to the equality boundary — which is the intended blast radius,
and confirms the tests pin the boundary itself rather than the surrounding arithmetic.

## Merge slot

**After the Monday 2026-08-03 train** (PR #76 → P4 → FC-068). This branch was built on
`fc-068/engine-path-deletion` @ `c72127a` — the post-FC-068-review tip, i.e. the post-train shape
of the scanner code this change touches. **Rebase-verify against post-train main before opening
the PR** so the diff stays exact and contains only the FC-071 predicate plus its tests.

## Review + rollout

Production behavior change → house rules apply: two adversarial Fable reviews in fresh contexts
with distinct personas, run concurrently; confirmation pass if fixes land in code.

Deploy rides the next Cloud Build. Verification: the next live scan shows unchanged strike sets
(no at-floor candidate expected on today's book) plus the suite's mutation-backed pins.
Rollback: single revert.
