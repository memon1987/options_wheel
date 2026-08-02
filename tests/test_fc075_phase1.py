"""FC-075 Phase 1 — strategy-isolation seams.

Covers the three seams that must hold before a second strategy service can exist:
  Seam 1: the GCS opportunity store is strategy-keyed (bucket from config +
          fail-closed strategy_id check on every read).
  Seam 2: a single STRATEGY_CONFIG-driven accessor + an account-number startup
          interlock that refuses trading endpoints on a credential/account mismatch.
  Seam 3: config namespacing — profile-aware validation, own covered_call.yaml.

Wheel-neutrality (Phase 1 must not change wheel behavior) is asserted where it
matters: the wheel profile keeps its bucket, dataset, and validation.
"""

import importlib
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import Config

# google-cloud-storage is an optional dependency not installed in the test env
# (only google-cloud-bigquery is). OpportunityStore does `from google.cloud
# import storage` at import time; stub it so the module imports. Every test here
# mocks storage.Client, so no real GCS call is ever made.
try:  # pragma: no cover - depends on the environment
    from google.cloud import storage  # noqa: F401
except ImportError:  # pragma: no cover
    _google = sys.modules.setdefault("google", types.ModuleType("google"))
    _cloud = sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
    _storage = types.ModuleType("google.cloud.storage")
    _storage.Client = Mock
    sys.modules["google.cloud.storage"] = _storage
    _cloud.storage = _storage

from src.data.opportunity_store import OpportunityStore

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Seam 3 — config namespacing / profile-aware validation
# --------------------------------------------------------------------------- #

class TestConfigProfiles:
    def test_real_wheel_config_loads_and_is_wheel(self):
        c = Config(str(REPO / "config" / "settings.yaml"))
        assert c.strategy_id == "wheel"
        assert c.expected_account_number == "PA3D36DVXSZ2"
        # Wheel-neutral defaults for the seams it doesn't set.
        assert c.opportunity_bucket == "options-wheel-opportunities"
        assert c.bigquery_dataset == "options_wheel"

    def test_real_covered_call_config_loads_without_stocks(self):
        c = Config(str(REPO / "config" / "covered_call.yaml"))
        assert c.strategy_id == "covered_call"
        assert c.expected_account_number == "PA37XLNWDLB3"
        assert c.opportunity_bucket == "covered-call-opportunities"
        assert c.bigquery_dataset == "covered_call"

    def _write(self, tmp_path, data):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.safe_dump(data))
        return str(p)

    def _valid_wheel(self):
        return {
            "strategy_id": "wheel",
            "alpaca": {"paper_trading": True, "api_key_id": "k", "secret_key": "s",
                       "expected_account_number": "PA_X"},
            "strategy": {"put_target_dte": 7, "call_target_dte": 7,
                         "put_delta_range": [0.1, 0.2], "call_delta_range": [0.1, 0.2],
                         "min_put_premium": 0.5, "min_call_premium": 0.3,
                         "min_stock_price": 20, "max_stock_price": 500,
                         "min_avg_volume": 1_000_000, "max_positions_per_stock": 1,
                         "max_total_positions": 10, "max_exposure_per_ticker": 40000},
            "risk": {"max_portfolio_allocation": 0.8, "max_position_size": 0.35,
                     "min_cash_reserve": 0.2},
            "stocks": {"symbols": ["AAPL"]},
            "monitoring": {"check_interval_minutes": 15},
        }

    def test_absent_strategy_id_defaults_to_wheel(self, tmp_path):
        data = self._valid_wheel()
        del data["strategy_id"]
        assert Config(self._write(tmp_path, data)).strategy_id == "wheel"

    def test_unknown_strategy_id_rejected(self, tmp_path):
        data = self._valid_wheel()
        data["strategy_id"] = "bogus"
        with pytest.raises(ValueError, match="Unknown strategy_id"):
            Config(self._write(tmp_path, data))

    def test_missing_expected_account_number_rejected(self, tmp_path):
        data = self._valid_wheel()
        del data["alpaca"]["expected_account_number"]
        with pytest.raises(ValueError, match="expected_account_number"):
            Config(self._write(tmp_path, data))

    def test_wheel_still_requires_stocks(self, tmp_path):
        data = self._valid_wheel()
        del data["stocks"]
        with pytest.raises(ValueError, match="stocks"):
            Config(self._write(tmp_path, data))

    def test_covered_call_profile_needs_no_stocks_or_puts(self, tmp_path):
        # A minimal covered-call profile: no stocks section, no put params.
        data = {
            "strategy_id": "covered_call",
            "alpaca": {"paper_trading": True, "api_key_id": "k", "secret_key": "s",
                       "expected_account_number": "PA_CC"},
            "strategy": {"call_target_dte": 7, "call_delta_range": [0.15, 0.25],
                         "max_positions_per_stock": 1, "max_total_positions": 20,
                         "max_exposure_per_ticker": 200000},
            "risk": {"max_portfolio_allocation": 0.8, "max_position_size": 0.35,
                     "min_cash_reserve": 0.2},
            "monitoring": {"check_interval_minutes": 15},
        }
        c = Config(self._write(tmp_path, data))
        assert c.strategy_id == "covered_call"


# --------------------------------------------------------------------------- #
# Seam 1 — opportunity store isolation
# --------------------------------------------------------------------------- #

class _FakeBlob:
    def __init__(self, name, payload, time_created):
        self.name = name
        self._payload = payload
        self.time_created = time_created
        self.uploaded = None

    def download_as_string(self):
        return _json(self._payload)

    def upload_from_string(self, data, content_type=None):
        self.uploaded = data

    def exists(self):
        return True


def _json(obj):
    import json
    return json.dumps(obj).encode()


class _FakeBucket:
    def __init__(self, blobs):
        self._blobs = blobs

    def exists(self):
        return True

    def blob(self, name):
        for b in self._blobs:
            if b.name == name:
                return b
        nb = _FakeBlob(name, {}, datetime(2026, 1, 1))
        self._blobs.append(nb)
        return nb

    def list_blobs(self, prefix=""):
        return [b for b in self._blobs if b.name.startswith(prefix)]


def _store(strategy_id, blobs=None):
    """Build an OpportunityStore with a mocked GCS client and a given strategy_id."""
    config = Mock()
    config.strategy_id = strategy_id
    config.opportunity_bucket = f"{strategy_id}-opportunities"
    config.opportunity_max_age_minutes = 30
    bucket = _FakeBucket(blobs or [])
    fake_client = Mock()
    fake_client.bucket.return_value = bucket
    with patch("src.data.opportunity_store.storage.Client", return_value=fake_client):
        store = OpportunityStore(config)
    store._bucket = bucket
    return store, bucket


class TestOpportunityStoreIsolation:
    def test_bucket_comes_from_config(self):
        store, _ = _store("covered_call")
        assert store.bucket_name == "covered_call-opportunities"

    def test_explicit_bucket_name_wins(self):
        config = Mock()
        config.strategy_id = "wheel"
        config.opportunity_bucket = "from-config"
        with patch("src.data.opportunity_store.storage.Client", return_value=Mock()):
            store = OpportunityStore(config, bucket_name="explicit")
        assert store.bucket_name == "explicit"

    def test_stored_payload_carries_strategy_id(self):
        store, bucket = _store("covered_call")
        ok = store.store_opportunities([{"symbol": "META"}], datetime(2026, 8, 2, 14, 0))
        assert ok
        written = bucket._blobs[-1].uploaded
        import json
        assert json.loads(written)["strategy_id"] == "covered_call"

    def test_read_rejects_other_strategys_blob_fail_closed(self):
        # A wheel-tagged blob must be invisible to the covered_call service.
        wheel_blob = _FakeBlob(
            "opportunities/2026-08-02/14-00.json",
            {"strategy_id": "wheel", "scan_time": "2026-08-02T14:00:00",
             "status": "pending", "opportunities": [{"symbol": "AAPL"}]},
            datetime(2026, 8, 2, 14, 0),
        )
        store, _ = _store("covered_call", blobs=[wheel_blob])
        got = store.get_pending_opportunities(datetime(2026, 8, 2, 14, 5))
        assert got == []  # refused, not consumed

    def test_read_accepts_matching_strategy_blob(self):
        cc_blob = _FakeBlob(
            "opportunities/2026-08-02/14-00.json",
            {"strategy_id": "covered_call", "scan_time": "2026-08-02T14:00:00",
             "status": "pending", "opportunities": [{"symbol": "META"}]},
            datetime(2026, 8, 2, 14, 0),
        )
        store, _ = _store("covered_call", blobs=[cc_blob])
        got = store.get_pending_opportunities(datetime(2026, 8, 2, 14, 5))
        assert got == [{"symbol": "META"}]

    def test_absent_strategy_id_treated_as_wheel_grace(self):
        # A legacy blob with no strategy_id is consumable by the wheel...
        legacy = {"scan_time": "2026-08-02T14:00:00", "status": "pending",
                  "opportunities": [{"symbol": "AAPL"}]}
        wheel_store, _ = _store("wheel", blobs=[_FakeBlob(
            "opportunities/2026-08-02/14-00.json", legacy, datetime(2026, 8, 2, 14, 0))])
        assert wheel_store.get_pending_opportunities(datetime(2026, 8, 2, 14, 5)) == \
            [{"symbol": "AAPL"}]
        # ...but NOT by the covered_call service (absent == wheel != covered_call).
        cc_store, _ = _store("covered_call", blobs=[_FakeBlob(
            "opportunities/2026-08-02/14-00.json", legacy, datetime(2026, 8, 2, 14, 0))])
        assert cc_store.get_pending_opportunities(datetime(2026, 8, 2, 14, 5)) == []

    def test_mark_executed_refuses_other_strategys_blob(self):
        wheel_blob = _FakeBlob(
            "opportunities/2026-08-02/14-00.json",
            {"strategy_id": "wheel", "scan_time": "2026-08-02T14:00:00",
             "status": "pending", "opportunities": []},
            datetime(2026, 8, 2, 14, 0),
        )
        store, _ = _store("covered_call", blobs=[wheel_blob])
        ok = store.mark_executed(datetime(2026, 8, 2, 14, 5), 1, [{"r": 1}],
                                 scan_blob_path=wheel_blob.name)
        assert ok is False
        assert wheel_blob.uploaded is None  # never mutated


# --------------------------------------------------------------------------- #
# Seam 2 — config accessor + account interlock
# --------------------------------------------------------------------------- #

flask = pytest.importorskip("flask")


@pytest.fixture
def server():
    mod = importlib.import_module("deploy.cloud_run_server")
    mod.reset_strategy_state()
    yield mod
    mod.reset_strategy_state()


class TestStrategyConfigAccessor:
    def test_defaults_to_settings_yaml(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        assert server.strategy_config().strategy_id == "wheel"

    def test_honors_strategy_config_env(self, server, monkeypatch):
        monkeypatch.setenv("STRATEGY_CONFIG", "config/covered_call.yaml")
        server.reset_strategy_state()
        assert server.strategy_config().strategy_id == "covered_call"

    def test_config_is_cached(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        assert server.strategy_config() is server.strategy_config()


def _mock_alpaca(account_number):
    alpaca = Mock()
    alpaca.get_account.return_value = {"account_number": account_number}
    return alpaca


class TestAccountInterlock:
    def test_matching_account_allows_trading_endpoint(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        alpaca = _mock_alpaca("PA3D36DVXSZ2")  # matches settings.yaml
        with patch("src.api.alpaca_client.AlpacaClient", return_value=alpaca):
            assert server._account_interlock_ok(server.strategy_config()) is True

    def test_mismatched_account_returns_503_on_scan(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        alpaca = _mock_alpaca("WRONG_ACCOUNT")
        with patch("src.api.alpaca_client.AlpacaClient", return_value=alpaca):
            resp = server.app.test_client().post("/scan")
        assert resp.status_code == 503
        assert b"account_interlock_mismatch" in resp.data

    def test_mismatch_blocks_run_and_monitor_and_roll(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        alpaca = _mock_alpaca("WRONG_ACCOUNT")
        for endpoint in ("/run", "/monitor", "/roll"):
            server.reset_strategy_state()
            with patch("src.api.alpaca_client.AlpacaClient", return_value=alpaca):
                resp = server.app.test_client().post(endpoint)
            assert resp.status_code == 503, f"{endpoint} should be blocked"

    def test_mismatch_verdict_latches(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        alpaca = _mock_alpaca("WRONG_ACCOUNT")
        with patch("src.api.alpaca_client.AlpacaClient", return_value=alpaca):
            assert server._account_interlock_ok(server.strategy_config()) is False
            # Even if the account "changes", the negative verdict is latched.
            alpaca.get_account.return_value = {"account_number": "PA3D36DVXSZ2"}
            assert server._account_interlock_ok(server.strategy_config()) is False

    def test_check_failure_does_not_latch(self, server, monkeypatch):
        monkeypatch.delenv("STRATEGY_CONFIG", raising=False)
        server.reset_strategy_state()
        boom = Mock()
        boom.get_account.side_effect = RuntimeError("alpaca down")
        with patch("src.api.alpaca_client.AlpacaClient", return_value=boom):
            assert server._account_interlock_ok(server.strategy_config()) is False
        # Transient failure must NOT latch — a later good check succeeds.
        good = _mock_alpaca("PA3D36DVXSZ2")
        with patch("src.api.alpaca_client.AlpacaClient", return_value=good):
            assert server._account_interlock_ok(server.strategy_config()) is True
