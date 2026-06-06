import { useState, useEffect } from 'react';
import { Play, Square, Settings, BarChart3, Cpu } from 'lucide-react';
import type { Strategy, BacktestSummary } from '../../types';

export default function StrategyPanel() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [btResult, setBtResult] = useState<BacktestSummary | null>(null);
  const [btLoading, setBtLoading] = useState(false);

  useEffect(() => {
    fetch('/api/v1/strategies').then(r => r.json()).then(setStrategies).catch(() => {});
  }, []);

  const startStrategy = async (id: string) => {
    await fetch(`/api/v1/strategies/${id}/start`, { method: 'POST' });
    const res = await fetch('/api/v1/strategies').then(r => r.json());
    setStrategies(res);
  };

  const stopStrategy = async (id: string) => {
    await fetch(`/api/v1/strategies/${id}/stop`, { method: 'POST' });
    const res = await fetch('/api/v1/strategies').then(r => r.json());
    setStrategies(res);
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
          params: {
            lookback: 20,
            entry_threshold: 2.0,
            stop_loss_pct: 2.0,
            take_profit_pct: 5.0,
          },
        }),
      });
      const data = await res.json();
      setBtResult(data.summary);
    } catch { /* */ }
    setBtLoading(false);
  };

  return (
    <div className="space-y-3">
      {/* Strategy List */}
      <div>
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <Cpu className="h-3 w-3" /> 策略
        </h3>
        {strategies.map((s) => (
          <div key={s.id} className="flex items-center justify-between p-2 rounded-lg bg-gray-900/50 border border-gray-800 mb-2">
            <div>
              <p className="text-sm font-medium">{s.name}</p>
              <p className="text-[10px] text-gray-500">{s.symbol} · {s.timeframe}</p>
            </div>
            <div className="flex items-center gap-1">
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.status === 'running' ? 'bg-green-500/20 text-green-400' : 'text-gray-500'}`}>
                {s.status}
              </span>
              {s.status !== 'running' ? (
                <button onClick={() => startStrategy(s.id)} className="p-1 hover:bg-gray-800 rounded">
                  <Play className="h-3.5 w-3.5 text-green-400" />
                </button>
              ) : (
                <button onClick={() => stopStrategy(s.id)} className="p-1 hover:bg-gray-800 rounded">
                  <Square className="h-3.5 w-3.5 text-red-400" />
                </button>
              )}
            </div>
          </div>
        ))}
        {strategies.length === 0 && (
          <p className="text-xs text-gray-500">暂无策略，启动后自动创建</p>
        )}
      </div>

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
