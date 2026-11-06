import { useCallback, useEffect, useRef, useState } from 'react';
import { api, download, saveBlob } from './api';
import { Analysis } from './Analysis';
import { emptyFilters, filterQuery } from './data';
import { useResource, useTheme } from './hooks';
import { ImportPanel } from './Import';
import { MutantTable } from './Mutants';
import { Operators } from './Operators';
import { Runs } from './Runs';
import type { Bootstrap, Dataset, DatasetInfo, FilterKey, Filters } from './types';
import { Empty, ErrorNotice, Icon, Loading, statusLabels } from './ui';

type Page = 'overview' | 'mutants' | 'runs' | 'operators';
const pages: { id: Page; label: string }[] = [{ id: 'overview', label: 'Overview' }, { id: 'mutants', label: 'Mutants' }, { id: 'runs', label: 'Runs' }, { id: 'operators', label: 'Operators' }];
function currentPage(): Page { const hash = window.location.hash.slice(1); return pages.some(item => item.id === hash) ? hash as Page : 'overview'; }

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [theme, setTheme] = useTheme();
  const bootstrap = useResource<Bootstrap>('/api/bootstrap');
  const [revision, setRevision] = useState(0);
  const datasets = useResource<{ datasets: DatasetInfo[] }>('/api/datasets', revision);
  const [selected, setSelected] = useState(() => { try { return localStorage.getItem('oasis-dataset') || ''; } catch { return ''; } });
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const dataset = useResource<Dataset>(selected ? `/api/datasets/${encodeURIComponent(selected)}${filterQuery(filters)}` : null, revision);
  const [showImport, setShowImport] = useState(false); const [exporting, setExporting] = useState(false); const [exportError, setExportError] = useState('');
  const importTrigger = useRef<HTMLButtonElement>(null);
  const refreshDatasets = useCallback(() => setRevision(n => n + 1), []);
  useEffect(() => { const update = () => setPage(currentPage()); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []);
  useEffect(() => {
    if (!datasets.value) return;
    const available = datasets.value.datasets;
    // Reconcile only a newly fetched catalog. A newly imported ID must not be
    // replaced merely because the previous catalog is still on screen.
    setSelected(current => current && available.some(item => item.id === current)
      ? current : available[0]?.id || '');
  }, [datasets.value]);
  useEffect(() => { try { if (selected) localStorage.setItem('oasis-dataset', selected); else localStorage.removeItem('oasis-dataset'); } catch { /* Local persistence is optional. */ } }, [selected]);
  function navigate(next: Page) { window.location.hash = next; setPage(next); }
  function select(key: FilterKey, value: string) { setFilters(previous => ({ ...previous, [key]: value })); setExportError(''); }
  function chooseDataset(id: string) { setSelected(id); setFilters(emptyFilters); setExportError(''); }
  function imported(id: string) { chooseDataset(id); setShowImport(false); refreshDatasets(); navigate('overview'); }
  function closeImport() { setShowImport(false); importTrigger.current?.focus(); }
  async function exportCsv() {
    if (!dataset.value) return;
    setExporting(true); setExportError('');
    try { await download(`/api/datasets/${encodeURIComponent(selected)}/csv${filterQuery(filters)}`, `oasis-${selected}-selection.csv`); }
    catch (reason) { setExportError(reason instanceof Error ? reason.message : 'CSV export failed.'); }
    finally { setExporting(false); }
  }
  function exportJson() {
    if (!dataset.value) return;
    try { saveBlob(new Blob([JSON.stringify({ ...dataset.value, applied_filters: filters }, null, 2)], { type: 'application/json' }), `oasis-${selected}-selection.json`); }
    catch (reason) { setExportError(reason instanceof Error ? reason.message : 'JSON export failed.'); }
  }
  const info = dataset.value || datasets.value?.datasets.find(item => item.id === selected);
  const analytic = page === 'overview' || page === 'mutants';
  return <>
    <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to content</a>
    <header className="app-header"><a className="brand" href="#overview" aria-label="Oasis overview" onClick={() => navigate('overview')}><Icon name="oasis" size={26} /><span>Oasis</span><small>Signal</small></a><nav aria-label="Workspace">{pages.map(item => <button key={item.id} aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}>{item.label}</button>)}</nav><div className="header-actions"><label className="theme-control"><span className="sr-only">Color theme</span><select aria-label="Color theme" value={theme} onChange={event => setTheme(event.target.value as typeof theme)}><option value="system">System theme</option><option value="light">Light theme</option><option value="dark">Dark theme</option></select></label><button className="primary" onClick={() => navigate('runs')}><Icon name="plus" /><span>New evaluation</span></button></div></header>
    <main id="main" tabIndex={-1}>
      {bootstrap.loading && <Loading label="Connecting to the local Oasis workspace…" />}
      {bootstrap.error && <ErrorNotice message={bootstrap.error} retry={bootstrap.retry} />}
      {bootstrap.value && <><section className="dataset-toolbar" aria-label="Result source"><div className="dataset-choice"><label>Dataset<select aria-label="Dataset" value={selected} onChange={event => chooseDataset(event.target.value)} disabled={!datasets.value?.datasets.length}><option value="">{datasets.loading ? 'Loading datasets…' : datasets.value?.datasets.length ? 'Choose a dataset…' : 'No results imported'}</option>{datasets.value?.datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{info && <div className={`provenance ${info.provenance.kind === 'verified' ? 'verified' : 'unverified'}`} title={info.provenance.message}><Icon name="shield" size={14} /><span>{info.provenance.kind === 'verified' ? 'Verified local run' : info.provenance.kind === 'historical' ? 'Historical · unrevalidated' : info.provenance.kind === 'imported' ? 'Uploaded · unverified' : 'Unverified artifacts'}</span></div>}</div><div className="toolbar-actions"><button ref={importTrigger} onClick={() => setShowImport(value => !value)} aria-expanded={showImport}><Icon name="upload" />Import results</button><button aria-label="Refresh datasets" className="icon-button" onClick={refreshDatasets}><Icon name="refresh" /></button></div></section>
        {datasets.error && <ErrorNotice message={datasets.error} retry={datasets.retry} />}
        {showImport && <ImportPanel bootstrap={bootstrap.value} imported={imported} close={closeImport} />}
        {info && <div className={`provenance-note ${info.provenance.kind !== 'verified' ? 'historical-note' : ''}`}><p>{info.provenance.message}</p><span>{new Date(info.created_at).toLocaleString()}</span></div>}
        {analytic && <><div className="page-heading"><div><h1>{page === 'overview' ? 'Where the tests fall short.' : 'Inspect the exact evidence.'}</h1><p>{page === 'overview' ? 'Follow each generated fault to its outcome. Separate assertion evidence from engine failures.' : 'Every recorded mutation, its outcome, source values and available raw execution logs.'}</p></div>{dataset.value && <div className="export-actions"><button onClick={exportCsv} disabled={exporting}><Icon name="download" />{exporting ? 'Exporting…' : 'CSV'}</button><button onClick={exportJson}><Icon name="download" />JSON</button></div>}</div>
          {selected && <section className="global-filters" aria-label="Global result filters">{(['repo','category','operator','status'] as const).map(key => <label key={key}>{({ repo: 'Repository', category: 'Category', operator: 'Operator', status: 'Outcome' })[key]}<select value={filters[key]} onChange={event => select(key, event.target.value)}><option value="">All {key === 'repo' ? 'repositories' : key === 'status' ? 'outcomes' : `${key === 'category' ? 'categorie' : 'operator'}s`}</option>{(dataset.value?.filter_options?.[key] || (filters[key] ? [filters[key]] : [])).map(value => <option key={value} value={value}>{key === 'status' ? statusLabels[value] || value : value || '(unnamed)'}</option>)}</select></label>)}<label className="search-control"><span>Search records</span><div><Icon name="search" /><input type="search" value={filters.q} onChange={event => select('q', event.target.value)} placeholder="Mutant, file, value…" /></div></label><button className="clear-filters" disabled={!Object.values(filters).some(Boolean)} onClick={() => setFilters(emptyFilters)}>Clear filters</button></section>}
          {exportError && <ErrorNotice message={exportError} />}
          {dataset.loading && <Loading label="Calculating the selected evidence on the server…" />}
          {dataset.error && <ErrorNotice message={dataset.error} retry={dataset.retry} />}
          {!selected && !datasets.loading && !datasets.error && <Empty title="Start with real results."><p>Import a registered historical dataset or upload an Oasis CSV. Scores, charts and evidence will appear here only when real records are available.</p><div className="empty-actions"><button className="primary" onClick={() => setShowImport(true)}><Icon name="upload" />Import results</button><button onClick={() => navigate('runs')}>Configure an evaluation<Icon name="arrow" /></button></div><p className="caption">No hosted service, demo records or background corpus runs.</p></Empty>}
          {dataset.value && <><div className="selection-line" aria-live="polite"><span>{dataset.value.selection.filtered_rows.toLocaleString()} of {dataset.value.selection.total_rows.toLocaleString()} source records selected</span><span>Shared server score contract · schema {dataset.value.summary.schema_version}</span></div>{dataset.value.summary.validation_problems.length > 0 && <details className="validation-notice"><summary>{dataset.value.summary.validation_problems.length} data validation concern(s) · inspect before interpreting scores</summary><ul>{dataset.value.summary.validation_problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul></details>}{page === 'overview' && <Analysis dataset={dataset.value} filters={filters} select={select} showMutants={() => navigate('mutants')} />}<MutantTable key={`${selected}-${filterQuery(filters)}-${page}`} dataset={dataset.value} compact={page === 'overview'} /></>}
        </>}
        {page === 'runs' && <Runs bootstrap={bootstrap.value} refreshDatasets={refreshDatasets} openDataset={id => { chooseDataset(id); refreshDatasets(); navigate('overview'); }} />}
        {page === 'operators' && <Operators bootstrap={bootstrap.value} />}
      </>}
    </main><footer className="app-footer"><span>Oasis{bootstrap.value ? ` ${bootstrap.value.version}` : ''} · Local workspace</span><span>Evidence before confidence.</span></footer>
  </>;
}
