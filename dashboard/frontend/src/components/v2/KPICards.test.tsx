import { describe, expect, it } from 'vitest';
import { buildHeadlineKpis } from './KPICards';

const base = {
  nlv: 120080,
  cash: 121090,
  buyingPower: 24479,
  startingCapital: 100000,
  realizedCashPnl: 21808,
  openValue: -1728,
  xirr: 0.276,
  twrCumulative: 0.2008,
  singleDeposit: true,
  maxDrawdown: -0.083,
  maxDrawdownDollars: -9950,
  currentDrawdown: -0.012,
  daysRunning: 274,
  nlvSource: 'live',
};

describe('buildHeadlineKpis (FC-031)', () => {
  it('produces four KPI tiles in order — Total P&L keeps the tile, not XIRR', () => {
    const kpis = buildHeadlineKpis(base);
    expect(kpis).toHaveLength(4);
    expect(kpis.map((k) => k.label)).toEqual([
      'Net Liquidation Value',
      'Total P&L',
      'Max Drawdown',
      'Return',
    ]);
  });

  it('Total P&L = NLV − deposits (bank-statement number)', () => {
    const kpis = buildHeadlineKpis(base);
    const tile = kpis.find((k) => k.label === 'Total P&L')!;
    expect(tile.rawPnl).toBeCloseTo(20080);
    expect(tile.sub).toContain('20.1% on deposits');
    expect(tile.sub).toContain('realized cash');
    expect(tile.sub).toContain('open value');
  });

  it('single-deposit XIRR is labeled as annualized, not money-weighted', () => {
    const kpis = buildHeadlineKpis(base);
    const tile = kpis.find((k) => k.label === 'Return')!;
    expect(tile.value).toBe('27.6%');
    expect(tile.sub).toContain('annualized (single deposit)');
    expect(tile.hint).toContain('single deposit');
  });

  it('multi-deposit XIRR is labeled money-weighted', () => {
    const kpis = buildHeadlineKpis({ ...base, singleDeposit: false });
    const tile = kpis.find((k) => k.label === 'Return')!;
    expect(tile.sub).toContain('XIRR (money-weighted)');
  });

  it('Max Drawdown shows % with $ and current-drawdown sub', () => {
    const kpis = buildHeadlineKpis(base);
    const tile = kpis.find((k) => k.label === 'Max Drawdown')!;
    expect(tile.value).toBe('-8.3%');
    expect(tile.sub).toContain('-$9,950');
    expect(tile.sub).toContain('from peak');
  });

  it('null inputs do not crash', () => {
    const kpis = buildHeadlineKpis({
      nlv: null, cash: null, buyingPower: null, startingCapital: null,
      realizedCashPnl: null, openValue: null, xirr: null, twrCumulative: null,
      singleDeposit: true, maxDrawdown: null, maxDrawdownDollars: null,
      currentDrawdown: null, daysRunning: null, nlvSource: null,
    });
    expect(kpis).toHaveLength(4);
    expect(kpis[0].value).toBe('—');
    expect(kpis.find((k) => k.label === 'Return')!.value).toBe('—');
  });
});
