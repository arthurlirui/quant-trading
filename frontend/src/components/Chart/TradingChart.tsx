import { useEffect, useRef } from 'react';
import { createChart, IChartApi, CandlestickData, HistogramData, CandlestickSeries, HistogramSeries } from 'lightweight-charts';
import type { Kline } from '../../types';

interface Props {
  data: Kline[];
  height?: number;
}

export default function TradingChart({ data, height = 500 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0a0a14' },
        textColor: '#888',
      },
      grid: {
        vertLines: { color: '#1a1a2e' },
        horzLines: { color: '#1a1a2e' },
      },
      crosshair: {
        mode: 0,
        vertLine: { color: '#555', width: 1, style: 2 },
        horzLine: { color: '#555', width: 1, style: 2 },
      },
      timeScale: {
        borderColor: '#333',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#333',
      },
      width: containerRef.current.clientWidth,
      height,
    });

    // Candlestick series (v5 API)
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
      }))
    );

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
      }))
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
    };
  }, [data, height]);

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />;
}
