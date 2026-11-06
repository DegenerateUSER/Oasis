import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useFocusReturn } from './hooks';

export function Icon({ name, size = 18 }: { name: 'oasis' | 'plus' | 'upload' | 'download' | 'close' | 'search' | 'arrow' | 'refresh' | 'shield' | 'clock' | 'chevron'; size?: number }) {
  const paths: Record<typeof name, ReactNode> = {
    oasis: <><path d="M3 16h5L12 5l4 11h5M6 21h12" /><path d="M10 16h4" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5" /></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 6a8 8 0 0 1 13 2M5 16a8 8 0 0 0 13 2" /></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    chevron: <path d="m9 5 7 7-7 7" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
export const statusLabels: Record<string, string> = {
  killed_assert: 'Assertion kill', killed_error: 'Engine-error kill', survived: 'Survived', invalid: 'Invalid', timeout: 'Timeout', no_op: 'No-op', execution_error: 'Execution error', scope_unresolved: 'Scope unresolved', not_executed: 'Not executed', no_tests: 'No tests', baseline_fail: 'Baseline failed', queued: 'Queued', running: 'Running', cancelling: 'Cancellation requested', cancelled: 'Cancelled', completed: 'Completed', failed: 'Failed', interrupted: 'Interrupted',
};
export function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}><span className="status-dot" />{statusLabels[value] || value || 'Unknown'}</span>;
}
export function ErrorNotice({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="notice error" role="alert"><div><strong>Could not complete the local request.</strong><p>{message}</p></div>{retry && <button onClick={retry}><Icon name="refresh" />Retry</button>}</div>;
}
export function Loading({ label = 'Loading local results…' }: { label?: string }) {
  return <div className="loading" role="status"><p>{label}</p><div /><div /><div /></div>;
}
export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <section className="empty"><Icon name="oasis" size={34} /><h2>{title}</h2>{children}</section>;
}
export function Drawer({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useFocusReturn(true);
  useEffect(() => {
    const element = ref.current;
    element?.querySelector<HTMLElement>('button')?.focus();
    const old = document.body.style.overflow; document.body.style.overflow = 'hidden';
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key !== 'Tab' || !element) return;
      const items = [...element.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, summary, [tabindex="0"]')].filter(item => {
        if (item.tabIndex < 0 || item.matches(':disabled, input[type="hidden"]') || item.closest('[hidden], [inert]')) return false;
        const { visibility } = getComputedStyle(item);
        if (visibility === 'hidden' || visibility === 'collapse') return false;
        // CSS/layout rectangles alone do not identify content hidden by closed details.
        for (let parent: HTMLElement | null = item; parent; parent = parent.parentElement) {
          if (getComputedStyle(parent).display === 'none') return false;
          if (parent !== item && parent instanceof HTMLDetailsElement && !parent.open && !parent.querySelector(':scope > summary')?.contains(item)) return false;
        }
        return true;
      });
      if (!items.length) { event.preventDefault(); element.focus(); return; }
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handle);
    return () => { document.body.style.overflow = old; document.removeEventListener('keydown', handle); };
  }, [close]);
  return createPortal(<div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}><aside ref={ref} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><header><div><h2 id="drawer-title">{title}</h2><p>Exact record and available evidence</p></div><button onClick={close} className="icon-button" aria-label="Close evidence"><Icon name="close" /></button></header>{children}</aside></div>, document.body);
}
export function CodeBlock({ title, value }: { title: string; value: unknown }) {
  return <section className="code-section"><h3>{title}</h3><pre tabIndex={0}><code>{value == null || value === '' ? 'Not recorded in this dataset.' : String(value)}</code></pre></section>;
}
