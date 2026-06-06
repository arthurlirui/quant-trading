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
  created_at?: string;
  updated_at?: string;
}

export interface StrategyState {
  symbol: string;
  params: Record<string, number>;
  position: {
    active: boolean;
    side: string;
    entry_price: number;
    quantity: number;
    trades: number;
    win_trades: number;
  };
  data_points: {
    prices: number;
    volumes: number;
  };
  recent_signals: SignalData[];
}

export interface SignalData {
  time: number;
  price: number;
  volume: number;
  action: string;
  strength: number;
  reason: string;
}

export interface MarketDownloadResult {
  symbol: string;
  interval: string;
  downloaded: number;
  skipped: number;
  range: {
    from: number;
    to: number;
    count: number;
  } | null;
}

export interface MarketDataQuery {
  symbol: string;
  interval: string;
  total: number;
  offset: number;
  limit: number;
  data: Kline[];
}

export interface MarketDataStat {
  symbol: string;
  interval: string;
  count: number;
  earliest: number;
  latest: number;
}

export type ViewMode = 'trading' | 'dashboard';
