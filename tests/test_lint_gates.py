"""Lint gates that guard a bug class, not a style preference.

There is no CI in this repo (`.github/` is absent), so the pytest suite is the
only enforcement vehicle that actually runs.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_undefined_names_in_production_code():
    """F821 (undefined name) over src/ and deploy/ must stay clean.

    FC-035's defect was `alpaca.trading.requests...` inside `poll_order_statuses`
    with no `import alpaca` — an F821 that raised on every invocation, was
    swallowed by a bare `except`, and so sat undetected from April to July while
    the surrounding code looked healthy. It was the ONLY F821 in src/ + deploy/,
    so this gate goes green with its deletion and permanently blocks the class:
    code that never executes because it references a name that does not exist.

    Same family as FC-015 (`_entry_times` in-process, gate dead) and FC-036
    (gap gate measuring the wrong thing) — healthy-looking dead code.
    """
    # Test-level, not module-level: a module-level importorskip silently skips
    # the whole file (2026-07-18 gotcha).
    pytest.importorskip("flake8")

    result = subprocess.run(
        [sys.executable, "-m", "flake8", "--select=F821", "src", "deploy"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )

    assert result.returncode == 0, (
        "flake8 F821 found undefined name(s) — this is the FC-035 bug class "
        "(code that can never run):\n" + (result.stdout or result.stderr)
    )
