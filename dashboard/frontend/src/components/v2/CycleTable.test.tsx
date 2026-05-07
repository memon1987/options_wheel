import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import CycleTable from './CycleTable';

// FC-027: split the previously-conflated "Cycle P&L" column into
//   Total Premium  = total_premium  (option-side net, was shown as "Cycle P&L")
//   Cycle P&L      = total_premium + capital_gain  (true cycle outcome)
// UNH Cycle 1 motivated this: option +$1,218 / share −$1,750 / true −$532.

interface Row {
  timestamp: string;
  symbol: string;
  put_date: string | null;
  put_strike: number | null;
  put_premium: number | null;
  assignment_date: string | null;
  call_date: string | null;
  call_strike: number | null;
  call_premium: number | null;
  calls_in_cycle: number | null;
  cycle_call_gross_premium: number | null;
  cycle_call_net_realized: number | null;
  capital_gain: number | null;
  total_premium: number | null;
  total_return: number | null;
  duration_days: number | null;
  shares: number | null;
}

function row(p: Partial<Row>): Row {
  return {
    timestamp: '2025-11-08T04:21:00Z',
    symbol: 'UNH',
    put_date: '2025-10-30',
    put_strike: 332.5,
    put_premium: 233,
    assignment_date: '2025-11-08',
    call_date: '2025-11-10',
    call_strike: 315,
    call_premium: 985,
    calls_in_cycle: 1,
    cycle_call_gross_premium: 985,
    cycle_call_net_realized: 985,
    capital_gain: -1750,
    total_premium: 1218,
    total_return: -0.016,
    duration_days: 7,
    shares: 100,
    ...p,
  };
}

describe('CycleTable FC-027 — Total Premium vs Cycle P&L split', () => {
  it('shows empty state with no rows', () => {
    render(<CycleTable rows={[]} />);
    expect(screen.getByText('No completed cycles for this symbol.')).toBeInTheDocument();
  });

  it('renders BOTH the option-only Total Premium and the true Cycle P&L for UNH cycle 1', () => {
    render(<CycleTable rows={[row({})]} />);
    // Total Premium (option-only, no share leg): $1,218
    expect(screen.getByText('$1,218')).toBeInTheDocument();
    // Cycle P&L (true outcome including share leg): $1,218 − $1,750 = −$532
    expect(screen.getByText(/-\$532/)).toBeInTheDocument();
    // Cap Gain column: −$1,750
    expect(screen.getByText(/-\$1,750/)).toBeInTheDocument();
    // Pre-FC-027 the column header was "Cycle P&L" but the cell showed
    // total_premium only. Verify column ordering: Cap Gain → Total Premium → Cycle P&L.
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent);
    const capGainIdx = headers.indexOf('Cap Gain');
    const totalPremIdx = headers.indexOf('Total Premium');
    const cyclePnlIdx = headers.indexOf('Cycle P&L');
    expect(capGainIdx).toBeGreaterThanOrEqual(0);
    expect(totalPremIdx).toBe(capGainIdx + 1);
    expect(cyclePnlIdx).toBe(totalPremIdx + 1);
  });

  it('Cycle P&L column equals total_premium + capital_gain, not total_premium alone', () => {
    // Construct a fixture where total_premium and total_premium+capital_gain
    // diverge so a regression to the pre-FC-027 single-column display would fail.
    const r = row({ total_premium: 500, capital_gain: 2000 });  // cycle P&L = 2,500
    render(<CycleTable rows={[r]} />);
    expect(screen.getByText('$500')).toBeInTheDocument();   // Total Premium
    expect(screen.getByText('$2,500')).toBeInTheDocument(); // Cycle P&L
  });

  it('handles all-null capital_gain by treating it as zero in Cycle P&L', () => {
    // In-flight cycle (capital_gain not yet computed). Cycle P&L should still
    // render as just total_premium rather than NaN or "—".
    const r = row({ capital_gain: null, total_premium: 233 });
    render(<CycleTable rows={[r]} />);
    // Both columns render $233 (total_premium displayed; cycle P&L = 233 + 0).
    expect(screen.getAllByText('$233').length).toBeGreaterThanOrEqual(2);
  });

  it('renders "—" only when both total_premium and capital_gain are null', () => {
    const r = row({ total_premium: null, capital_gain: null });
    render(<CycleTable rows={[r]} />);
    // At least one "—" should appear in the row for the Cycle P&L column.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });

  it('positive cycle (UNH cycle 3 shape: $145 option + $0 share) renders correctly', () => {
    // Cycle 3: put kept $145 + call kept $360 = $505 total premium; share
    // round-trip $267.5 → $267.5 = $0 cap_gain. Cycle P&L = $505.
    const r = row({
      put_strike: 267.5, put_premium: 145, call_strike: 267.5, call_premium: 360,
      cycle_call_net_realized: 360, capital_gain: 0, total_premium: 505,
    });
    render(<CycleTable rows={[r]} />);
    expect(screen.getAllByText('$505').length).toBeGreaterThanOrEqual(2);
  });
});
