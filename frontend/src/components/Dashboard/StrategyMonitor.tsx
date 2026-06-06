import { useEffect, useState, useRef } from 'react';
import { Cpu, TrendingUp, TrendingDown, Activity, Zap, RefreshCw } from 'lucide-react';
import type { Strategy, StrategyState, SignalData } from '../../types';

export default function StrategyMonitor() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [states, setStates] = useState<Record<string, StrategyState>>({});
  const [loading, setLoading] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchStrategies();
    // Poll every 3s
    intervalRef.current = setInterval(fetchStrategies, 3000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const fetchStrategies = async () => {
    try {
      const res = await fetch('/api/v1/strategies');
      const list: Strategy[] = await res.json();
      setStrategies(list);

      // Fetch state for running strategies
      for (const s of list) {
        if (s.status === 'running') {
          try {
            const stateRes = await fetch(`/api/v1/strategies/${s.id}/state`);
            if (stateRes.ok) {
              const state: StrategyState = await stateRes.json();
              setStates(prev => ({ ...prev, [s.id]: state }));
            }
          } catch { /* */ }
        } else {
          // Remove stale state
          setStates(prev => {
            const next = { ...prev };
            delete next[s.id];
            return next;
          });
        }
      }
    } catch { /* */ }
  };

  const startStrategy = async (id: string) => {
    setLoading(true);
    try {
      await fetch(`/api/v1/strategies/${id}/start`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 500));
      await fetchStrategies();
    } finally {
      setLoading(false);
    }
  };

  const stopStrategy = async (id: string) => {
    setLoading(true);
    try {
      await fetch(`/api/v1/strategies/${id}/stop`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 500));
      await fetchStrategies();
    } finally {
      setLoading(false);
    }
  };

  const running = strategies.filter(s => s.status === 'running');

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
          <Cpu className="h-3 w-3" /> 运行中策略
        </h3>
        <button
          onClick={fetchStrategies}
          className="p-1 hover:bg-gray-800 rounded transition"
          title="刷新"
        >
          <RefreshCw className="h-3 w-3 text-gray-500" />
        </button>
      </div>

      {running.length === 0 && (
        <div className="p-4 rounded-lg bg-gray-900/50 border border-gray-800 text-center">
          <p className="text-xs text-gray-500">暂无运行中的策略</p>
          <p className="text-[10px] text-gray-600 mt-1">在「交易」页面创建并启动策略</p>
        </div>
      )}

      {running.map(s => {
        const st = states[s.id];
        return (
          <div key={s.id} className="rounded-lg bg-gray-900/50 border border-gray-800 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 bg-gray-900/80 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-sm font-medium">{s.name}</span>
                <span className="text-[10px] text-gray-500">{s.symbol}</span>
              </div>
              <button
                onClick={() => stopStrategy(s.id)}
                disabled={loading}
                className="text-[10px] px-2 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition disabled:opacity-50"
              >
                停止
              </button>
            </div>

            {/* Stats Grid */}
            <div className="p-3">
              {/* Price + Signal Bar */}
              {st && (
                <>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-lg font-mono font-bold text-white">
                        ${st.recent_signals.length > 0
                          ? st.recent_signals[st.recent_signals.length - 1].price.toLocaleString(undefined, { minimumFractionDigits: 2 })
                          : '---'}
                      </span>
                    </div>
                    {st.recent_signals.length > 0 && (
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        signalColor(st.recent_signals[st.recent_signals.length - 1].action)
                      }`}>
                        {signalLabel(st.recent_signals[st.recent_signals.length - 1].action)}
                      </span>
                    )}
                  </div>

                  {/* Metrics */}
                  <div className="grid grid-cols-2 gap-2 mb-3">
                    <MetricBox
                      label="数据点"
                      value={`${st.data_points.prices}`}
                      icon={<Activity className="h-3 w-3" />}
                      color="text-blue-400"
                    />
                    <MetricBox
                      label="信号强度"
                      value={st.recent_signals.length > 0
                        ? `${(st.recent_signals[st.recent_signals.length - 1].strength * 100).toFixed(0)}%`
                        : '---'}
                      icon={<Zap className="h-3 w-3" />}
                      color="text-yellow-400"
                    />
                  </div>

                  {/* Position */}
                  <div className="mb-3">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">持仓</p>
                    {st.position.active ? (
                      <div className="bg-gray-950/50 rounded p-2 space-y-1">
                        <div className="flex justify-between text-[11px]">
                          <span className="text-gray-400">方向</span>
                          <span className={`font-medium ${st.position.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                            {st.position.side === 'buy' ? '做多 📈' : '做空 📉'}
                          </span>
                        </div>
                        <div className="flex justify-between text-[11px]">
                          <span className="text-gray-400">入场价</span>
                          <span className="font-mono">${st.position.entry_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                        </div>
                        <div className="flex justify-between text-[11px]">
                          <span className="text-gray-400">数量</span>
                          <span className="font-mono">{st.position.quantity.toFixed(4)}</span>
                        </div>
                        <div className="flex justify-between text-[11px]">
                          <span className="text-gray-400">胜率</span>
                          <span className={`font-medium ${st.position.trades > 0
                            ? (st.position.win_trades / st.position.trades) >= 0.5 ? 'text-green-400' : 'text-red-400'
                            : 'text-gray-500'}`}>
                            {st.position.trades > 0
                              ? `${(st.position.win_trades / st.position.trades * 100).toFixed(0)}% (${st.position.win_trades}/${st.position.trades})`
                              : '暂无交易'}
                          </span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-[10px] text-gray-600">当前无持仓</p>
                    )}
                  </div>

                  {/* Recent Signals */}
                  {st.recent_signals.length > 0 && (
                    <div>
                      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">最近信号</p>
                      <div className="space-y-0.5 max-h-24 overflow-y-auto">
                        {[...st.recent_signals].reverse().map((sig, i) => (
                          <div key={i} className={`flex items-center justify-between text-[10px] px-1.5 py-0.5 rounded ${
                            sig.action === 'buy' ? 'bg-green-500/10' :
                            sig.action === 'sell' ? 'bg-red-500/10' :
                            sig.action === 'close_buy' ? 'bg-yellow-500/10' :
                            sig.action === 'close_sell' ? 'bg-orange-500/10' : ''
                          }`}>
                            <span className={`font-medium ${
                              sig.action === 'buy' ? 'text-green-400' :
                              sig.action === 'sell' ? 'text-red-400' :
                              sig.action === 'close_buy' ? 'text-yellow-400' :
                              sig.action === 'close_sell' ? 'text-orange-400' :
                              'text-gray-500'
                            }`}>
                              {sig.action.toUpperCase()}
                            </span>
                            <span className="text-gray-500 truncate max-w-[120px]">{sig.reason || 'hold'}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {!st && (
                <div className="flex items-center justify-center py-4">
                  <RefreshCw className="h-4 w-4 text-gray-600 animate-spin" />
                  <span className="text-xs text-gray-500 ml-2">获取策略状态...</span>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* Stopped strategies (collapsed) */}
      {strategies.filter(s => s.status !== 'running').length > 0 && (
        <div>
          <p className="text-[10px] text-gray-600 uppercase tracking-wider mb-1 mt-3">已停止</p>
          {strategies.filter(s => s.status !== 'running').map(s => (
            <div key={s.id} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-900/30 border border-gray-800/50 mb-1">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-gray-600" />
                <span className="text-xs text-gray-500">{s.name}</span>
                <span className="text-[10px] text-gray-600">{s.symbol}</span>
              </div>
              <button
                onClick={() => startStrategy(s.id)}
                disabled={loading}
                className="text-[10px] px-2 py-0.5 rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 transition disabled:opacity-50"
              >
                启动
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricBox({ label, value, icon, color }: {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div className="bg-gray-950/50 rounded p-2">
      <div className="flex items-center gap-1 text-[10px] text-gray-500 mb-0.5">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`text-sm font-mono font-medium ${color}`}>{value}</p>
    </div>
  );
}

function signalColor(action: string): string {
  switch (action) {
    case 'buy': return 'bg-green-500/20 text-green-400';
    case 'sell': return 'bg-red-500/20 text-red-400';
    case 'close_buy': return 'bg-yellow-500/20 text-yellow-400';
    case 'close_sell': return 'bg-orange-500/20 text-orange-400';
    default: return 'bg-gray-500/20 text-gray-400';
  }
}

function signalLabel(action: string): string {
  switch (action) {
    case 'buy': return '做多 🟢';
    case 'sell': return '做空 🔴';
    case 'close_buy': return '平多 ⚠️';
    case 'close_sell': return '平空 ⚠️';
    default: return '持仓中';
  }
}
