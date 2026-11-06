import type { Filters, Row } from './types';
export function runtimeData(rows: Row[]): { label: string; seconds: number }[] {
  return rows.flatMap((row, index) => {
    const raw = row.total_seconds;
    if (raw == null || String(raw).trim() === '') return [];
    const seconds = Number(raw);
    return Number.isFinite(seconds) && seconds >= 0 ? [{ label: String(row.mutant_id || `Record ${index + 1}`), seconds }] : [];
  });
}
export function survivalData(rows: Row[]): { label: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const row of rows) if (row.test_status === 'survived') {
    const reason = row.survival_reason;
    const label = reason && reason !== 'n/a' ? String(reason) : 'Unknown / unclassified';
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
export function sortRows(rows: Row[], key: string, direction: 'asc' | 'desc'): Row[] {
  const numeric = key.endsWith('_seconds');
  return [...rows].sort((a, b) => {
    const x = a[key], y = b[key];
    const missingX = x == null || x === '', missingY = y == null || y === '';
    if (missingX || missingY) return Number(missingX) - Number(missingY);
    const comparison = numeric ? Number(x) - Number(y) : String(x).localeCompare(String(y), undefined, { numeric: true });
    return direction === 'asc' ? comparison : -comparison;
  });
}
export function pageRows(rows: Row[], requested: number, size: number): { rows: Row[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const page = Math.max(1, Math.min(requested, pages));
  return { rows: rows.slice((page - 1) * size, page * size), page, pages };
}
export const emptyFilters: Filters = { repo: '', category: '', operator: '', status: '', q: '' };
export function filterQuery(filters: Filters): string {
  const query = new URLSearchParams();
  for (const key of ['repo', 'category', 'operator', 'status', 'q'] as const) if (filters[key]) query.set(key, filters[key]);
  return query.size ? `?${query}` : '';
}
export function formatScore(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(1)}%`;
}
