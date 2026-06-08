import { useEffect, useMemo, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import type { Ticker, MarketType } from '../../types';
import { useSWR } from '../../lib/hooks/useSWR';

interface Props {
  market: MarketType;
  symbols?: string[];
}

const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT'];

/** 单 symbol ticker — 让每个 ticker 走独立 useSWR，更好的缓存复用 */
function useTickers(market: MarketType, symbols: string[]): Record<string, Ticker> {
  const [results, setResults] = useState<Record<string, Ticker>>({});

  // 用一个聚合 key 触发统一节奏拉取，但实际请求并行
  const aggKey = `tickers:${market}:${symbols.join(',')}`;
  const { lastUpdated } = useSWR<Record<string, Ticker>>(
    aggKey,
    {
      parser: async () => {
        const res = await Promise.allSettled(
          symbols.map(async sym => {
            const r = await fetch(`/api/v1/market/ticker/${sym}?market=${market}`);
            const d = await r.json();
            return d.error ? null : { sym, t: d as Ticker };
          }),
        );
        const next: Record<string, Ticker> = {};
        for (const r of res) {
          if (r.status === 'fulfilled' && r.value) next[r.value.sym] = r.value.t;
        }
        setResults(next);
        return next;
      },
      silent: true,
    },
  );

  useEffect(() => {
    setResults({});  // clear on market change
  }, [market, symbols.join(',')]);

  void lastUpdated;
  return results;
}

export default function TickerBar({ market, symbols = DEFAULT_SYMBOLS }: Props) {
  const tickers = useTickers(market, symbols);

  return (
    <div className="flex items-center gap-4 px-4 py-1.5 bg-gray-900/80 border-b border-gray-800 text-xs overflow-x-auto">
      <span className={`text-[10px] uppercase font-semibold tracking-wider shrink-0 ${
        market === 'spot' ? 'text-blue-400' : 'text-orange-400'
      }`}>
        {market === 'spot' ? '现货' : '合约'} ·
      </span>
      {symbols.map((sym) => {
        const t = tickers[sym];
        if (!t) {
          return <span key={sym} className="text-gray-600">{sym.replace('USDT','')}…</span>;
        }
        const isUp = t.change >= 0;
        return (
          <div key={sym} className="flex items-center gap-2 shrink-0">
            <span className="font-semibold text-white">{sym.replace('USDT', '')}</span>
            <span className="font-mono">${t.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
            <span className={`flex items-center gap-0.5 font-mono ${isUp ? 'text-green-400' : 'text-red-400'}`}>
              {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
              {t.change_pct > 0 ? '+' : ''}{t.change_pct.toFixed(2)}%
            </span>
            <span className="text-gray-600">V:{t.volume.toFixed(0)}</span>
          </div>
        );
      })}
    </div>
  );
}
