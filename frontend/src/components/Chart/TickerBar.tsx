import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import type { Ticker, MarketType } from '../../types';
import { api } from '../../lib/api';

interface Props {
  market: MarketType;
  symbols?: string[];
}

const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT'];

export default function TickerBar({ market, symbols = DEFAULT_SYMBOLS }: Props) {
  const [tickers, setTickers] = useState<Record<string, Ticker>>({});

  useEffect(() => {
    setTickers({});  // clear when market changes
    let alive = true;

    const tick = async () => {
      const results = await Promise.allSettled(
        symbols.map(sym => api.getTicker(sym, market).then(t => ({ sym, t }))),
      );
      if (!alive) return;
      const next: Record<string, Ticker> = {};
      for (const r of results) {
        if (r.status === 'fulfilled' && r.value.t) next[r.value.sym] = r.value.t;
      }
      setTickers(next);
    };

    tick();
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, [market, symbols.join(',')]);

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
