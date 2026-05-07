import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AcbWalkChart, { dotAxisFor } from './AcbWalkChart';
import type { AcbTimelineRow } from '../../types/v2';

// FC-024: the ACB Walk chart used to drop reference dots to y=0 on the ACB
// axis whenever `acb_per_share` was null (which was always, due to a broken
// view). After FC-024 we expect:
//   - The chart renders for fixtures that include all 6 event types
//   - The legend lists all 6 event-marker colors regardless of data
//   - Dots during cash phases (acb=null) ride the cumulative-premium axis,
//     not the ACB axis at y=0

function row(partial: Partial<AcbTimelineRow>): AcbTimelineRow {
  return {
    event_time: '2025-10-06T15:28:00Z',
    event_date: '2025-10-06',
    activity_type: 'FILL',
    occ_symbol: null,
    order_id: null,
    expiration: null,
    option_type: null,
    side: null,
    qty: null,
    strike_price: null,
    premium_total: null,
    outcome: null,
    realized_pnl: null,
    net_premium_delta: 0,
    shares_delta: 0,
    cumulative_net_premium: 0,
    running_shares: 0,
    running_share_cost: 0,
    acb_per_share: null,
    event_label: 'put_sold',
    ...partial,
  };
}

const sixEventTypeFixture: AcbTimelineRow[] = [
  row({ event_time: '2025-10-06T15:28:00Z', event_label: 'put_sold',      cumulative_net_premium: 159 }),
  row({ event_time: '2025-10-14T04:20:00Z', event_label: 'expired',       cumulative_net_premium: 159 }),
  row({ event_time: '2025-10-15T15:51:00Z', event_label: 'put_sold',      cumulative_net_premium: 260 }),
  row({ event_time: '2025-10-17T09:55:00Z', event_label: 'option_closed', cumulative_net_premium: 210 }),
  row({ event_time: '2025-11-08T04:21:00Z', event_label: 'put_assigned',  cumulative_net_premium: 864,  running_shares: 100, acb_per_share: 323.86 }),
  row({ event_time: '2025-11-10T10:15:00Z', event_label: 'call_sold',     cumulative_net_premium: 1849, running_shares: 100, acb_per_share: 314.01 }),
  row({ event_time: '2025-11-15T04:24:00Z', event_label: 'called_away',   cumulative_net_premium: 1849 }),
];

describe('AcbWalkChart', () => {
  it('renders empty state when no events provided', () => {
    render(<AcbWalkChart data={[]} />);
    expect(screen.getByText('No events recorded for this symbol.')).toBeInTheDocument();
  });

  it('renders when fixture covers all 6 event types', () => {
    render(<AcbWalkChart data={sixEventTypeFixture} />);
    expect(screen.getByText('ACB Walk')).toBeInTheDocument();
  });

  it('legend lists all 6 event-marker labels', () => {
    render(<AcbWalkChart data={sixEventTypeFixture} />);
    // Hidden on small screens but present in DOM via `hidden md:flex`.
    expect(screen.getByText('put sold')).toBeInTheDocument();
    expect(screen.getByText('call sold')).toBeInTheDocument();
    expect(screen.getByText('closed')).toBeInTheDocument();
    expect(screen.getByText('assigned')).toBeInTheDocument();
    expect(screen.getByText('called away')).toBeInTheDocument();
    expect(screen.getByText('expired')).toBeInTheDocument();
  });

  it('subtitle explains both lines and the dot color encoding', () => {
    render(<AcbWalkChart data={sixEventTypeFixture} />);
    const heading = screen.getByText('ACB Walk');
    const card = heading.closest('div')!.parentElement!.parentElement!;
    expect(card.textContent).toMatch(/yellow line/i);
    expect(card.textContent).toMatch(/cumulative net premium/i);
    expect(card.textContent).toMatch(/dots mark events/i);
  });

  it('legend renders all 6 colors even if data is sparse (only put_sold)', () => {
    // Single-event fixture: legend should still advertise the full event taxonomy
    // because users picking different symbols in the dropdown should always see
    // the same legend.
    render(<AcbWalkChart data={[row({ event_label: 'put_sold' })]} />);
    expect(screen.getByText('put sold')).toBeInTheDocument();
    expect(screen.getByText('called away')).toBeInTheDocument();
  });

});

describe('dotAxisFor', () => {
  // FC-024 regression guards. The pre-FC-024 chart anchored every dot at
  // `y = s.acb_per_share ?? 0` on the ACB axis, so cash-phase events with
  // null ACB collapsed to y=0 (the chart floor) and disappeared. These
  // tests fail loudly if anyone reverts to that pattern.

  it('share-phase row (acb set) rides the ACB axis at the ACB value', () => {
    const result = dotAxisFor({ acb_per_share: 323.86, cumulative_net_premium: 864 });
    expect(result).toEqual({ yAxisId: 'acb', y: 323.86 });
  });

  it('cash-phase row (acb null) rides the PREMIUM axis at cumulative premium', () => {
    const result = dotAxisFor({ acb_per_share: null, cumulative_net_premium: 159 });
    expect(result).toEqual({ yAxisId: 'prem', y: 159 });
  });

  it('cash-phase row never collapses to y=0 (the pre-FC-024 bug)', () => {
    // The pre-FC-024 bug used `acb ?? 0`. This test pins the contract that
    // a null ACB does NOT silently fall back to 0, regardless of premium.
    const result = dotAxisFor({ acb_per_share: null, cumulative_net_premium: 1234.56 });
    expect(result.y).not.toBe(0);
    expect(result.y).toBe(1234.56);
    expect(result.yAxisId).toBe('prem');
  });

  it('zero-premium cash-phase row rides the prem axis at 0 (legitimate, not the fallback)', () => {
    // Edge case: a chart for a freshly-tracked symbol with no events yet.
    // Returning { yAxisId: 'prem', y: 0 } here is correct — the dot rides
    // the (empty) premium axis. Distinct from the pre-FC-024 bug which
    // forced every dot onto the ACB axis.
    const result = dotAxisFor({ acb_per_share: null, cumulative_net_premium: 0 });
    expect(result).toEqual({ yAxisId: 'prem', y: 0 });
  });

  it('handles undefined acb_per_share the same as null', () => {
    const result = dotAxisFor({ acb_per_share: undefined as unknown as null, cumulative_net_premium: 50 });
    expect(result.yAxisId).toBe('prem');
    expect(result.y).toBe(50);
  });
});
