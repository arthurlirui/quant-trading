/**
 * 技术指标计算（纯函数）
 */
import type { Kline } from '../types';

export interface PointVal {
  time: number; // unix seconds
  value: number;
}

/** Simple Moving Average */
export function ma(klines: Kline[], period: number): PointVal[] {
  if (period <= 0) return [];
  const result: PointVal[] = [];
  let sum = 0;
  for (let i = 0; i < klines.length; i++) {
    sum += klines[i].close;
    if (i >= period) sum -= klines[i - period].close;
    if (i >= period - 1) {
      result.push({ time: Math.floor(klines[i].open_time / 1000), value: sum / period });
    }
  }
  return result;
}

/** Exponential Moving Average */
export function ema(klines: Kline[], period: number): PointVal[] {
  if (period <= 0 || klines.length === 0) return [];
  const k = 2 / (period + 1);
  const result: PointVal[] = [];
  let prev = klines[0].close;
  for (let i = 0; i < klines.length; i++) {
    const v = klines[i].close * k + prev * (1 - k);
    prev = v;
    if (i >= period - 1) {
      result.push({ time: Math.floor(klines[i].open_time / 1000), value: v });
    }
  }
  return result;
}

/** RSI(period) */
export function rsi(klines: Kline[], period = 14): PointVal[] {
  if (klines.length <= period) return [];
  const result: PointVal[] = [];
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = klines[i].close - klines[i - 1].close;
    if (diff > 0) avgGain += diff; else avgLoss -= diff;
  }
  avgGain /= period;
  avgLoss /= period;
  for (let i = period + 1; i < klines.length; i++) {
    const diff = klines[i].close - klines[i - 1].close;
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    const v = 100 - 100 / (1 + rs);
    result.push({ time: Math.floor(klines[i].open_time / 1000), value: v });
  }
  return result;
}

/** MACD(fast,slow,signal) */
export interface MACDResult {
  dif: PointVal[];
  dea: PointVal[];
  hist: PointVal[];
}
export function macd(klines: Kline[], fast = 12, slow = 26, signal = 9): MACDResult {
  if (klines.length === 0) return { dif: [], dea: [], hist: [] };
  // EMAs on full close array
  const closes = klines.map(k => k.close);
  function _ema(arr: number[], period: number): number[] {
    const k = 2 / (period + 1);
    const out: number[] = [];
    let prev = arr[0];
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i] * k + prev * (1 - k);
      prev = v;
      out.push(v);
    }
    return out;
  }
  const emaFast = _ema(closes, fast);
  const emaSlow = _ema(closes, slow);
  const difArr = closes.map((_, i) => emaFast[i] - emaSlow[i]);
  const deaArr = _ema(difArr, signal);
  const dif: PointVal[] = [], dea: PointVal[] = [], hist: PointVal[] = [];
  for (let i = slow - 1; i < klines.length; i++) {
    const t = Math.floor(klines[i].open_time / 1000);
    dif.push({ time: t, value: difArr[i] });
    dea.push({ time: t, value: deaArr[i] });
    hist.push({ time: t, value: (difArr[i] - deaArr[i]) * 2 });
  }
  return { dif, dea, hist };
}
