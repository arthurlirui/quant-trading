import { useState, useEffect, useRef } from 'react';
import { TrendingUp, Activity, Radio } from 'lucide-react';
import TradingChart from './components/Chart/TradingChart';
import TickerBar from './components/Chart/TickerBar';
import StrategyPanel from './components/Trading/StrategyPanel';
import type { Kline, Signal } from './types';

export default function App() {
  const [klines, setKlines] = useState<Kline[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [status, setStatus] = useState<any>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetch('/api/v1/status').then(r => r.json()).then(setStatus).catch(() => {});

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/api/v1/ws/market/BTCUSDT`);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'kline') {
          setKlines((prev) => {
            const k = msg.data as Kline;
            const existing = prev.findIndex(p => p.open_time === k.open_time);
            if (existing >= 0) {
              const next = [...prev];
              next[existing] = k;
              return next;
            }
            return [...prev.slice(-200), k];
          });
        } else if (msg.type === 'signal') {
          setSignals((prev) => [msg.data, ...prev].slice(0, 50));
        }
      } catch { /* */ }
    };

    // Fetch historical klines
    fetch('/api/v1/market/klines/BTCUSDT?interval=1m&limit=200')
      .then(r => r.json())
      .then((data: Kline[]) => setKlines(data))
      .catch(() => {});

    return () => ws.close();
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col bg-gray-950 text-white overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-900/80 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green-500 to-blue-600 flex items-center justify-center">
            <TrendingUp className="h-4 w-4" />
          </div>
          <span className="font-semibold text-sm">Quant <span className="text-green-400">Trading</span></span>
          <span className="text-[10px] text-gray-500">v0.1.0</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[11px]">
            <Radio className={`h-3 w-3 ${wsConnected ? 'text-green-400' : 'text-red-400'}`} />
            <span className={wsConnected ? 'text-green-400' : 'text-red-400'}>
              {wsConnected ? '实时' : '断连'}
            </span>
          </div>
          {status && (
            <span className="text-[10px] text-gray-500">
              {status.testnet ? '测试网' : '主网'}
            </span>
          )}
        </div>
      </header>

      {/* Ticker Bar */}
      <TickerBar />

      {/* Main Grid */}
      <div className="flex-1 flex gap-0.5 overflow-hidden">
        {/* Chart */}
        <main className="flex-1 min-w-0 p-2">
          <TradingChart data={klines} height={500} />
        </main>

        {/* Sidebar */}
        <aside className="w-72 shrink-0 bg-gray-900/50 border-l border-gray-800 overflow-y-auto p-3">
          <StrategyPanel />

          {/* Signal Log */}
          <div className="mt-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Activity className="h-3 w-3" /> 信号日志
            </h3>
            <div className="space-y-1">
              {signals.length === 0 && (
                <p className="text-[10px] text-gray-600">暂无信号</p>
              )}
              {signals.map((s, i) => (
                <div key={i} className={`p-1.5 rounded text-[10px] border-l-2 ${
                  s.action === 'buy' ? 'border-green-500 bg-green-500/5' :
                  s.action === 'sell' ? 'border-red-500 bg-red-500/5' :
                  s.action === 'close_buy' ? 'border-yellow-500 bg-yellow-500/5' :
                  s.action === 'close_sell' ? 'border-orange-500 bg-orange-500/5' :
                  'border-gray-700'
                }`}>
                  <div className="flex justify-between">
                    <span className="font-mono font-medium">
                      {s.action.toUpperCase()}
                    </span>
                    <span className="text-gray-500">
                      ${s.price.toFixed(2)}
                    </span>
                  </div>
                  {s.reason && (
                    <p className="text-gray-500 mt-0.5 truncate">{s.reason}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
