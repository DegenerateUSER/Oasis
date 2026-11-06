import { describe, expect, it } from 'vitest';
import { formatScore, filterQuery, runtimeData, survivalData, sortRows, pageRows } from './data';

describe('honest data presentation', () => {
  it('keeps unknown scores distinct from zero', () => {
    expect(formatScore(null)).toBe('—');
    expect(formatScore(undefined)).toBe('—');
    expect(formatScore(0)).toBe('0.0%');
    expect(formatScore(0.4)).toBe('40.0%');
  });
  it('serializes only nonempty global filters without changing exact categorical tokens', () => {
    expect(filterQuery({ repo: 'a/b', category: '', operator: ' OP ', status: 'survived', q: 'hello world' })).toBe('?repo=a%2Fb&operator=+OP+&status=survived&q=hello+world');
    expect(filterQuery({ repo: '', category: '', operator: '', status: '', q: '' })).toBe('');
  });
  it('uses explicit nonnegative total timings only, including real zero, not fabricated totals', () => {
    expect(runtimeData([{ total_seconds: '' }, { total_seconds: null }, { test_seconds: 4 }, { total_seconds: '-1' }, { total_seconds: 'NaN' }])).toEqual([]);
    expect(runtimeData([{ mutant_id: 'm1', total_seconds: '2.5' }, { mutant_id: 'm2', total_seconds: 0 }])).toEqual([{ label: 'm1', seconds: 2.5 }, { label: 'm2', seconds: 0 }]);
  });
});

it('counts only survivor classifications without treating static evidence as runtime coverage', () => {
  expect(survivalData([{ test_status: 'killed_assert', survival_reason: 'weak_assertion' }, { test_status: 'survived', survival_reason: 'weak_assertion' }, { test_status: 'survived', survival_reason: 'n/a' }, { test_status: 'survived', survival_reason: '' }])).toEqual([{ label: 'Unknown / unclassified', count: 2 }, { label: 'weak_assertion', count: 1 }]);
});

it('sorts numerical timings without mutating rows and clamps pagination', () => {
  const rows = [{ mutant_id: 'm10', total_seconds: '10' }, { mutant_id: 'm2', total_seconds: '2' }, { mutant_id: 'm1', total_seconds: '' }];
  expect(sortRows(rows, 'total_seconds', 'asc').map(r => r.mutant_id)).toEqual(['m2', 'm10', 'm1']);
  expect(sortRows(rows, 'mutant_id', 'asc').map(r => r.mutant_id)).toEqual(['m1', 'm2', 'm10']);
  expect(rows[0].mutant_id).toBe('m10');
  expect(pageRows(rows, 20, 2)).toEqual({ rows: [rows[2]], page: 2, pages: 2 });
  expect(pageRows([], 3, 25)).toEqual({ rows: [], page: 1, pages: 1 });
});
