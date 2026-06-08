import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Activity, DollarSign, Layers } from 'lucide-react';
import { api, type MarketSummary } from '../../lib/api';

interface Props {
  symbol: string;
}

export default function FuturesInfoCard({ symbol }: Props) {
  const [data, setData] = useState<MarketSummary | null>(null);

  useEffect(() => {
    let alive = true;
    const fetchOnce = async () => {
      const d = await api.getMarketSummary(symbol);
      if (alive) setData(d);
    };
    fetchOnce();
    const id = setInterval(fetchOnce, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [symbol]);

  if (!data) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded p-3 text-xs text-gray-500">
        加载合约数据中…
      </div>
    );
  }

  const mark = data.futures_mark;
  const fut = data.futures;
  const oi = data.futures_open_interest;
  const spot = data.spot;

  const fundingPct = mark ? (mark.funding_rate * 100).toFixed(4) : '–';
  const fundingClass = mark && mark.funding_rate >= 0 ? 'text-green-400' : 'text-red-400';

  const nextFunding = mark?.next_funding_time
    ? new Date(mark.next_funding_time).toLocaleString('zh-CN', {
        hour: '2-digit', minute: '2-digit', month: '2-digit', day: '2-digit',
      })
    : '–';

  const basis = (() => {
    if (!spot || !mark) return null;
    const diff = mark.mark_price - spot.price;
    const pct = (diff / spot.price) * 100;
    return { diff, pct };
  })();

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded">
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-orange-400 flex items-center gap-1.5">
          <Layers className="h-3 w-3" /> 合约信息 · {symbol}
        </h3>
        <span className="text-[9px] text-gray-600">永续 U本位</span>
      </div>

      <div className="p-3 space-y-2.5 text-xs">
        {/* Mark Price */}
        <Row label={<><DollarSign className="h-3 w-3 inline" /> 标记价</>}>
          <span className="font-mono font-semibold text-white">
            {mark ? `$${mark.mark_price.toFixed(2)}` : '–'}
          </span>
        </Row>

        {/* Index Price */}
        <Row label="指数价">
          <span className="font-mono text-gray-300">
            {mark ? `$${mark.index_price.toFixed(2)}` : '–'}
          </span>
        </Row>

        {/* Basis */}
        {basis && (
          <Row label="基差 (vs 现货)">
            <span className={`font-mono ${basis.diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {basis.diff >= 0 ? '+' : ''}{basis.diff.toFixed(2)} ({basis.pct.toFixed(3)}%)
            </span>
          </Row>
        )}

        <div className="border-t border-gray-800 my-2" />

        {/* Funding Rate */}
        <Row label={<><Activity className="h-3 w-3 inline" /> 资金费率</>}>
          <span className={`font-mono font-semibold ${fundingClass}`}>
            {mark && mark.funding_rate >= 0 ? '+' : ''}{fundingPct}%
          </span>
        </Row>

        {/* Next Funding */}
        <Row label="下次结算">
          <span className="text-gray-300 text-[10px]">{nextFunding}</span>
        </Row>

        <div className="border-t border-gray-800 my-2" />

        {/* Open Interest */}
        <Row label="未平仓位 (BTC)">
          <span className="font-mono text-gray-300">
            {oi ? oi.open_interest.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '–'}
          </span>
        </Row>

        {/* 24h Volume */}
        {fut && (
          <Row label="24h 成交量">
            <span className="font-mono text-gray-300">
              {fut.volume.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          </Row>
        )}

        {fut?.quote_volume && (
          <Row label="24h 成交额 (USDT)">
            <span className="font-mono text-gray-300">
              ${(fut.quote_volume / 1e6).toFixed(1)}M
            </span>
          </Row>
        )}

        <div className="border-t border-gray-800 my-2" />

        {/* 24h Stats */}
        {fut && (
          <>
            <Row label="24h 最高 / 最低">
              <span className="font-mono text-[10px] text-gray-300">
                ${fut.high.toFixed(0)} / ${fut.low.toFixed(0)}
              </span>
            </Row>
            <Row label="24h 涨跌">
              <span className={`font-mono ${fut.change >= 0 ? 'text-green-400' : 'text-red-400'} flex items-center gap-1`}>
                {fut.change >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                {fut.change >= 0 ? '+' : ''}{fut.change_pct.toFixed(2)}%
              </span>
            </Row>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-gray-500">{label}</span>
      {children}
    </div>
  );
}
