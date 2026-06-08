import { Pause, Play, RefreshCw, Zap } from 'lucide-react';
import { useRefresh, type RefreshMode } from '../context/RefreshContext';

const MODES: { mode: RefreshMode; label: string; icon?: React.ReactNode }[] = [
  { mode: 'realtime', label: '实时', icon: <Zap className="h-2.5 w-2.5" /> },
  { mode: '5s', label: '5s' },
  { mode: '30s', label: '30s' },
  { mode: 'paused', label: '暂停', icon: <Pause className="h-2.5 w-2.5" /> },
];

export default function RefreshControl() {
  const { mode, setMode, refreshNow } = useRefresh();

  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] text-gray-500 mr-1">刷新</span>
      <div className="flex items-center bg-gray-800/60 rounded p-0.5 gap-0.5">
        {MODES.map(m => (
          <button
            key={m.mode}
            onClick={() => setMode(m.mode)}
            className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded transition ${
              mode === m.mode
                ? m.mode === 'paused' ? 'bg-yellow-500/30 text-yellow-200' :
                  m.mode === 'realtime' ? 'bg-green-500/30 text-green-200' :
                  'bg-blue-500/30 text-blue-200'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {m.icon}
            {m.label}
          </button>
        ))}
      </div>
      <button
        onClick={refreshNow}
        className="p-1 hover:bg-gray-800 rounded text-gray-400 hover:text-white"
        title="立即刷新 (R)"
      >
        <RefreshCw className="h-3 w-3" />
      </button>
    </div>
  );
}
