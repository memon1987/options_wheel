"""Pure return/risk math for the dashboard (FC-031).

No BigQuery or FastAPI imports — everything here takes plain Python values
so it can be unit-tested without cloud dependencies.

Conventions:
- Cash flows are (date, amount) with deposits POSITIVE (money into the
  account) and withdrawals negative, matching Alpaca JNLC net_amount.
- Equity points are (date, account_value) end-of-day observations.
- XIRR follows the spreadsheet convention: solve NPV(rate) = 0 over flows
  where investor outflows (deposits) are negative and the terminal value is
  a positive inflow. The sign flip from JNLC convention happens inside.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

Flow = Tuple[date, float]
EquityPoint = Tuple[date, float]


def xirr(flows: List[Flow], terminal: Flow) -> Optional[float]:
    """Money-weighted annual return (spreadsheet XIRR).

    ``flows``: dated external flows in JNLC convention (deposit positive).
    ``terminal``: (as-of date, current account value).

    Returns None when undefined: no flows, zero/negative time span, or no
    sign change (e.g. account value has gone to zero alongside deposits).
    """
    if not flows or terminal[1] is None:
        return None
    t0 = min(d for d, _ in flows)
    span_days = (terminal[0] - t0).days
    if span_days <= 0:
        return None

    # Investor perspective: deposits are outflows (negative), terminal value inflow.
    cfs = [(d, -amt) for d, amt in flows if amt is not None and amt != 0]
    cfs.append(terminal)
    if not any(a > 0 for _, a in cfs) or not any(a < 0 for _, a in cfs):
        return None

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** ((d - t0).days / 365.0) for d, a in cfs)

    # Bisection on (-0.999, huge). NPV is monotonically decreasing in rate
    # for the standard invest-then-collect shape; guard against no bracket.
    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    tries = 0
    while f_lo * f_hi > 0 and tries < 10:
        hi *= 2
        f_hi = npv(hi)
        tries += 1
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _flows_by_date(flows: List[Flow]) -> Dict[date, float]:
    out: Dict[date, float] = {}
    for d, amt in flows:
        if amt:
            out[d] = out.get(d, 0.0) + amt
    return out


def twr_series(
    equity_points: List[EquityPoint], flows: List[Flow]
) -> List[Tuple[date, float]]:
    """GIPS-style chain-linked TWR index (base 100) over the equity series.

    A flow dated D is treated as start-of-day D: the sub-period return for D
    is (EV_D − flow_D) / EV_{D−1}. Equity points before the first positive
    equity observation are skipped. Points must be pre-sorted or sortable.
    """
    pts = sorted((d, v) for d, v in equity_points if v is not None)
    if not pts:
        return []
    fl = _flows_by_date(flows)
    series: List[Tuple[date, float]] = []
    index = 100.0
    prev_val: Optional[float] = None
    prev_date: Optional[date] = None
    for d, v in pts:
        if prev_val is None:
            series.append((d, index))
            prev_val, prev_date = v, d
            continue
        # Sum flows that landed after the previous observation, up to and
        # including this one (handles weekend deposits with no equity row).
        flow = sum(a for fd, a in fl.items() if prev_date < fd <= d)
        if prev_val > 0:
            r = (v - flow - prev_val) / prev_val
            index *= 1.0 + r
        series.append((d, index))
        prev_val, prev_date = v, d
    return series


def twr(equity_points: List[EquityPoint], flows: List[Flow]) -> Optional[float]:
    """Cumulative time-weighted return over the whole series (fraction)."""
    series = twr_series(equity_points, flows)
    if len(series) < 2 or series[0][1] == 0:
        return None
    return series[-1][1] / series[0][1] - 1.0


def annualize(cumulative: Optional[float], days: int) -> Optional[float]:
    """Annualize a cumulative return over `days`. None below 90 days —
    short-window annualization is noise, not information."""
    if cumulative is None or days < 90:
        return None
    return (1.0 + cumulative) ** (365.0 / days) - 1.0


def max_drawdown(
    equity_points: List[EquityPoint], flows: List[Flow]
) -> Dict[str, Optional[object]]:
    """Max and current drawdown on the flow-adjusted (TWR-indexed) curve.

    Using the TWR index means a deposit can neither mask a drawdown nor
    fabricate a recovery. Returns fractions ≤ 0 plus the peak/trough dates.
    """
    series = twr_series(equity_points, flows)
    if len(series) < 2:
        return {"max_dd": None, "max_dd_peak": None, "max_dd_trough": None, "current_dd": None}
    peak_val = series[0][1]
    peak_date = series[0][0]
    max_dd = 0.0
    max_peak: Optional[date] = None
    max_trough: Optional[date] = None
    for d, v in series:
        if v > peak_val:
            peak_val, peak_date = v, d
        dd = (v - peak_val) / peak_val if peak_val > 0 else 0.0
        if dd < max_dd:
            max_dd, max_peak, max_trough = dd, peak_date, d
    current_dd = (series[-1][1] - peak_val) / peak_val if peak_val > 0 else None
    return {
        "max_dd": max_dd if max_dd < 0 else 0.0,
        "max_dd_peak": max_peak,
        "max_dd_trough": max_trough,
        "current_dd": current_dd,
    }


def dollar_drawdown(
    equity_points: List[EquityPoint], flows: List[Flow]
) -> Dict[str, Optional[object]]:
    """Max peak-to-trough drawdown in DOLLARS on flow-adjusted equity.

    Flow-adjusted equity = raw equity − cumulative external flows, so a
    deposit neither erases a drawdown nor manufactures one. Complements the
    percentage drawdown from `max_drawdown` (a PM wants both).
    """
    pts = sorted((d, v) for d, v in equity_points if v is not None)
    if len(pts) < 2:
        return {"max_dd_dollars": None, "current_dd_dollars": None}
    fl = sorted(_flows_by_date(flows).items())
    out: List[Tuple[date, float]] = []
    cum = 0.0
    i = 0
    for d, v in pts:
        while i < len(fl) and fl[i][0] <= d:
            cum += fl[i][1]
            i += 1
        out.append((d, v - cum))
    peak = out[0][1]
    max_dd = 0.0
    for _, v in out:
        peak = max(peak, v)
        max_dd = min(max_dd, v - peak)
    return {
        "max_dd_dollars": max_dd if max_dd < 0 else 0.0,
        "current_dd_dollars": out[-1][1] - peak,
    }


def indexed_curve(
    equity_points: List[EquityPoint], flows: List[Flow]
) -> List[Dict[str, object]]:
    """TWR index as chart-ready dicts: [{date: iso, index: float}, ...]."""
    return [
        {"date": d.isoformat(), "index": round(v, 4)}
        for d, v in twr_series(equity_points, flows)
    ]
