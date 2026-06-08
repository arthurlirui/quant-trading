import { Radio } from 'lucide-react';
import RefreshControl from './RefreshControl';
import { useRefresh } from '../context/RefreshContext';

interface Props {
  wsStatus: 'connecting' | 'open' | 'closed' | 'error';
  wsRetries: number;
  marketMode: 'spot' | 'futures';
  testnet?: boolean;
  version?: string;
}

export default function StatusBar({ wsStatus, wsRetries, marketMode, testnet, version }: Props) {
  const ctx = useRefresh();

  const wsLabel = wsStatus === 'open' ? '实时'
    : wsStatus === 'connecting' ? '连接中…'
    : wsStatus === 'error' ? '错误'
    : marketMode === 'futures' ? '轮询' : '断连';

  const wsColor = wsStatus === 'open' ? 'text-green-400'
    : wsStatus === 'connecting' ? 'text-yellow-400'
    : marketMode === 'futures' ? 'text-orange-400'
    : 'text-red-400';

  return (
    <div className="flex items-center justify-between px-4 py-1 border-t border-gray-800 bg-gray-900/80 text-[10px] shrink-0">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <Radio className={`h-3 w-3 ${wsColor}`} />
          <span className={wsColor}>{wsLabel}</span>
          {wsStatus !== 'open' && wsRetries > 0 && (
            <span className="text-gray-600">(重试 #{wsRetries})</span>
          )}
        </div>
        {ctx.paused && (
          <span className="px-1.5 py-0.5 bg-yellow-500/20 text-yellow-300 rounded text-[9px]">
            ⏸ 已暂停
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <RefreshControl />
        <span className="text-gray-600">|</span>
        <span className="text-gray-500">
          {testnet ? '测试网' : '主网'}
          {version && ` · v${version}`}
        </span>
      </div>
    </div>
  );
}
