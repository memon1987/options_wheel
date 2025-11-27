// API Response types

export interface AccountInfo {
  id: string;
  account_number: string;
  status: string;
  portfolio_value: number;
  cash: number;
  buying_power: number;
  equity: number;
  options_trading_level: number;
}

export interface Position {
  asset_id: string;
  symbol: string;
  asset_class: 'us_equity' | 'us_option';
  qty: number;
  side: 'long' | 'short';
  market_value: number;
  cost_basis: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  current_price: number;
  avg_entry_price: number;
}

export interface Trade {
  id: string;
  timestamp: string;
  symbol: string;
  underlying: string;
  strategy: 'sell_put' | 'sell_call' | 'buy_to_close';
  action: string;
  quantity: number;
  strike_price: number;
  expiration: string;
  premium: number;
  status: string;
  dte: number;
  delta: number;
}

export interface DailySummary {
  date: string;
  total_premium: number;
  trades_count: number;
  puts_sold: number;
  calls_sold: number;
  positions_closed: number;
  win_rate: number;
}

export interface FilteringStats {
  timestamp: string;
  symbol: string;
  stage: string;
  passed: boolean;
  reason: string;
  value: number;
  threshold: number;
}

export interface ErrorLog {
  timestamp: string;
  severity: 'ERROR' | 'WARNING' | 'INFO';
  component: string;
  message: string;
  details: string;
}

export interface WheelCycle {
  underlying: string;
  start_date: string;
  end_date: string | null;
  status: 'active' | 'completed';
  total_premium: number;
  trades_count: number;
  current_position: string;
}

export interface PerformanceMetrics {
  total_premium: number;
  total_trades: number;
  win_rate: number;
  avg_premium: number;
  avg_dte: number;
  total_puts: number;
  total_calls: number;
}

export interface PnLBySymbol {
  symbol: string;
  total_premium: number;
  trades_count: number;
  win_rate: number;
  avg_premium: number;
}

export interface PortfolioHistory {
  timestamp: string;
  portfolio_value: number;
  cash: number;
  buying_power: number;
}

export interface Expiration {
  expiration_date: string;
  symbol: string;
  option_symbol: string;
  strike: number;
  option_type: 'put' | 'call';
  premium_received: number;
  dte: number;
}

export interface BotStatus {
  status: string;
  market_open: boolean;
  last_check: string;
  active_positions: number;
  pending_orders: number;
}

export interface Config {
  strategy: {
    put_target_dte: number;
    call_target_dte: number;
    put_delta_range: [number, number];
    call_delta_range: [number, number];
    min_put_premium: number;
    min_call_premium: number;
  };
  risk: {
    max_portfolio_allocation: number;
    max_position_size: number;
    profit_target_percent: number;
  };
  stocks: {
    symbols: string[];
  };
}
