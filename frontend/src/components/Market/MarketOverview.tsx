import { useEffect, useMemo, useState } from 'react';
import { Search, TrendingUp, TrendingDown, ChevronUp, ChevronDown, Globe } from 'lucide-react';
import type { MarketType, Ticker } from '../../types';
import { type ExchangeSymbolInfo } from '../../lib/api';
import { useSWR } from '../../lib/hooks/useSWR';

type SortKey = 'symbol' | 'price' | 'change_pct' | 'volume' | 'quote_volume';

const FAVORITE_KEY = '***';
const TOP_LIMIT = 60;

export default function MarketOverview() {
  const [market, setMarket] = useState<MarketType>('spot');
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('quote_volume');
  const [sortDesc, setSortDesc] = useState(true);
  const [tickers, setTickers] = useState<Record<string, Ticker>>({});
  const [favorites, setFavorites] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(FAVORITE_KEY) || '[]')); }
    catch { return new Set(); }
  });

  useEffect(() => {
    const id = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(id);
  }, [query]);

  const { data: symbols = [] } = useSWR<ExchangeSymbolInfo[]>(
    `/api/v1/market/info?market=${market}`,
    { intervalMs: 30000 },
  );
  const usdtSymbols = useMemo(
    () => symbols.filter(s => s.quote_asset === 'USDT'),
    [symbols],
  );

  const displayList = useMemo(() => {
    const q = debouncedQuery.trim().toUpperCase();
    const list = q
      ? usdtSymbols.filter(s => s.symbol.includes(q))
      : [...Array.from(favorites).map(f => ({ symbol: f, quote_asset: 'USDT' })) as ExchangeSymbolInfo[], ...usdtSymbols];
    return list.slice(0, TOP_LIMIT);
  }, [usdtSymbols, debouncedQuery, favorites]);

  const tickerKey = `marketOverview:${market}:${displayList.map(s => s.symbol).join(',')}`;
  useSWR<void>(displayList.length ? tickerKey : null, {
    silent: true,
    parser: async () => {
      const res = await Promise.allSettled(
        displayList.map(async s => {
          try {
            const r = await fetch(`/api/v1/market/ticker/${s.symbol}?market=${market}`);
            const d = await r.json();
            return d.error ? null : { sym: s.symbol, t: d as Ticker };
          } catch { return null; }
        }),
      );
      const next: Record<string, Ticker> = {};
      for (const r of res) {
        if (r.status === 'fulfilled' && r.value) next[r.value.sym] = r.value.t;
      }
      setTickers(next);
      return undefined;
    },
  });

  useEffect(() => { setTickers({}); }, [market]);

  const toggleFav = (sym: string) => {
    setFavorites(prev => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym); else next.add(sym);
      localStorage.setItem(FAVORITE_KEY, JSON.stringify([...next]));
      return next;
    });
  };

  const sortedRows = useMemo(() => {
    const rows = Object.entries(tickers).map(([sym, t]) => ({
      symbol: sym,
      ...t,
      quote_volume: (t as any).quote_volume ?? t.price * t.volume,
      fav: favorites.has(sym),
    }));
    rows.sort((a, b) => {
      if (a.fav !== b.fav) return a.fav ? -1 : 1;
      const va = (a as any)[sortKey];
      const vb = (b as any)[sortKey];
      if (sortKey === 'symbol') return sortDesc ? String(vb).localeCompare(String(va)) : String(va).localeCompare(String(vb));
      return sortDesc ? (vb - va) : (va - vb);
    });
    return rows;
  }, [tickers, favorites, sortKey, sortDesc]);

  const sortBy = (k: SortKey) => {
    if (sortKey === k) setSortDesc(!sortDesc);
    else { setSortKey(k); setSortDesc(true); }
  };

  const SortIcon = ({ k }: { k: SortKey }) => sortKey !== k ? null :
    sortDesc ? <ChevronDown className="h-3 w-3 inline" /> : <ChevronUp className="h-3 w-3 inline" />;

  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900/30 shrink-0">
        <div className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-blue-400" />
          <h2 className="text-sm font-semibold">市场总览</h2>
          <span className="text-[10px] text-gray-500">显示 Top {TOP_LIMIT}</span>
        </div>

        <div className="flex items-center bg-gray-800 rounded p-0.5">
          {(['spot', 'futures'] as MarketType[]).map(m => (
            <button
              key={m}
              onClick={() => setMarket(m)}
              className={`px-3 py-1 text-xs rounded ${
                market === m
                  ? m === 'spot' ? 'bg-blue-600 text-white' : 'bg-orange-600 text-white'
                  : 'text-gray-400'
              }`}
            >
              {m === 'spot' ? '现货' : '合约'}
            </button>
          ))}
        </div>

        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="搜索交易对…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="w-full pl-7 pr-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-xs text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <span className="text-[10px] text-gray-500">
          {sortedRows.length} 个交易对
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        <table className="w-full text-xs">
          <thead className="text-[10px] uppercase text-gray-500 sticky top-0 bg-gray-950/95 backdrop-blur">
            <tr>
              <th className="w-8 px-2 py-2"></th>
              <th className="text-left px-2 py-2 font-normal cursor-pointer hover:text-gray-300" onClick={() => sortBy('symbol')}>
                交易对 <SortIcon k="symbol" />
              </th>
              <th className="text-right px-2 py-2 font-normal cursor-pointer hover:text-gray-300" onClick={() => sortBy('price')}>
                最新价 <SortIcon k="price" />
              </th>
              <th className="text-right px-2 py-2 font-normal cursor-pointer hover:text-gray-300" onClick={() => sortBy('change_pct')}>
                24h 涨跌 <SortIcon k="change_pct" />
              </th>
              <th className="text-right px-2 py-2 font-normal cursor-pointer hover:text-gray-300" onClick={() => sortBy('volume')}>
                24h 量 <SortIcon k="volume" />
              </th>
              <th className="text-right px-2 py-2 font-normal cursor-pointer hover:text-gray-300" onClick={() => sortBy('quote_volume')}>
                24h 额 (USDT) <SortIcon k="quote_volume" />
              </th>
              <th className="text-right px-2 py-2 font-normal">最高 / 最低</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map(row => (
              <tr key={row.symbol} className="border-t border-gray-800/40 hover:bg-gray-900/40">
                <td className="px-2 py-1.5 text-center">
                  <button
                    onClick={() => toggleFav(row.symbol)}
                    className={`text-base leading-none ${row.fav ? 'text-yellow-400' : 'text-gray-700 hover:text-yellow-500'}`}
                    title={row.fav ? '取消收藏' : '收藏'}
                  >★</button>
                </td>
                <td className="px-2 py-1.5 font-mono font-medium">{row.symbol}</td>
                <td className="px-2 py-1.5 text-right font-mono">
                  ${row.price.toLocaleString(undefined, { maximumFractionDigits: row.price > 1 ? 2 : 6 })}
                </td>
                <td className={`px-2 py-1.5 text-right font-mono ${row.change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  <span className="inline-flex items-center gap-0.5 justify-end">
                    {row.change >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                    {row.change >= 0 ? '+' : ''}{row.change_pct.toFixed(2)}%
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-gray-400">
                  {row.volume >= 1e6 ? (row.volume / 1e6).toFixed(2) + 'M'
                    : row.volume >= 1e3 ? (row.volume / 1e3).toFixed(2) + 'K'
                    : row.volume.toFixed(2)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-gray-400">
                  {row.quote_volume >= 1e9 ? '$' + (row.quote_volume / 1e9).toFixed(2) + 'B'
                    : row.quote_volume >= 1e6 ? '$' + (row.quote_volume / 1e6).toFixed(2) + 'M'
                    : '$' + (row.quote_volume / 1e3).toFixed(2) + 'K'}
                </td>
                <td className="px-2 py-1.5 text-right font-mono text-[10px] text-gray-500">
                  ${row.high.toFixed(0)} / ${row.low.toFixed(0)}
                </td>
              </tr>
            ))}
            {sortedRows.length === 0 && (
              <tr><td colSpan={7} className="text-center py-6 text-gray-500">未找到匹配的交易对</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
