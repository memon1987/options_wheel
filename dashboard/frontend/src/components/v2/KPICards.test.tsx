import { describe, expect, it } from 'vitest';
import { buildHeadlineKpis } from './KPICards';

describe('buildHeadlineKpis', () => {
  it('produces four KPI tiles in order', () => {
    const kpis = buildHeadlineKpis({
      nlv: 120080,
      cash: 121090,
      buyingPower: 24479,
      startingCapital: 100000,
      grossPremium: 56766,
      netRealizedPnl: 26358,
      boughtBack: 30408,
      daysRunning: 211,
    });

    expect(kpis).toHaveLength(4);
    expect(kpis.map((k) => k.label)).toEqual([
      'Net Liquidation Value',
      'Total Return',
      'Net Realized P&L',
      'Days Running',
    ]);
  });

  it('Total Return = NLV − starting_capital, not premium-based', () => {
    const kpis = buildHeadlineKpis({
      nlv: 120000,
      cash: null,
      buyingPower: null,
      startingCapital: 100000,
      grossPremium: 999999, // distractor — should not affect Total Return
      netRealizedPnl: 50000,
      boughtBack: 0,
      daysRunning: 100,
    });
    const totalReturn = kpis.find((k) => k.label === 'Total Return')!;
    expect(totalReturn.rawPnl).toBe(20000);
  });

  it('Total Return shows annualized return when ≥30 days running', () => {
    const kpis = buildHeadlineKpis({
      nlv: 120000,
      cash: null,
      buyingPower: null,
      startingCapital: 100000,
      grossPremium: null,
      netRealizedPnl: null,
      boughtBack: null,
      daysRunning: 365, // exactly 1 year → annualized = 20%
    });
    const totalReturn = kpis.find((k) => k.label === 'Total Return')!;
    expect(totalReturn.sub).toContain('20.0% since inception');
    expect(totalReturn.sub).toContain('20.0% annualized');
  });

  it('Total Return suppresses annualized below 30 days running', () => {
    const kpis = buildHeadlineKpis({
      nlv: 102000,
      cash: null,
      buyingPower: null,
      startingCapital: 100000,
      grossPremium: null,
      netRealizedPnl: null,
      boughtBack: null,
      daysRunning: 14,
    });
    const totalReturn = kpis.find((k) => k.label === 'Total Return')!;
    expect(totalReturn.sub).not.toContain('annualized');
  });

  it('Net Realized P&L sub shows gross − bought back when buybacks exist', () => {
    const kpis = buildHeadlineKpis({
      nlv: null,
      cash: null,
      buyingPower: null,
      startingCapital: null,
      grossPremium: 56766,
      netRealizedPnl: 26358,
      boughtBack: 30408,
      daysRunning: null,
    });
    const npr = kpis.find((k) => k.label === 'Net Realized P&L')!;
    expect(npr.sub).toContain('Gross');
    expect(npr.sub).toContain('bought back');
  });

  it('null inputs do not crash', () => {
    const kpis = buildHeadlineKpis({
      nlv: null, cash: null, buyingPower: null, startingCapital: null,
      grossPremium: null, netRealizedPnl: null, boughtBack: null, daysRunning: null,
    });
    expect(kpis).toHaveLength(4);
    expect(kpis[0].value).toBe('—');
  });
});
