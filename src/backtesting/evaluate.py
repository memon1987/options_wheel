"""Evaluate mode — run one symbol end to end and produce its fitness report.

Ties the pieces together: data provider → chain builder → simulator (which drives
the live strategy) → cycle analytics → fitness scorecard → markdown/JSON.

Also runs the **fill sensitivity** pass the plan requires. The headline result
uses mid-minus-haircut fills; the same window is replayed at the bid, and if the
verdict flips between the two the report says so outright. A fitness call that
survives only under optimistic fills is not a fitness call.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Sequence

import structlog

from ..utils.config import Config
from .data.alpaca_provider import AlpacaDataProvider
from .data.chain_builder import ChainBuilder
from .engine.simulator import SimulationResult, Simulator
from .metrics.cycles import build_cycles, count_rolls
from .metrics.fitness import FitnessReport, compute_fitness

logger = structlog.get_logger(__name__)

# Fill haircut of 1.0 = sell at the bid: the worst case a marketable order sees.
BID_FILL_HAIRCUT = 1.0


def evaluate_symbol(
    symbol: str,
    start: date,
    end: date,
    *,
    config: Optional[Config] = None,
    starting_cash: float = 100_000.0,
    fill_haircut: float = 0.25,
    run_sensitivity: bool = True,
) -> tuple:
    """Replay ``symbol`` and score it.

    Returns:
        ``(FitnessReport, sensitivity_dict_or_None)``.
    """
    config = config or Config()
    provider = AlpacaDataProvider.from_config(config)
    builder = ChainBuilder(provider)
    max_dte = getattr(config, "put_target_dte", 7)

    result = _run(
        symbol, start, end, config, provider, builder,
        starting_cash=starting_cash, fill_haircut=fill_haircut, max_dte=max_dte,
    )
    report = _score(symbol, result, provider, starting_cash)

    sensitivity = None
    if run_sensitivity:
        bid_result = _run(
            symbol, start, end, config, provider, builder,
            starting_cash=starting_cash, fill_haircut=BID_FILL_HAIRCUT, max_dte=max_dte,
        )
        bid_report = _score(symbol, bid_result, provider, starting_cash)
        sensitivity = {
            "mid_haircut": fill_haircut,
            "mid_return": report.total_return,
            "mid_verdict": report.verdict(),
            "bid_return": bid_report.total_return,
            "bid_verdict": bid_report.verdict(),
            "verdict_flips": report.verdict() != bid_report.verdict(),
            "return_delta": bid_report.total_return - report.total_return,
        }
        if sensitivity["verdict_flips"]:
            logger.warning(
                "Fitness verdict depends on the fill assumption",
                event_category="backtest", event_type="fill_sensitivity_flip",
                symbol=symbol, mid_verdict=report.verdict(),
                bid_verdict=bid_report.verdict(),
            )
    return report, sensitivity


def _run(
    symbol: str, start: date, end: date, config, provider, builder, *,
    starting_cash: float, fill_haircut: float, max_dte: int,
) -> SimulationResult:
    simulator = Simulator(
        config, provider, builder, [symbol], start, end,
        starting_cash=starting_cash, max_dte=max_dte, fill_haircut=fill_haircut,
    )
    return simulator.run()


def _score(
    symbol: str, result: SimulationResult, provider, starting_cash: float
) -> FitnessReport:
    cycles = build_cycles(result.broker.ledger)
    prices = _closes(provider, symbol, result.start, result.end)
    quality = _data_quality(result, cycles)
    return compute_fitness(
        symbol, result.daily, cycles, starting_cash,
        benchmark_prices=prices, data_quality=quality, rolls=count_rolls(cycles),
    )


def _closes(provider, symbol: str, start: date, end: date) -> Dict[date, float]:
    return {b.bar_date: b.close for b in provider.get_stock_bars(symbol, start, end)}


def _data_quality(result: SimulationResult, cycles: Sequence) -> Dict:
    """Facts a reader needs to judge whether the result rests on real data."""
    return {
        "decision_days": len(result.daily),
        "days_with_a_qualifying_candidate": result.candidate_days,
        "blocked_days_by_reason": result.rejections,
        "ledger_events": len(result.broker.ledger),
        "cycles_still_open_at_end": sum(1 for c in cycles if c.is_open),
        "option_marks": "daily bar closes (trade prints); bid/ask modeled",
        "greeks": "Black-Scholes inversions, not published values",
    }
