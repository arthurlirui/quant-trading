import { useEffect, useRef, useState } from 'react';
import {
  createChart, type IChartApi, type CandlestickData, type HistogramData, type LineData,
  CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers,
  type SeriesMarker, type ISeriesMarkersPluginApi, type ISeriesApi,
} from 'lightweight-charts';
import { Maximize2, Minimize2 } from 'lucide-react';
import type { Kline } from '../../types';
import { ma, ema, rsi } from '../../lib/indicators';

export interface TradeMarker {
  time: number;
  side: 'buy' | 'sell';
  price: number;
  quantity?: number;
  text?: string;
}

export type Interval = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';
const INTERVALS: Interval[] = ['1m', '5m', '15m', '1h', '4h', '1d'];

export interface IndicatorConfig {
  ma?: number[];
  ema?: number[];
  rsi?: boolean;
}

interface Props {
  data: Kline[];
  trades?: TradeMarker[];
  height?: number;
  interval: Interval;
  onIntervalChange: (i: Interval) => void;
  indicators?: IndicatorConfig;
  onIndicatorsChange?: (next: IndicatorConfig) => void;
}

interface Hover {
  o: number; h: number; l: number; c: number; v: number;
  changePct: number; time: number; x: number; y: number;
}

export default function TradingChart({
  data, trades = [], height = 500,
  interval, onIntervalChange,
  indicators = { ma: [20], ema: [50], rsi: false },
  onIndicatorsChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const markerRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const indicatorSeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
  const followRef = useRef(true);
  const [hover, setHover] = useState<Hover | null>(null);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!chartContainerRef.current) return;
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: '#0a0a14' }, textColor: '#888' },
      grid: { vertLines: { color: '#1a1a2e' }, horzLines: { color: '#1a1a2e' } },
      crosshair: { mode: 0,
        vertLine: { color: '#555', width: 1, style: 2 },
        horzLine: { color: '#555', width: 1, style: 2 } },
      timeScale: { borderColor: '#333', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#333' },
      width: chartContainerRef.current.clientWidth,
      height,
    });

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350',
      borderDownColor: '#ef5350', borderUpColor: '#26a69a',
      wickDownColor: '#ef5350', wickUpColor: '#26a69a',
    });
    candle.setData(data.map((k): CandlestickData => ({
      time: (k.open_time / 1000) as any,
      open: k.open, high: k.high, low: k.low, close: k.close,
    })));
    candleRef.current = candle;
    markerRef.current = createSeriesMarkers(candle, []);

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volume.setData(data.map((k): HistogramData => ({
      time: (k.open_time / 1000) as any,
      value: k.volume,
      color: k.close >= k.open ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)',
    })));
    volumeRef.current = volume;
    chartRef.current = chart;

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point || !candleRef.current) { setHover(null); return; }
      const cd = param.seriesData.get(candleRef.current) as CandlestickData | undefined;
      const vd = volumeRef.current ? param.seriesData.get(volumeRef.current) as HistogramData | undefined : undefined;
      if (!cd) { setHover(null); return; }
      const changePct = cd.open ? ((cd.close - cd.open) / cd.open) * 100 : 0;
      setHover({
        o: cd.open, h: cd.high, l: cd.low, c: cd.close,
        v: vd ? vd.value : 0,
        changePct,
        time: (cd.time as number) * 1000,
        x: param.point.x, y: param.point.y,
      });
    });

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range) return;
      const last = data.length - 1;
      followRef.current = range.to >= last - 1;
    });

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: fullscreen ? window.innerHeight - 80 : height,
        });
      }
    };
    window.addEventListener('resize', handleResize);
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      indicatorSeriesRef.current.clear();
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, height, fullscreen]);

  useEffect(() => {
    if (!markerRef.current) return;
    const markers: SeriesMarker<any>[] = trades.map(t => ({
      time: (Math.floor(t.time / 1000)) as any,
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? '#26a69a' : '#ef5350',
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: t.text || `${t.side.toUpperCase()} @ ${t.price.toFixed(2)}`,
    }));
    markerRef.current.setMarkers(markers);
  }, [trades]);

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;
    const chart = chartRef.current;
    indicatorSeriesRef.current.forEach((s) => { try { chart.removeSeries(s); } catch { /* */ } });
    indicatorSeriesRef.current.clear();

    const palette = ['#3b82f6', '#a855f7', '#eab308', '#22d3ee', '#f97316'];
    let i = 0;
    for (const p of indicators.ma || []) {
      const s = chart.addSeries(LineSeries, {
        color: palette[i++ % palette.length], lineWidth: 1, title: `MA${p}`,
      });
      s.setData(ma(data, p) as LineData[]);
      indicatorSeriesRef.current.set(`MA${p}`, s);
    }
    for (const p of indicators.ema || []) {
      const s = chart.addSeries(LineSeries, {
        color: palette[i++ % palette.length], lineWidth: 1, title: `EMA${p}`, lineStyle: 1,
      });
      s.setData(ema(data, p) as LineData[]);
      indicatorSeriesRef.current.set(`EMA${p}`, s);
    }
    if (indicators.rsi) {
      const s = chart.addSeries(LineSeries, {
        color: '#fbbf24', lineWidth: 1, title: 'RSI14',
        priceScaleId: 'rsi',
      });
      chart.priceScale('rsi').applyOptions({ scaleMargins: { top: 0.7, bottom: 0.15 } });
      s.setData(rsi(data, 14) as LineData[]);
      indicatorSeriesRef.current.set('RSI', s);
    }
  }, [data, indicators]);

  useEffect(() => {
    if (followRef.current && chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [data.length]);

  const toggleMA = (n: number) => {
    if (!onIndicatorsChange) return;
    const cur = indicators.ma || [];
    onIndicatorsChange({ ...indicators, ma: cur.includes(n) ? cur.filter(x => x !== n) : [...cur, n] });
  };
  const toggleEMA = (n: number) => {
    if (!onIndicatorsChange) return;
    const cur = indicators.ema || [];
    onIndicatorsChange({ ...indicators, ema: cur.includes(n) ? cur.filter(x => x !== n) : [...cur, n] });
  };
  const toggleRSI = () => onIndicatorsChange?.({ ...indicators, rsi: !indicators.rsi });

  return (
    <div ref={containerRef} className={`relative ${fullscreen ? 'fixed inset-0 z-50 bg-gray-950 p-2' : ''}`}>
      <div className="flex items-center justify-between mb-1.5 px-1">
        <div className="flex items-center gap-1 bg-gray-900/60 rounded p-0.5">
          {INTERVALS.map(iv => (
            <button
              key={iv}
              onClick={() => onIntervalChange(iv)}
              className={`px-2 py-0.5 text-[10px] rounded transition ${
                interval === iv ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >{iv}</button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <IndChip active={!!indicators.ma?.includes(20)} onClick={() => toggleMA(20)} label="MA20" color="text-blue-400" />
          <IndChip active={!!indicators.ema?.includes(50)} onClick={() => toggleEMA(50)} label="EMA50" color="text-purple-400" />
          <IndChip active={!!indicators.rsi} onClick={toggleRSI} label="RSI" color="text-yellow-400" />
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="p-1 hover:bg-gray-800 rounded text-gray-400"
            title={fullscreen ? "Exit" : "Full"}>
            {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <div className="relative">
        <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden" />

        {hover && (
          <div
            className="absolute pointer-events-none bg-gray-900/95 backdrop-blur border border-gray-700 rounded px-2 py-1 text-[10px] font-mono text-gray-200 shadow-lg z-10"
            style={{ left: 8, top: 8 }}
          >
            <div className="text-gray-500 text-[9px]">
              {new Date(hover.time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
            </div>
            <div className="flex gap-2 mt-0.5">
              <span>O <span className="text-white">{hover.o.toFixed(2)}</span></span>
              <span>H <span className="text-green-400">{hover.h.toFixed(2)}</span></span>
              <span>L <span className="text-red-400">{hover.l.toFixed(2)}</span></span>
              <span>C <span className="text-white">{hover.c.toFixed(2)}</span></span>
            </div>
            <div className="flex gap-2 mt-0.5">
              <span>V <span className="text-blue-400">{hover.v.toFixed(2)}</span></span>
              <span className={hover.changePct >= 0 ? 'text-green-400' : 'text-red-400'}>
                {hover.changePct >= 0 ? '+' : ''}{hover.changePct.toFixed(2)}%
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function IndChip({ active, onClick, label, color }: {
  active: boolean; onClick: () => void; label: string; color: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-1.5 py-0.5 text-[10px] rounded border transition ${
        active ? `${color} border-current bg-current/10` : 'text-gray-500 border-gray-700 hover:border-gray-500'
      }`}
    >
      {label}
    </button>
  );
}
