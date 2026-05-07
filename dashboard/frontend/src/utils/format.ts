// FC-018 v2: shared formatters for dashboard display.

// FC-022: All trading is anchored to NYSE hours; render dates in ET regardless
// of the viewer's locale so the dashboard matches Alpaca's UI and the bot logs.
export const ET_TZ = 'America/New_York';

// FC-028: pure calendar-date strings (no time component) — e.g. an option's
// `expiration` or BQ's `DATE(event_time, 'America/New_York')` — must NOT be
// run through timezone conversion. JS parses "2026-04-24" as UTC midnight;
// converting to ET (UTC-4) rolls back to "Apr 23" — wrong by a day. We detect
// the YYYY-MM-DD shape and render directly from the parts.
const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dateOnlyMatch = (s: string): { year: number; month: number; day: number } | null => {
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  return { year: parseInt(m[1], 10), month: parseInt(m[2], 10), day: parseInt(m[3], 10) };
};

export const fmtCurrency = (n: number | null | undefined, opts: { compact?: boolean } = {}): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  if (opts.compact && Math.abs(n) >= 1000) {
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return `${n < 0 ? '-' : ''}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1000) return `${n < 0 ? '-' : ''}$${(abs / 1000).toFixed(1)}K`;
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
};

export const fmtCurrencyDetail = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
};

export const fmtPercent = (n: number | null | undefined, digits: number = 1): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${(n * 100).toFixed(digits)}%`;
};

export const fmtNumber = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US').format(n);
};

export const fmtDate = (s: string | null | undefined): string => {
  if (!s) return '—';
  try {
    const parts = dateOnlyMatch(s);
    if (parts) {
      return `${MONTH_SHORT[parts.month - 1]} ${parts.day}, ${parts.year}`;
    }
    return new Date(s).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      timeZone: ET_TZ,
    });
  } catch {
    return s;
  }
};

export const fmtDateShort = (s: string | null | undefined): string => {
  if (!s) return '—';
  try {
    const parts = dateOnlyMatch(s);
    if (parts) {
      return `${MONTH_SHORT[parts.month - 1]} ${parts.day}`;
    }
    return new Date(s).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: ET_TZ,
    });
  } catch {
    return s;
  }
};

export const fmtDateTime = (s: string | null | undefined): string => {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: ET_TZ,
      timeZoneName: 'short',
    });
  } catch {
    return s;
  }
};

export const fmtRelativeAge = (s: string | null | undefined): string => {
  if (!s) return 'never';
  try {
    const then = new Date(s).getTime();
    const now = Date.now();
    const diffMs = now - then;
    const diffMin = Math.floor(diffMs / 60_000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 30) return `${diffDay}d ago`;
    return fmtDate(s);
  } catch {
    return s;
  }
};

export const cls = (...classes: Array<string | false | null | undefined>): string =>
  classes.filter(Boolean).join(' ');

// Color a numeric P&L: green for positive, red for negative.
export const pnlColor = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n) || n === 0) return 'text-gray-300';
  return n > 0 ? 'text-green-400' : 'text-red-400';
};

// OCC symbol → human-readable underlying + expiry + type + strike.
export const parseOcc = (occ: string | null | undefined): {
  underlying: string;
  expiration: string | null;
  optionType: 'P' | 'C' | null;
  strike: number | null;
} => {
  const empty = { underlying: '', expiration: null, optionType: null, strike: null };
  if (!occ) return empty;
  const m = occ.match(/^([A-Z]{1,6})(\d{6})([CP])(\d{8})$/);
  if (!m) return { ...empty, underlying: occ };
  const [, underlying, dateStr, type, strikeStr] = m;
  const yy = parseInt(dateStr.slice(0, 2), 10);
  const yyyy = yy < 50 ? 2000 + yy : 1900 + yy;
  const mm = dateStr.slice(2, 4);
  const dd = dateStr.slice(4, 6);
  return {
    underlying,
    expiration: `${yyyy}-${mm}-${dd}`,
    optionType: type as 'P' | 'C',
    strike: parseInt(strikeStr, 10) / 1000,
  };
};
