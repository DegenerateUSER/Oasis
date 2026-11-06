import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Analysis } from './Analysis';
import { emptyFilters } from './data';
import type { Dataset, Metrics } from './types';

const metrics: Metrics = {
  total_records: 10, generated_mutants: 10, module_baseline_records: 0, scored_mutants: 8,
  killed_assert: 3, killed_error: 1, survived: 4, mutation_score: 0.5, assertion_score: 0.375,
  status_counts: { killed_assert: 3, killed_error: 1, survived: 4, invalid: 2 },
  excluded_statuses: { invalid: 2 },
};

function dataset(overall = metrics): Dataset {
  return {
    id: 'explicit-unit-test', name: 'Explicit synthetic unit fixture', created_at: '2026-01-01T00:00:00Z',
    provenance: { kind: 'imported', message: 'Synthetic component-test input, not experiment results.' },
    rows: [], metadata: {}, filter_options: { repo: [], category: [], operator: [], status: [] },
    selection: { total_rows: 10, filtered_rows: 10 },
    summary: { schema_version: 3, overall, by_repo: {}, by_category: {}, by_operator: {}, validation_problems: [] },
  };
}

describe('narrow outcome composition', () => {
  it('provides native HTML labels and exact counts instead of scaling SVG text', () => {
    render(<Analysis dataset={dataset()} filters={emptyFilters} select={vi.fn()} showMutants={vi.fn()} />);
    const mobile = screen.getByRole('group', { name: 'Mobile mutation outcome flow' });
    expect(within(mobile).getByText('Generated')).toBeInTheDocument();
    expect(within(mobile).getByText('Scored denominator')).toBeInTheDocument();
    expect(within(mobile).getByRole('button', { name: 'Survived: 4. Filter these records.' })).toBeInTheDocument();
    expect(mobile.querySelector('svg text')).toBeNull();
  });

  it('keeps outcome filtering and its selected state on the readable narrow controls', () => {
    const select = vi.fn();
    render(<Analysis dataset={dataset()} filters={{ ...emptyFilters, status: 'survived' }} select={select} showMutants={vi.fn()} />);
    const mobile = screen.getByRole('group', { name: 'Mobile mutation outcome flow' });
    const button = within(mobile).getByRole('button', { name: 'Survived: 4. Filter these records.' });
    expect(button).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(button);
    expect(select).toHaveBeenCalledWith('status', '');
  });

  it('uses the shared generated-count denominator for the mobile data geometry', () => {
    render(<Analysis dataset={dataset()} filters={emptyFilters} select={vi.fn()} showMutants={vi.fn()} />);
    const mobile = screen.getByRole('group', { name: 'Mobile mutation outcome flow' });
    const button = within(mobile).getByRole('button', { name: 'Survived: 4. Filter these records.' });
    expect(button.querySelector<HTMLElement>('.mobile-flow-bar > i')?.style.width)
      .toBe(`${metrics.survived / metrics.generated_mutants * 100}%`);
  });
});
