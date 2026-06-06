export interface Ticker {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  high: number;
  low: number;
  volume: number;
  quote_volume?: number;
}

export interface Kline {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time?: number;
  is_final?: boolean;
}

export interface Signal {
  symbol: string;
  action: 'buy' | 'sell' | 'close_buy' | 'close_sell' | 'hold';
  strength: number;
  price: number;
  reason: string;
}

export interface BacktestSummary {
  total_return_pct: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  profit_factor: number;
}

export interface Strategy {
  id: string;
  name: string;
  symbol: string;
  timeframe: string;
  params: string;
  status: string;
  enabled: boolean;
}
