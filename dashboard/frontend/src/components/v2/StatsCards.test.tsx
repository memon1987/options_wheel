import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import CycleStatsCard from './CycleStatsCard';
import PutStatsCard from './PutStatsCard';
import ReconciliationBanner from './ReconciliationBanner';
import type { CycleStats, PutStats, Reconciliation } from '../../types/v2';

const regime = { count: 0, win_rate: null, avg_win: null, avg_loss: null, expectancy: null, pnl_per_collateral_day: null };

const cycleStats: CycleStats = {
  count: 8,
  win_rate: 0.875,
  avg_win: 1200,
  avg_loss: -532,
  expectancy: 983,
  pnl_per_collateral_day: 0.0008,
  closed_count: 8,
  open_count: 2,
  open_mtm_to_date: -3100,
  excluded_overlapping_symbols: ['AMD'],
  regime_pre_fc029: { ...regime, count: 6, expectancy: 850, win_rate: 0.83 },
  regime_post_fc029: { ...regime, count: 2, expectancy: 1380, win_rate: 1.0 },
  fc029_deploy_date: '2026-05-08',
};

describe('CycleStatsCard (FC-031)', () => {
  it('disclosures: FC-020 exclusions and open cycles are visible', () => {
    render(<CycleStatsCard data={cycleStats} />);
    expect(screen.getByText(/1 symbol\(s\) excluded \(FC-020\)/)).toBeInTheDocument();
    expect(screen.getByText(/8 closed · 2 open/)).toBeInTheDocument();
    // Survivorship guard: open-cycle MTM rendered beside closed stats.
    expect(screen.getByText('-$3,100')).toBeInTheDocument();
  });

  it('shows the FC-029 regime split', () => {
    render(<CycleStatsCard data={cycleStats} />);
    expect(screen.getByText(/Since FC-029 \(2026-05-08\)/)).toBeInTheDocument();
  });

  it('P&L per $1k·day uses the Σ/Σ aggregate', () => {
    render(<CycleStatsCard data={cycleStats} />);
    expect(screen.getByText('$0.80')).toBeInTheDocument();
  });

  it('empty state', () => {
    render(<CycleStatsCard data={null} />);
    expect(screen.getByText('No completed cycles yet.')).toBeInTheDocument();
  });
});

const putStats: PutStats = {
  closed_count: 52,
  win_rate: 0.92,
  net_pnl: 14200,
  assignment_count: 11,
  expiration_count: 12,
  early_close_count: 40,
  pct_closed_early: 40 / 63,
  assignment_rate_held_to_expiry: 11 / 23,
  put_delta_band: [0.10, 0.20],
};

describe('PutStatsCard (FC-031)', () => {
  it('win rate is labeled a diagnostic, not a KPI', () => {
    render(<PutStatsCard data={putStats} />);
    expect(screen.getByText('Win rate (diagnostic)')).toBeInTheDocument();
  });

  it('assignment rate is held-to-expiry (48%), not diluted by early closes (17%)', () => {
    render(<PutStatsCard data={putStats} />);
    expect(screen.getByText(/48%/)).toBeInTheDocument();
    expect(screen.queryByText(/17%/)).toBeNull();
  });

  it('flags assignment rate outside the put delta band', () => {
    render(<PutStatsCard data={putStats} />);
    // 48% >> 20% band top → warning color class on the stat.
    const stat = screen.getByText(/48%/);
    expect(stat.className).toContain('text-yellow-300');
  });
});

const recOk: Reconciliation = {
  nlv: 120080,
  deposits: 100000,
  deposits_source: 'BQ',
  realized_cash_pnl: 21808,
  open_option_premium: 200,
  fees: -24,
  live_market_value: -310,
  residual: -1594,
  residual_net_of_known_gaps: 0,
  known_gaps: [{ symbol: 'AMD', amount: -1594, as_of: '2026-05-05', reason: 'paper-engine anomaly' }],
  share_count_mismatches: [{ symbol: 'AMD', view_shares: 100, live_shares: 0 }],
  status: 'ok',
};

describe('ReconciliationBanner (FC-031)', () => {
  it('ok state renders the quiet footer line, not a warning', () => {
    render(<ReconciliationBanner data={recOk} />);
    expect(screen.getByText(/Books reconcile/)).toBeInTheDocument();
    expect(screen.queryByText(/Reconciliation warning/)).toBeNull();
  });

  it('warn state shows the component math and mismatches', () => {
    render(<ReconciliationBanner data={{ ...recOk, status: 'warn', residual: -26594, residual_net_of_known_gaps: -25000 }} />);
    expect(screen.getByText(/Reconciliation warning/)).toBeInTheDocument();
    expect(screen.getByText(/AMD 100 vs 0/)).toBeInTheDocument();
  });

  it('unknown state renders nothing', () => {
    const { container } = render(<ReconciliationBanner data={{ ...recOk, status: 'unknown' }} />);
    expect(container.innerHTML).toBe('');
  });
});
