import { useEffect, useState } from 'react';
import type { MarketType } from '../../types';
import { api, type ExchangeSymbolInfo } from '../../lib/api';

interface Props {
  market: MarketType;
  symbol: string;
  onMarketChange: (m: MarketType) => void;
  onSymbolChange: (s: string) => void;
}

const POPULAR = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT'];

export default function MarketSelector({
  market, symbol, onMarketChange, onSymbolChange,
}: Props) {
  const [symbols, setSymbols] = useState<ExchangeSymbolInfo[]>([]);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.getExchangeInfo(market).then(setSymbols);
  }, [market]);

  const filtered = (() => {
    const q = query.trim().toUpperCase();
    const list = q
      ? symbols.filter(s => s.symbol.includes(q))
      : symbols.filter(s => POPULAR.includes(s.symbol) || s.symbol.endsWith('USDT'));
    return list.slice(0, 40);
  })();

  return (
    <div className="flex items-center gap-3">
      {/* spot/futures */}
      <div className="flex items-center bg-gray-800 rounded p-0.5">
        {(['spot', 'futures'] as MarketType[]).map(m => (
          <button
            key={m}
            onClick={() => onMarketChange(m)}
            className={`px-3 py-1 text-xs font-medium rounded transition ${
              market === m
                ? m === 'spot'
                  ? 'bg-blue-600 text-white'
                  : 'bg-orange-600 text-white'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {m === 'spot' ? '现货' : '合约'}
          </button>
        ))}
      </div>

      {/* symbol picker */}
      <div className="relative">
        <button
          onClick={() => setOpen(!open)}
          className="px-3 py-1 text-xs font-mono font-medium bg-gray-800 hover:bg-gray-700 rounded text-white min-w-[110px] text-left flex items-center justify-between gap-2"
        >
          <span>{symbol}</span>
          <span className="text-gray-500 text-[10px]">▾</span>
        </button>

        {open && (
          <div className="absolute top-full mt-1 left-0 w-64 bg-gray-900 border border-gray-700 rounded shadow-xl z-50 max-h-80 overflow-y-auto">
            <input
              autoFocus
              type="text"
              placeholder="搜索交易对…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 text-xs border-b border-gray-700 outline-none text-white"
            />
            <div className="py-1">
              {filtered.length === 0 && (
                <div className="px-3 py-2 text-xs text-gray-500">未找到</div>
              )}
              {filtered.map(s => (
                <button
                  key={s.symbol}
                  onClick={() => {
                    onSymbolChange(s.symbol);
                    setOpen(false);
                    setQuery('');
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-gray-800 flex items-center justify-between ${
                    s.symbol === symbol ? 'text-blue-400 bg-gray-800/50' : 'text-gray-300'
                  }`}
                >
                  <span>{s.symbol}</span>
                  {s.contract_type && (
                    <span className="text-[9px] text-gray-600">{s.contract_type}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
