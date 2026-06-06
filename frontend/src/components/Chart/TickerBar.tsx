import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import type { Ticker } from '../../types';

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'];

export default function TickerBar() {
  const [tickers, setTickers] = useState<Record<string, Ticker>>({});

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/api/v1/ws/market/BTCUSDT`);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'ticker') {
          setTickers((prev) => ({ ...prev, [msg.data.symbol]: msg.data }));
        }
      } catch { /* */ }
    };

    // Poll REST for tickers
    const interval = setInterval(async () => {
      for (const sym of SYMBOLS) {
        try {
          const res = await fetch(`/api/v1/market/ticker/${sym}`);
          const data = await res.json();
          if (data.price) setTickers((prev) => ({ ...prev, [sym]: data }));
        } catch { /* */ }
      }
    }, 5000);

    return () => {
      ws.close();
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="flex items-center gap-4 px-4 py-1.5 bg-gray-900/80 border-b border-gray-800 text-xs overflow-x-auto">
      {SYMBOLS.map((sym) => {
        const t = tickers[sym];
        if (!t) return <span key={sym} className="text-gray-500">{sym}...</span>;
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
