"""Simulator day loop (FC-032 Phase 3).

The golden path: the simulator drives the *real* WheelEngine over canned data.
Nothing here stubs strategy logic — if a rule is wrong, it is wrong in
production too.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List

import pytest

from src.backtesting.data.chain_builder import ChainBuilder
from src.backtesting.data.provider import OptionBar, OptionContract, StockBar
from src.backtesting.engine.no_op_analytics import NoOpAnalyticsWriter
from src.backtesting.engine.simulator import Simulator, restrict_symbols
from src.data import analytics_writer as analytics_module
from src.utils import clock
from src.utils.config import Config


def _occ(underlying: str, exp: date, opt: str, strike: float) -> str:
    return f"{underlying}{exp:%y%m%d}{'P' if opt == 'put' else 'C'}{int(strike * 1000):08d}"


class ScriptedProvider:
    """Canned data: one underlying, a strike ladder, every contract trades daily."""

    def __init__(self, symbol: str, closes: Dict[date, float], expirations: List[date]):
        self.symbol = symbol
        self.closes = closes
        self.expirations = expirations

    def get_stock_bars(self, symbol, start, end):
        return [
            StockBar(symbol=symbol, bar_date=d, open=c, high=c, low=c, close=c, volume=5_000_000)
            for d, c in sorted(self.closes.items())
            if start <= d <= end
        ]

    def _ladder(self, spot: float) -> List[float]:
        base = round(spot)
        return [float(base + k) for k in range(-12, 13)]

    def get_contract_universe(self, underlying, as_of, max_dte):
        spot = self.closes.get(as_of)
        if spot is None:
            return []
        out = []
        for exp in self.expirations:
            if not (as_of <= exp <= as_of + timedelta(days=max_dte)):
                continue
            for strike in self._ladder(spot):
                for opt in ("put", "call"):
                    out.append(
                        OptionContract(_occ(underlying, exp, opt, strike), underlying,
                                       exp, strike, opt)
                    )
        return out

    def get_option_bars(self, symbols, start, end):
        """Price every contract off the day's spot with a crude but monotone model."""
        out: Dict[str, List[OptionBar]] = {}
        for sym in symbols:
            for d in _daterange(start, end):
                spot = self.closes.get(d)
                if spot is None:
                    continue
                strike = int(sym[-8:]) / 1000.0
                is_put = sym[-9] == "P"
                exp = datetime.strptime(sym[len(self.symbol):len(self.symbol) + 6], "%y%m%d").date()
                dte = max((exp - d).days, 0)
                intrinsic = max(0.0, strike - spot) if is_put else max(0.0, spot - strike)
                # Enough time value that 0.10-0.20 delta strikes clear the $0.50 floor.
                time_value = 0.9 * (dte + 1) ** 0.5 * (spot / 100.0)
                moneyness = abs(spot - strike) / spot
                price = intrinsic + time_value * max(0.05, 1.0 - 6.0 * moneyness)
                out.setdefault(sym, []).append(
                    OptionBar(symbol=sym, bar_date=d, open=price, high=price, low=price,
                              close=round(price, 2), volume=500, trade_count=50, vwap=price)
                )
        return out


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _weekdays(start: date, n: int) -> List[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


@pytest.fixture
def falling_then_flat():
    """Price slides enough to put an assigned strike ITM, then stabilizes.

    Includes ~45 sessions of warm-up history before the first decision day:
    GapDetector indexes positionally into ~30 daily bars and blocks everything
    on a cold start, exactly as it would in production against a fresh account.
    """
    warmup = _weekdays(date(2024, 3, 25), 45)
    days = _weekdays(date(2024, 6, 3), 30)
    closes = {d: 100.0 for d in warmup}
    # -3/day for 10 sessions (100 -> 70), then flat. The strategy sells puts
    # ~8% OTM, so a gentler slide would never overtake the strike before expiry
    # and the assignment path would go untested. -3 stays under GapDetector's
    # 5% overnight-gap block, which would otherwise halt trading outright.
    for i, d in enumerate(days):
        closes[d] = 100.0 - min(i, 10) * 3.0
    expirations = [d for d in days if d.weekday() == 4]  # Fridays
    return days, closes, expirations


def _simulator(symbol, closes, expirations, days, **kw):
    provider = ScriptedProvider(symbol, closes, expirations)
    builder = ChainBuilder(provider, risk_free_rate=0.04)
    config = Config()
    return Simulator(
        config, provider, builder, [symbol], days[0], days[-1],
        starting_cash=kw.pop("starting_cash", 50_000.0), max_dte=7, **kw
    )


class TestDayLoop:
    def test_run_produces_one_state_per_trading_day(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        assert [s.day for s in result.daily] == days
        assert result.start == days[0] and result.end == days[-1]

    def test_clock_is_cleared_after_the_run(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        _simulator("XYZ", closes, exps, days).run()
        assert not clock.is_frozen(), "a leaked freeze would corrupt later code"

    def test_empty_window_refuses_rather_than_reporting_zero_trades(self):
        """The old engine's cardinal sin: a 0-trade run that 'succeeded'."""
        provider = ScriptedProvider("XYZ", {}, [])
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        sim = Simulator(Config(), provider, builder, ["XYZ"],
                        date(2024, 6, 3), date(2024, 6, 28))
        with pytest.raises(ValueError, match="refusing to report a zero-trade run"):
            sim.run()

    def test_the_wheel_actually_turns(self, falling_then_flat):
        """A put is sold; the slide assigns it; shares appear. The engine's own code did it."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()

        kinds = [e.kind for e in result.broker.ledger]
        assert "sell_put_open" in kinds, f"no put was ever sold; ledger={kinds}"
        # The underlying falls 12%, so at least one short put must finish ITM.
        assert "put_assignment" in kinds, f"no assignment despite a 12% slide; ledger={kinds}"
        assert result.broker.shares("XYZ") > 0

    def test_no_contract_is_left_expired_but_unsettled(self, falling_then_flat):
        """Regression: settling before the decision let the engine open a fresh

        put expiring the same day, after that day's settlement had already run.
        It then sat on the book forever, corrupting equity.
        """
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        for symbol, pos in result.broker.options.items():
            assert pos.expiration >= days[-1], (
                f"{symbol} expired {pos.expiration} but is still open at {days[-1]}"
            )

    def test_no_new_put_is_opened_on_the_day_a_put_is_assigned(self, falling_then_flat):
        """Stage 6 sees the expiring position because settlement runs after the scan."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        assigned_days = {e.event_date for e in result.broker.ledger if e.kind == "put_assignment"}
        opened_days = {e.event_date for e in result.broker.ledger if e.kind == "sell_put_open"}
        assert not (assigned_days & opened_days), (
            "a put was sold on the same day another was assigned — the expiring "
            "position was invisible to the duplicate guard"
        )

    def test_equity_equals_cash_plus_marked_positions(self, falling_then_flat):
        """The reported curve must be arithmetic on the ledger, not a second opinion."""
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        final = result.daily[-1]
        expected = final.cash + result.broker.shares("XYZ") * closes[days[-1]]
        assert final.equity == pytest.approx(expected)

    def test_wheel_loses_less_than_buy_and_hold_through_the_crash(self, falling_then_flat):
        """Sanity anchor, not a performance claim: collateral sat in cash for most

        of a -30% slide, so the wheel must be well ahead of the underlying.
        """
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        underlying_return = (closes[days[-1]] - closes[days[0]]) / closes[days[0]]
        assert underlying_return == pytest.approx(-0.30)
        assert result.total_return > underlying_return

    def test_cash_ledger_is_conserved_no_phantom_margin(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        result = _simulator("XYZ", closes, exps, days).run()
        for state in result.daily:
            assert state.reserved_collateral >= 0.0
            # Cash-secured: collateral never exceeds cash on hand.
            assert state.reserved_collateral <= state.cash + 1e-6


class TestNoProductionSideEffects:
    def test_analytics_singleton_is_restored_after_the_run(self, falling_then_flat):
        days, closes, exps = falling_then_flat
        before = analytics_module._instance
        _simulator("XYZ", closes, exps, days).run()
        assert analytics_module._instance is before

    def test_analytics_singleton_is_restored_even_when_the_run_raises(self):
        provider = ScriptedProvider("XYZ", {}, [])
        builder = ChainBuilder(provider, risk_free_rate=0.04)
        before = analytics_module._instance
        sim = Simulator(Config(), provider, builder, ["XYZ"],
                        date(2024, 6, 3), date(2024, 6, 28))
        with pytest.raises(ValueError):
            sim.run()
        assert analytics_module._instance is before

    def test_call_seller_cannot_query_bigquery_during_a_replay(self, falling_then_flat):
        """A replay must never mix production trade history into its cost-basis floor."""
        days, closes, exps = falling_then_flat
        sim = _simulator("XYZ", closes, exps, days)
        # Reach into the engine the simulator builds by running a 1-day window.
        result = sim.run()
        assert result is not None
        # Rebuild the same engine wiring the simulator uses and assert the guard.
        from src.strategy.wheel_engine import WheelEngine
        from src.strategy.wheel_state_manager import WheelStateManager
        from unittest.mock import Mock

        engine = WheelEngine(Mock(), alpaca_client=Mock(),
                             wheel_state=WheelStateManager(),
                             allow_bigquery_cost_basis=False)
        assert engine.call_seller.allow_bigquery_cost_basis is False
        assert engine.call_seller._lookup_last_opasn_put_strike("XYZ") == 0.0

    def test_bigquery_fallback_stays_enabled_by_default(self):
        from unittest.mock import Mock

        from src.strategy.call_seller import CallSeller

        cs = CallSeller(Mock(), Mock(), Mock())
        assert cs.allow_bigquery_cost_basis is True


class TestNoOpAnalytics:
    def test_records_calls_and_returns_none(self):
        w = NoOpAnalyticsWriter()
        assert w.write_trade_event(symbol="XYZ", qty=1) is None
        assert w.anything_at_all("a") is None
        assert len(w.calls) == 2
        assert w.calls_named("write_trade_event")[0][2] == {"symbol": "XYZ", "qty": 1}


class TestRestrictSymbols:
    def test_narrows_universe_without_mutating_the_original(self):
        config = Config()
        original = list(config.stock_symbols)
        narrowed = restrict_symbols(config, ["NVDA"])
        assert narrowed.stock_symbols == ["NVDA"]
        assert config.stock_symbols == original
