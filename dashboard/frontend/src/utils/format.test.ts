import { describe, expect, it } from 'vitest';
import { fmtCurrency, fmtCurrencyDetail, fmtPercent, fmtNumber, parseOcc, pnlColor, fmtDate, fmtDateShort, fmtDateTime } from './format';

describe('format helpers', () => {
  describe('fmtCurrency', () => {
    it('formats positive numbers without cents', () => {
      expect(fmtCurrency(1234.56)).toBe('$1,235');
    });
    it('returns em-dash for null', () => {
      expect(fmtCurrency(null)).toBe('—');
      expect(fmtCurrency(undefined)).toBe('—');
    });
    it('compact format kicks in over 1000', () => {
      expect(fmtCurrency(15500, { compact: true })).toBe('$15.5K');
      expect(fmtCurrency(1500000, { compact: true })).toBe('$1.50M');
    });
    it('handles negative compactly', () => {
      expect(fmtCurrency(-2500, { compact: true })).toBe('-$2.5K');
    });
  });

  describe('fmtCurrencyDetail', () => {
    it('always shows two decimals', () => {
      expect(fmtCurrencyDetail(123)).toBe('$123.00');
      expect(fmtCurrencyDetail(123.456)).toBe('$123.46');
    });
  });

  describe('fmtPercent', () => {
    it('multiplies by 100 and tags %', () => {
      expect(fmtPercent(0.123)).toBe('12.3%');
      expect(fmtPercent(0.05, 2)).toBe('5.00%');
    });
    it('em-dashes nullish', () => {
      expect(fmtPercent(null)).toBe('—');
    });
  });

  describe('fmtNumber', () => {
    it('groups thousands', () => {
      expect(fmtNumber(1234567)).toBe('1,234,567');
    });
    it('em-dashes nullish', () => {
      expect(fmtNumber(null)).toBe('—');
    });
  });

  describe('parseOcc', () => {
    it('parses a valid OCC put symbol', () => {
      const r = parseOcc('AMD260501P00277500');
      expect(r.underlying).toBe('AMD');
      expect(r.expiration).toBe('2026-05-01');
      expect(r.optionType).toBe('P');
      expect(r.strike).toBe(277.5);
    });

    it('parses a valid OCC call symbol', () => {
      const r = parseOcc('GOOGL260415C00312500');
      expect(r.underlying).toBe('GOOGL');
      expect(r.optionType).toBe('C');
      expect(r.strike).toBe(312.5);
    });

    it('returns underlying-only for non-OCC strings', () => {
      const r = parseOcc('AMD');
      expect(r.underlying).toBe('AMD');
      expect(r.expiration).toBeNull();
      expect(r.optionType).toBeNull();
      expect(r.strike).toBeNull();
    });

    it('returns empties for null', () => {
      const r = parseOcc(null);
      expect(r.underlying).toBe('');
    });
  });

  describe('date helpers (FC-022 ET-anchored)', () => {
    // Pick an instant that crosses a date boundary in some timezones but not ET.
    // 2026-04-15 03:00Z = 2026-04-14 23:00 ET (previous day)
    const lateNightET = '2026-04-15T03:00:00.000Z';

    it('fmtDate renders ET-anchored date regardless of system locale', () => {
      // In ET, this instant is April 14, not April 15.
      expect(fmtDate(lateNightET)).toContain('Apr 14');
    });

    it('fmtDateShort renders ET-anchored short date', () => {
      expect(fmtDateShort(lateNightET)).toContain('Apr 14');
    });

    it('fmtDateTime includes a TZ marker (ET) on output', () => {
      // The output should include either "EST" or "EDT" depending on DST.
      const out = fmtDateTime(lateNightET);
      expect(out).toMatch(/E[SD]T/);
    });

    it('em-dashes null and undefined', () => {
      expect(fmtDate(null)).toBe('—');
      expect(fmtDateShort(undefined)).toBe('—');
      expect(fmtDateTime(null)).toBe('—');
    });
  });

  describe('pnlColor', () => {
    it('green for positive', () => {
      expect(pnlColor(100)).toContain('green');
    });
    it('red for negative', () => {
      expect(pnlColor(-100)).toContain('red');
    });
    it('gray for zero/null', () => {
      expect(pnlColor(0)).toContain('gray');
      expect(pnlColor(null)).toContain('gray');
    });
  });
});
