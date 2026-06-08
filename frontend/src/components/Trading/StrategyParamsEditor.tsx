import { useEffect, useState } from 'react';
import { Settings, Save, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import type { Strategy, StrategyMeta } from '../../types';

interface Props {
  strategy: Strategy & { live_state?: any; running?: boolean };
  meta?: StrategyMeta;
  onUpdated?: () => void;
}

/**
 * Strategy 参数编辑器 — 展开 / 修改 / 保存
 */
export default function StrategyParamsEditor({ strategy, meta, onUpdated }: Props) {
  const [open, setOpen] = useState(false);
  const [params, setParams] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // 初始化参数：优先 strategy.params (JSON)，回退 meta.default_params
  useEffect(() => {
    let raw: Record<string, any> = {};
    try {
      raw = strategy.params ? JSON.parse(strategy.params) : {};
    } catch { /* */ }
    const defaults = meta?.default_params || {};
    setParams({ ...defaults, ...raw });
    setDirty(false);
  }, [strategy.id, strategy.params, meta?.id]);

  const setParam = (k: string, v: any) => {
    setParams(prev => ({ ...prev, [k]: v }));
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      await fetch(`/api/v1/strategies/${strategy.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ params }),
      });
      setDirty(false);
      onUpdated?.();
    } finally {
      setSaving(false);
    }
  };

  const entries = Object.entries(params);

  return (
    <div className="border-t border-gray-800/60">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-2 py-1.5 text-[10px] text-gray-400 hover:bg-gray-800/40 transition"
      >
        <span className="flex items-center gap-1">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <Settings className="h-3 w-3" /> 参数 ({entries.length})
        </span>
        {dirty && <span className="text-yellow-400">未保存</span>}
      </button>

      {open && (
        <div className="px-2 py-2 space-y-1.5 bg-gray-950/40">
          {entries.length === 0 && (
            <p className="text-[10px] text-gray-600">无参数</p>
          )}
          {entries.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2">
              <label className="text-[10px] text-gray-500 w-32 truncate" title={k}>{k}</label>
              {typeof v === 'boolean' ? (
                <input
                  type="checkbox"
                  checked={v}
                  onChange={e => setParam(k, e.target.checked)}
                  className="accent-blue-500"
                />
              ) : (
                <input
                  type="number"
                  step="any"
                  value={v}
                  onChange={e => {
                    const n = e.target.value === '' ? '' : Number(e.target.value);
                    setParam(k, Number.isNaN(n as number) ? e.target.value : n);
                  }}
                  className="flex-1 bg-gray-900 border border-gray-700 rounded px-1.5 py-0.5 text-[10px] font-mono text-white focus:outline-none focus:border-blue-500"
                />
              )}
            </div>
          ))}
          {dirty && (
            <button
              onClick={save}
              disabled={saving}
              className="w-full mt-2 py-1 bg-blue-600/30 hover:bg-blue-600/50 border border-blue-500/40 rounded text-[10px] font-medium text-blue-300 transition disabled:opacity-50 flex items-center justify-center gap-1"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
              {saving ? '保存中…' : '保存参数'}
            </button>
          )}
          {strategy.running && (
            <p className="text-[9px] text-yellow-500/80 italic mt-1">
              💡 参数修改对运行中策略立即生效
            </p>
          )}
        </div>
      )}
    </div>
  );
}
