"""FIFO open-lot walk over OPTRD share events (FC-031).

This is the *open-lot subset* of the FC-020 FIFO pairing design: buys push
lots, sells pop the oldest lot (splitting on partial sells). It answers one
question only — "what is the cost basis of the shares currently held?" —
for display and breakeven-distance purposes.

It deliberately does NOT re-pair closed cycles (that is FC-020 proper —
which should extend THIS walk to emit closed (buy, sell) pairs rather than
re-implementing the loop, so the scorecard's open-lot basis and the cycle
table's lot boundaries can never diverge). Its output must never be summed
into P&L: under the dashboard's accounting convention, share acquisition
cost is already expensed in the OPTRD cash ledger (`share_side_pnl`), so
MTM P&L uses full market value of held shares, not (price − basis) ×
shares. See docs/plans/fc-031.md.

Pure Python, no cloud imports — unit-tested in tests/test_dashboard_lots.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def open_lots(optrd_events: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Walk OPTRD events in time order and return the still-open share lots.

    ``optrd_events``: dicts with ``transaction_time`` (sortable), ``qty``
    (signed: + buy, − sell), ``price``. Rows with missing/zero qty are
    skipped. An unpaired sell (selling shares never bought — a data error)
    is skipped and counted.

    Returns ``(lots, unpaired_sell_count)`` with lots as
    ``{"qty", "price", "buy_time"}`` oldest-first.
    """
    lots: List[Dict[str, Any]] = []
    unpaired = 0
    for ev in sorted(optrd_events, key=lambda e: str(e.get("transaction_time") or "")):
        qty = ev.get("qty")
        price = ev.get("price")
        if not qty:
            continue
        qty = float(qty)
        if qty > 0:
            lots.append({
                "qty": qty,
                "price": float(price) if price is not None else None,
                "buy_time": ev.get("transaction_time"),
            })
            continue
        # Sell: pop FIFO, splitting the front lot on partial consumption.
        remaining = -qty
        while remaining > 0 and lots:
            lot = lots[0]
            if lot["qty"] <= remaining:
                remaining -= lot["qty"]
                lots.pop(0)
            else:
                lot["qty"] -= remaining
                remaining = 0
        if remaining > 0:
            unpaired += 1
    return lots, unpaired


def open_lot_basis(optrd_events: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Basis of currently-held shares from the FIFO walk.

    Returns ``{shares, basis_per_share, acquired_at, unpaired_sells}`` —
    all None/0 when no lots remain open.
    """
    lots, unpaired = open_lots(optrd_events)
    shares = sum(lot["qty"] for lot in lots)
    if shares <= 0:
        return {"shares": 0.0, "basis_per_share": None,
                "acquired_at": None, "unpaired_sells": unpaired}
    priced = [lot for lot in lots if lot["price"] is not None]
    cost = sum(lot["qty"] * lot["price"] for lot in priced)
    priced_shares = sum(lot["qty"] for lot in priced)
    return {
        "shares": shares,
        "basis_per_share": (cost / priced_shares) if priced_shares > 0 else None,
        "acquired_at": lots[0]["buy_time"],
        "unpaired_sells": unpaired,
    }
