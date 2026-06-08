/**
 * useSWR — 轻量数据 fetching hook，原生实现，无外部依赖
 *
 * 功能：
 * - 受 RefreshContext 统一控制刷新频率
 * - 同 key 并发请求合并
 * - AbortController 在 key 变化/unmount 时取消
 * - 失败退避 1→2→4→8s 上限
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefresh } from '../../context/RefreshContext';

export interface UseSWROptions<T> {
  /** 覆盖全局刷新频率（ms）；undefined = 跟随 RefreshContext */
  intervalMs?: number | null;
  /** 是否在 paused 时也跑（极少用） */
  ignorePause?: boolean;
  /** false 时不发请求 */
  enabled?: boolean;
  /** 反序列化（默认 r => r.json()） */
  parser?: (r: Response) => Promise<T>;
  /** key 变化时是否清掉旧数据；默认 true */
  clearOnKeyChange?: boolean;
  /** 静默错误（不 setError，只 console.warn）；默认 false */
  silent?: boolean;
  /** realtime 模式下的兜底周期；默认 0 = 不兜底 */
  realtimeFallbackMs?: number;
}

export interface UseSWRResult<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  fetching: boolean;
  lastUpdated: number | null;
  refresh: () => Promise<void>;
}

interface CacheEntry<T> {
  data?: T;
  ts: number;
  inflight: Promise<T> | null;
  refCount: number;
  evictTimer: ReturnType<typeof setTimeout> | null;
}

const cache = new Map<string, CacheEntry<any>>();
const EVICT_DELAY_MS = 30_000;

async function dedupedFetch<T>(
  key: string,
  parser: (r: Response) => Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  let entry = cache.get(key);
  if (!entry) {
    entry = { ts: 0, inflight: null, refCount: 0, evictTimer: null };
    cache.set(key, entry);
  }
  if (entry.inflight) return entry.inflight;

  const promise = (async () => {
    const r = await fetch(key, { signal });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const d = await parser(r);
    entry!.data = d;
    entry!.ts = Date.now();
    entry!.inflight = null;
    return d;
  })();
  entry.inflight = promise;
  return promise;
}

function acquire(key: string) {
  const e = cache.get(key);
  if (e) {
    e.refCount += 1;
    if (e.evictTimer) { clearTimeout(e.evictTimer); e.evictTimer = null; }
  }
}
function release(key: string) {
  const e = cache.get(key);
  if (!e) return;
  e.refCount -= 1;
  if (e.refCount <= 0) {
    if (e.evictTimer) clearTimeout(e.evictTimer);
    e.evictTimer = setTimeout(() => {
      const cur = cache.get(key);
      if (cur && cur.refCount <= 0) cache.delete(key);
    }, EVICT_DELAY_MS);
  }
}

export function useSWR<T = unknown>(
  key: string | null,
  options: UseSWROptions<T> = {},
): UseSWRResult<T> {
  const {
    intervalMs: overrideInterval,
    ignorePause = false,
    enabled = true,
    parser = ((r) => r.json() as Promise<T>) as (r: Response) => Promise<T>,
    clearOnKeyChange = true,
    silent = false,
    realtimeFallbackMs = 0,
  } = options;

  const ctx = useRefresh();
  const [data, setData] = useState<T | undefined>(() => key ? cache.get(key)?.data : undefined);
  const [error, setError] = useState<Error | undefined>();
  const [loading, setLoading] = useState<boolean>(() => !(key && cache.get(key)?.data));
  const [fetching, setFetching] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(() => key ? cache.get(key)?.ts ?? null : null);

  const backoffRef = useRef(0); // 连续失败次数
  const aliveRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const parserRef = useRef(parser);
  parserRef.current = parser;

  const doFetch = useCallback(async (k: string) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setFetching(true);
    try {
      const d = await dedupedFetch<T>(k, parserRef.current, ctrl.signal);
      if (!aliveRef.current) return;
      setData(d);
      setError(undefined);
      setLastUpdated(Date.now());
      backoffRef.current = 0;
    } catch (e: any) {
      if (e?.name === 'AbortError' || !aliveRef.current) return;
      if (!silent) setError(e instanceof Error ? e : new Error(String(e)));
      else console.warn('[useSWR]', k, e);
      backoffRef.current += 1;
    } finally {
      if (aliveRef.current) {
        setFetching(false);
        setLoading(false);
      }
    }
  }, [silent]);

  const refresh = useCallback(async () => {
    if (key) await doFetch(key);
  }, [key, doFetch]);

  // 计算最终 interval
  const baseInterval =
    overrideInterval !== undefined ? overrideInterval : ctx.intervalMs;
  const effectivePaused = !ignorePause && ctx.paused;

  // ref counting + initial fetch on key change
  useEffect(() => {
    aliveRef.current = true;
    if (!key || !enabled) {
      if (clearOnKeyChange) {
        setData(undefined);
        setLastUpdated(null);
      }
      setLoading(false);
      return () => { aliveRef.current = false; };
    }

    acquire(key);
    const cached = cache.get(key);
    if (cached?.data !== undefined) {
      setData(cached.data);
      setLastUpdated(cached.ts);
      setLoading(false);
    } else {
      if (clearOnKeyChange) setData(undefined);
      setLoading(true);
    }

    // immediate fetch
    void doFetch(key);

    return () => {
      aliveRef.current = false;
      abortRef.current?.abort();
      release(key);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  // polling
  useEffect(() => {
    if (!key || !enabled || effectivePaused) return;
    const interval = baseInterval ?? (realtimeFallbackMs > 0 ? realtimeFallbackMs : null);
    if (interval === null) return;

    const handle = setInterval(() => {
      // 退避：连续失败时加倍延迟（最多 8 倍）
      const back = Math.min(Math.pow(2, backoffRef.current), 8);
      if (Math.random() < 1 / back) {
        void doFetch(key);
      }
    }, interval);
    return () => clearInterval(handle);
  }, [key, enabled, baseInterval, effectivePaused, realtimeFallbackMs, doFetch]);

  // manual tick
  useEffect(() => {
    if (key && enabled && ctx.manualTick > 0) {
      void doFetch(key);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.manualTick]);

  return { data, error, loading, fetching, lastUpdated, refresh };
}
