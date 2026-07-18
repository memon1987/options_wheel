"""Black-Scholes pricing and greeks for point-in-time chain construction.

Alpaca does not serve historical implied volatility or greeks (only live
snapshots), and it serves no historical bid/ask at all — only trade-derived
bars. So for a backtest we must *compute* delta and IV ourselves from the
option's traded price (the bar close) and the underlying's price on the same
day. These are the standard European Black-Scholes formulas with a continuous
dividend yield.

Two honest caveats, surfaced wherever these values are used:
  * Delta/IV are derived from a daily trade print, not a quote midpoint, so
    they inherit whatever staleness the last trade carries.
  * European BS is a fine approximation for the short-dated OTM options the
    wheel sells; it misprices deep-ITM American options near a dividend. The
    engine handles early exercise separately in the broker, not here.
"""

from __future__ import annotations

import math

# Standard normal CDF and PDF (avoid a scipy dependency for such simple math).


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1(S: float, K: float, T: float, r: float, sigma: float, q: float) -> float:
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float,
    option_type: str,
) -> float:
    """Black-Scholes price of a European option with continuous dividend yield.

    Args:
        S: underlying spot price.
        K: strike price.
        T: time to expiration in years.
        r: continuously-compounded risk-free rate.
        sigma: volatility (annualized).
        q: continuous dividend yield.
        option_type: 'put' or 'call'.

    Returns:
        Theoretical option price. At/after expiration (T <= 0) or with a
        non-positive vol, returns intrinsic value.
    """
    option_type = option_type.lower()
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        intrinsic = (S - K) if option_type == "call" else (K - S)
        return max(0.0, intrinsic)

    d1 = _d1(S, K, T, r, sigma, q)
    d2 = d1 - sigma * math.sqrt(T)
    disc_r = math.exp(-r * T)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return S * disc_q * _norm_cdf(d1) - K * disc_r * _norm_cdf(d2)
    return K * disc_r * _norm_cdf(-d2) - S * disc_q * _norm_cdf(-d1)


def bs_delta(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float,
    option_type: str,
) -> float:
    """Black-Scholes delta (dividend-adjusted).

    Calls in [0, 1], puts in [-1, 0]. At/after expiration returns the terminal
    delta (0 or ±1 depending on moneyness).
    """
    option_type = option_type.lower()
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    d1 = _d1(S, K, T, r, sigma, q)
    disc_q = math.exp(-q * T)
    if option_type == "call":
        return disc_q * _norm_cdf(d1)
    return -disc_q * _norm_cdf(-d1)


def implied_vol(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    option_type: str,
    *,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Invert Black-Scholes for implied volatility via bisection.

    Bisection (not Newton) is deliberate: it is robust for the deep-OTM, thin,
    near-worthless weeklies the wheel trades, where vega collapses and Newton
    diverges. Returns None when no vol reproduces the price within the search
    bracket (e.g. the price is below intrinsic — common with stale/wide prints),
    so callers can fall back rather than trust a garbage number.

    Args:
        price: observed option price to match.
        S, K, T, r, q, option_type: Black-Scholes inputs (see bs_price).
        lo, hi: volatility search bracket.
        tol: price-match tolerance.
        max_iter: bisection iteration cap.
    """
    if price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None

    # Price must exceed (discounted) intrinsic for a real IV to exist.
    intrinsic = bs_price(S, K, T, r, hi, q, option_type)  # upper-bracket price
    lo_price = bs_price(S, K, T, r, lo, q, option_type)
    if price <= lo_price:
        # At or below the lowest-vol price; either no solution or ~zero vol.
        return lo if abs(price - lo_price) <= tol else None
    if price >= intrinsic:
        # Above the highest-vol price in the bracket; vol exceeds hi.
        return None

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        p = bs_price(S, K, T, r, mid, q, option_type)
        if abs(p - price) < tol:
            return mid
        if p > price:
            b = mid
        else:
            a = mid
    return 0.5 * (a + b)


def year_fraction(dte_days: int, *, basis: float = 365.0) -> float:
    """Convert integer days-to-expiration into a year fraction for BS.

    Uses a 365-day calendar basis (matches the live strategy's annualization in
    market_data.py, which uses 365/dte). A floor of half a day keeps expiration
    day itself from collapsing T to exactly zero mid-simulation.
    """
    return max(dte_days, 0.5) / basis
