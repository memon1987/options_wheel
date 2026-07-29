"""FC-045: /monitor must classify option positions by contract, not substring.

`deploy/cloud_run_server.py`'s monitor loop decided put-vs-call with
`is_put = 'P' in symbol`, where `symbol` is a full OCC contract symbol. That
tests the TICKER's own letters, so every option on an underlying containing a
"P" matched — and because `is_put` was evaluated first, covered calls on those
underlyings were evaluated by `should_close_put_early` and tagged
`position_type='PUT'`.

Three of the fourteen configured symbols are affected: AAPL, SPY, PFE.

This is the fourth occurrence of the OCC-substring family (FC-041, FC-043,
FC-048, FC-045), which is why the fix uses the shared `strict_option_type`
primitive rather than another local heuristic.
"""

import pytest
import yaml
from pathlib import Path

from src.utils.option_symbols import strict_option_type


def _universe():
    cfg = yaml.safe_load(Path("config/settings.yaml").read_text())
    return cfg["stocks"]["symbols"]


def _occ(root, kind):
    """A well-formed OCC contract for `root` (2026-08-15, strike 100)."""
    return f"{root}260815{'C' if kind == 'call' else 'P'}00100000"


class TestMonitorClassification:
    def test_the_old_substring_test_was_wrong_for_three_real_symbols(self):
        """Pins the bug: 'P' in symbol matched calls on AAPL / SPY / PFE."""
        affected = [s for s in _universe() if "P" in s.upper()]

        assert set(affected) == {"AAPL", "SPY", "PFE"}, (
            f"universe changed; affected set is now {affected} — the blast "
            "radius of the pre-FC-045 substring test moved with it"
        )
        for root in affected:
            call = _occ(root, "call")
            assert "P" in call, "precondition: the ticker's P is in the symbol"
            assert strict_option_type(call) == "call", (
                f"{call} must classify as a call despite the ticker's 'P'"
            )

    def test_every_universe_symbol_classifies_correctly_both_ways(self):
        for root in _universe():
            assert strict_option_type(_occ(root, "call")) == "call", root
            assert strict_option_type(_occ(root, "put")) == "put", root

    def test_a_non_contract_is_not_silently_classified(self):
        """The monitor must skip, not guess, on anything that isn't a contract.

        Under the old code a bare ticker took the put branch and was evaluated
        by should_close_put_early.
        """
        for junk in ("AAPL", "SPY", "NOT_AN_OCC", "", "1AAPL260815C00100000"):
            assert strict_option_type(junk) is None, junk

    def test_monitor_uses_the_strict_parser(self):
        """Guard against a future edit reintroducing substring matching.

        Inspects EXECUTABLE lines only — the fix's own explanatory comment
        quotes the old `'P' in symbol` expression, so a naive text search
        matches the very comment documenting the fix.
        """
        src = Path("deploy/cloud_run_server.py").read_text()
        monitor = src[src.index("# Evaluate each option position"):][:2500]
        code = "\n".join(
            ln for ln in monitor.splitlines()
            if not ln.strip().startswith("#")
        )

        assert "strict_option_type(symbol)" in code
        assert "'P' in symbol" not in code, "substring classification is back"
        assert "'C' in symbol" not in code, "substring classification is back"
