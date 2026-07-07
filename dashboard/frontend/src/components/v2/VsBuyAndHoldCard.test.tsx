import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import VsBuyAndHoldCard from './VsBuyAndHoldCard';
import type { VsBuyAndHold } from '../../types/v2';

// FC-031: the Wheel column is `wheel_mtm_pnl` — net cash P&L plus full
// market value of held shares. The convention (adversarial review F1): share
// acquisition cost is already expensed in the cash ledger, so the add-back
// is market value, never (price − basis) × shares.

const unhData: VsBuyAndHold = {
  underlying: 'UNH',
  first_trade_date: '2025-10-06',
  first_strike: 347.5,
  realized_pnl: 4334,
  share_side_pnl: -1750,
  total_realized_pnl: 2584,
  total_premium: 5888,
  current_shares: 0,
  current_acb_per_share: null,
  price_at_start: 350.12,
  price_at_start_date: '2025-10-06',
  price_now: 353.45,
  price_now_date: '2026-07-03',
  hypothetical_shares: 99.25,
  bh_dollar_pnl: 997.76,
  wheel_mtm_pnl: 2584, // no shares held → MTM = cash
  wheel_minus_bh: 1586.24,
};

describe('VsBuyAndHoldCard (FC-031)', () => {
  it('fully-cycled symbol: Wheel (MTM) equals net cash P&L', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    expect(screen.getByText('Wheel (MTM)')).toBeInTheDocument();
    expect(screen.getByText('$2,584.00')).toBeInTheDocument();
    // Pre-FC-023 buggy total (realized + gross premium) must not appear.
    expect(screen.queryByText(/\$10,222/)).toBeNull();
  });

  it('symbol holding shares: Wheel column is the MTM field with the marks caveat', () => {
    const holding: VsBuyAndHold = {
      ...unhData,
      underlying: 'AMD',
      total_realized_pnl: -17319,
      current_shares: 100,
      price_now: 252.5,
      wheel_mtm_pnl: -17319 + 100 * 252.5, // cash + full share MV = 7,931
      wheel_minus_bh: 0,
    };
    render(<VsBuyAndHoldCard data={holding} />);
    expect(screen.getByText('$7,931.00')).toBeInTheDocument();
    expect(screen.getByText(/excl\. open option marks/)).toBeInTheDocument();
    // The F1 double-count value must NOT appear anywhere.
    expect(screen.queryByText(/-\$16,319/)).toBeNull();
  });

  it('renders the wheel_minus_bh delta from the view, not recomputed', () => {
    const divergentDelta: VsBuyAndHold = {
      ...unhData,
      wheel_mtm_pnl: 5000,
      bh_dollar_pnl: 1000,
      wheel_minus_bh: 12345, // intentionally not 4000 — view is authoritative
    };
    render(<VsBuyAndHoldCard data={divergentDelta} />);
    expect(screen.getByText('$12,345.00')).toBeInTheDocument();
    expect(screen.queryByText('$4,000.00')).toBeNull();
  });

  it('flags buy-and-hold as price-only and perfect-foresight', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    expect(screen.getByText(/price only/)).toBeInTheDocument();
    expect(screen.getByText(/perfect-foresight/)).toBeInTheDocument();
  });

  it('flags a late B&H baseline (bar history starts after first trade)', () => {
    const late: VsBuyAndHold = {
      ...unhData,
      first_trade_date: '2025-10-06',
      price_at_start_date: '2025-11-15',
    };
    render(<VsBuyAndHoldCard data={late} />);
    expect(screen.getByText(/baseline uses the 2025-11-15 close/)).toBeInTheDocument();
  });

  it('shows graceful empty state when data is null', () => {
    render(<VsBuyAndHoldCard data={null} />);
    expect(screen.getByText('No comparison available.')).toBeInTheDocument();
  });

  it('zero price_at_start renders the backfill message via null-check, not truthiness', () => {
    const zeroStart: VsBuyAndHold = { ...unhData, price_at_start: 0, bh_dollar_pnl: null, wheel_minus_bh: null };
    render(<VsBuyAndHoldCard data={zeroStart} />);
    // price_at_start = 0 is "present but degenerate" — bh_dollar_pnl null is
    // what gates readiness now.
    expect(screen.getByText(/backfill not yet complete/)).toBeInTheDocument();
  });
});
