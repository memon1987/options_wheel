// FC-018 v2 dashboard types — shared across all v2 pages.

export interface ScorecardRow {
  symbol: string;
  trade_count: number | null;
  cycles_completed: number | null;
  total_premium: number | null;
  put_premium: number | null;
  call_premium: number | null;
  realized_pnl: number | null;
  open_count: number | null;
  put_assignment_count: number | null;
  called_away_count: number | null;
  early_close_count: number | null;
  expiration_count: number | null;
  cycle_capital_gain: number | null;
  avg_cycle_days: number | null;
  first_trade_time: string | null;
  last_trade_time: string | null;
  current_shares: number | null;
  current_acb_per_share: number | null;
  current_cumulative_net_premium: number | null;
  price_now: number | null;
  bh_dollar_pnl: number | null;
  wheel_minus_bh: number | null;
}

export interface AcbTimelineRow {
  event_time: string;
  event_date: string;
  activity_type: string;
  option_type: string | null;
  side: string | null;
  qty: number | null;
  strike_price: number | null;
  premium_total: number | null;
  outcome: string | null;
  realized_pnl: number | null;
  net_premium_delta: number;
  shares_delta: number;
  cumulative_net_premium: number;
  running_shares: number;
  running_share_cost: number;
  acb_per_share: number | null;
  event_label: string;
}

export interface DecisionQualityRow {
  open_time: string;
  close_time: string | null;
  occ_symbol: string;
  option_type: string;
  strike_price: number;
  premium_total: number;
  close_price: number | null;
  close_qty: number | null;
  outcome: string;
  realized_pnl: number | null;
  capture_ratio: number | null;
  days_held: number | null;
}

export interface VsBuyAndHold {
  underlying: string;
  first_trade_date: string | null;
  first_strike: number | null;
  realized_pnl: number | null;
  total_premium: number | null;
  current_shares: number | null;
  current_acb_per_share: number | null;
  price_at_start: number | null;
  price_now: number | null;
  hypothetical_shares: number | null;
  bh_dollar_pnl: number | null;
  wheel_minus_bh: number | null;
}

export interface StockBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IngestHealth {
  trades_from_activities: string | null;
  equity_history_from_alpaca: string | null;
  stock_history_from_alpaca: string | null;
}

export interface PortfolioHistoryPoint {
  date: string;
  portfolio_value: number;
  cash: number | null;
  buying_power: number | null;
}

export interface PremiumByDayPoint {
  date: string;
  total_premium: number;
  put_premium: number;
  call_premium: number;
  trade_count: number;
}

export interface MetricsSummary {
  total_trades: number;
  total_puts_sold: number;
  total_early_closes: number;
  total_scans: number;
  total_errors: number;
  trading_days: number;
  total_premium: number;
  put_premium_30d: number;
  call_premium_30d: number;
  win_rate: number | null;
  avg_premium: number;
  return_30d: number | null;
}

export interface AccountData {
  portfolio_value: number;
  cash: number;
  buying_power: number;
  equity: number;
  options_buying_power?: number;
  paper_trading?: boolean;
}

export interface LivePosition {
  symbol: string;
  qty: number | string;
  side: string;
  market_value: number | string;
  cost_basis: number | string;
  unrealized_pl: number | string;
  current_price?: number | string;
}

export interface FilteringStat {
  date_et: string;
  stage: string;
  result: string;
  total_events: number;
  unique_symbols: number;
  passed: number;
  blocked: number;
  reason: string | null;
  avg_premium: number | null;
  avg_delta: number | null;
  avg_dte: number | null;
}

export interface ErrorEvent {
  timestamp: string;
  date_et: string;
  event_type: string;
  error_type: string | null;
  error_message: string | null;
  symbol: string | null;
  underlying: string | null;
  component: string | null;
  recoverable: boolean | null;
  request_id: string | null;
}

export interface DailySummary {
  date_et: string;
  total_scans: number;
  total_opportunities: number;
  total_executions: number;
  total_errors: number;
  avg_scan_duration_sec: number;
  total_trades_failed: number;
}
