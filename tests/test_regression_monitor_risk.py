"""Shape tests for `RegressionMonitor.check_risk_parameters` (FC-069 S1, card 16).

`/regression` is a **deployed detective control**, not a dev tool: Cloud
Scheduler invokes it hourly during market hours and any check with status
`fail` makes the endpoint return HTTP 500. Before this module it had **zero**
tests, which is how four of its checks came to mirror policies that do not
exist and one of them (cost basis) came to be blind on exactly the positions it
was written to protect.

Each surviving check gets a fires-on-violation test and a passes-when-clean
test, driven off synthetic position/account fixtures. Every test here was
mutation-checked at authoring time: the check's comparison was weakened, the
test was confirmed to fail, and the code was restored.

Deliberately NOT tested here: checks 1/3/5/6, deleted with the knobs they
mirrored (`max_total_positions`, `min_cash_reserve`,
`max_portfolio_allocation`, `max_exposure_per_ticker`). `test_deleted_checks_
are_absent` pins that they stay gone — a re-added mirror of a nonexistent
policy is the failure mode card 16 exists to prevent.
"""

import pytest

from tools.testing.regression_monitor import RegressionMonitor


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _stock(symbol, qty, avg_entry_price, market_value, cost_basis=None):
    """A us_equity position as Alpaca's /positions renders it."""
    return {
        "symbol": symbol,
        "asset_class": "us_equity",
        "qty": str(qty),
        "avg_entry_price": str(avg_entry_price),
        "market_value": str(market_value),
        # Alpaca returns "0" here for ASSIGNED lots — the FC-029 finding that
        # made the old cost_basis/qty derivation blind.
        "cost_basis": str(cost_basis if cost_basis is not None else qty * avg_entry_price),
        "side": "long",
    }


def _option(symbol, qty, market_value=-500.0):
    """A us_option position. Negative qty == short."""
    return {
        "symbol": symbol,
        "asset_class": "us_option",
        "qty": str(qty),
        "market_value": str(market_value),
        "side": "short" if qty < 0 else "long",
    }


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def run_checks(monkeypatch, positions, portfolio_value=100_000.0):
    """Drive check_risk_parameters against synthetic data, keyed by check name."""
    monitor = RegressionMonitor(service_url="http://test", api_key="k")

    def fake_get(path, timeout=30):
        if path == "/account":
            return _Resp({
                "portfolio_value": str(portfolio_value),
                "cash": "50000",
                "buying_power": "50000",
            })
        if path == "/positions":
            return _Resp(positions)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(monitor, "_get", fake_get)

    # Check 9 hits BigQuery; force its ImportError branch so these tests never
    # touch the network or ambient credentials.
    monkeypatch.setitem(__import__("sys").modules, "google.cloud.bigquery", None)

    results = monitor.check_risk_parameters()
    out = {}
    for r in results:
        # A check that fires more than once keeps its first (failing) result.
        out.setdefault(r.name, r)
    return out


def statuses(results, name):
    return results[name].status


# ---------------------------------------------------------------------------
# Check 2 — one option position per underlying
# ---------------------------------------------------------------------------

class TestDuplicateUnderlying:

    def test_passes_when_each_underlying_has_one_option(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _option("AAPL260821C00250000", -1),
            _option("MSFT260821P00400000", -1),
        ])
        assert statuses(res, "risk_duplicate_underlying") == "pass"

    def test_fires_on_two_options_for_same_underlying(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _option("AAPL260821C00250000", -1),
            _option("AAPL260828C00260000", -1),
        ])
        r = res["risk_duplicate_underlying"]
        assert r.status == "fail"
        assert r.details["duplicates"] == {"AAPL": 2}

    def test_canonical_parser_does_not_confuse_f_and_pfe(self, monkeypatch):
        """The hand-rolled leading-alpha parser this replaced was correct for
        the underlying, but the OCC-substring family it belongs to is the
        reason this is now parsed, not sliced. F and PFE must stay distinct."""
        res = run_checks(monkeypatch, [
            _option("F260821P00012000", -1),
            _option("PFE260821P00025000", -1),
        ])
        assert statuses(res, "risk_duplicate_underlying") == "pass"


# ---------------------------------------------------------------------------
# Check 4 — max position size, re-sourced from Config
# ---------------------------------------------------------------------------

class TestMaxPositionSize:

    def test_passes_when_all_positions_within_limit(self, monkeypatch):
        # 30% of a $100k portfolio, under the live 0.35.
        res = run_checks(monkeypatch, [_stock("AAPL", 100, 300.0, 30_000.0)])
        r = res["risk_max_position_size"]
        assert r.status == "pass"
        assert r.details["limit"] == pytest.approx(0.35)

    def test_fires_when_a_position_exceeds_the_limit(self, monkeypatch):
        res = run_checks(monkeypatch, [_stock("AAPL", 100, 400.0, 40_000.0)])
        r = res["risk_max_position_size"]
        assert r.status == "fail"
        assert r.details["symbol"] == "AAPL"
        assert r.details["pct"] == pytest.approx(0.40)

    def test_limit_tracks_config_not_a_hardcoded_constant(self, monkeypatch):
        """The point of the re-source: change the policy, the alarm follows."""
        import tools.testing.regression_monitor as rm
        from src.utils.config import Config

        real_init = Config.__init__

        class TighterConfig(Config):
            def __init__(self, *a, **kw):
                real_init(self, *a, **kw)
                self._config["risk"]["max_position_size"] = 0.10

        monkeypatch.setattr("src.utils.config.Config", TighterConfig)

        # 30% now violates a 10% policy; under a hardcoded 0.35 it would pass.
        res = run_checks(monkeypatch, [_stock("AAPL", 100, 300.0, 30_000.0)])
        r = res["risk_max_position_size"]
        assert r.status == "fail"
        assert r.details["limit"] == pytest.approx(0.10)

    def test_fails_loudly_when_config_cannot_load(self, monkeypatch):
        """Never silently fall back to a stale number and report pass."""
        def boom(*a, **kw):
            raise RuntimeError("settings.yaml unreadable")

        monkeypatch.setattr("src.utils.config.Config", boom)
        res = run_checks(monkeypatch, [_stock("AAPL", 100, 300.0, 30_000.0)])
        r = res["risk_max_position_size"]
        assert r.status == "fail"
        assert "Config failed to load" in r.message


# ---------------------------------------------------------------------------
# Check 7 — naked call detection
# ---------------------------------------------------------------------------

class TestNakedCall:

    def test_passes_when_short_call_is_fully_covered(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 200.0, 25_000.0),
            _option("AAPL260821C00250000", -1),
        ])
        assert statuses(res, "risk_naked_call") == "pass"

    def test_fires_when_shares_are_insufficient(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 200.0, 25_000.0),
            _option("AAPL260821C00250000", -2),   # needs 200 shares, owns 100
        ])
        r = res["risk_naked_call"]
        assert r.status == "fail"
        assert r.details["required_shares"] == 200
        assert r.details["owned_shares"] == 100

    def test_fires_when_no_shares_are_held_at_all(self, monkeypatch):
        res = run_checks(monkeypatch, [_option("AAPL260821C00250000", -1)])
        assert statuses(res, "risk_naked_call") == "fail"

    def test_short_put_is_not_treated_as_a_call(self, monkeypatch):
        """The old `"C" in symbol` test. A cash-secured put needs no shares."""
        res = run_checks(monkeypatch, [_option("AAPL260821P00200000", -1)])
        assert statuses(res, "risk_naked_call") == "pass"

    def test_long_call_commits_no_shares(self, monkeypatch):
        res = run_checks(monkeypatch, [_option("AAPL260821C00250000", 1)])
        assert statuses(res, "risk_naked_call") == "pass"

    def test_malformed_symbol_is_not_classified_as_a_call(self, monkeypatch):
        """`strict_option_type` returns None for a non-OCC symbol, so the
        check skips rather than inheriting `parse_option_symbol`'s last-resort
        `'C' if 'C' in symbol` heuristic."""
        res = run_checks(monkeypatch, [_option("NOT_AN_OCC", -1)])
        assert statuses(res, "risk_naked_call") == "pass"


# ---------------------------------------------------------------------------
# Check 8 — cost-basis floor, re-specced onto avg_entry_price
# ---------------------------------------------------------------------------

class TestCostBasisProtection:

    def test_passes_when_strike_is_above_basis(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 200.0, 25_000.0),
            _option("AAPL260821C00250000", -1),   # $250 strike vs $200 basis
        ])
        assert statuses(res, "risk_cost_basis_protection") == "pass"

    def test_fires_when_strike_is_below_basis(self, monkeypatch):
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 300.0, 25_000.0),
            _option("AAPL260821C00250000", -1),   # $250 strike vs $300 basis
        ])
        r = res["risk_cost_basis_protection"]
        assert r.status == "fail"
        assert r.details["strike"] == pytest.approx(250.0)
        assert r.details["cost_basis"] == pytest.approx(300.0)

    def test_assigned_lot_with_zero_cost_basis_is_still_checked(self, monkeypatch):
        """THE regression this re-spec exists for.

        Alpaca returns ``cost_basis: 0`` for assigned positions (FC-029). The
        old derivation computed 0/qty = 0, hit the ``> 0`` guard and skipped
        **silently** — so the detective floor check was blind on exactly the
        assigned lots it was written to protect. With ``avg_entry_price`` as
        the source the below-basis call is caught.
        """
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 300.0, 25_000.0, cost_basis=0),
            _option("AAPL260821C00250000", -1),
        ])
        r = res["risk_cost_basis_protection"]
        assert r.status == "fail"
        assert r.details["cost_basis"] == pytest.approx(300.0)

    def test_unusable_avg_entry_price_fails_instead_of_skipping(self, monkeypatch):
        """An unresolvable basis is a finding, not a silent pass."""
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 0, 25_000.0, cost_basis=0),
            _option("AAPL260821C00250000", -1),
        ])
        r = res["risk_cost_basis_protection"]
        assert r.status == "fail"
        assert "no usable avg_entry_price" in r.message

    def test_short_put_below_basis_is_not_flagged(self, monkeypatch):
        """Only short CALLS can be written below basis."""
        res = run_checks(monkeypatch, [
            _stock("AAPL", 100, 300.0, 25_000.0),
            _option("AAPL260821P00250000", -1),
        ])
        assert statuses(res, "risk_cost_basis_protection") == "pass"

    def test_naked_call_is_check_sevens_finding_not_this_ones(self, monkeypatch):
        res = run_checks(monkeypatch, [_option("AAPL260821C00250000", -1)])
        assert statuses(res, "risk_cost_basis_protection") == "pass"
        assert statuses(res, "risk_naked_call") == "fail"


# ---------------------------------------------------------------------------
# The deleted mirrors stay deleted
# ---------------------------------------------------------------------------

def test_deleted_checks_are_absent(monkeypatch):
    """Checks 1/3/5/6 mirrored knobs FC-069 S1 deleted.

    Re-adding any of them would alarm hourly against a policy that does not
    exist — and check 6 in particular would return HTTP 500 hourly on a healthy
    account once the portfolio crosses roughly $114k.
    """
    res = run_checks(monkeypatch, [
        _stock("AAPL", 100, 300.0, 45_000.0),
        _option("AAPL260821C00350000", -1),
    ], portfolio_value=500_000.0)

    for gone in (
        "risk_max_total_positions",
        "risk_min_cash_reserve",
        "risk_max_portfolio_allocation",
        "risk_max_exposure_per_ticker",
        "risk_max_positions_per_stock",
    ):
        assert gone not in res, f"{gone} mirrors a policy that no longer exists"


def test_healthy_account_produces_no_failures(monkeypatch):
    """The post-sweep steady state: `/regression` returns 200, not 500."""
    res = run_checks(monkeypatch, [
        _stock("AAPL", 100, 200.0, 25_000.0),
        _option("AAPL260821C00250000", -1),
        _option("MSFT260821P00400000", -1),
    ])
    for name in ("risk_duplicate_underlying", "risk_max_position_size",
                 "risk_naked_call", "risk_cost_basis_protection"):
        assert res[name].status == "pass", f"{name}: {res[name].message}"
