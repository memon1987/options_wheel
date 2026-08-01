import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import UncoveredPositionsCard from './DrawdownPauseCard';
import type { UncoveredRow, UncoveredSymbols } from '../../types/v2';

// FC-065 Phase 4, review round 1 (BLOCKER 2): the card must never assert an
// all-clear it cannot support. Three states have to stay visually distinct:
// clear, unknown, and unreadable — the old card collapsed all three into
// "Every held symbol has a call written against it."

const row = (symbol: string, days: number | null): UncoveredRow => ({
  symbol,
  shares: 100,
  cost_basis_per_share: 218.43,
  last_price: 199,
  underwater_pct: -0.089,
  uncovered_days: days,
  outcome: days === null ? '' : 'no_candidates',
  reason: days === null ? 'no_decision_records' : 'no_qualifying_strikes',
  run_id: '20260801T140000Z-abcdef12',
  last_decision_at: '2026-08-01T14:00:00+00:00',
});

const data = (over: Partial<UncoveredSymbols> = {}): UncoveredSymbols => ({
  threshold_days: 7,
  source: 'decision_events',
  decision_source_available: true,
  uncovered: [],
  unknown_uncovered_days: [],
  share_count_mismatches: [],
  ...over,
});

describe('UncoveredPositionsCard', () => {
  it('renders an unavailable state when the decision table cannot be read', () => {
    render(<UncoveredPositionsCard data={data({ decision_source_available: false })} />);
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
    expect(screen.queryByText(/Every held symbol has a call written/i)).toBeNull();
  });

  it('does not claim an all-clear while any symbol is unknown', () => {
    render(<UncoveredPositionsCard data={data({ unknown_uncovered_days: [row('AAPL', null)] })} />);
    expect(screen.queryByText(/Every held symbol has a call written/i)).toBeNull();
    expect(screen.getByText(/see the unknowns below/i)).toBeInTheDocument();
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
  });

  it('claims an all-clear only when nothing is uncovered and nothing is unknown', () => {
    render(<UncoveredPositionsCard data={data()} />);
    expect(screen.getByText(/Every held symbol has a call written/i)).toBeInTheDocument();
  });

  it('lists uncovered symbols with their day count', () => {
    render(<UncoveredPositionsCard data={data({ uncovered: [row('NVDA', 9)] })} />);
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
  });

  it('renders the null-data state as unavailable, not as clear', () => {
    render(<UncoveredPositionsCard data={null} />);
    expect(screen.getByText(/Unavailable/i)).toBeInTheDocument();
  });
});
