import { useEffect, useRef, useState } from 'react';
import { api } from './api';

export function useResource<T>(url: string | null, revision = 0) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setValue(null); setError('');
    if (!url) { setLoading(false); return; }
    setLoading(true);
    api<T>(url, { signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) { setValue(result); setLoading(false); }
    }).catch(reason => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'Local request failed.'); setLoading(false); }
    });
    return () => controller.abort();
  }, [url, revision, retry]);
  return { value, error, loading, retry: () => setRetry(n => n + 1) };
}

export type Theme = 'system' | 'light' | 'dark';
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try { const saved = localStorage.getItem('oasis-theme'); return saved === 'dark' || saved === 'light' ? saved : 'system'; } catch { return 'system'; }
  });
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme; };
    apply(); media.addEventListener('change', apply);
    try { localStorage.setItem('oasis-theme', theme); } catch { /* Storage may be disabled; theme still works this session. */ }
    return () => media.removeEventListener('change', apply);
  }, [theme]);
  return [theme, setTheme] as const;
}

export function useFocusReturn(active: boolean) {
  const previous = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!active) return;
    previous.current = document.activeElement as HTMLElement;
    return () => { previous.current?.focus(); };
  }, [active]);
}
