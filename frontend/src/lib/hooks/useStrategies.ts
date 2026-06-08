/**
 * useStrategies — 统一封装 /strategies + 各 running state
 */
import { useEffect, useState } from 'react';
import { useSWR } from './useSWR';
import type { Strategy } from '../../types';

export interface StrategyWithState extends Strategy {
  running?: boolean;
  live_state?: any;
}

export function useStrategies(opts: { intervalMs?: number | null } = {}) {
  const { data: strategies, loading, refresh, lastUpdated } = useSWR<StrategyWithState[]>(
    '/api/v1/strategies',
    { intervalMs: opts.intervalMs },
  );

  const [states, setStates] = useState<Record<string, any>>({});

  useEffect(() => {
    if (!strategies) return;
    const running = strategies.filter(s => s.running).map(s => s.id);
    // remove states for non-running
    setStates(prev => {
      const next = { ...prev };
      for (const k of Object.keys(next)) {
        if (!running.includes(k)) delete next[k];
      }
      return next;
    });

    // fetch state for each running with concurrency 5
    if (running.length === 0) return;
    let cancelled = false;
    (async () => {
      const queue = [...running];
      const workers = Array.from({ length: Math.min(5, queue.length) }, async () => {
        while (queue.length && !cancelled) {
          const sid = queue.shift()!;
          try {
            const r = await fetch(`/api/v1/strategies/${sid}/state`);
            if (r.ok) {
              const d = await r.json();
              if (!cancelled) setStates(prev => ({ ...prev, [sid]: d }));
            }
          } catch { /* */ }
        }
      });
      await Promise.all(workers);
    })();
    return () => { cancelled = true; };
  }, [strategies, lastUpdated]);

  return {
    strategies: strategies ?? [],
    states,
    loading,
    refresh,
  };
}
