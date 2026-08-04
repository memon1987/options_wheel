"""Roll-leg risk validation for the options wheel strategy.

FC-069 item 7 (absorbing FC-014) shrank this module to its one live method.
Six methods were deleted with zero production call sites ever recorded:
``validate_new_position``, ``_validate_option_specific_risks``,
``calculate_portfolio_risk_metrics``, ``should_reduce_positions``,
``get_emergency_stop_conditions`` and ``check_emergency_conditions``. Two of
them carried the ancestral OCC-substring bugs (``underlying_symbol in
p['symbol']``, ``'PUT' in pos['symbol']``) that would have misbehaved had they
ever been wired.

Their pre-trade checks are dispositioned elsewhere, not lost: the global
position cap, the per-stock cap and per-ticker exposure were deleted as knobs
(FC-069 items 1/2/3), portfolio allocation and cash reserve likewise (card 17 /
item 7 rider), and enforcement on this system is distributed by design —
scanner filters, `select_batch` ledgers, the execute-time cost-basis floor, and
the hourly `/regression` detective layer. The account-level loss-limit concepts
the emergency-stop methods encoded were never running code; whether this system
should have a kill switch is **FC-074**, to be answered with the account's own
drawdown history rather than the dead code's inherited 15%/5%.
"""

from datetime import date
from typing import Dict, Any, Tuple
import structlog

from ..utils.config import Config
from ..utils.option_symbols import coerce_expiry_date

logger = structlog.get_logger(__name__)


class RiskManager:
    """Validates call-roll replacement legs for the Friday roller."""

    def __init__(self, config: Config):
        """Initialize risk manager.
        
        Args:
            config: Configuration instance
        """
        self.config = config
        
    def validate_roll(self, new_call: Dict[str, Any], current_strike: float,
                      cost_basis_per_share: float,
                      max_expiry: date) -> Tuple[bool, str]:
        """Validate a call roll replacement leg.

        Deliberately carries no portfolio-level checks (position count,
        concentration, cash reserve): a roll is a replacement, not a new
        position. The method that once carried them never ran and was deleted
        by FC-069 item 7.

        FC-078 rewrote three of the five checks (DD-3):

        - The **entry delta band** is replaced by a bare upper rail. The band's
          lower bound forces far-OTM replacements exactly when a defensive roll
          needs near-money strikes — the documented trap that made shallow-ITM
          rescue illegal. The rail still blocks replace-ITM-with-deep-ITM churn.
        - The **DTE cap** is replaced by an expiry-relative date bound. Roll
          economics extend the *existing contract's* tenor, so the horizon is
          measured from the old expiry, not from today. The eval-relative frame
          would have excluded GOOGL C370 8/07 -> C375 8/21 (17 DTE from the
          evaluation, exactly old-expiry + 14).
        - The **``min_call_premium`` floor is gone**: what a roll must clear is
          the net credit against the contract being closed, which the roller
          enforces on the placed limit prices. A standalone premium floor
          answers a question nobody asked on this path.

        Args:
            new_call: Candidate replacement call from find_suitable_calls
            current_strike: Strike of the call being closed
            cost_basis_per_share: Stock cost basis per share
            max_expiry: Latest expiration the replacement may carry — the
                roller computes it as ``old expiry + rolling_max_extension_days``.
                Required, not defaulted: a roll horizon that silently falls back
                to "no bound" is how a defensive roll parks capital under a cap
                for a month.

        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            new_strike = new_call.get('strike_price', 0)

            # Roll-up only: new strike must exceed current strike
            if new_strike <= current_strike:
                return False, f"New strike {new_strike} not above current {current_strike} (roll-up only)"

            # Cost basis protection
            if new_strike < cost_basis_per_share:
                return False, f"New strike {new_strike} below cost basis {cost_basis_per_share:.2f}"

            # Delta upper rail (FC-078 DD-3) — no lower bound
            delta = abs(new_call.get('delta', 0))
            max_delta = self.config.rolling_max_replacement_delta
            if delta > max_delta:
                return False, f"Delta {delta:.3f} above roll rail {max_delta}"

            # Expiry within the expiry-relative roll-out horizon (FC-078 DD-3).
            # Fail closed on an unparseable expiry: "we could not tell how far
            # out this expires" must not resolve to "sell it".
            expiry = coerce_expiry_date(new_call.get('expiration_date'))
            if expiry is None:
                return False, (
                    f"Replacement expiry unparseable "
                    f"({new_call.get('expiration_date')!r})")
            horizon = coerce_expiry_date(max_expiry)
            if horizon is None:
                return False, f"Roll horizon unparseable ({max_expiry!r})"
            if expiry > horizon:
                return False, (
                    f"Expiry {expiry.isoformat()} beyond roll horizon "
                    f"{horizon.isoformat()}")

            return True, "Roll target validated"

        except Exception as e:
            logger.error("Roll validation failed",
                        event_category="error",
                        event_type="roll_validation_failed",
                        error=str(e))
            return False, f"Roll validation error: {str(e)}"
