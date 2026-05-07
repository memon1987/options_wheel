import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import DecisionQuality from './DecisionQuality';
import type { DecisionQualityRow } from '../../types/v2';

// jsdom lacks ResizeObserver; Recharts' ResponsiveContainer needs it. Stub
// here so this test file doesn't depend on test/setup.ts (FC-024 adds the
// same stub at setup level — leaving this local keeps FC-026 self-contained
// and avoids a merge-time conflict on setup.ts).
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).ResizeObserver = (globalThis as any).ResizeObserver ?? ResizeObserverStub;

// FC-026: dollar-weighted aggregates surfaced in the chart header.
//   Received  = Σ premium_total
//   Captured  = Σ realized_pnl
//   Foregone  = received − captured (buyback cash spent on early closes)
// These are distinct from avg_capture (trade-weighted mean of per-trade
// capture ratios) which the component already showed.

function row(partial: Partial<DecisionQualityRow>): DecisionQualityRow {
  return {
    open_time: '2025-10-15T15:51:00Z',
    close_time: '2025-10-17T09:55:00Z',
    occ_symbol: 'UNH251017P00350000',
    option_type: 'put',
    strike_price: 350,
    premium_total: 100,
    close_price: 0.50,
    close_qty: 1,
    outcome: 'early_close',
    realized_pnl: 50,
    capture_ratio: 0.5,
    days_held: 2,
    ...partial,
  };
}

const mixedFixture: DecisionQualityRow[] = [
  // Held to outcome — captures 100% of premium, 0 foregone.
  row({ premium_total: 159, realized_pnl: 159, outcome: 'expiration', capture_ratio: 1.0 }),
  row({ premium_total: 985, realized_pnl: 985, outcome: 'called_away', capture_ratio: 1.0 }),
  // Early closes — partial capture, dollars foregone.
  row({ premium_total: 101, realized_pnl: 51, outcome: 'early_close', capture_ratio: 0.505 }),
  row({ premium_total: 189, realized_pnl: 115, outcome: 'early_close', capture_ratio: 0.608 }),
];
// Totals: received 1434, captured 1310, foregone 124.

describe('DecisionQuality FC-026 aggregates', () => {
  it('shows empty state when no closed trades', () => {
    render(<DecisionQuality rows={[]} />);
    expect(screen.getByText('No closed trades to evaluate.')).toBeInTheDocument();
  });

  it('renders Received / Captured / Foregone with dollar amounts and percentages', () => {
    render(<DecisionQuality rows={mixedFixture} />);
    expect(screen.getByText('Received')).toBeInTheDocument();
    expect(screen.getByText('Captured')).toBeInTheDocument();
    // "Foregone (buybacks)" is split across the rendered DOM; match the parent.
    expect(screen.getByText(/Foregone \(buybacks\)/)).toBeInTheDocument();
    // Received: 159+985+101+189 = $1,434
    expect(screen.getByText('$1,434')).toBeInTheDocument();
    // Captured: 159+985+51+115 = $1,310
    expect(screen.getByText(/\$1,310/)).toBeInTheDocument();
    // Foregone: 1434 − 1310 = $124
    expect(screen.getByText(/\$124/)).toBeInTheDocument();
  });

  it('foregone is computed as received − captured, not summed from per-row close_cost', () => {
    // Construct a fixture where the per-row close_price * close_qty * 100
    // would yield a *different* number than received − captured. The
    // component must use the macro identity, not re-derive from close_price.
    const fixture: DecisionQualityRow[] = [
      row({
        premium_total: 200,
        realized_pnl: 70,
        // close_price * 100 = $50 * 100 = $5,000 — wildly different from
        // the actual buyback cost of $130. If the component computed
        // foregone from close_price it would show $5,000 instead of $130.
        close_price: 50,
        close_qty: 1,
        outcome: 'early_close',
      }),
    ];
    render(<DecisionQuality rows={fixture} />);
    // Expect $130 (200 − 70), NOT $5,000.
    expect(screen.getByText(/\$130/)).toBeInTheDocument();
    expect(screen.queryByText(/\$5,000/)).toBeNull();
  });

  it('handles all-held-to-outcome fixture (foregone = 0)', () => {
    const heldOnly: DecisionQualityRow[] = [
      row({ premium_total: 500, realized_pnl: 500, outcome: 'expiration', capture_ratio: 1.0 }),
      row({ premium_total: 300, realized_pnl: 300, outcome: 'called_away', capture_ratio: 1.0 }),
    ];
    render(<DecisionQuality rows={heldOnly} />);
    // Received and Captured both equal $800; Foregone = $0. Use getAllByText
    // for the duplicates and assert the foregone-zero exists somewhere.
    expect(screen.getAllByText('$800').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/\$0/)).toBeInTheDocument();
  });

  it('handles negative captured (loss-making early closes) without crashing', () => {
    // Pre-FC-010 stop-loss buybacks could realize negative P&L. Component
    // must keep the sign and not crash on a negative captured/percent.
    const losses: DecisionQualityRow[] = [
      row({ premium_total: 100, realized_pnl: -50, outcome: 'early_close', capture_ratio: -0.5 }),
    ];
    render(<DecisionQuality rows={losses} />);
    expect(screen.getByText('$100')).toBeInTheDocument();   // received
    expect(screen.getByText(/-\$50/)).toBeInTheDocument();  // captured (negative)
    expect(screen.getByText(/\$150/)).toBeInTheDocument();  // foregone (received − captured = 100 − (−50) = 150)
  });
});
