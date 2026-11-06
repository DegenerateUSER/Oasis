import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from './api';
import type { Bootstrap, Job, Preview, RunConfig } from './types';
import { CodeBlock, Empty, ErrorNotice, Icon, Loading, Status } from './ui';

const activeStates = new Set(['queued', 'running', 'cancelling']);
const stateOrder: Record<Job['state'], number> = { queued: 0, running: 1, cancelling: 2, completed: 3, failed: 3, cancelled: 3, interrupted: 3 };
function mergeJobs(previous: Job[], snapshots: Job[]): Job[] {
  const jobs = new Map(previous.map(item => [item.id, item]));
  for (const snapshot of snapshots) {
    const known = jobs.get(snapshot.id);
    // Only server snapshot order can advance evidence for an immutable job ID.
    if (known && snapshot.snapshot_revision <= known.snapshot_revision) continue;
    // A stale poll cannot undo cancellation or a terminal result.
    if (known && (stateOrder[known.state] > stateOrder[snapshot.state] || (!activeStates.has(known.state) && known.state !== snapshot.state))) continue;
    jobs.set(snapshot.id, snapshot);
  }
  return [...jobs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
}
const boundFields = [
  { key: 'max_mutants', label: 'Maximum mutants', default: 20, maximum: 5000, help: 'Stop generating work at this bound.' },
  { key: 'budget_seconds', label: 'Run budget (seconds)', default: 120, maximum: 7200, help: 'Bounded run budget; restoration may take longer.' },
  { key: 'timeout', label: 'Command timeout (seconds)', default: 30, maximum: 300, help: 'Per validation / test command.' },
  { key: 'init_timeout', label: 'Init timeout (seconds)', default: 30, maximum: 300, help: 'Provider initialization command.' },
  { key: 'init_attempts', label: 'Init attempts', default: 1, maximum: 3, help: 'At most this many initialization attempts.' },
] as const;

export function Runs({ bootstrap, openDataset, refreshDatasets }: { bootstrap: Bootstrap; openDataset: (id: string) => void; refreshDatasets: () => void }) {
  const [jobs, setJobs] = useState<Job[]>([]); const [loading, setLoading] = useState(true); const [feedError, setFeedError] = useState('');
  const [selected, setSelected] = useState(''); const [jobError, setJobError] = useState('');
  const [revision, setRevision] = useState(0); const [cancelling, setCancelling] = useState(false); const [cancelError, setCancelError] = useState('');
  const [config, setConfig] = useState<RunConfig>(() => ({ target_path: '', engine: bootstrap.capabilities.terraform ? 'terraform' : bootstrap.capabilities.tofu ? 'tofu' : 'terraform', operators: bootstrap.operators.map(op => op.id), test_directory: 'tests', max_mutants: 20, budget_seconds: 120, timeout: 30, init_timeout: 30, init_attempts: 1, acknowledge_execution: false }));
  const [preview, setPreview] = useState<Preview | null>(null); const [previewBusy, setPreviewBusy] = useState(false); const [launchBusy, setLaunchBusy] = useState(false); const [formError, setFormError] = useState(''); const [showAllPreview, setShowAllPreview] = useState(false);
  const published = useRef(new Set<string>());
  const formRef = useRef<HTMLFormElement>(null);
  const job = jobs.find(item => item.id === selected) || null;
  const active = jobs.find(item => activeStates.has(item.state));

  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<{ jobs: Job[] }>('/api/jobs', { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJobs(previous => mergeJobs(previous, result.jobs)); setFeedError(''); setLoading(false);
        for (const item of result.jobs) if (item.dataset_id && !published.current.has(item.dataset_id)) { published.current.add(item.dataset_id); refreshDatasets(); }
      } catch (reason) { if (!controller.signal.aborted) { setFeedError(reason instanceof Error ? reason.message : 'Run list unavailable.'); setLoading(false); } }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [revision, refreshDatasets]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setJobError(''); setCancelError('');
    async function poll() {
      try {
        const result = await api<Job>(`/api/jobs/${encodeURIComponent(selected)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJobs(previous => mergeJobs(previous, [result])); setJobError('');
        if (activeStates.has(result.state)) timer = setTimeout(poll, 1500);
        else if (result.dataset_id) refreshDatasets();
      } catch (reason) { if (!controller.signal.aborted) { setJobError(reason instanceof Error ? reason.message : 'Run status unavailable.'); timer = setTimeout(poll, 3000); } }
    }
    poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [selected, revision, refreshDatasets]);

  function update<K extends keyof RunConfig>(key: K, value: RunConfig[K]) {
    setConfig(previous => ({ ...previous, [key]: value, acknowledge_execution: key === 'acknowledge_execution' ? Boolean(value) : false }));
    if (key !== 'acknowledge_execution') { setPreview(null); setShowAllPreview(false); }
    setFormError('');
  }
  async function getPreview() {
    if (!formRef.current?.reportValidity()) return;
    if (!config.operators.length) { setFormError('Select at least one registered operator.'); return; }
    setPreviewBusy(true); setPreview(null); setFormError(''); setConfig(c => ({ ...c, acknowledge_execution: false }));
    try { setPreview(await api<Preview>('/api/preview', { method: 'POST', body: JSON.stringify({ target_path: config.target_path, engine: config.engine, operators: config.operators, test_directory: config.test_directory }) })); }
    catch (reason) { setFormError(reason instanceof Error ? reason.message : 'Preview failed.'); }
    finally { setPreviewBusy(false); }
  }
  async function launch(event: FormEvent) {
    event.preventDefault();
    if (!preview?.mutants.length || !config.acknowledge_execution || active || launchBusy) return;
    setLaunchBusy(true); setFormError('');
    try {
      const result = await api<Job>('/api/jobs', { method: 'POST', body: JSON.stringify(config) });
      setJobs(previous => mergeJobs(previous, [result]));
      setSelected(result.id); setRevision(n => n + 1); setConfig(c => ({ ...c, acknowledge_execution: false }));
    } catch (reason) { setFormError(reason instanceof Error ? reason.message : 'Run was not launched.'); }
    finally { setLaunchBusy(false); }
  }
  async function cancel() {
    if (!job || !activeStates.has(job.state)) return;
    setCancelling(true); setCancelError('');
    try {
      const requested = await api<Job>(`/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST', body: '{}' });
      setJobs(previous => mergeJobs(previous, [requested]));
      const actual = await api<Job>(`/api/jobs/${encodeURIComponent(job.id)}`);
      setJobs(previous => mergeJobs(previous, [actual])); setRevision(n => n + 1);
    } catch (reason) { setCancelError(reason instanceof Error ? reason.message : 'Cancellation request failed.'); }
    finally { setCancelling(false); }
  }
  return <section className="runs-page"><div className="page-heading"><div><h1>Run a bounded local evaluation.</h1><p>One trusted repository. One active job. Explicit limits and inspectable evidence.</p></div><span className="local-badge"><Icon name="shield" />Local execution</span></div>
    {active && <div className="notice"><div><strong>An evaluation is active.</strong><p>Oasis allows one job at a time. Configuration and read-only preview remain available.</p></div><button onClick={() => setSelected(active.id)}>View active run</button></div>}
    <div className="run-layout"><form ref={formRef} className="run-form" onSubmit={launch}><div className="section-heading"><h2>Evaluation configuration</h2><span>New run</span></div><fieldset disabled={previewBusy || launchBusy}><legend className="sr-only">Target and limits</legend><label>Local repository path<input required maxLength={4096} value={config.target_path} onChange={event => update('target_path', event.target.value)} placeholder="/absolute/path/to/trusted-repository" autoComplete="off" spellCheck={false} /></label><p className="caption">Use a clean Git repository with an existing commit and .tftest.hcl tests. The server refuses dirty tracked files and unsafe paths.</p><div className="form-pair"><label>Engine<select value={config.engine} onChange={event => update('engine', event.target.value as RunConfig['engine'])}><option value="terraform">Terraform{!bootstrap.capabilities.terraform ? ' · not installed' : ''}</option><option value="tofu">OpenTofu{!bootstrap.capabilities.tofu ? ' · not installed' : ''}</option></select></label><label>Test directory<input required maxLength={200} value={config.test_directory} onChange={event => update('test_directory', event.target.value)} spellCheck={false} /></label></div>
      <details className="operator-picker"><summary>Mutation operators <span>{config.operators.length} / {bootstrap.operators.length} selected</span></summary><div className="operator-picker-actions"><button type="button" onClick={() => update('operators', bootstrap.operators.map(op => op.id))}>Select all</button><button type="button" onClick={() => update('operators', [])}>Clear selection</button></div><div className="operator-checks">{bootstrap.operators.map(op => <label key={op.id} title={op.description}><input type="checkbox" checked={config.operators.includes(op.id)} onChange={event => update('operators', event.target.checked ? [...config.operators, op.id] : config.operators.filter(id => id !== op.id))} /><span><code>{op.id}</code><small>{op.category}</small></span></label>)}</div></details>
      <div className="bounds">{boundFields.slice(0, 2).map(field => <label key={field.key}>{field.label}<input required type="number" min={1} max={bootstrap.limits[field.key] || field.maximum} step={1} value={config[field.key]} onChange={event => update(field.key, Number(event.target.value))} /><small>{field.help} Maximum {bootstrap.limits[field.key] || field.maximum}.</small></label>)}</div>
      <details className="advanced"><summary>Command and initialization bounds</summary><div className="bounds">{boundFields.slice(2).map(field => <label key={field.key}>{field.label}<input required type="number" min={1} max={bootstrap.limits[field.key] || field.maximum} step={1} value={config[field.key]} onChange={event => update(field.key, Number(event.target.value))} /><small>{field.help}</small></label>)}</div></details>
      <button type="button" className="preview-button" disabled={!config.operators.length} onClick={getPreview}><Icon name="search" />{previewBusy ? 'Inspecting source…' : 'Read-only preview'}</button><p className="caption">No init, native validation, providers or tests run during preview.</p></fieldset>
      {formError && <ErrorNotice message={formError} />}
      {previewBusy && <Loading label="Discovering eligible mutation sites without execution…" />}
      {preview && <section className="preview-result" aria-live="polite"><div className="section-heading"><h3>Read-only preview</h3><span>{preview.mutants.length}{preview.truncated ? '+' : ''} sites</span></div><p className="caption">{preview.modules.length} module(s): {preview.modules.join(', ') || 'none'}</p>{preview.warnings.map((warning, index) => <p className="preview-warning" key={index}>{warning}</p>)}{preview.truncated && <p className="notice">Preview is capped at 200 sites. The run still uses your explicit mutant and time bounds.</p>}{!preview.mutants.length && <p className="quiet-empty">No eligible mutation sites. Choose different operators or a repository with supported source literals.</p>}<div className="preview-sites">{preview.mutants.slice(0, showAllPreview ? undefined : 8).map(mutant => <details key={mutant.id}><summary><code>{mutant.operator_id}</code><span>{mutant.file}:{mutant.line}</span></summary><div className="snippet-pair"><CodeBlock title="Original" value={mutant.original} /><CodeBlock title="Mutated" value={mutant.mutated} /></div><CodeBlock title="Source diff" value={mutant.diff} /></details>)}</div>{preview.mutants.length > 8 && <button type="button" className="text-button" onClick={() => setShowAllPreview(v => !v)}>{showAllPreview ? 'Show fewer sites' : `Show all ${preview.mutants.length} preview sites`}</button>}</section>}
      <div className="execution-consent"><h3>Before you execute</h3><p>Terraform/OpenTofu executes trusted repository and provider code locally. It can access credentials, contact networks and create or change cloud resources. Oasis does not sandbox it. Use isolated test credentials and a repository you trust.</p><label className="checkbox-label"><input type="checkbox" checked={config.acknowledge_execution} disabled={!preview?.mutants.length || launchBusy} onChange={event => update('acknowledge_execution', event.target.checked)} /><span>I trust this repository and acknowledge local code execution and potential cloud changes.</span></label>{!bootstrap.capabilities[config.engine] && <p className="preview-warning">The selected engine is not installed on the server PATH. Install it before starting an evaluation.</p>}<button className="primary" type="submit" disabled={!preview?.mutants.length || !config.acknowledge_execution || !!active || launchBusy || !bootstrap.capabilities[config.engine]}><Icon name="plus" />{launchBusy ? 'Starting evaluation…' : 'Start bounded evaluation'}</button>{!preview && <p className="caption">Inspect a read-only preview to enable execution acknowledgement.</p>}</div>
    </form><aside className="run-history"><div className="section-heading"><h2>Local runs</h2><button className="icon-button" aria-label="Refresh runs" onClick={() => setRevision(n => n + 1)}><Icon name="refresh" /></button></div><p className="caption">Factual snapshots refreshed while this page is open. Elapsed time is reported by the worker; there is no estimated percentage.</p>{feedError && <ErrorNotice message={`Live run list paused: ${feedError}`} retry={() => setRevision(n => n + 1)} />}{loading ? <Loading label="Reading local run history…" /> : !jobs.length ? <Empty title="No local runs yet"><p>Preview a trusted repository, then start a bounded evaluation. Historical imports do not appear as executed jobs.</p></Empty> : <div className="job-list">{jobs.map(item => <button key={item.id} className={`job-row ${selected === item.id ? 'selected' : ''}`} onClick={() => setSelected(item.id)}><span><strong>{item.config.target_path.split('/').filter(Boolean).at(-1) || item.id.slice(0, 8)}</strong><small>{new Date(item.created_at).toLocaleString()}</small></span><Status value={item.state} /></button>)}</div>}
      {selected && <section className="job-detail" aria-live="polite">{jobError && <ErrorNotice message={`Live status unavailable: ${jobError}`} retry={() => setRevision(n => n + 1)} />}{!job && !jobError && <Loading label="Reading run status…" />}{job && <><div className="section-heading"><h3>Run evidence</h3><Status value={job.state} /></div><code className="job-id">{job.id}</code><dl className="job-facts"><div><dt>Phase</dt><dd>{job.progress?.phase || 'Not reported'}</dd></div><div><dt>Completed commands</dt><dd>{job.progress?.completed_commands ?? '—'}</dd></div><div><dt>Elapsed (reported)</dt><dd>{Number.isFinite(job.duration_seconds) ? `${job.duration_seconds.toFixed(1)} s` : '—'}</dd></div><div><dt>Engine</dt><dd>{job.config.engine}</dd></div><div><dt>Mutant bound</dt><dd>{job.config.max_mutants}</dd></div><div><dt>Budget</dt><dd>{job.config.budget_seconds} s</dd></div><div><dt>Started</dt><dd>{job.started_at ? new Date(job.started_at).toLocaleString() : 'Not started'}</dd></div><div><dt>Finished</dt><dd>{job.finished_at ? new Date(job.finished_at).toLocaleString() : 'Not finished'}</dd></div></dl>{job.error && <ErrorNotice message={job.error} />}{job.state === 'cancelling' && <p className="notice">Cancellation requested, not yet confirmed. Waiting for the worker to restore source files safely.</p>}{job.state === 'cancelled' && <p className="caption">Worker cancellation is confirmed. This is not a completed evaluation.</p>}{job.state === 'interrupted' && <p className="preview-warning">This run was interrupted. Inspect the repository and run evidence before starting again.</p>}{activeStates.has(job.state) && <button className="danger-button" type="button" disabled={job.state === 'cancelling' || cancelling || !!jobError} onClick={cancel}>{cancelling ? 'Requesting cancellation…' : job.state === 'cancelling' ? 'Awaiting safe cancellation' : 'Request cancellation'}</button>}{cancelError && <ErrorNotice message={cancelError} />}{job.dataset_id && <button className="primary" onClick={() => openDataset(job.dataset_id!)}>Open recorded results<Icon name="arrow" /></button>}<CodeBlock title="Worker log tail" value={job.log_tail} /><details><summary>Submitted configuration</summary><pre tabIndex={0}>{JSON.stringify(job.config, null, 2)}</pre></details></>}</section>}
    </aside></div>
  </section>;
}
