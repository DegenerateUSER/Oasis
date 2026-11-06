import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Runs } from './Runs';
import type { Bootstrap, Job, Preview } from './types';

const transport = vi.hoisted(() => vi.fn());
vi.mock('./api', () => ({ api: transport }));

const bootstrap: Bootstrap = {
  version: 'test', operators: [{ id: 'literal', category: 'test', description: 'Test operator' }],
  categories: ['test'], sources: [], limits: {}, capabilities: { terraform: true, tofu: false },
};
const preview: Preview = {
  modules: ['.'], warnings: [], truncated: false,
  mutants: [{ id: 'site-1', operator_id: 'literal', file: 'main.tf', line: 1, original: '1', mutated: '2', diff: '-1\n+2' }],
};
let snapshotRevision: number;
function snapshot(state: Job['state'], overrides: Partial<Job> = {}): Job {
  return {
    id: 'run-1', state, snapshot_revision: ++snapshotRevision,
    config: { target_path: '/local/example', engine: 'terraform', operators: ['literal'], test_directory: 'tests', max_mutants: 20, budget_seconds: 120, timeout: 30, init_timeout: 30, init_attempts: 1, acknowledge_execution: true },
    created_at: '2026-01-01T00:00:00Z', started_at: '2026-01-01T00:00:01Z', finished_at: null,
    dataset_id: null, error: null, progress: { phase: state, completed_commands: 1 }, log_tail: state, duration_seconds: 1,
    ...overrides,
  };
}

type Pending = { path: string; method: string; resolve: (value: unknown) => void };
let pending: Pending[];
beforeEach(() => {
  vi.useFakeTimers(); snapshotRevision = 0; pending = []; transport.mockReset();
  transport.mockImplementation((path: string, options: RequestInit = {}) => new Promise(resolve => {
    pending.push({ path, method: options.method || 'GET', resolve });
  }));
});
afterEach(() => { vi.useRealTimers(); });

async function reply(path: string, value: unknown, method = 'GET') {
  const index = pending.findIndex(item => item.path === path && item.method === method);
  expect(index, `pending ${method} ${path}`).toBeGreaterThanOrEqual(0);
  const [request] = pending.splice(index, 1);
  await act(async () => { request.resolve(value); });
}
async function tick(milliseconds: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}
function mount() {
  return render(<Runs bootstrap={bootstrap} openDataset={vi.fn()} refreshDatasets={vi.fn()} />);
}
async function readyToLaunch() {
  fireEvent.change(screen.getByLabelText('Local repository path'), { target: { value: '/local/example' } });
  fireEvent.click(screen.getByRole('button', { name: 'Read-only preview' }));
  await reply('/api/preview', preview, 'POST');
  fireEvent.click(screen.getByLabelText(/I trust this repository/));
}
function row() { return screen.getByRole('button', { name: /example/ }); }
function detail() { return screen.getByRole('heading', { name: 'Run evidence' }).closest('section')!; }

describe('Runs canonical polling evidence', () => {
  it.each([
    ['running', 'list', 'older'], ['running', 'detail', 'older'],
    ['cancelling', 'list', 'older'], ['cancelling', 'detail', 'older'],
    ['running', 'list', 'equal'], ['running', 'detail', 'equal'],
    ['cancelling', 'list', 'equal'], ['cancelling', 'detail', 'equal'],
  ] as const)('rejects a delayed %s %s snapshot with an %s revision and accepts newer evidence', async (state, delayedSource, revisionAge) => {
    mount();
    await reply('/api/jobs', { jobs: [snapshot(state)] });
    fireEvent.click(row());
    await tick(2000);
    // Revisions reflect server snapshot order, not request start or arrival order.
    const olderSnapshot = snapshot(state, { progress: { phase: 'init', completed_commands: 2 }, duration_seconds: 3, log_tail: 'old worker log' });
    const moreRecentResponse = snapshot(state, { progress: { phase: 'restoring', completed_commands: 12 }, duration_seconds: 15, log_tail: 'newer worker log' });
    const delayed = revisionAge === 'equal' ? { ...olderSnapshot, snapshot_revision: moreRecentResponse.snapshot_revision } : olderSnapshot;
    const delayedPath = delayedSource === 'list' ? '/api/jobs' : '/api/jobs/run-1';
    const newerPath = delayedSource === 'list' ? '/api/jobs/run-1' : '/api/jobs';
    const respond = (path: string, job: Job) => reply(path, path === '/api/jobs' ? { jobs: [job] } : job);
    function expectEvidence(job: Job) {
      const evidence = within(detail());
      expect(evidence.getByText('Completed commands').nextElementSibling).toHaveTextContent(String(job.progress.completed_commands));
      expect(evidence.getByText('Elapsed (reported)').nextElementSibling).toHaveTextContent(`${job.duration_seconds.toFixed(1)} s`);
      expect(evidence.getByText('Phase').nextElementSibling).toHaveTextContent(job.progress.phase);
      expect(evidence.getByText(job.log_tail)).toBeInTheDocument();
    }
    await respond(newerPath, moreRecentResponse);
    expectEvidence(moreRecentResponse);
    await respond(delayedPath, delayed);
    expectEvidence(moreRecentResponse);
    expect(within(row()).getByText(state === 'running' ? 'Running' : 'Cancellation requested', { selector: '.status' })).toBeInTheDocument();
    if (state === 'cancelling') expect(screen.getByRole('button', { name: 'Awaiting safe cancellation' })).toBeDisabled();

    // A higher revision wins even when commands/duration are lower: no progress heuristics.
    const newest = snapshot(state, { progress: { phase: 'waiting for cleanup', completed_commands: 0 }, duration_seconds: 0, log_tail: 'latest worker log' });
    await tick(2000);
    await respond(newerPath, newest);
    expectEvidence(newest);
  });

  it.each([
    ['completed', 'Completed'], ['failed', 'Failed'], ['cancelled', 'Cancelled'], ['interrupted', 'Interrupted'],
  ] as const)('keeps %s detail, row, banner and launch eligibility consistent after a stale list response', async (state, label) => {
    mount();
    await reply('/api/jobs', { jobs: [snapshot('running')] });
    await readyToLaunch();
    fireEvent.click(row());
    // The list poll is in flight when terminal detail evidence arrives.
    await tick(2000);
    await reply('/api/jobs/run-1', snapshot(state, { dataset_id: state === 'completed' ? 'dataset-1' : null, finished_at: '2026-01-01T00:00:02Z' }));
    await reply('/api/jobs', { jobs: [snapshot('running')] });

    expect(within(detail()).getByText(label, { selector: '.status' })).toBeInTheDocument();
    expect(within(row()).getByText(label, { selector: '.status' })).toBeInTheDocument();
    expect(screen.queryByText('An evaluation is active.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start bounded evaluation' })).toBeEnabled();
    if (state === 'completed') expect(screen.getByRole('button', { name: 'Open recorded results' })).toBeInTheDocument();
  });

  it.each([
    ['completed', 'Completed'], ['failed', 'Failed'], ['cancelled', 'Cancelled'], ['interrupted', 'Interrupted'],
  ] as const)('keeps a %s list snapshot ahead of stale selected-detail and later list polls', async (state, label) => {
    mount();
    await reply('/api/jobs', { jobs: [snapshot('running')] });
    await readyToLaunch();
    fireEvent.click(row());
    await tick(2000);
    await reply('/api/jobs', { jobs: [snapshot(state, { finished_at: '2026-01-01T00:00:02Z' })] });
    await reply('/api/jobs/run-1', snapshot('running'));
    await tick(2000);
    await reply('/api/jobs', { jobs: [snapshot('queued')] });

    expect(within(row()).getByText(label, { selector: '.status' })).toBeInTheDocument();
    expect(within(detail()).getByText(label, { selector: '.status' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Request cancellation' })).not.toBeInTheDocument();
    expect(screen.queryByText('An evaluation is active.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start bounded evaluation' })).toBeEnabled();
  });

  it('keeps acknowledged cancellation ahead of in-flight running and queued snapshots', async () => {
    mount();
    await reply('/api/jobs', { jobs: [snapshot('running')] });
    await readyToLaunch();
    fireEvent.click(row());
    await reply('/api/jobs/run-1', snapshot('running'));
    await tick(1500);
    fireEvent.click(screen.getByRole('button', { name: 'Request cancellation' }));
    await reply('/api/jobs/run-1/cancel', snapshot('cancelling'), 'POST');

    expect(within(row()).getByText('Cancellation requested', { selector: '.status' })).toBeInTheDocument();
    expect(within(detail()).getByText('Cancellation requested', { selector: '.status' })).toBeInTheDocument();
    // Both the older detail poll and the post-cancel confirmation can be stale.
    await reply('/api/jobs/run-1', snapshot('running'));
    await reply('/api/jobs/run-1', snapshot('running'));
    await reply('/api/jobs', { jobs: [snapshot('queued')] });
    await reply('/api/jobs/run-1', snapshot('queued'));

    expect(within(row()).getByText('Cancellation requested', { selector: '.status' })).toBeInTheDocument();
    expect(within(detail()).getByText('Cancellation requested', { selector: '.status' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Awaiting safe cancellation' })).toBeDisabled();
    expect(screen.getByText('An evaluation is active.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start bounded evaluation' })).toBeDisabled();
  });

  it('counts a newly launched job before it appears in any list snapshot', async () => {
    mount();
    await reply('/api/jobs', { jobs: [] });
    await readyToLaunch();
    fireEvent.click(screen.getByRole('button', { name: 'Start bounded evaluation' }));
    await reply('/api/jobs', snapshot('queued'), 'POST');

    expect(screen.getByText('An evaluation is active.')).toBeInTheDocument();
    expect(within(row()).getByText('Queued', { selector: '.status' })).toBeInTheDocument();
    await reply('/api/jobs/run-1', snapshot('running'));
    await reply('/api/jobs', { jobs: [] });
    fireEvent.click(screen.getByLabelText(/I trust this repository/));
    expect(within(row()).getByText('Running', { selector: '.status' })).toBeInTheDocument();
    expect(within(detail()).getByText('Running', { selector: '.status' })).toBeInTheDocument();
    expect(screen.getByText('An evaluation is active.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start bounded evaluation' })).toBeDisabled();
  });
});
