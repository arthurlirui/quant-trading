import { useState, useEffect } from 'react';
import { Download, Database, ChevronDown, ChevronUp, Clock, BarChart3, RefreshCw, CheckCircle, XCircle } from 'lucide-react';
import type { MarketDownloadResult, MarketDataStat, MarketDataQuery } from '../../types';

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'DOGEUSDT'];
const INTERVALS = [
  { label: '1m', value: '1m' },
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '30m', value: '30m' },
  { label: '1h', value: '1h' },
  { label: '4h', value: '4h' },
  { label: '1d', value: '1d' },
];
const LIMITS = [
  { label: '100', value: 100 },
  { label: '500', value: 500 },
  { label: '1000', value: 1000 },
];

export default function DataDownloadPanel() {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setInterval] = useState('1m');
  const [limit, setLimit] = useState(500);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<MarketDownloadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<MarketDataStat[]>([]);
  const [statsOpen, setStatsOpen] = useState(false);
  const [preview, setPreview] = useState<MarketDataQuery | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Load stats on mount
  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/v1/market/data/stats');
      if (res.ok) setStats(await res.json());
    } catch { /* */ }
  };

  const downloadData = async () => {
    setDownloading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch('/api/v1/market/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, interval, limit }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
      await fetchStats();
      await loadPreview();
    } catch (e) {
      setError('请求失败: ' + (e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  const loadPreview = async () => {
    setPreviewLoading(true);
    try {
      const res = await fetch(`/api/v1/market/data?symbol=${symbol}&interval=${interval}&limit=5`);
      if (res.ok) setPreview(await res.json());
    } catch { /* */ }
    setPreviewLoading(false);
  };

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleString('zh-CN', { hour12: false });
  };

  const totalDownloaded = stats.reduce((acc, s) => acc + s.count, 0);

  return (
    <div className="space-y-3">
      {/* Header */}
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
        <Database className="h-3 w-3" /> 市场数据下载
      </h3>

      {/* Controls */}
      <div className="rounded-lg bg-gray-900/50 border border-gray-800 p-3 space-y-3">
        {/* Symbol + Interval */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-gray-500 uppercase tracking-wider block mb-1">交易对</label>
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
            >
              {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-gray-500 uppercase tracking-wider block mb-1">周期</label>
            <select
              value={interval}
              onChange={e => setInterval(e.target.value)}
              className="w-full bg-gray-950 border border-gray-700 rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
            >
              {INTERVALS.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
            </select>
          </div>
        </div>

        {/* Limit */}
        <div>
          <label className="text-[10px] text-gray-500 uppercase tracking-wider block mb-1">条数</label>
          <div className="flex gap-1">
            {LIMITS.map(l => (
              <button
                key={l.value}
                onClick={() => setLimit(l.value)}
                className={`flex-1 py-1.5 rounded text-xs font-medium transition ${
                  limit === l.value
                    ? 'bg-blue-600/30 text-blue-400 border border-blue-500/30'
                    : 'bg-gray-950 text-gray-500 border border-gray-700 hover:border-gray-600'
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        {/* Download button */}
        <button
          onClick={downloadData}
          disabled={downloading}
          className="w-full py-2 rounded-lg text-xs font-medium transition flex items-center justify-center gap-2 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 text-blue-400 disabled:opacity-50"
        >
          {downloading ? (
            <>
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              下载中...
            </>
          ) : (
            <>
              <Download className="h-3.5 w-3.5" />
              下载并保存到数据库
            </>
          )}
        </button>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-1.5 text-[10px] text-red-400">
            <XCircle className="h-3 w-3" />
            {error}
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="bg-gray-950/50 rounded p-2 space-y-1">
            <div className="flex items-center gap-1.5 text-green-400 text-[10px] mb-1">
              <CheckCircle className="h-3 w-3" />
              下载完成
            </div>
            <InfoRow label="新增记录" value={`${result.downloaded}`} />
            <InfoRow label="跳过重复" value={`${result.skipped}`} />
            {result.range && (
              <>
                <InfoRow label="数据范围" value={`${result.range.count} 根`} />
                <InfoRow label="起始时间" value={formatTime(result.range.from)} />
                <InfoRow label="结束时间" value={formatTime(result.range.to)} />
              </>
            )}
          </div>
        )}
      </div>

      {/* Preview */}
      <div>
        <button
          onClick={() => { setStatsOpen(!statsOpen); if (!statsOpen) loadPreview(); }}
          className="flex items-center justify-between w-full text-[10px] text-gray-500 uppercase tracking-wider mb-1"
        >
          <span className="flex items-center gap-1">
            <BarChart3 className="h-3 w-3" /> 数据预览
          </span>
          {statsOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>

        {statsOpen && (
          <div className="rounded-lg bg-gray-900/50 border border-gray-800 p-2">
            {previewLoading ? (
              <div className="flex items-center justify-center py-3">
                <RefreshCw className="h-3.5 w-3.5 text-gray-600 animate-spin" />
              </div>
            ) : preview && preview.data.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-[10px] font-mono">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-800">
                      <th className="text-left py-1 pr-2">时间</th>
                      <th className="text-right px-1">开</th>
                      <th className="text-right px-1">高</th>
                      <th className="text-right px-1">低</th>
                      <th className="text-right px-1">收</th>
                      <th className="text-right pl-1">量</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.data.map((k, i) => (
                      <tr key={i} className="border-b border-gray-800/50">
                        <td className="py-1 pr-2 text-gray-500">{formatTime(k.open_time).slice(5, -3)}</td>
                        <td className="text-right px-1">{k.open.toFixed(2)}</td>
                        <td className="text-right px-1 text-green-400">{k.high.toFixed(2)}</td>
                        <td className="text-right px-1 text-red-400">{k.low.toFixed(2)}</td>
                        <td className="text-right px-1">{k.close.toFixed(2)}</td>
                        <td className="text-right pl-1 text-gray-500">{k.volume.toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[10px] text-gray-600 text-center py-2">暂无数据，先下载试试</p>
            )}

            {/* Stats */}
            {stats.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-800">
                <p className="text-[10px] text-gray-500 mb-1">已保存数据统计</p>
                <div className="space-y-0.5">
                  {stats.map((st, i) => (
                    <div key={i} className="flex items-center justify-between text-[10px]">
                      <span className="text-gray-400">{st.symbol} ({st.interval})</span>
                      <span className="text-gray-500 font-mono">{st.count} 根</span>
                    </div>
                  ))}
                  <div className="flex items-center justify-between text-[10px] pt-1 border-t border-gray-800">
                    <span className="text-gray-300">总计</span>
                    <span className="text-white font-mono">{totalDownloaded} 根</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-[10px]">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-300 font-mono">{value}</span>
    </div>
  );
}
