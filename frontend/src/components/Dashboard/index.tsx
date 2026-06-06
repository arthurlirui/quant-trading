import { LayoutDashboard } from 'lucide-react';
import StrategyMonitor from './StrategyMonitor';
import DataDownloadPanel from './DataDownloadPanel';

export default function Dashboard() {
  return (
    <div className="flex-1 flex gap-0.5 overflow-hidden">
      {/* Left Column: Strategy Monitor */}
      <main className="flex-1 min-w-0 p-3 overflow-y-auto">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center gap-2 mb-4">
            <LayoutDashboard className="h-4 w-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-white">策略仪表盘</h2>
            <span className="text-[10px] text-gray-600">实时监控 · 每秒刷新</span>
          </div>

          {/* Quick Status Cards */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            <QuickStatCard
              label="策略"
              value="监控中"
              sub="运行状态"
              color="text-green-400"
            />
            <QuickStatCard
              label="数据"
              value="本地数据库"
              sub="SQLite"
              color="text-blue-400"
            />
            <QuickStatCard
              label="模式"
              value="测试网"
              sub="Binance"
              color="text-yellow-400"
            />
          </div>

          <StrategyMonitor />
        </div>
      </main>

      {/* Right Column: Data Download */}
      <aside className="w-80 shrink-0 bg-gray-900/50 border-l border-gray-800 overflow-y-auto p-3">
        <DataDownloadPanel />
      </aside>
    </div>
  );
}

function QuickStatCard({ label, value, sub, color }: {
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="rounded-lg bg-gray-900/50 border border-gray-800 p-3 text-center">
      <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xs font-semibold ${color}`}>{value}</p>
      <p className="text-[9px] text-gray-600 mt-0.5">{sub}</p>
    </div>
  );
}
