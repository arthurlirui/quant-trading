import { useEffect, useState } from 'react';
import { History, TrendingUp, TrendingDown, ChevronDown, RefreshCw } from 'lucide-react';
import type { Strategy } from '../../types';

export interface TradeRecord {
  id: string;
  strategy_id: string;
  symbol: string;
  side: 'buy' | 'sell';
  price: number;
  quantity: number;
  pnl: number | null;
  status: string;
  signal_strength: number | null;
  mode: 'sim' | 'live' | null;
  open_time: string | null;
  close_time: string | null;
  created_at: string | null;
}

interface Props {
  /** 选中的策略 id, 'all' = 不过滤 */
  defaultStrategyId?: string;
  /** 选中的模式 */
  defaultMode?: 'all' | 'sim' | 'live';
  /** 拉到 trades 后回调（用于联动 chart markers） */
  onTradesLoaded?: (trades: TradeRecord[]) => void;
  symbolFilter?: string;
}

export default function TradeHistory({
  defaultStrategyId = 'all',
  defaultMode = 'all',
  onTradesLoaded,
  symbolFilter,
}: Props) {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [strategyId, setStrategyId] = useState(defaultStrategyId);
  const [mode, setMode] = useState<'all' | 'sim' | 'live'>(defaultMode);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/v1/strategies').then(r => r.json()).then(setStrategies).catch(() => {});
  }, []);

  const fetchTrades = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (strategyId !== 'all') params.set('strategy_id', strategyId);
      if (mode !== 'all') params.set('mode', mode);
      if (symbolFilter) params.set('symbol', symbolFilter);
      params.set('limit', '100');
      const res = await fetch(`/api/v1/trades?${params}`);
      const data: TradeRecord[] = await res.json();
      setTrades(data);
      onTradesLoaded?.(data);
    } catch { /* */ }
    setLoading(false);
  };

  useEffect(() => {
    fetchTrades();
    const id = setInterval(fetchTrades, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyId, mode, symbolFilter]);

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded">
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-gray-300 flex items-center gap-1.5">
          <History className="h-3 w-3" /> 交易明细
          <span className="text-[10px] text-gray-500">({trades.length})</span>
        </h3>
        <div className="flex items-center gap-1.5">
          {/* 策略下拉 */}
          <div className="relative">
            <select
              value={strategyId}
              onChange={e => setStrategyId(e.target.value)}
              className="appearance-none bg-gray-800 border border-gray-700 rounded text-[10px] px-2 py-1 pr-6 text-white focus:outline-none focus:border-blue-500"
            >
              <option value="all">全部策略</option>
              {strategies.map(s => (
                <option key={s.id} value={s.id}>{s.name} · {s.symbol}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-500 pointer-events-none" />
          </div>
          {/* mode 下拉 */}
          <div className="relative">
            <select
              value={mode}
              onChange={e => setMode(e.target.value as any)}
              className="appearance-none bg-gray-800 border border-gray-700 rounded text-[10px] px-2 py-1 pr-6 text-white focus:outline-none focus:border-blue-500"
            >
              <option value="all">全部</option>
              <option value="sim">模拟盘</option>
              <option value="live">实盘</option>
            </select>
            <ChevronDown className="absolute right-1 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-500 pointer-events-none" />
          </div>
          <button
            onClick={fetchTrades}
            disabled={loading}
            className="p-1 hover:bg-gray-800 rounded transition"
            title="刷新"
          >
            <RefreshCw className={`h-3 w-3 text-gray-500 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="max-h-[420px] overflow-y-auto">
        {trades.length === 0 ? (
          <p className="text-[11px] text-gray-500 text-center py-6">暂无交易记录</p>
        ) : (
          <table className="w-full text-[11px]">
            <thead className="text-gray-500 text-[10px] uppercase tracking-wider sticky top-0 bg-gray-900/95 backdrop-blur">
              <tr>
                <th className="text-left px-2 py-1.5 font-normal">时间</th>
                <th className="text-left px-2 py-1.5 font-normal">交易对</th>
                <th className="text-left px-2 py-1.5 font-normal">方向</th>
                <th className="text-right px-2 py-1.5 font-normal">价格</th>
                <th className="text-right px-2 py-1.5 font-normal">数量</th>
                <th className="text-right px-2 py-1.5 font-normal">PnL</th>
                <th className="text-left px-2 py-1.5 font-normal">模式</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.id} className="border-t border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-2 py-1 text-gray-500 whitespace-nowrap">
                    {t.created_at ? new Date(t.created_at).toLocaleString('zh-CN', {
                      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
                    }) : '–'}
                  </td>
                  <td className="px-2 py-1 font-mono">{t.symbol}</td>
                  <td className="px-2 py-1">
                    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      t.side === 'buy' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {t.side === 'buy' ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
                      {t.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-2 py-1 text-right font-mono">${t.price.toFixed(2)}</td>
                  <td className="px-2 py-1 text-right font-mono text-gray-400">{t.quantity.toFixed(4)}</td>
                  <td className={`px-2 py-1 text-right font-mono ${
                    t.pnl == null ? 'text-gray-600' :
                    t.pnl > 0 ? 'text-green-400' : t.pnl < 0 ? 'text-red-400' : 'text-gray-400'
                  }`}>
                    {t.pnl == null ? '–' : (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2)}
                  </td>
                  <td className="px-2 py-1">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                      t.mode === 'live' ? 'bg-red-500/10 text-red-300' :
                      t.mode === 'sim' ? 'bg-blue-500/10 text-blue-300' : 'text-gray-600'
                    }`}>
                      {t.mode === 'live' ? '实盘' : t.mode === 'sim' ? '模拟' : '–'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
