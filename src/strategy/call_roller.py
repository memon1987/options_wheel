"""Covered call rolling engine — daily, credit-only defensive rolls.

Plan: docs/plans/fc-078.md (revives FC-006, which never executed a roll in
production; FC-066 diagnosed the four stacked causes).

Buys-to-close an ITM short call and sells-to-open a higher strike further out,
as two sequential single-leg limit orders, **BTC first**. The whole design turns
on one invariant:

    STO_limit - BTC_limit >= rolling.min_net_credit_per_contract / 100

checked on the *limit prices actually placed*, at four sites: the candidate
screen, immediately before BTC placement, order construction, and every ladder
rung. Because both legs are limit orders, fills can only improve on it (BTC
fills at <= limit, STO at >= limit), so **a filled roll can never net a debit**.
There is no debit path to tolerate, so there is no debit tolerance — and no
dependency on a wheel-state ``original_premium`` that has never persisted.

Terminal-event contract (FC-078 DD-5): every short call evaluated in a cycle
emits **exactly one** terminal event, one of:

    call_roll_skipped{skip_reason}   no order was ever placed
    call_roll_btc_rejected           the BTC was refused; nothing live
    call_roll_btc_timeout_canceled   canceled with VERIFIED zero fill
    call_roll_naked_exposure         some BTC qty filled, STO ladder exhausted
    call_roll_completed              both legs done
    call_roll_dry_run                ROLLER_DRY_RUN=true; nothing placed

Events must tell the truth about what filled. A cancel that fails *because the
order filled* is a fill, not an error — which is why every cancel on this path
is followed by a re-fetch before anything is reported.
"""

import time
from datetime import date, timedelta
from typing import Dict, Any, Iterator, List, Optional, Set, Tuple

import structlog

from ..api.alpaca_client import AlpacaClient
from ..api.market_data import MarketDataManager
from ..api.earnings_calendar import (
    EarningsCalendarService, EARNINGS_KNOWN, EARNINGS_UNKNOWN)
from ..risk.risk_manager import RiskManager
from ..utils.config import Config
from ..utils.option_symbols import parse_option_symbol, coerce_expiry_date
from ..utils.logging_events import log_trade_event, log_error_event, log_position_update
from .cost_basis import CostBasisResolver, SOURCE_DIVERGENT

logger = structlog.get_logger(__name__)

# Float slack on the credit comparison. Limits are rounded to cents before the
# invariant is tested, so this only absorbs binary-representation noise on an
# exactly-at-the-floor roll (the default floor is $0.00, which is exactly the
# case that must not be rejected by 1e-17).
_CREDIT_EPSILON = 1e-9

# Half-spread crossed in imminence mode, per share. Symmetric on both legs so
# the invariant is tested against a like-for-like pair.
_IMMINENCE_PAD = 0.05

# Stock-quote spread sanity bound. A live IEX example that motivated it: AAPL
# bid 287.82 / ask 318.75 — a 10.7% spread that makes the ITM ratio 0.92 or 1.02
# depending on which side you trust. A quote that wide must not gate a money
# decision.
_MAX_STOCK_SPREAD_RATIO = 1.05

# Statuses at which an order is done moving on its own. ``partially_filled`` is
# deliberately absent: it is NOT terminal, and returning on it (as the as-built
# code did) leaves the remainder working while the next leg is placed.
_TERMINAL_ORDER_STATUSES = ('filled', 'expired', 'canceled', 'rejected')


class CallRoller:
    """Daily credit-only covered-call rolling engine."""

    def __init__(self, alpaca_client: AlpacaClient, market_data: MarketDataManager,
                 config: Config,
                 risk_manager: RiskManager,
                 earnings_calendar: Optional[EarningsCalendarService] = None,
                 allow_bigquery_cost_basis: bool = True):
        """Initialize the call roller.

        Args:
            alpaca_client: Alpaca API client.
            market_data: Market data manager.
            config: Configuration instance.
            risk_manager: Validates the replacement leg.
            earnings_calendar: Earnings service for the FC-013 span gate on the
                replacement. Required whenever ``earnings.enabled`` — a missing
                service fails the roll CLOSED (``earnings_unknown``), never open.
            allow_bigquery_cost_basis: whether the cost-basis divergence
                cross-check may query BigQuery. A backtest passes False: the
                cross-check would otherwise read *production* trade history —
                against CURRENT_TIMESTAMP() — mixing real assignments into a
                simulated run. Mirrors ``CallSeller`` (FC-065).

        There is no state-manager parameter. FC-078 DD-6 deleted the roller's
        persistence dependency rather than repairing it: the only consumer was
        the debit tolerance's ``original_premium``, credit-only has no debit to
        tolerate, and ``STATE_STORAGE_BUCKET`` has been unset since project
        start so nothing was ever persisted to read back. Alpaca positions are
        the truth; ``reconcile_positions`` already rebuilds from them.
        """
        self.alpaca = alpaca_client
        self.market_data = market_data
        self.config = config
        self.risk_manager = risk_manager
        self.earnings_calendar = earnings_calendar
        # FC-065 Phase 2: the roll's strike floor is resolved through the same
        # shared resolver the scanner and the seller use — one floor
        # implementation, no fifth copy. The suite's hermeticity guard patches
        # ``_lookup_assignment_basis`` on the class, so this instance is covered
        # like the other two.
        self.cost_basis_resolver = CostBasisResolver(
            alpaca_client, config, allow_bigquery=allow_bigquery_cost_basis
        )

    # ------------------------------------------------------------------ #
    # Terminal events
    # ------------------------------------------------------------------ #
    def log_terminal_skip(self, option_symbol: str, underlying: str,
                          skip_reason: str, **fields: Any) -> None:
        """Emit the ``call_roll_skipped`` terminal event.

        Public because the cycle owns two skip reasons the roller cannot see
        from inside a single position's evaluation — ``cycle_budget_exhausted``
        and ``open_orders_unavailable`` — and the terminal-event contract is
        only worth anything if every path spells the event the same way.
        """
        log_trade_event(
            logger, event_type="call_roll_skipped",
            symbol=option_symbol, underlying=underlying,
            strategy="roll_call", success=False,
            skip_reason=skip_reason, gate_failed=skip_reason,
            **fields,
        )

    # ------------------------------------------------------------------ #
    # Eligibility
    # ------------------------------------------------------------------ #
    def should_roll(self, short_call_position: Dict[str, Any],
                    stock_position: Dict[str, Any],
                    current_stock_price: float,
                    open_order_symbols: Optional[Set[str]] = None
                    ) -> Tuple[bool, str]:
        """Check the pre-order eligibility gates for rolling a short call.

        FC-078 DD-2 deleted three gates and added one:

        - **DTE <= 1 is gone.** It existed to bound *debit* escalation near
          expiry; credit-only removes the hazard, and it is precisely what
          blinded the roller — a churned book's calls are 5-7 DTE on any given
          day (FC-066 cause 2). Self-timing is the credit sign, not the calendar.
        - **Max-rolls-per-position is gone.** It counted wheel-state rolls that
          were never persisted, so it always read 0 and never bound. The process
          terminates structurally instead: ``validate_roll`` requires strictly
          increasing strikes and every roll nets >= $0, so re-rolls are monotone
          and profitable.
        - **The fail-OPEN earnings blackout is gone**, subsumed by the fail-CLOSED
          span predicate applied to the *replacement* in evaluate_roll_opportunity.
        - **The open-order guard is new** (DD-4): ``/monitor`` places
          fire-and-forget DAY buy-to-close limits that outlive its 14:55 slot, so
          at 15:30 the roller can see a short call with a live BTC working
          against it. Rolling it could fill both buys — an unintended LONG call
          plus a sold replacement. We skip rather than cancel: the working order
          belongs to the profit-taker, which has precedence by design, and a
          cancel can lose the race to a fill anyway. Cost is one cycle.

        Returns:
            (should_roll, reason_code) — a bare reason code from the DD-5
            taxonomy, with the numbers carried as event fields rather than
            interpolated into the string.
        """
        option_symbol = short_call_position.get('symbol', '')
        parsed = parse_option_symbol(option_symbol)
        current_strike = parsed.get('strike_price', 0)

        if current_strike <= 0:
            return False, "invalid_strike"

        if open_order_symbols and option_symbol in open_order_symbols:
            return False, "open_order_conflict"

        ratio = current_stock_price / current_strike
        if ratio < self.config.rolling_itm_trigger_ratio:
            return False, "not_itm_enough"

        return True, "eligible"

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    def evaluate_roll_opportunity(self, short_call_position: Dict[str, Any],
                                  stock_position: Dict[str, Any],
                                  open_order_symbols: Optional[Set[str]] = None
                                  ) -> Optional[Dict[str, Any]]:
        """Evaluate a short call and select the replacement to execute.

        Emits a terminal ``call_roll_skipped`` event on every failure path —
        including the three that used to ``return None`` silently (falsy or
        raising stock quote, zero stock price, zero BTC ask), which is FC-066
        checklist item 2 and the reason five Fridays of production told us
        nothing.

        Returns:
            Roll opportunity dict, or None if no roll (a terminal event fired).
        """
        option_symbol = short_call_position.get('symbol', '')
        parsed = parse_option_symbol(option_symbol)
        underlying = parsed.get('underlying', '')
        current_strike = parsed.get('strike_price', 0)
        old_expiry = coerce_expiry_date(parsed.get('expiration_date'))
        contracts = abs(int(float(short_call_position.get('qty', 0))))

        # --- Stock quote: two-sided, spread-sane, or no decision (DD-1/M-5) ---
        # get_stock_quote RAISES on failure — the as-built `if not quote` branch
        # was unreachable, which is why a data outage looked like "no roll today".
        try:
            quote = self.alpaca.get_stock_quote(underlying)
        except Exception as exc:
            self.log_terminal_skip(
                option_symbol, underlying, "stock_quote_unavailable",
                current_strike=current_strike, error=str(exc))
            return None
        if not quote:
            self.log_terminal_skip(
                option_symbol, underlying, "stock_quote_unavailable",
                current_strike=current_strike, error="empty quote")
            return None

        stock_bid = _as_float(quote.get('bid'))
        stock_ask = _as_float(quote.get('ask'))
        if stock_bid <= 0 or stock_ask <= 0 or stock_ask / stock_bid > _MAX_STOCK_SPREAD_RATIO:
            # Fail closed, both ways. The deleted "whichever side is positive"
            # fallback would answer a money question from half a quote.
            self.log_terminal_skip(
                option_symbol, underlying, "stock_quote_unusable",
                current_strike=current_strike,
                stock_bid=stock_bid, stock_ask=stock_ask,
                max_spread_ratio=_MAX_STOCK_SPREAD_RATIO)
            return None
        current_stock_price = (stock_bid + stock_ask) / 2

        # Earnings proximity, for log enrichment only. The gate itself is the
        # span predicate below.
        earnings_info: Dict[str, Any] = {}
        if self.earnings_calendar is not None:
            try:
                earnings_info = self.earnings_calendar.get_earnings_proximity(underlying) or {}
            except Exception:
                earnings_info = {}

        # --- Eligibility gates ---
        should, reason = self.should_roll(
            short_call_position, stock_position, current_stock_price,
            open_order_symbols)
        if not should:
            self.log_terminal_skip(
                option_symbol, underlying, reason,
                current_strike=current_strike,
                stock_price=current_stock_price,
                itm_ratio=(round(current_stock_price / current_strike, 4)
                           if current_strike > 0 else None),
                itm_trigger_ratio=self.config.rolling_itm_trigger_ratio,
                **earnings_info,
            )
            return None

        # --- Cost-basis floor, fail closed (FC-065 Phase 2) ---
        # Rolling is the one path that places orders without passing
        # execute_call_sale, so this floor is the only thing between a BTC/STO
        # pair and a strike below what the shares cost.
        shares = int(float(stock_position.get('qty', 0)))
        resolution = self.cost_basis_resolver.resolve_detailed(
            underlying, stock_position, shares)
        cost_basis_per_share = resolution['basis']

        if cost_basis_per_share <= 0:
            # resolve_detailed returns a zero basis for both verdicts that mean
            # "no usable floor", split into two events because they are
            # different failures: unresolved (nothing to floor against) vs
            # divergent (the broker gave a number and the assignment history
            # contradicts it — resolved and *vetoed*). Both are alert-wired
            # since FC-078 (FC-066 checklist item 1).
            cross_check = resolution.get('cross_check') or {}
            divergent = resolution.get('source') == SOURCE_DIVERGENT
            log_trade_event(
                logger,
                event_type=("call_roll_skipped_cost_basis_divergent" if divergent
                            else "call_roll_skipped_cost_basis_unresolved"),
                symbol=option_symbol, underlying=underlying,
                strategy="roll_call", success=False,
                skip_reason=("cost_basis_divergent" if divergent
                             else "cost_basis_unresolved"),
                current_strike=current_strike,
                stock_price=current_stock_price,
                shares=shares,
                cost_basis_source=resolution.get('source'),
                broker_basis=resolution.get('broker_basis'),
                expected_basis=cross_check.get('expected_basis'),
                basis_delta=cross_check.get('basis_delta'),
                tolerance=cross_check.get('tolerance'),
                cross_check_status=cross_check.get('status'),
                cross_check_reason=cross_check.get('reason'),
                **earnings_info,
            )
            return None

        # --- BTC quote and the pricing mode (DD-1/DD-2) ---
        btc_quote = self.alpaca.get_option_quote(option_symbol) or {}
        btc_ask = _as_float(btc_quote.get('ask'))
        btc_bid = _as_float(btc_quote.get('bid'))
        if btc_ask <= 0:
            self.log_terminal_skip(
                option_symbol, underlying, "btc_quote_unavailable",
                current_strike=current_strike,
                stock_price=current_stock_price, **earnings_info)
            return None

        extrinsic_per_share: Optional[float] = None
        imminent = False
        if btc_bid > 0 and btc_ask > 0:
            # A mid needs two sides. Without them there is no extrinsic estimate
            # worth acting on, so base pricing applies and the override does not
            # fire — no aggression on junk data.
            option_mid = (btc_bid + btc_ask) / 2
            intrinsic = max(0.0, current_stock_price - current_strike)
            extrinsic_per_share = max(0.0, option_mid - intrinsic)
            imminent = extrinsic_per_share <= self.config.rolling_imminence_extrinsic_threshold
        else:
            option_mid = None

        pricing_mode = 'imminence' if imminent else 'base'
        # Imminence mode crosses half the spread on both legs: when assignment is
        # imminent, bid/ask pricing double-counts the spread and the escape is
        # worth the fill risk. It relaxes NOTHING else — not the invariant, not
        # the floor, not the span gate.
        btc_limit = (round(option_mid + _IMMINENCE_PAD, 2) if imminent
                     else round(btc_ask, 2))

        # --- FC-013 span gate on the replacement, fail closed (DD-3) ---
        span_floor: Optional[date] = None
        if self.config.earnings_enabled:
            if self.earnings_calendar is None:
                # Never fail open on a missing service.
                self.log_terminal_skip(
                    option_symbol, underlying, "earnings_unknown",
                    current_strike=current_strike,
                    stock_price=current_stock_price,
                    earnings_status="no_calendar_service")
                return None
            status, earnings_date = self.earnings_calendar.next_earnings_info(underlying)
            if status == EARNINGS_UNKNOWN:
                # A span test with no date cannot clear any candidate.
                self.log_terminal_skip(
                    option_symbol, underlying, "earnings_unknown",
                    current_strike=current_strike,
                    stock_price=current_stock_price,
                    earnings_status=status, **earnings_info)
                return None
            if status == EARNINGS_KNOWN:
                span_floor = earnings_date

        # --- Candidate search ---
        if old_expiry is None:
            # Without the old expiry there is no horizon to bound the
            # replacement by. Fail closed rather than roll unbounded.
            self.log_terminal_skip(
                option_symbol, underlying, "invalid_expiry",
                current_strike=current_strike,
                stock_price=current_stock_price, **earnings_info)
            return None
        max_expiry = old_expiry + timedelta(days=self.config.rolling_max_extension_days)

        min_strike = max(cost_basis_per_share, current_strike + 0.01)
        candidates = self.market_data.find_suitable_calls(
            underlying,
            min_strike_price=min_strike,
            exclude_expiry_on_or_after=span_floor,
            include_expiry_on_or_before=max_expiry,
            criteria_profile='roll',
        )
        if not candidates:
            self.log_terminal_skip(
                option_symbol, underlying, "no_suitable_replacement",
                current_strike=current_strike,
                stock_price=current_stock_price,
                min_strike=min_strike,
                max_expiry=max_expiry.isoformat(),
                # Named span_floor_date, not next_earnings_date: the latter is
                # already a get_earnings_proximity key and would collide.
                span_floor_date=(span_floor.isoformat() if span_floor else None),
                **earnings_info)
            return None

        # --- Credit screen over the LEGAL set; execute maximum net credit ---
        min_credit_per_share = self.config.rolling_min_net_credit_per_contract / 100.0
        legal = self._legal_candidates(
            candidates, current_strike, cost_basis_per_share, max_expiry,
            btc_limit, min_credit_per_share, imminent)

        if not legal:
            self.log_terminal_skip(
                option_symbol, underlying, "no_credit_candidate",
                current_strike=current_strike,
                stock_price=current_stock_price,
                btc_limit=btc_limit,
                pricing_mode=pricing_mode,
                candidates_screened=len(candidates),
                min_net_credit_per_contract=self.config.rolling_min_net_credit_per_contract,
                **earnings_info)
            return None

        primary = legal[0]

        opportunity = {
            'underlying': underlying,
            'old_option_symbol': option_symbol,
            'new_option_symbol': primary['new_option_symbol'],
            'old_strike': current_strike,
            'new_strike': primary['new_strike'],
            'old_expiry': old_expiry,
            'max_expiry': max_expiry,
            'contracts': contracts,
            'btc_limit': btc_limit,
            'stc_limit': primary['stc_limit'],
            'net_credit_per_contract': primary['net_credit_per_contract'],
            'pricing_mode': pricing_mode,
            'imminent': imminent,
            'extrinsic_per_share': extrinsic_per_share,
            'stock_price': current_stock_price,
            'cost_basis_per_share': cost_basis_per_share,
            'min_credit_per_share': min_credit_per_share,
            'earnings_info': earnings_info,
            'candidate': primary['candidate'],
            # The ladder reuses THIS list and never re-queries the chain
            # (DD-1/M-8): a fresh find_suitable_calls at execute time could
            # admit candidates filtered under a different earnings-cache state
            # or drifted deltas, and an unfiltered order is a money bug. Price
            # freshness is obtained per-rung from the candidate's own quote.
            'fallback_candidates': legal,
        }

        log_trade_event(
            logger, event_type="call_roll_evaluated",
            symbol=option_symbol, underlying=underlying,
            strategy="roll_call", success=True,
            current_strike=current_strike,
            target_strike=primary['new_strike'],
            target_symbol=primary['new_option_symbol'],
            btc_limit=btc_limit, stc_limit=primary['stc_limit'],
            net_credit=primary['net_credit_per_contract'],
            net_credit_total=round(primary['net_credit_per_contract'] * contracts, 2),
            pricing_mode=pricing_mode,
            imminence=imminent,
            extrinsic_per_share=extrinsic_per_share,
            legal_candidates=len(legal),
            max_expiry=max_expiry.isoformat(),
            contracts=contracts,
            **earnings_info,
        )
        return opportunity

    def _legal_candidates(self, candidates: List[Dict[str, Any]],
                          current_strike: float, cost_basis_per_share: float,
                          max_expiry: date, btc_limit: float,
                          min_credit_per_share: float,
                          imminent: bool) -> List[Dict[str, Any]]:
        """Screen every candidate, credit-ordered, most credit first.

        FC-078 DD-3: selection is **maximum net credit among legal candidates**,
        ties broken toward the higher strike — not first-past-the-post on
        ``return_score``. That score is annualised yield x OTM preference, an
        entry-shaped ordering; letting it pick the executed contract is how a
        book takes +$13 over +$248 on the same position. Every legal candidate
        already improves the strike strictly (``validate_roll``), so strike
        improvement is guaranteed and credit is the honest maximand. Paying
        certain credit for contingent strike value is a delta bet — the
        roll-up chasing this FC excludes.
        """
        legal: List[Dict[str, Any]] = []
        for candidate in candidates:
            valid, _reason = self.risk_manager.validate_roll(
                candidate, current_strike, cost_basis_per_share, max_expiry)
            if not valid:
                continue

            stc_limit = self._stc_limit_from_quote(
                _as_float(candidate.get('bid')), _as_float(candidate.get('ask')),
                imminent)
            if stc_limit is None:
                continue

            net = stc_limit - btc_limit
            if net + _CREDIT_EPSILON < min_credit_per_share:
                continue

            legal.append({
                'candidate': candidate,
                'new_option_symbol': candidate['symbol'],
                'new_strike': candidate.get('strike_price', 0),
                'stc_limit': stc_limit,
                'net_credit_per_share': net,
                'net_credit_per_contract': round(net * 100, 2),
            })

        legal.sort(key=lambda entry: (-entry['net_credit_per_share'],
                                      -entry['new_strike']))
        return legal

    @staticmethod
    def _stc_limit_from_quote(bid: float, ask: float,
                              imminent: bool) -> Optional[float]:
        """The sell-to-open limit for a pricing mode, or None if unquotable.

        Base mode sells at the bid — the conservative side, so the screened
        credit is the worst case rather than a hope. Imminence mode sells at
        mid - $0.05, which requires a two-sided quote; without one there is no
        mid, and the candidate is dropped rather than silently priced by another
        mode's rule.
        """
        if imminent:
            if bid <= 0 or ask <= 0:
                return None
            limit = round((bid + ask) / 2 - _IMMINENCE_PAD, 2)
        else:
            if bid <= 0:
                return None
            limit = round(bid, 2)
        return limit if limit > 0 else None

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    def execute_roll(self, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a two-leg roll: buy-to-close, then sell-to-open.

        BTC is always first. STO-first would momentarily hold two short calls
        against 100 shares — a naked call Alpaca would either reject or margin.
        There is no acceptable STO-first sequence.

        Returns:
            Result dict with success status, order IDs, and fill details.
        """
        underlying = opportunity['underlying']
        old_symbol = opportunity['old_option_symbol']
        new_symbol = opportunity['new_option_symbol']
        contracts = opportunity['contracts']
        btc_limit = opportunity['btc_limit']
        earnings_info = opportunity.get('earnings_info', {})
        min_credit = opportunity['min_credit_per_share']

        if self.config.roller_dry_run:
            log_trade_event(
                logger, event_type="call_roll_dry_run",
                symbol=old_symbol, underlying=underlying,
                strategy="roll_call", success=True,
                would_be_btc_symbol=old_symbol,
                would_be_btc_limit=btc_limit,
                would_be_stc_symbol=new_symbol,
                would_be_stc_limit=opportunity['stc_limit'],
                net_credit=opportunity['net_credit_per_contract'],
                pricing_mode=opportunity['pricing_mode'],
                contracts=contracts,
                **earnings_info,
            )
            return {'success': False, 'reason': 'dry_run',
                    'underlying': underlying}

        # --- Pre-BTC invariant re-check (DD-1) ---
        # Evaluation quotes are minutes old by order time. Re-pricing the STO
        # leg here shrinks the staleness window to the BTC poll itself, and
        # losing the race HERE costs nothing: no order exists yet.
        fresh = self.alpaca.get_option_quote(new_symbol) or {}
        fresh_stc_limit = self._stc_limit_from_quote(
            _as_float(fresh.get('bid')), _as_float(fresh.get('ask')),
            opportunity['imminent'])
        if fresh_stc_limit is None or \
                (fresh_stc_limit - btc_limit) + _CREDIT_EPSILON < min_credit:
            self.log_terminal_skip(
                old_symbol, underlying, "credit_gone_at_execution",
                current_strike=opportunity['old_strike'],
                target_strike=opportunity['new_strike'],
                btc_limit=btc_limit,
                evaluated_stc_limit=opportunity['stc_limit'],
                recheck_stc_limit=fresh_stc_limit,
                pricing_mode=opportunity['pricing_mode'],
                **earnings_info)
            return {'success': False, 'reason': 'credit_gone_at_execution',
                    'underlying': underlying}
        opportunity['stc_limit'] = fresh_stc_limit
        if opportunity['fallback_candidates']:
            opportunity['fallback_candidates'][0]['stc_limit'] = fresh_stc_limit

        # === LEG 1: Buy-to-close ===
        log_trade_event(
            logger, event_type="call_roll_btc_placed",
            symbol=old_symbol, underlying=underlying,
            strategy="roll_call", success=True,
            current_strike=opportunity['old_strike'],
            contracts=contracts, limit_price=btc_limit,
            pricing_mode=opportunity['pricing_mode'],
        )

        btc_result = self.alpaca.place_option_order(
            symbol=old_symbol, qty=contracts,
            side='buy', order_type='limit', limit_price=btc_limit)

        if not btc_result or not btc_result.get('success', False):
            error_msg = (btc_result.get('error_message', 'BTC order rejected')
                         if btc_result else 'No result')
            log_error_event(
                logger, error_type="call_roll_btc_rejected",
                error_message=error_msg, component="call_roller",
                recoverable=True, symbol=old_symbol, underlying=underlying,
                limit_price=btc_limit, contracts=contracts,
            )
            return {'success': False, 'reason': 'btc_rejected',
                    'error': error_msg, 'underlying': underlying}

        btc_order_id = btc_result.get('order_id', '')

        # --- Poll, then cancel-and-VERIFY on timeout ---
        # "Cancel failed because it filled" is a fill, not an error. The
        # as-built code returned on timeout with the DAY order still live and
        # reported `btc_unfilled` without ever looking again — a fiction that
        # would have been logged while contracts were being bought.
        btc_order = self._poll_order_fill(btc_order_id)
        timed_out = btc_order is None
        if timed_out:
            self._safe_cancel(btc_order_id)
            btc_order = self._safe_get_order(btc_order_id)

        btc_filled_qty = int(_as_float(btc_order.get('filled_qty')))
        if btc_filled_qty <= 0:
            log_trade_event(
                logger, event_type="call_roll_btc_timeout_canceled",
                symbol=old_symbol, underlying=underlying,
                strategy="roll_call", success=False,
                order_id=btc_order_id,
                order_status=btc_order.get('status'),
                disposition=('timeout_canceled' if timed_out else 'terminal_no_fill'),
                limit_price=btc_limit, contracts=contracts,
                **earnings_info,
            )
            return {'success': False, 'reason': 'btc_timeout_canceled',
                    'order_id': btc_order_id, 'underlying': underlying}

        btc_filled_price = _as_float(btc_order.get('filled_avg_price')) or btc_limit

        log_trade_event(
            logger, event_type="call_roll_btc_filled",
            symbol=old_symbol, underlying=underlying,
            strategy="roll_call", success=True,
            order_id=btc_order_id,
            filled_qty=btc_filled_qty,
            filled_price=btc_filled_price,
            requested_qty=contracts,
        )

        if btc_filled_qty < contracts:
            # Partial-fill truth (DD-1). The remainder is dead — either our
            # cancel above killed it or the order reached a terminal status —
            # and the position keeps `contracts - filled` of the OLD call, still
            # covered, still evaluated tomorrow. The STO leg must be sized to
            # what actually closed; the as-built code passed the REQUESTED qty,
            # which would sell a call against shares still pledged to the
            # unclosed remainder.
            #
            # No cancel is needed here: either the timeout path above already
            # canceled, or the poll returned a TERMINAL status, which means
            # nothing of this order is still working.
            log_trade_event(
                logger, event_type="call_roll_partial_fill",
                symbol=old_symbol, underlying=underlying,
                strategy="roll_call", success=True,
                leg="btc",
                requested_qty=contracts,
                filled_qty=btc_filled_qty,
                unfilled_qty=contracts - btc_filled_qty,
            )

        # === LEG 2: Sell-to-open, sized to what actually closed ===
        stc_result = self._attempt_stc(opportunity, btc_filled_qty, btc_filled_price)

        if stc_result and stc_result.get('success'):
            stc_filled_qty = stc_result['filled_qty']
            stc_filled_price = stc_result['filled_price']

            btc_total = btc_filled_price * btc_filled_qty * 100
            stc_total = stc_filled_price * stc_filled_qty * 100
            net_credit = stc_total - btc_total

            if stc_filled_qty < btc_filled_qty:
                log_trade_event(
                    logger, event_type="call_roll_partial_fill",
                    symbol=stc_result['symbol'], underlying=underlying,
                    strategy="roll_call", success=True,
                    leg="stc",
                    requested_qty=btc_filled_qty,
                    filled_qty=stc_filled_qty,
                    unfilled_qty=btc_filled_qty - stc_filled_qty,
                )

            log_position_update(
                logger, event_type="call_roll_completed",
                symbol=underlying,
                position_status="rolled",
                old_strike=opportunity['old_strike'],
                new_strike=stc_result.get('new_strike', opportunity['new_strike']),
                old_option_symbol=old_symbol,
                new_option_symbol=stc_result['symbol'],
                net_credit=round(net_credit, 2),
                contracts=stc_filled_qty,
                pricing_mode=opportunity['pricing_mode'],
                btc_filled_price=btc_filled_price,
                stc_filled_price=stc_filled_price,
                btc_order_id=btc_order_id,
                stc_order_id=stc_result['order_id'],
                **earnings_info,
            )

            return {
                'success': True,
                'underlying': underlying,
                'old_strike': opportunity['old_strike'],
                'new_strike': stc_result.get('new_strike', opportunity['new_strike']),
                'contracts': stc_filled_qty,
                'net_credit': round(net_credit, 2),
                'btc_order_id': btc_order_id,
                'stc_order_id': stc_result['order_id'],
            }

        # STO ladder exhausted after a BTC fill. The shares are uncovered but
        # LONG-ONLY — there is no naked position — and the residual is not "a
        # day's premium leak": worst case is the full BTC debit paid in cash
        # with nothing sold against it, re-covered later through the entry path
        # at entry-band premiums, adversely selected. Near a report the FC-013
        # span gate can legitimately leave the shares uncovered through the
        # event. That is correct by doctrine and a real terminal outcome, which
        # is why this event is alert-wired rather than absorbed.
        log_error_event(
            logger, error_type="call_roll_naked_exposure",
            error_message=("STO ladder exhausted after BTC filled — shares "
                           "uncovered (no naked position); next /scan -> /run "
                           "re-covers through the entry path with all entry "
                           "gates applied"),
            component="call_roller", recoverable=False,
            symbol=new_symbol, underlying=underlying,
            btc_order_id=btc_order_id,
            btc_filled_qty=btc_filled_qty,
            btc_filled_price=btc_filled_price,
        )
        return {
            'success': False,
            'reason': 'stc_failed_naked_exposure',
            'btc_order_id': btc_order_id,
            'btc_filled_qty': btc_filled_qty,
            'underlying': underlying,
        }

    # ------------------------------------------------------------------ #
    # The STO ladder
    # ------------------------------------------------------------------ #
    def _attempt_stc(self, opportunity: Dict[str, Any], qty: int,
                     btc_filled_price: float) -> Optional[Dict[str, Any]]:
        """Sell-to-open with a bounded retry ladder.

        **At most one STO order is live at any instant** — an invariant, not an
        aspiration. As-built, a rung that timed out left its DAY limit working
        and the ladder placed the next sell on top of it: two live sells against
        one covered lot, and a late fill on rung 1 while rung 2 works is a
        genuine **naked short call**. Every rung transition here is
        cancel-then-verify, and a cancel that fails because the order filled is
        reported as that rung *succeeding*.
        """
        underlying = opportunity['underlying']
        # (order_id, symbol, strike, limit)
        live: Optional[Tuple[str, str, float, float]] = None

        for symbol, limit, new_strike in self._rungs(opportunity, btc_filled_price):
            if live is not None:
                resolved = self._cancel_and_verify(live, underlying)
                live = None
                if resolved:
                    return resolved

            order_id = self._place_stc(symbol, underlying, qty, limit)
            if order_id is None:
                continue

            order = self._poll_order_fill(order_id)
            if order is None:
                # Timed out with the order still working — carry it forward so
                # the NEXT rung cancels-and-verifies before placing anything.
                live = (order_id, symbol, new_strike, limit)
                continue

            filled_qty = int(_as_float(order.get('filled_qty')))
            if filled_qty > 0:
                return self._stc_success(order_id, symbol, underlying, new_strike,
                                         filled_qty, order, limit)
            # Terminal with zero fill (rejected / expired / canceled): nothing
            # is live, so the next rung may be placed directly.
            log_error_event(
                logger, error_type="call_roll_stc_unfilled",
                error_message=f"STO order {order_id} status={order.get('status')}",
                component="call_roller", recoverable=True,
                symbol=symbol, underlying=underlying, order_id=order_id,
            )

        if live is not None:
            resolved = self._cancel_and_verify(live, underlying)
            if resolved:
                return resolved

        return None

    def _rungs(self, opportunity: Dict[str, Any],
               btc_filled_price: float) -> Iterator[Tuple[str, float, float]]:
        """Yield ``(symbol, limit, strike)`` per ladder rung, priced when reached.

        Rung 1 — the primary candidate at the pre-BTC re-checked limit.
        Rung 2 — the primary at the invariant *minimum* price
                 (``btc_filled_price + min_credit``), used only when that is
                 BELOW rung 1's price, i.e. only when the BTC filled better than
                 its limit. Never below the minimum: that is the invariant.
        Rungs 3+ — up to ``fallback_strike_attempts`` further candidates from the
                 stored legal list, each re-quoted, re-validated through
                 ``validate_roll``, and re-tested against the invariant computed
                 from the **actual BTC fill price**. Candidates are never
                 re-queried from the chain (M-8): the stored list is the one that
                 passed the span gate, the profile and the floor.
        """
        min_credit = opportunity['min_credit_per_share']
        floor_price = round(btc_filled_price + min_credit, 2)
        primary_symbol = opportunity['new_option_symbol']
        primary_limit = opportunity['stc_limit']

        yield (primary_symbol, primary_limit, opportunity['new_strike'])

        if 0 < floor_price < primary_limit:
            yield (primary_symbol, floor_price, opportunity['new_strike'])

        attempts = self.config.rolling_fallback_strike_attempts
        for entry in opportunity['fallback_candidates'][1:1 + attempts]:
            symbol = entry['new_option_symbol']
            quote = self.alpaca.get_option_quote(symbol) or {}
            limit = self._stc_limit_from_quote(
                _as_float(quote.get('bid')), _as_float(quote.get('ask')),
                opportunity['imminent'])
            if limit is None:
                continue

            valid, _reason = self.risk_manager.validate_roll(
                entry['candidate'], opportunity['old_strike'],
                opportunity['cost_basis_per_share'], opportunity['max_expiry'])
            if not valid:
                continue

            # The invariant against what the BTC ACTUALLY cost, not its limit.
            if (limit - btc_filled_price) + _CREDIT_EPSILON < min_credit:
                continue

            yield (symbol, limit, entry['new_strike'])

    def _cancel_and_verify(self, live: Tuple[str, str, float, float],
                           underlying: str) -> Optional[Dict[str, Any]]:
        """Cancel a working STO order and re-read it before believing anything.

        Returns the success dict when the cancel lost the race to a fill — that
        rung SUCCEEDED — and None when the order is confirmed dead with nothing
        filled. A partial fill counts as that rung's result; the uncovered
        remainder falls through to the naked-exposure terminal if no later rung
        covers it.
        """
        order_id, symbol, new_strike, limit_price = live
        self._safe_cancel(order_id)
        order = self._safe_get_order(order_id)
        filled_qty = int(_as_float(order.get('filled_qty')))
        if filled_qty > 0:
            return self._stc_success(order_id, symbol, underlying, new_strike,
                                     filled_qty, order, limit_price)
        return None

    def _place_stc(self, symbol: str, underlying: str, contracts: int,
                   limit_price: float) -> Optional[str]:
        """Place one STO rung. Returns the order id, or None if it was refused."""
        log_trade_event(
            logger, event_type="call_roll_stc_placed",
            symbol=symbol, underlying=underlying,
            strategy="roll_call", success=True,
            contracts=contracts, limit_price=limit_price,
        )

        result = self.alpaca.place_option_order(
            symbol=symbol, qty=contracts,
            side='sell', order_type='limit', limit_price=limit_price)

        if not result or not result.get('success', False):
            log_error_event(
                logger, error_type="call_roll_stc_rejected",
                error_message=(result.get('error_message', 'STO order rejected')
                               if result else 'No result'),
                component="call_roller", recoverable=True,
                symbol=symbol, underlying=underlying, limit_price=limit_price,
            )
            return None
        return result.get('order_id', '')

    def _stc_success(self, order_id: str, symbol: str, underlying: str,
                     new_strike: float, filled_qty: int, order: Dict[str, Any],
                     limit_price: Optional[float]) -> Dict[str, Any]:
        filled_price = _as_float(order.get('filled_avg_price'))
        if filled_price <= 0 and limit_price is not None:
            filled_price = limit_price
        log_trade_event(
            logger, event_type="call_roll_stc_filled",
            symbol=symbol, underlying=underlying,
            strategy="roll_call", success=True,
            order_id=order_id,
            filled_qty=filled_qty,
            filled_price=filled_price,
        )
        return {
            'success': True,
            'order_id': order_id,
            'filled_qty': filled_qty,
            'filled_price': filled_price,
            'symbol': symbol,
            'new_strike': new_strike,
        }

    # ------------------------------------------------------------------ #
    # Order plumbing
    # ------------------------------------------------------------------ #
    def _poll_order_fill(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Poll until the order reaches a terminal status, or the timeout.

        ``partially_filled`` is NOT terminal: returning on it (as-built) hands
        the caller a half-fill while the remainder is still working, which is
        how the STO leg came to be sized off the requested quantity. Returns
        None on timeout — the caller then cancels and re-reads, which is the
        only way to learn what actually happened.
        """
        timeout = self.config.rolling_btc_fill_timeout_seconds
        poll_interval = 5
        elapsed = 0

        while True:
            try:
                order = self.alpaca.get_order_by_id(order_id)
                if order and order.get('status', '') in _TERMINAL_ORDER_STATUSES:
                    return order
            except Exception:
                pass
            if elapsed >= timeout:
                return None
            time.sleep(poll_interval)
            elapsed += poll_interval

    def _safe_cancel(self, order_id: str) -> bool:
        """Cancel, swallowing failure. A failed cancel is never conclusive — the
        caller re-reads the order, which is what decides the disposition."""
        try:
            return bool(self.alpaca.cancel_order(order_id))
        except Exception:
            return False

    def _safe_get_order(self, order_id: str) -> Dict[str, Any]:
        """Re-read an order after a cancel. An unreadable order is reported as
        zero-filled: the alternative is inventing a fill, and the position and
        the next cycle both survive an under-report."""
        try:
            return self.alpaca.get_order_by_id(order_id) or {}
        except Exception as exc:
            log_error_event(
                logger, error_type="call_roll_order_refetch_failed",
                error_message=str(exc), component="call_roller",
                recoverable=True, order_id=order_id,
            )
            return {}


def _as_float(value: Any) -> float:
    """Coerce a quote/order field to a float, treating junk as 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
