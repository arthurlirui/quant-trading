import { useState, useEffect, useMemo } from 'react';
import { TrendingUp, Activity, LayoutDashboard, BarChart3, Globe } from 'lucide-react';
import TradingChart, { type TradeMarker, type Interval, type IndicatorConfig } from './components/Chart/TradingChart';
import TickerBar from './components/Chart/TickerBar';
import MarketSelector from './components/Market/MarketSelector';
import FuturesInfoCard from './components/Market/FuturesInfoCard';
import MarketOverview from './components/Market/MarketOverview';
import StrategyPanel from './components/Trading/StrategyPanel';
import TradeHistory, { type TradeRecord } from './components/Trading/TradeHistory';
import Dashboard from './components/Dashboard';
import StatusBar from './components/StatusBar';
import { useSWR } from './lib/hooks/useSWR';
import { useWebSocket } from './lib/hooks/useWebSocket';
import { useResponsive } from './lib/hooks/useResponsive';
import type { Kline, Signal, ViewMode, MarketType } from './types';

export default function App() {
  const [view, setView] = useState<ViewMode>('trading');
  const [market, setMarket] = useState<MarketType>('spot');
  const [symbol, setSymbol] = useState<string>('BTCUSDT');
  const [interval, setInterval_] = useState<Interval>('1m');
  const [indicators, setIndicators] = useState<IndicatorConfig>({ ma: [20], ema: [50], rsi: false });
  const [signals, setSignals] = useState<Signal[]>([]);
  const [wsKlines, setWsKlines] = useState<Kline[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const isNarrow = useResponsive();

  // status (auto refresh via useSWR)
  const { data: status } = useSWR<any>('/api/v1/status', { intervalMs: 30000 });

  // klines via REST (poll + initial); WS will append/update on top
  const klinesKey = `/api/v1/market/klines/${symbol}?interval=${interval}&limit=200&market=${market}`;
  const { data: restKlines = [] } = useSWR<Kline[]>(klinesKey);

  // Spot 1m only -> use WS for real-time updates; other timeframes/markets use polling only
  const useWs = market === 'spot' && interval === '1m';
  const wsUrl = useWs
    ? `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws/market/${symbol}`
    : null;

  const ws = useWebSocket(wsUrl, {
    enabled: useWs,
    onMessage: (msg: any) => {
      if (msg.type === 'kline' && msg.data.symbol === symbol) {
        const k = msg.data as Kline;
        setWsKlines(prev => {
          const i = prev.findIndex(p => p.open_time === k.open_time);
          if (i >= 0) {
            const next = [...prev];
            next[i] = k;
            return next;
          }
          return [...prev.slice(-200), k];
        });
      } else if (msg.type === 'signal') {
        setSignals(prev => [msg.data, ...prev].slice(0, 50));
      }
    },
  });

  // Reset ws klines when symbol/interval/market changes
  useEffect(() => {
    setWsKlines([]);
  }, [symbol, interval, market]);

  // Merge REST + WS klines (WS takes precedence at the tail)
  const klines = useMemo<Kline[]>(() => {
    if (!useWs || wsKlines.length === 0) return restKlines;
    const byTime = new Map<number, Kline>();
    for (const k of restKlines) byTime.set(k.open_time, k);
    for (const k of wsKlines) byTime.set(k.open_time, k);
    return Array.from(byTime.values()).sort((a, b) => a.open_time - b.open_time).slice(-200);
  }, [restKlines, wsKlines, useWs]);

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
      {/* Top bar — slimmed */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-gray-800 bg-gray-900/80 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green-500 to-blue-600 flex items-center justify-center">
            <TrendingUp className="h-4 w-4" />
          </div>
          <span className="font-semibold text-sm">Quant <span className="text-green-400">Trading</span></span>
        </div>

        <div className="flex-1 flex justify-center">
          <MarketSelector
            market={market}
            symbol={symbol}
            onMarketChange={setMarket}
            onSymbolChange={setSymbol}
          />
        </div>

        <div className="w-32" />
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
      <div className="flex-1 overflow-hidden flex flex-col">
        {view === 'trading' ? (
          <div className={`flex-1 gap-0.5 overflow-hidden ${isNarrow ? 'flex flex-col' : 'flex'}`}>
            <main className={`min-w-0 p-2 overflow-y-auto space-y-2 ${isNarrow ? 'flex-1' : 'flex-1'}`}>
              <TradingChart
                data={klines}
                trades={tradeMarkers}
                height={460}
                interval={interval}
                onIntervalChange={setInterval_}
                indicators={indicators}
                onIndicatorsChange={setIndicators}
              />
              <TradeHistory
                symbolFilter={symbol}
                onTradesLoaded={setTrades}
              />
            </main>

            <aside className={`${isNarrow ? 'w-full max-h-72' : 'w-72'} shrink-0 bg-gray-900/50 ${isNarrow ? 'border-t' : 'border-l'} border-gray-800 overflow-y-auto p-3 space-y-3`}>
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

      {/* Bottom Status Bar */}
      <StatusBar
        wsStatus={ws.status}
        wsRetries={ws.retries}
        marketMode={market}
        testnet={status?.testnet}
        version={status?.version}
      />
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
