import { useEffect, useState } from 'react';

/** 监听 (max-width: 1280px) — 窄屏布局 */
export function useResponsive(query = '(max-width: 1280px)'): boolean {
  const [match, setMatch] = useState<boolean>(() =>
    typeof window !== 'undefined' && window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mm = window.matchMedia(query);
    const h = (e: MediaQueryListEvent) => setMatch(e.matches);
    mm.addEventListener('change', h);
    return () => mm.removeEventListener('change', h);
  }, [query]);
  return match;
}
