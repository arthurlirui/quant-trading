import { useState, useEffect, useRef, useMemo } from 'react';
import { TrendingUp, Activity, Radio, LayoutDashboard, BarChart3, Globe } from 'lucide-react';
import TradingChart, { type TradeMarker } from './components/Chart/TradingChart';
import TickerBar from './components/Chart/TickerBar';
import MarketSelector from './components/Market/MarketSelector';
import FuturesInfoCard from './components/Market/FuturesInfoCard';
import MarketOverview from './components/Market/MarketOverview';
import StrategyPanel from './components/Trading/StrategyPanel';
import TradeHistory, { type TradeRecord } from './components/Trading/TradeHistory';
import Dashboard from './components/Dashboard';
import { api } from './lib/api';
import type { Kline, Signal, ViewMode, MarketType } from './types';

export default function App() {
  const [klines, setKlines] = useState<Kline[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [status, setStatus] = useState<any>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [view, setView] = useState<ViewMode>('trading');
  const [market, setMarket] = useState<MarketType>('spot');
  const [symbol, setSymbol] = useState<string>('BTCUSDT');
  const wsRef = useRef<WebSocket | null>(null);

  // status (once)
  useEffect(() => {
    fetch('/api/v1/status').then(r => r.json()).then(setStatus).catch(() => {});
  }, []);

  // klines + ws when symbol/market changes
  useEffect(() => {
    setKlines([]);
    api.getKlines(symbol, '1m', 200, market).then(setKlines);

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (market === 'spot') {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${protocol}//${location.host}/api/v1/ws/market/${symbol}`);
      wsRef.current = ws;
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => setWsConnected(false);
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'kline' && msg.data.symbol === symbol) {
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
    } else {
      setWsConnected(false);
      const id = setInterval(async () => {
        const fresh = await api.getKlines(symbol, '1m', 200, 'futures');
        if (fresh.length) setKlines(fresh);
      }, 5000);
      return () => clearInterval(id);
    }
  }, [symbol, market]);

  // 把 trades 转成 chart markers (只过滤当前 symbol)
  const tradeMarkers: TradeMarker[] = useMemo(() => {
    return trades
      .filter(t => t.symbol === symbol && t.created_at)
      .map(t => ({
        time: new Date(t.created_at!).getTime(),
        side: t.side,
        price: t.price,
        quantity: t.quantity,
        text: `${t.side.toUpperCase()} ${t.quantity.toFixed(4)} @ ${t.price.toFixed(2)}`,
      }));
  }, [trades, symbol]);

  return (
    <div className="h-screen w-screen flex flex-col bg-gray-950 text-white overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-900/80 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green-500 to-blue-600 flex items-center justify-center">
            <TrendingUp className="h-4 w-4" />
          </div>
          <span className="font-semibold text-sm">Quant <span className="text-green-400">Trading</span></span>
          <span className="text-[10px] text-gray-500">v0.2.0</span>
        </div>

        <div className="flex-1 flex justify-center">
          <MarketSelector
            market={market}
            symbol={symbol}
            onMarketChange={setMarket}
            onSymbolChange={setSymbol}
          />
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[11px]">
            <Radio className={`h-3 w-3 ${wsConnected ? 'text-green-400' : market === 'futures' ? 'text-yellow-400' : 'text-red-400'}`} />
            <span className={wsConnected ? 'text-green-400' : market === 'futures' ? 'text-yellow-400' : 'text-red-400'}>
              {market === 'futures' ? '轮询' : wsConnected ? '实时' : '断连'}
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
      <TickerBar market={market} />

      {/* Navigation Tabs */}
      <div className="flex items-center gap-0 px-4 border-b border-gray-800 bg-gray-900/50 shrink-0">
        <NavTab active={view === 'trading'} onClick={() => setView('trading')}
          icon={<BarChart3 className="h-3.5 w-3.5" />} label="交易" />
        <NavTab active={view === 'market'} onClick={() => setView('market')}
          icon={<Globe className="h-3.5 w-3.5" />} label="市场" />
        <NavTab active={view === 'dashboard'} onClick={() => setView('dashboard')}
          icon={<LayoutDashboard className="h-3.5 w-3.5" />} label="仪表盘" />
      </div>

      {/* Main Content */}
      {view === 'trading' ? (
        <div className="flex-1 flex gap-0.5 overflow-hidden">
          {/* Chart + TradeHistory */}
          <main className="flex-1 min-w-0 p-2 overflow-y-auto space-y-2">
            <TradingChart data={klines} trades={tradeMarkers} height={460} />
            <TradeHistory
              symbolFilter={symbol}
              onTradesLoaded={setTrades}
            />
          </main>

          {/* Sidebar */}
          <aside className="w-72 shrink-0 bg-gray-900/50 border-l border-gray-800 overflow-y-auto p-3 space-y-3">
            {market === 'futures' && <FuturesInfoCard symbol={symbol} />}

            <StrategyPanel />

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
                      <span className="font-mono font-medium">{s.action.toUpperCase()}</span>
                      <span className="text-gray-500">${s.price.toFixed(2)}</span>
                    </div>
                    {s.reason && <p className="text-gray-500 mt-0.5 truncate">{s.reason}</p>}
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      ) : view === 'market' ? (
        <MarketOverview />
      ) : (
        <Dashboard />
      )}
    </div>
  );
}

function NavTab({ active, onClick, icon, label }: {
  active: boolean; onClick: () => void; icon: React.ReactNode; label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-4 py-2 text-xs font-medium transition border-b-2 ${
        active
          ? 'text-blue-400 border-blue-500 bg-gray-800/30'
          : 'text-gray-500 border-transparent hover:text-gray-300 hover:border-gray-600'
      }`}
    >
      {icon} {label}
    </button>
  );
}
