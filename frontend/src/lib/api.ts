// API client — 统一接口
import type { Ticker, Kline, MarketType } from '../types';

export interface MarkPriceData {
  symbol: string;
  mark_price: number;
  index_price: number;
  funding_rate: number;
  next_funding_time: number;
}

export interface OpenInterestData {
  symbol: string;
  open_interest: number;
}

export interface FuturesOrderBook {
  symbol: string;
  bids: [string, string][];
  asks: [string, string][];
}

export interface MarketSummary {
  symbol: string;
  spot: Ticker | null;
  futures: (Ticker & { quote_volume?: number }) | null;
  futures_mark: MarkPriceData | null;
  futures_open_interest: OpenInterestData | null;
}

export interface ExchangeSymbolInfo {
  symbol: string;
  status: string;
  base_asset: string;
  quote_asset: string;
  contract_type?: string;
}

export const api = {
  async getTicker(symbol: string, market: MarketType = 'spot'): Promise<Ticker | null> {
    const r = await fetch(`/api/v1/market/ticker/${symbol}?market=${market}`);
    const d = await r.json();
    return d.error ? null : d;
  },

  async getKlines(symbol: string, interval = '1m', limit = 200,
                  market: MarketType = 'spot'): Promise<Kline[]> {
    const r = await fetch(
      `/api/v1/market/klines/${symbol}?interval=${interval}&limit=${limit}&market=${market}`,
    );
    const d = await r.json();
    return Array.isArray(d) ? d : [];
  },

  async getExchangeInfo(market: MarketType = 'spot'): Promise<ExchangeSymbolInfo[]> {
    const r = await fetch(`/api/v1/market/info?market=${market}`);
    const d = await r.json();
    return Array.isArray(d) ? d : [];
  },

  async getMarkPrice(symbol: string): Promise<MarkPriceData | null> {
    const r = await fetch(`/api/v1/market/futures/mark-price/${symbol}`);
    const d = await r.json();
    return d.error ? null : d;
  },

  async getOpenInterest(symbol: string): Promise<OpenInterestData | null> {
    const r = await fetch(`/api/v1/market/futures/open-interest/${symbol}`);
    const d = await r.json();
    return d.error ? null : d;
  },

  async getFuturesDepth(symbol: string, limit = 10): Promise<FuturesOrderBook | null> {
    const r = await fetch(`/api/v1/market/futures/depth/${symbol}?limit=${limit}`);
    const d = await r.json();
    return d.error ? null : d;
  },

  async getMarketSummary(symbol: string): Promise<MarketSummary> {
    const r = await fetch(`/api/v1/market/summary/${symbol}`);
    return r.json();
  },
};
