import { useState, useEffect } from 'react';
import { Play, Square, Settings, BarChart3, Cpu, Plus, Layers, Globe, Loader2 } from 'lucide-react';
import StrategyParamsEditor from './StrategyParamsEditor';
import type { Strategy, BacktestSummary, StrategyMeta, MarketType } from '../../types';

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT'];
const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h'];

export default function StrategyPanel() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [btResult, setBtResult] = useState<BacktestSummary | null>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [strategyTypes, setStrategyTypes] = useState<StrategyMeta[]>([]);
  const [positions, setPositions] = useState<any[]>([]);
  const [loadingOps, setLoadingOps] = useState<Set<string>>(new Set());  // strategy_id
  const [toast, setToast] = useState<{msg: string; ok: boolean} | null>(null);

  // Create form state
  const [newStrategy, setNewStrategy] = useState({
    strategy_type: 'volume_surge',
    market_type: 'spot' as MarketType,
    symbol: 'BTCUSDT',
    timeframe: '1m',
    name: '',
  });

  useEffect(() => {
    fetchStrategies();
    fetchStrategyTypes();
    fetchPositions();
  }, []);

  const fetchStrategyTypes = async () => {
    try {
      const res = await fetch('/api/v1/strategies/types');
      const types: StrategyMeta[] = await res.json();
      setStrategyTypes(types);
      if (types.length > 0 && !newStrategy.name) {
        setNewStrategy(prev => ({ ...prev, name: types[0].name }));
      }
    } catch { /* */ }
  };

  const fetchStrategies = async () => {
    try {
      const res = await fetch('/api/v1/strategies');
      setStrategies(await res.json());
    } catch { /* */ }
  };

  const fetchPositions = async () => {
    try {
      const res = await fetch('/api/v1/positions');
      setPositions(await res.json());
    } catch { /* */ }
  };

  const createStrategy = async () => {
    try {
      await fetch('/api/v1/strategies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newStrategy),
      });
      await fetchStrategies();
      setShowCreate(false);
    } catch { /* */ }
  };

  const startStrategy = async (id: string, marketType?: string) => {
    setLoadingOps(prev => new Set(prev).add(id));
    try {
      const res = await fetch(`/api/v1/strategies/${id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ market_type: marketType || 'spot' }),
      });
      if (!res.ok) {
        const err = await res.text();
        setToast({ msg: `启动失败: ${err.slice(0, 60)}`, ok: false });
      }
      await fetchStrategies();
    } catch {
      setToast({ msg: '启动失败: 网络错误', ok: false });
    } finally {
      setLoadingOps(prev => { const n = new Set(prev); n.delete(id); return n; });
    }
  };

  const stopStrategy = async (id: string) => {
    setLoadingOps(prev => new Set(prev).add(id));
    try {
      await fetch(`/api/v1/strategies/${id}/stop`, { method: 'POST' });
      setToast({ msg: '策略已停止', ok: true });
      await fetchStrategies();
    } catch {
      setToast({ msg: '停止失败', ok: false });
    } finally {
      setLoadingOps(prev => { const n = new Set(prev); n.delete(id); return n; });
    }
  };

  const runBacktest = async () => {
    setBtLoading(true);
    try {
      const res = await fetch('/api/v1/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: 'BTCUSDT',
          lookback_hours: 48,
          strategy_type: 'volume_surge',
        }),
      });
      const data = await res.json();
      setBtResult(data.summary);
    } catch { /* */ }
    setBtLoading(false);
  };

  // 获取 meta
  const getMeta = (s: Strategy & { strategy_type?: string }) => {
    return strategyTypes.find(t => t.id === s.strategy_type || t.name === s.name);
  };

  // 自动消失 toast
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  return (
    <div className="space-y-3 relative">
      {/* Toast */}
      {toast && (
        <div className={`absolute top-0 left-0 right-0 z-50 px-3 py-1.5 rounded text-[11px] font-medium ${
          toast.ok ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'
        }`}>
          {toast.msg}
        </div>
      )}
      {/* Strategy List */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
            <Cpu className="h-3 w-3" /> 策略
          </h3>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="p-1 hover:bg-gray-800 rounded transition"
          >
            <Plus className={`h-3.5 w-3.5 ${showCreate ? 'text-blue-400' : 'text-gray-500'}`} />
          </button>
        </div>

        {/* Create Strategy Form */}
        {showCreate && (
          <div className="p-3 rounded-lg bg-gray-900/50 border border-blue-500/20 mb-3 space-y-2">
            <p className="text-[10px] text-gray-400 uppercase tracking-wider">新建策略</p>

            <div>
              <label className="text-[10px] text-gray-500 block mb-0.5">策略类型</label>
              <select
                value={newStrategy.strategy_type}
                onChange={e => {
                  const meta = strategyTypes.find(t => t.id === e.target.value);
                  setNewStrategy({
                    ...newStrategy,
                    strategy_type: e.target.value,
                    name: meta?.name || '',
                    market_type: (meta?.supported_markets?.includes('futures') ? 'futures' : 'spot') as MarketType,
                  });
                }}
                className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
              >
                {strategyTypes.map(t => (
                  <option key={t.id} value={t.id}>{t.name} — {t.description}</option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">市场</label>
                <select
                  value={newStrategy.market_type}
                  onChange={e => setNewStrategy({ ...newStrategy, market_type: e.target.value as MarketType })}
                  className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="spot">现货 Spot</option>
                  <option value="futures">合约 Futures</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-gray-500 block mb-0.5">交易对</label>
                <select
                  value={newStrategy.symbol}
                  onChange={e => setNewStrategy({ ...newStrategy, symbol: e.target.value })}
                  className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>

            <button
              onClick={createStrategy}
              className="w-full py-1.5 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 rounded-lg text-xs font-medium text-blue-400 transition"
            >
              创建
            </button>
          </div>
        )}

        {/* Strategy Cards */}
        {strategies.map((s) => {
          const running = (s as any).running;
          const liveState = (s as any).live_state;
          const meta = getMeta(s as any);
          const isLoading = loadingOps.has(s.id);
          return (
            <div key={s.id} className={`rounded-lg border mb-2 overflow-hidden transition ${
              running ? 'border-green-500/30 bg-gray-900/60' : 'border-gray-800 bg-gray-900/30'
            }`}>
              <div className="flex items-center justify-between p-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    {running && <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
                    <p className="text-sm font-medium truncate">{s.name}</p>
                    <span className={`text-[9px] px-1 py-0.5 rounded ${
                      liveState?.market_type === 'futures' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'
                    }`}>
                      {liveState?.market_type || 'spot'}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500 truncate">{s.symbol} · {s.timeframe}</p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {isLoading ? (
                    <Loader2 className="h-3.5 w-3.5 text-gray-400 animate-spin" />
                  ) : !running ? (
                    <button
                      onClick={() => startStrategy(s.id, liveState?.market_type)}
                      className="p-1 hover:bg-gray-800 rounded"
                      title="启动"
                    >
                      <Play className="h-3.5 w-3.5 text-green-400" />
                    </button>
                  ) : (
                    <button
                      onClick={() => stopStrategy(s.id)}
                      className="p-1 hover:bg-gray-800 rounded"
                      title="停止"
                    >
                      <Square className="h-3.5 w-3.5 text-red-400" />
                    </button>
                  )}
                </div>
              </div>
              {liveState && (
                <div className="px-2 pb-2 flex gap-2 text-[9px] font-mono text-gray-500">
                  <span>信号: {liveState.signal_count}</span>
                  <span>📊 {liveState.position?.active ? `${liveState.position.side} @ $${liveState.position.entry_price}` : '空仓'}</span>
                </div>
              )}

              {/* 参数编辑器 */}
              <StrategyParamsEditor
                strategy={s as any}
                meta={meta}
                onUpdated={fetchStrategies}
              />
            </div>
          );
        })}
        {strategies.length === 0 && (
          <p className="text-xs text-gray-500 text-center py-3">暂无策略，点击 + 创建</p>
        )}
      </div>

      {/* Positions Summary */}
      {positions.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Layers className="h-3 w-3" /> 持仓
          </h3>
          <div className="space-y-1">
            {positions.map((p, i) => (
              <div key={i} className="flex items-center justify-between p-1.5 rounded bg-gray-900/50 border border-gray-800 text-[10px]">
                <div className="flex items-center gap-1.5">
                  <span className={`font-medium ${p.side === 'long' ? 'text-green-400' : 'text-red-400'}`}>
                    {p.side === 'long' ? '📈' : '📉'} {p.symbol}
                  </span>
                  <span className="text-gray-500">{p.quantity.toFixed(4)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-gray-400">${p.entry_price.toFixed(2)}</span>
                  <span className={`font-mono ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Backtest */}
      <div>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <BarChart3 className="h-3 w-3" /> 回测
        </h3>
        <button
          onClick={runBacktest}
          disabled={btLoading}
          className="w-full py-2 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 rounded-lg text-xs font-medium transition disabled:opacity-50"
        >
          {btLoading ? '运行中...' : '运行回测 (48h BTCUSDT)'}
        </button>

        {btResult && (
          <div className="mt-2 p-2 rounded-lg bg-gray-900/50 border border-gray-800 space-y-1">
            {[
              { label: '收益率', value: `${btResult.total_return_pct}%`, color: btResult.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: 'Sharp率', value: btResult.sharpe.toFixed(2), color: 'text-blue-400' },
              { label: '最大回撤', value: `${btResult.max_drawdown}%`, color: 'text-red-400' },
              { label: '胜率', value: `${btResult.win_rate}%`, color: 'text-green-400' },
              { label: '交易次数', value: btResult.total_trades, color: 'text-gray-300' },
              { label: '盈亏比', value: btResult.profit_factor.toFixed(2), color: btResult.profit_factor > 1 ? 'text-green-400' : 'text-red-400' },
            ].map((item) => (
              <div key={item.label} className="flex justify-between text-[11px]">
                <span className="text-gray-400">{item.label}</span>
                <span className={`font-mono font-medium ${item.color}`}>{item.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
