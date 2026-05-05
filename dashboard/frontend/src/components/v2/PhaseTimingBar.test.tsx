import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import PhaseTimingBar from './PhaseTimingBar';

describe('PhaseTimingBar', () => {
  it('renders empty state when data is null', () => {
    render(<PhaseTimingBar data={null} />);
    expect(screen.getByText('Phase Timing')).toBeInTheDocument();
    expect(screen.getByText(/No timing data/i)).toBeInTheDocument();
  });

  it('renders empty state when total is zero', () => {
    render(<PhaseTimingBar data={{
      cash_waiting: 0, short_put: 0, long_stock: 0, covered: 0,
      first_event: null, last_event: null, current_phase: 'cash_waiting',
    }} />);
    expect(screen.getByText(/No tracked time/i)).toBeInTheDocument();
  });

  it('renders four phase tiles with day counts when data present', () => {
    render(<PhaseTimingBar data={{
      cash_waiting: 30,
      short_put: 60,
      long_stock: 10,
      covered: 100,
      first_event: '2025-10-06T00:00:00Z',
      last_event: '2026-05-05T00:00:00Z',
      current_phase: 'covered',
    }} />);
    expect(screen.getByText('30.0d')).toBeInTheDocument();
    expect(screen.getByText('60.0d')).toBeInTheDocument();
    expect(screen.getByText('10.0d')).toBeInTheDocument();
    expect(screen.getByText('100.0d')).toBeInTheDocument();
    // Current phase indicator (renders as the value next to "current:" label)
    expect(screen.getByText('covered')).toBeInTheDocument();
  });
});
