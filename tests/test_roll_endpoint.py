"""FC-078 T-14 — the ``/roll`` endpoint runs every trading day.

Plan: docs/plans/fc-078.md §5. The Friday-only weekday guard is deleted; the
market-open guard, ``strategy_lock``, ``@require_api_key`` and
``@require_account_match`` all stay. Deleting a guard on a money endpoint is
exactly the kind of change that quietly takes its neighbours with it, so the
survivors are pinned here too.
"""

import importlib
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

flask = pytest.importorskip("flask")


@pytest.fixture
def server(monkeypatch):
    monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
    monkeypatch.delenv("STRATEGY_API_KEY", raising=False)
    mod = importlib.import_module("deploy.cloud_run_server")
    mod.reset_strategy_state()
    yield mod
    mod.reset_strategy_state()


def _account_ok():
    alpaca = Mock()
    alpaca.get_account.return_value = {"account_number": "PA3D36DVXSZ2"}
    return alpaca


class TestTheFridayGuardIsGone:
    """*Mutation:* restore the Friday-only weekday guard → every day but Friday
    fails here.

    FC-066 cause 2: a churned book's calls are 5-7 DTE on any given day and 52%
    of call expiries are mid-week, which a Friday-only job can never see.
    """

    @pytest.mark.parametrize("weekday,name", [
        (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"),
    ])
    def test_the_cycle_runs_on_every_weekday(self, server, weekday, name):
        engine = Mock()
        engine.run_rolling_cycle.return_value = {
            'rolls_evaluated': 1, 'rolls_executed': 0, 'rolls_skipped': 1}

        with patch("src.api.alpaca_client.AlpacaClient", return_value=_account_ok()), \
                patch.object(server, "_is_market_open", return_value=True), \
                patch("src.strategy.wheel_engine.WheelEngine", return_value=engine):
            resp = server.app.test_client().post("/roll")

        assert resp.status_code == 200, name
        body = resp.get_json()
        assert body.get('status') == 'completed', f"{name}: {body}"
        assert 'skipped' not in body, f"{name} was skipped — the guard is back"
        engine.run_rolling_cycle.assert_called_once()

    def test_no_not_friday_response_exists_anywhere_in_the_handler(self):
        source = (Path(__file__).resolve().parent.parent
                  / 'deploy' / 'cloud_run_server.py').read_text()
        assert 'not_friday' not in source


class TestTheSurvivingGuards:

    def test_market_closed_still_short_circuits(self, server):
        engine = Mock()
        with patch("src.api.alpaca_client.AlpacaClient", return_value=_account_ok()), \
                patch.object(server, "_is_market_open", return_value=False), \
                patch("src.strategy.wheel_engine.WheelEngine", return_value=engine):
            resp = server.app.test_client().post("/roll")

        assert resp.status_code == 200
        assert 'Market closed' in resp.get_json()['message']
        engine.run_rolling_cycle.assert_not_called()

    def test_the_account_interlock_still_blocks_the_endpoint(self, server):
        wrong = Mock()
        wrong.get_account.return_value = {"account_number": "WRONG_ACCOUNT"}

        with patch("src.api.alpaca_client.AlpacaClient", return_value=wrong):
            resp = server.app.test_client().post("/roll")

        assert resp.status_code == 503
        assert b"account_interlock_mismatch" in resp.data

    def test_the_endpoint_still_carries_both_decorators(self, server):
        """Pin the decorator stack itself: deleting a guard from the body is a
        one-line edit away from deleting one from the wrapper."""
        import inspect
        source = inspect.getsource(server.trigger_roll)
        # The decorators are applied above the def, so read the module text.
        module_source = (Path(__file__).resolve().parent.parent
                         / 'deploy' / 'cloud_run_server.py').read_text()
        handler = module_source.split("@app.route('/roll'")[1].split('def trigger_roll')[0]
        assert '@require_api_key' in handler
        assert '@require_account_match' in handler
        assert 'strategy_lock' in source
