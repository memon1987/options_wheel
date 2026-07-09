"""Unit tests for the FC-032 backtest data layer (network-free).

Covers Black-Scholes greeks, point-in-time chain construction (no lookahead),
the spread model, the parquet chain store, and the coverage report, all against
an in-memory mock provider.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Dict, List

import pytest

from src.backtesting.data import greeks
from src.backtesting.data.chain_builder import ChainBuilder
from src.backtesting.data.chain_store import ChainStore
from src.backtesting.data.provider import OptionBar, OptionContract, StockBar
from src.backtesting.data.quality import evaluate_coverage
from src.backtesting.data.spread_model import SpreadModel


# --------------------------------------------------------------------------- #
# Greeks
# --------------------------------------------------------------------------- #
class TestGreeks:
    def test_atm_call_matches_textbook(self):
        # S=K=100, T=1, r=0, sigma=0.2, q=0 -> 7.9656 (standard reference value)
        assert greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "call") == pytest.approx(
            7.9656, abs=1e-3
        )

    def test_put_call_parity_at_zero_rates(self):
        c = greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "call")
        p = greeks.bs_price(100, 100, 1, 0.0, 0.2, 0.0, "put")
        assert c == pytest.approx(p, abs=1e-9)

    def test_delta_signs_and_sum(self):
        dc = greeks.bs_delta(100, 100, 1, 0.0, 0.2, 0.0, "call")
        dp = greeks.bs_delta(100, 100, 1, 0.0, 0.2, 0.0, "put")
        assert 0 < dc < 1
        assert -1 < dp < 0
        assert dc - dp == pytest.approx(1.0, abs=1e-9)  # call - put delta = e^{-qT} = 1

    def test_iv_round_trip(self):
        T = greeks.year_fraction(30)
        price = greeks.bs_price(100, 95, T, 0.04, 0.35, 0.01, "put")
        iv = greeks.implied_vol(price, 100, 95, T, 0.04, 0.01, "put")
        assert iv == pytest.approx(0.35, abs=1e-4)

    def test_iv_none_below_intrinsic(self):
        # A put priced below its discounted intrinsic has no real IV.
        T = greeks.year_fraction(7)
        assert greeks.implied_vol(0.001, 100, 130, T, 0.04, 0.0, "put") is None

    def test_expiration_intrinsic_and_delta(self):
        assert greeks.bs_price(105, 100, 0, 0.04, 0.3, 0, "call") == pytest.approx(5.0)
        assert greeks.bs_delta(105, 100, 0, 0.04, 0.3, 0, "call") == 1.0
        assert greeks.bs_delta(95, 100, 0, 0.04, 0.3, 0, "call") == 0.0


# --------------------------------------------------------------------------- #
# Spread model
# --------------------------------------------------------------------------- #
class TestSpreadModel:
    def test_abs_floor_enforced(self):
        m = SpreadModel(base_frac=0.05, abs_floor=0.02)
        # tiny mark -> percentage spread below floor -> floor wins
        assert m.half_spread(0.10, moneyness=0.0) == pytest.approx(
            max(0.02, 0.05 * 0.10 + 0.05 * 0.10)  # includes cheap widening
        )

    def test_otm_widens_spread(self):
        m = SpreadModel()
        atm = m.half_spread(2.0, moneyness=0.0)
        otm = m.half_spread(2.0, moneyness=0.15)
        assert otm > atm

    def test_bid_never_negative(self):
        m = SpreadModel(base_frac=0.5, abs_floor=0.5)
        bid, ask = m.bid_ask(0.10, moneyness=0.2)
        assert bid == 0.0
        assert ask > 0.10

    def test_calibrate_fits_or_defaults(self):
        # Too few samples -> defaults.
        assert SpreadModel.calibrate([]) == SpreadModel()
        # Enough samples on a clean line half_spread/mark = 0.03 + 0.2*moneyness.
        samples = [
            {"mark": 1.0, "moneyness": mny, "half_spread": (0.03 + 0.2 * mny)}
            for mny in [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
        ]
        fitted = SpreadModel.calibrate(samples)
        assert fitted.base_frac == pytest.approx(0.03, abs=1e-3)
        assert fitted.otm_widening == pytest.approx(0.2, abs=1e-3)


# --------------------------------------------------------------------------- #
# Mock provider
# --------------------------------------------------------------------------- #
class MockProvider:
    """In-memory provider with explicit control over contracts, bars, and prices.

    Crucially, ``get_option_bars`` returns a bar for a symbol ONLY on the exact
    dates listed in ``bar_dates[symbol]`` — so a contract that "trades only on a
    later date" genuinely has no bar on an earlier ``as_of``, which is how the
    no-lookahead test is enforced.
    """

    def __init__(self):
        self.contracts: List[OptionContract] = []
        self.bar_dates: Dict[str, List[date]] = {}
        self.bar_close: Dict[str, float] = {}
        self.stock: Dict[date, float] = {}

    def add_contract(self, c: OptionContract, close: float, traded_on: List[date]):
        self.contracts.append(c)
        self.bar_close[c.symbol] = close
        self.bar_dates[c.symbol] = traded_on

    def get_contract_universe(self, underlying, as_of, max_dte):
        hi = as_of + timedelta(days=max_dte)
        return [
            c
            for c in self.contracts
            if c.underlying == underlying and as_of <= c.expiration <= hi
        ]

    def get_option_bars(self, symbols, start, end):
        out: Dict[str, List[OptionBar]] = {}
        for s in symbols:
            days = [d for d in self.bar_dates.get(s, []) if start <= d <= end]
            if not days:
                continue
            close = self.bar_close[s]
            out[s] = [
                OptionBar(s, d, close, close, close, close, volume=100, trade_count=5)
                for d in days
            ]
        return out

    def get_stock_bars(self, symbol, start, end):
        return [
            StockBar(symbol, d, px, px, px, px, volume=1_000_000)
            for d, px in sorted(self.stock.items())
            if start <= d <= end
        ]


def _occ(underlying, exp, opt, strike):
    cp = "P" if opt == "put" else "C"
    return f"{underlying}{exp:%y%m%d}{cp}{int(strike * 1000):08d}"


# --------------------------------------------------------------------------- #
# Chain builder — including the no-lookahead guarantee
# --------------------------------------------------------------------------- #
class TestChainBuilder:
    def _provider_with_chain(self):
        p = MockProvider()
        as_of = date(2025, 1, 6)  # a Monday
        exp = date(2025, 1, 10)  # that Friday, 4 DTE
        p.stock = {as_of: 100.0}
        # A ladder of puts around spot, all traded on as_of.
        for strike in [85, 90, 95, 98, 100]:
            sym = _occ("XYZ", exp, "put", strike)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, float(strike), "put"),
                close=max(0.05, (100 - strike) * 0.02 + 0.30),
                traded_on=[as_of],
            )
        return p, as_of, exp

    def test_builds_priced_chain_with_greeks(self):
        p, as_of, exp = self._provider_with_chain()
        b = ChainBuilder(p, risk_free_rate=0.04)
        snap = b.build("XYZ", as_of, max_dte=7)
        assert snap is not None
        assert snap.underlying_price == 100.0
        assert len(snap.puts) == 5
        for q in snap.puts:
            assert q.dte == 4
            assert q.bid <= q.mark <= q.ask
            assert q.modeled_spread and q.modeled_greeks
            if q.implied_volatility is not None:
                assert -1.0 <= q.delta <= 0.0

    def test_no_lookahead_contract_listed_later_excluded(self):
        """A contract that only trades AFTER as_of must not appear in the chain."""
        p, as_of, exp = self._provider_with_chain()
        future = as_of + timedelta(days=1)
        later_exp = date(2025, 1, 17)
        sym = _occ("XYZ", later_exp, "put", 92)
        # Listed with a bar only on a future date, not on as_of.
        p.add_contract(
            OptionContract(sym, "XYZ", later_exp, 92.0, "put"),
            close=1.20,
            traded_on=[future],
        )
        b = ChainBuilder(p)
        snap = b.build("XYZ", as_of, max_dte=14)
        symbols = {q.symbol for q in snap.puts}
        assert sym not in symbols  # no bar on as_of -> excluded

    def test_expired_contract_excluded(self):
        """A contract expiring before as_of is outside the window."""
        p, as_of, exp = self._provider_with_chain()
        past_exp = as_of - timedelta(days=3)
        sym = _occ("XYZ", past_exp, "put", 95)
        p.add_contract(
            OptionContract(sym, "XYZ", past_exp, 95.0, "put"),
            close=0.50,
            traded_on=[as_of],  # even with an as_of bar, it's expired
        )
        b = ChainBuilder(p)
        snap = b.build("XYZ", as_of, max_dte=7)
        assert sym not in {q.symbol for q in snap.puts}

    def test_none_when_no_underlying_price(self):
        p, as_of, exp = self._provider_with_chain()
        b = ChainBuilder(p)
        assert b.build("XYZ", date(2025, 1, 7), max_dte=7) is None  # no stock bar


# --------------------------------------------------------------------------- #
# Chain store round-trip
# --------------------------------------------------------------------------- #
class TestChainStore:
    def test_round_trip(self, tmp_path):
        p = MockProvider()
        as_of = date(2025, 1, 6)
        exp = date(2025, 1, 10)
        p.stock = {as_of: 100.0}
        for strike in [90, 95, 100]:
            sym = _occ("XYZ", exp, "put", strike)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, float(strike), "put"),
                close=1.0,
                traded_on=[as_of],
            )
        snap = ChainBuilder(p).build("XYZ", as_of, max_dte=7)
        store = ChainStore(str(tmp_path))
        assert not store.has("XYZ", as_of)
        store.put(snap)
        assert store.has("XYZ", as_of)
        loaded = store.get("XYZ", as_of)
        assert loaded.underlying_price == 100.0
        assert len(loaded.puts) == 3
        assert {q.strike for q in loaded.puts} == {90.0, 95.0, 100.0}

    def test_empty_chain_round_trip(self, tmp_path):
        # An empty chain (price known, no contracts) must survive round-trip and
        # not be confused with a cache miss.
        from src.backtesting.data.chain_builder import ChainSnapshot

        store = ChainStore(str(tmp_path))
        snap = ChainSnapshot("XYZ", date(2025, 1, 6), 100.0, [], [])
        store.put(snap)
        assert store.has("XYZ", date(2025, 1, 6))
        loaded = store.get("XYZ", date(2025, 1, 6))
        assert loaded is not None
        assert loaded.underlying_price == 100.0
        assert loaded.puts == [] and loaded.calls == []


# --------------------------------------------------------------------------- #
# Coverage report
# --------------------------------------------------------------------------- #
class TestCoverage:
    def test_usable_fraction_and_verdict(self):
        p = MockProvider()
        # Ten trading days; put a usable in-band put on each.
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = 100.0
        # For each day, add a ~15-delta put expiring ~7 days out with premium>0.50.
        for d in days:
            exp = d + timedelta(days=7)
            # strike chosen to land near 0.15 delta; premium set above floor.
            sym = _occ("XYZ", exp, "put", 93)
            p.add_contract(
                OptionContract(sym, "XYZ", exp, 93.0, "put"),
                close=0.80,
                traded_on=[d],
            )
        b = ChainBuilder(p, risk_free_rate=0.04)
        report = evaluate_coverage(
            p, b, "XYZ", days[0], days[-1], max_dte=7, sample_every_trading_days=1
        )
        assert report.decision_days == 10
        assert report.days_with_underlying == 10
        # Delta of a 7% OTM 7DTE put depends on implied vol from premium; just
        # assert the plumbing produced candidates and a verdict string.
        assert report.usable_fraction >= 0.0
        assert report.verdict() in {"good", "marginal", "poor"}
        assert "usable_fraction" in report.summary()

    def test_does_not_refetch_the_underlying_per_decision_day(self):
        """Coverage already holds the window's closes; the builder must reuse them.

        A per-day underlying refetch is one wasted request per decision day, on a
        200 req/min tier that already bounds the run's wall time.
        """
        p = MockProvider()
        base = date(2025, 1, 6)
        days = [base + timedelta(days=i) for i in range(10)]
        for d in days:
            p.stock[d] = 100.0

        calls = {"n": 0}
        original = p.get_stock_bars

        def counting_get_stock_bars(symbol, start, end):
            calls["n"] += 1
            return original(symbol, start, end)

        p.get_stock_bars = counting_get_stock_bars

        b = ChainBuilder(p, risk_free_rate=0.04)
        evaluate_coverage(p, b, "XYZ", days[0], days[-1], max_dte=7, sample_every_trading_days=1)

        assert calls["n"] == 1, (
            f"expected a single windowed stock-bars fetch, got {calls['n']} "
            "(the builder is refetching the underlying per decision day)"
        )

    def test_zero_decision_days_is_no_data_not_poor(self):
        """A symbol with no bars must not read as 'poor' coverage.

        'poor' is the verdict that argues for paying a data vendor; an empty API
        response or a bad ticker is not evidence about coverage at all.
        """
        p = MockProvider()  # no stock bars at all
        b = ChainBuilder(p, risk_free_rate=0.04)
        report = evaluate_coverage(
            p, b, "NOSUCH", date(2025, 1, 6), date(2025, 1, 16), max_dte=7
        )
        assert report.decision_days == 0
        assert report.usable_fraction == 0.0
        assert report.verdict() == "no-data"
        assert report.summary()["verdict"] == "no-data"


# --------------------------------------------------------------------------- #
# Alpaca provider: real-time entitlement clamp
# --------------------------------------------------------------------------- #
class TestRealtimeClamp:
    """Alpaca 403s any request reaching into the undelayed window.

    Regression guard for the Phase 1 gate failing on all 14 symbols with
    "subscription does not permit querying recent SIP data" (stocks) and
    "OPRA agreement is not signed" (options) whenever --end was today.
    """

    def test_delayed_end_clamps_today_out_of_realtime_window(self):
        from src.backtesting.data.alpaca_provider import (
            REALTIME_DELAY_MINUTES,
            _delayed_end,
        )

        delay = timedelta(minutes=REALTIME_DELAY_MINUTES)
        before = datetime.now()
        got = _delayed_end(date.today())
        after = datetime.now()
        # Bracket the call rather than comparing to a single sampled clock read,
        # which races the microseconds elapsed inside _delayed_end.
        assert before - delay <= got <= after - delay

    def test_delayed_end_leaves_past_windows_untouched(self):
        from src.backtesting.data.alpaca_provider import _delayed_end

        past = date.today() - timedelta(days=30)
        assert _delayed_end(past) == datetime.combine(past, time.max)

    def test_current_session_bar_is_not_settled(self):
        from src.backtesting.data.alpaca_provider import _is_settled

        assert not _is_settled(date.today())
        assert _is_settled(date.today() - timedelta(days=1))

    def test_adjusted_contracts_are_not_standard_occ(self):
        """Real symbols Alpaca's contracts endpoint returned and its bars endpoint rejected."""
        from src.backtesting.data.alpaca_provider import is_standard_occ

        assert is_standard_occ("AAPL240429P00170000")
        assert is_standard_occ("NVDA260601C00152500")
        assert is_standard_occ("F240419P00012000")
        # Adjusted / non-standard deliverable — must never enter a wheel backtest.
        assert not is_standard_occ("1AAPL240429P00170000")
        assert not is_standard_occ("1MSFT240621C00241000")
        assert not is_standard_occ("")
        assert not is_standard_occ("AAPL240429X00170000")  # bad option type

    def test_universe_excludes_adjusted_contracts(self):
        from alpaca.trading.enums import ContractType

        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)

        class _C:
            def __init__(self, symbol):
                self.symbol = symbol
                self.expiration_date = date(2024, 4, 29)
                self.strike_price = 170.0
                self.type = ContractType.PUT

        class _Resp:
            next_page_token = None
            option_contracts = [
                _C("AAPL240429P00170000"),
                _C("1AAPL240429P00170000"),  # adjusted
            ]

        provider._trading.get_option_contracts = lambda req: _Resp()

        universe = provider.get_contract_universe("AAPL", date(2024, 4, 24), 7)
        symbols = [c.symbol for c in universe]
        assert symbols == ["AAPL240429P00170000"]

    def test_option_bars_screens_nonstandard_symbols(self):
        """One bad symbol 400s the whole chunk; the provider must not send it."""
        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)
        seen = {}

        class _Bars:
            data = {}

        def _stub(req):
            seen["symbols"] = list(req.symbol_or_symbols)
            return _Bars()

        provider._option_data.get_option_bars = _stub

        past = date.today() - timedelta(days=30)
        provider.get_option_bars(
            ["AAPL240429P00170000", "1AAPL240429P00170000"], past, past
        )
        assert seen["symbols"] == ["AAPL240429P00170000"]

        # All-nonstandard input must short-circuit without an API call at all.
        seen.clear()
        out = provider.get_option_bars(["1AAPL240429P00170000"], past, past)
        assert out == {} and "symbols" not in seen

    def test_contract_universe_is_memoized_per_process(self):
        """The chain builder and the coverage report ask for the same universe.

        Contract discovery paginates two statuses, so an unmemoized second call
        doubles the request count of every run against a 200 req/min limit.
        """
        from src.backtesting.data.alpaca_provider import AlpacaDataProvider

        provider = AlpacaDataProvider(api_key="k", secret_key="s", paper=True)

        calls = []

        class _StubResp:
            option_contracts = []
            next_page_token = None

        def _stub_get_option_contracts(req):
            calls.append(req)
            return _StubResp()

        provider._trading.get_option_contracts = _stub_get_option_contracts

        as_of = date(2025, 3, 4)
        first = provider.get_contract_universe("XYZ", as_of, 7)
        n_after_first = len(calls)
        second = provider.get_contract_universe("XYZ", as_of, 7)

        assert n_after_first > 0
        assert len(calls) == n_after_first, "second identical call must hit the memo"
        assert first == second

        # A different key still goes to the API.
        provider.get_contract_universe("XYZ", as_of, 14)
        assert len(calls) > n_after_first

        # Callers must not be able to corrupt the memo by mutating the result.
        first.append("junk")
        assert provider.get_contract_universe("XYZ", as_of, 7) == second

    def test_settlement_ignores_a_frozen_simulated_clock(self):
        """Entitlement is a wall-clock question, not a simulated-time one.

        If _is_settled honored the freeze, replaying June 2024 would classify
        every subsequent bar as unsettled and the provider would fetch nothing.
        """
        from src.backtesting.data.alpaca_provider import _delayed_end, _is_settled
        from src.utils import clock

        past = datetime(2024, 6, 3, 16, 0)
        with clock.frozen(past):
            assert clock.now() == past  # the freeze is genuinely in effect
            # A bar well after the frozen instant is still a settled session.
            assert _is_settled(date.today() - timedelta(days=1))
            # And the request cutoff still tracks real time, not 2024.
            assert _delayed_end(date.today()).year == date.today().year
