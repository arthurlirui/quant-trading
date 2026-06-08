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

export type ViewMode = 'trading' | 'dashboard' | 'market';

// ── New types for v0.2.0 ──

export type MarketType = 'spot' | 'futures';

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  supported_markets: MarketType[];
  default_params: Record<string, number>;
}

export interface CreateStrategyRequest {
  strategy_type: string;
  market_type: MarketType;
  symbol: string;
  timeframe?: string;
  name?: string;
  params?: Record<string, number>;
}

export interface Order {
  id: string;
  strategy_id: string;
  symbol: string;
  side: string;
  order_type: string;
  market_type: MarketType;
  price: number;
  quantity: number;
  filled_quantity: number;
  avg_fill_price: number;
  status: string;
  stop_price: number | null;
  sl_price: number | null;
  tp_price: number | null;
  leverage: number;
  pnl: number | null;
  created_at: number;
  error: string;
}

export interface PositionInfo {
  symbol: string;
  side: 'long' | 'short';
  quantity: number;
  entry_price: number;
  mark_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  leverage: number;
  market_type: MarketType;
}

export interface RiskSummary {
  equity: { current: number; peak: number; drawdown_pct: number };
  daily: { pnl: number; loss: number; trades: number };
  limits: { max_positions: number; max_position_value: number; max_leverage: number };
  can_trade: boolean;
}
