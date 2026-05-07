import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import VsBuyAndHoldCard from './VsBuyAndHoldCard';
import type { VsBuyAndHold } from '../../types/v2';

// Reflects the FC-023 fix: the Wheel total comes from `total_realized_pnl`
// (option leg + share leg, FC-019), not the pre-FC-023 buggy
// `realized_pnl + total_premium` which double-counted gross premium.

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
  price_now: 353.45,
  hypothetical_shares: 99.25,
  bh_dollar_pnl: 997.76,
  wheel_minus_bh: 1586.24,
};

describe('VsBuyAndHoldCard', () => {
  it('renders Wheel total from total_realized_pnl, not realized_pnl + total_premium', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    // The pre-FC-023 buggy total would be 4334 + 5888 = 10,222 — must NOT be present.
    expect(screen.queryByText(/\$10,222/)).toBeNull();
    // Canonical total: 2,584 (option 4,334 + share −1,750).
    expect(screen.getByText('$2,584.00')).toBeInTheDocument();
  });

  it('shows option + share breakdown in the Wheel subtitle', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    // Subtitle is "option $4,334 + share -$1,750" (rounded display).
    const subtitle = screen.getByText(/option .* \+ share /);
    expect(subtitle.textContent).toContain('option');
    expect(subtitle.textContent).toContain('share');
    // The pre-FC-023 wording must be gone.
    expect(subtitle.textContent).not.toContain('prem');
    expect(subtitle.textContent).not.toContain('realized');
  });

  it('renders the wheel_minus_bh delta unmodified', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    // Delta column shows the corrected wheel_minus_bh from the view.
    expect(screen.getByText('$1,586.24')).toBeInTheDocument();
  });

  it('flags buy-and-hold as price-only', () => {
    render(<VsBuyAndHoldCard data={unhData} />);
    expect(screen.getByText(/price only/)).toBeInTheDocument();
  });

  it('shows graceful empty state when data is null', () => {
    render(<VsBuyAndHoldCard data={null} />);
    expect(screen.getByText('No comparison available.')).toBeInTheDocument();
  });

  it('Wheel total is total_realized_pnl, not recomputed from option+share legs', () => {
    // Construct a fixture where total_realized_pnl deliberately diverges
    // from realized_pnl + share_side_pnl. The view is the authoritative
    // source — frontend must read total_realized_pnl directly, not derive it.
    const divergent: VsBuyAndHold = {
      ...unhData,
      realized_pnl: 1000,
      share_side_pnl: 500,
      total_realized_pnl: 9999, // intentionally not 1500
    };
    render(<VsBuyAndHoldCard data={divergent} />);
    expect(screen.getByText('$9,999.00')).toBeInTheDocument();
    expect(screen.queryByText('$1,500.00')).toBeNull();
  });

  it('Δ vs B&H comes from wheel_minus_bh field, not recomputed from total − bh', () => {
    // Set wheel_minus_bh to a value that does NOT equal
    // total_realized_pnl − bh_dollar_pnl. The view is the source of truth
    // for the delta; the frontend must not re-derive it.
    const divergentDelta: VsBuyAndHold = {
      ...unhData,
      total_realized_pnl: 5000,
      bh_dollar_pnl: 1000,
      wheel_minus_bh: 12345, // intentionally not 4000
    };
    render(<VsBuyAndHoldCard data={divergentDelta} />);
    expect(screen.getByText('$12,345.00')).toBeInTheDocument();
    expect(screen.queryByText('$4,000.00')).toBeNull();
  });
});
