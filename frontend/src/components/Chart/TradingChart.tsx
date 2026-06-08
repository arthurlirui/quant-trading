import { useEffect, useRef } from 'react';
import {
  createChart, IChartApi, CandlestickData, HistogramData,
  CandlestickSeries, HistogramSeries, createSeriesMarkers,
  type SeriesMarker, type ISeriesMarkersPluginApi,
} from 'lightweight-charts';
import type { Kline } from '../../types';

export interface TradeMarker {
  time: number;          // ms
  side: 'buy' | 'sell';
  price: number;
  quantity?: number;
  text?: string;         // tooltip text
}

interface Props {
  data: Kline[];
  trades?: TradeMarker[];
  height?: number;
}

export default function TradingChart({ data, trades = [], height = 500 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const markerRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);

  // Build chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0a0a14' }, textColor: '#888' },
      grid: {
        vertLines: { color: '#1a1a2e' },
        horzLines: { color: '#1a1a2e' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#555', width: 1, style: 2 },
        horzLine: { color: '#555', width: 1, style: 2 },
      },
      timeScale: { borderColor: '#333', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#333' },
      width: containerRef.current.clientWidth,
      height,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderDownColor: '#ef5350',
      borderUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      wickUpColor: '#26a69a',
    });
    candleSeries.setData(
      data.map((k): CandlestickData => ({
        time: (k.open_time / 1000) as any,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      })),
    );

    // Markers plugin
    markerRef.current = createSeriesMarkers(candleSeries, []);

    // Volume histogram
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeries.setData(
      data.map((k): HistogramData => ({
        time: (k.open_time / 1000) as any,
        value: k.volume,
        color: k.close >= k.open ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)',
      })),
    );

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, height]);

  // Update markers reactively when trades change
  useEffect(() => {
    if (!markerRef.current) return;
    const markers: SeriesMarker<any>[] = trades.map(t => ({
      time: (Math.floor(t.time / 1000)) as any,
      position: t.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: t.side === 'buy' ? '#26a69a' : '#ef5350',
      shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: t.text || `${t.side.toUpperCase()} ${t.quantity ? '×' + t.quantity.toFixed(4) : ''} @ ${t.price.toFixed(2)}`,
    }));
    markerRef.current.setMarkers(markers);
  }, [trades]);

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />;
}
