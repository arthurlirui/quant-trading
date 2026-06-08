/**
 * useWebSocket — 自动重连 + 状态可观测
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRefresh } from '../../context/RefreshContext';

export type WSStatus = 'connecting' | 'open' | 'closed' | 'error';

export interface UseWebSocketOptions {
  enabled?: boolean;
  /** RefreshContext.paused 时是否主动断开；默认 true */
  pauseOnPaused?: boolean;
  onMessage?: (data: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
  /** 退避策略；默认 min 1000 / max 15000 / factor 1.6 */
  backoff?: { min?: number; max?: number; factor?: number };
}

export interface UseWebSocketResult {
  status: WSStatus;
  retries: number;
  lastConnectedAt: number | null;
  /** 主动重连 */
  reconnect: () => void;
}

export function useWebSocket(
  url: string | null,
  options: UseWebSocketOptions = {},
): UseWebSocketResult {
  const {
    enabled = true,
    pauseOnPaused = true,
    onMessage,
    onOpen,
    onClose,
    backoff = {},
  } = options;
  const { min = 1000, max = 15000, factor = 1.6 } = backoff;

  const ctx = useRefresh();
  const [status, setStatus] = useState<WSStatus>('closed');
  const [retries, setRetries] = useState(0);
  const [lastConnectedAt, setLastConnectedAt] = useState<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);
  const retriesRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  onMessageRef.current = onMessage;
  onOpenRef.current = onOpen;
  onCloseRef.current = onClose;

  const cleanup = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      try { wsRef.current.close(); } catch { /* */ }
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback((targetUrl: string) => {
    if (!aliveRef.current) return;
    cleanup();
    setStatus('connecting');
    try {
      const ws = new WebSocket(targetUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        if (!aliveRef.current) return;
        setStatus('open');
        setLastConnectedAt(Date.now());
        retriesRef.current = 0;
        setRetries(0);
        onOpenRef.current?.();
      };
      ws.onclose = () => {
        if (!aliveRef.current) return;
        setStatus('closed');
        onCloseRef.current?.();
        // schedule reconnect
        const delay = Math.min(max, min * Math.pow(factor, retriesRef.current));
        retriesRef.current += 1;
        setRetries(retriesRef.current);
        retryTimerRef.current = setTimeout(() => connect(targetUrl), delay);
      };
      ws.onerror = () => {
        if (!aliveRef.current) return;
        setStatus('error');
      };
      ws.onmessage = (ev) => {
        if (!aliveRef.current || !onMessageRef.current) return;
        try {
          onMessageRef.current(JSON.parse(ev.data));
        } catch (e) {
          console.warn('[useWebSocket] parse error', e);
        }
      };
    } catch (e) {
      console.warn('[useWebSocket] connect failed', e);
      setStatus('error');
      const delay = Math.min(max, min * Math.pow(factor, retriesRef.current));
      retriesRef.current += 1;
      setRetries(retriesRef.current);
      retryTimerRef.current = setTimeout(() => connect(targetUrl), delay);
    }
  }, [cleanup, max, min, factor]);

  const reconnect = useCallback(() => {
    if (url && enabled && !(pauseOnPaused && ctx.paused)) {
      retriesRef.current = 0;
      setRetries(0);
      connect(url);
    }
  }, [url, enabled, pauseOnPaused, ctx.paused, connect]);

  useEffect(() => {
    aliveRef.current = true;
    if (!url || !enabled || (pauseOnPaused && ctx.paused)) {
      cleanup();
      setStatus('closed');
      return () => { aliveRef.current = false; cleanup(); };
    }
    retriesRef.current = 0;
    setRetries(0);
    connect(url);
    return () => {
      aliveRef.current = false;
      cleanup();
    };
  }, [url, enabled, pauseOnPaused, ctx.paused, connect, cleanup]);

  return { status, retries, lastConnectedAt, reconnect };
}
