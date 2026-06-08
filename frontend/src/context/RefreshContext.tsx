import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export type RefreshMode = 'realtime' | '5s' | '30s' | 'paused';

export interface RefreshContextValue {
  mode: RefreshMode;
  /** mode 转化成毫秒；paused / realtime 返回 null（HTTP poll 不主动跑） */
  intervalMs: number | null;
  paused: boolean;
  setMode: (m: RefreshMode) => void;
  setPaused: (p: boolean) => void;
  /** 触发所有订阅 hook 立即重新拉取一次 */
  refreshNow: () => void;
  /** 单调递增的 tick；hook 把它列入 deps 实现「立即刷新」 */
  manualTick: number;
}

const STORAGE_KEY = '***';

const MODE_TO_MS: Record<RefreshMode, number | null> = {
  realtime: null,
  '5s': 5000,
  '30s': 30000,
  paused: null,
};

const RefreshContext = createContext<RefreshContextValue | null>(null);

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<RefreshMode>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as RefreshMode | null;
      if (stored && stored in MODE_TO_MS) return stored;
    } catch { /* */ }
    return '5s';
  });
  const [manualTick, setManualTick] = useState(0);

  const setMode = useCallback((m: RefreshMode) => {
    setModeState(m);
    try { localStorage.setItem(STORAGE_KEY, m); } catch { /* */ }
  }, []);

  const setPaused = useCallback((p: boolean) => {
    setMode(p ? 'paused' : '5s');
  }, [setMode]);

  const refreshNow = useCallback(() => {
    setManualTick(t => t + 1);
  }, []);

  // Spacebar shortcut: pause/resume
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.code === 'Space' && (e.target as HTMLElement)?.tagName !== 'INPUT' &&
          (e.target as HTMLElement)?.tagName !== 'TEXTAREA' &&
          (e.target as HTMLElement)?.tagName !== 'SELECT') {
        e.preventDefault();
        setMode(mode === 'paused' ? '5s' : 'paused');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, setMode]);

  const value: RefreshContextValue = {
    mode,
    intervalMs: MODE_TO_MS[mode],
    paused: mode === 'paused',
    setMode,
    setPaused,
    refreshNow,
    manualTick,
  };

  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>;
}

export function useRefresh(): RefreshContextValue {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error('useRefresh must be used inside <RefreshProvider>');
  return ctx;
}
