import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from './api';
import type { Bootstrap, Dataset } from './types';
import { ErrorNotice, Icon } from './ui';

export function ImportPanel({ bootstrap, imported, close }: { bootstrap: Bootstrap; imported: (id: string) => void; close: () => void }) {
  const [source, setSource] = useState(bootstrap.sources[0]?.id || '');
  const [name, setName] = useState(''); const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { ref.current?.querySelector<HTMLElement>('button')?.focus(); }, []);
  async function perform(body: { source_id: string } | { name: string; csv: string }) {
    setBusy(true); setError('');
    try { const result = await api<Dataset>('/api/import', { method: 'POST', body: JSON.stringify(body) }); imported(result.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Import failed.'); }
    finally { setBusy(false); }
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) { setError('Choose a CSV file first.'); return; }
    if (file.size > 8 * 1024 * 1024) { setError('CSV must be at most 8 MiB. Export a smaller selection and try again.'); return; }
    try { await perform({ name: name.trim() || file.name, csv: await file.text() }); }
    catch { setError('The file could not be read as UTF-8 text. Choose a readable CSV file.'); }
  }
  return <section className="import-panel" ref={ref} aria-labelledby="import-title" onKeyDown={event => { if (event.key === 'Escape') close(); }}><div className="section-heading"><div><h2 id="import-title">Bring results into the workspace</h2><p className="caption">Imports preserve the source data. They are not verified reruns.</p></div><button className="icon-button" aria-label="Close import" onClick={close}><Icon name="close" /></button></div><div className="import-columns"><div><h3>Registered historical results</h3><p className="caption">Load an original CSV already registered with the local server. Historical scores have not been revalidated.</p>{bootstrap.sources.length ? <><label>Historical source<select value={source} onChange={event => setSource(event.target.value)}>{bootstrap.sources.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><p className="caption">{bootstrap.sources.find(item => item.id === source)?.description}</p><button disabled={busy || !source} onClick={() => perform({ source_id: source })}>{busy ? 'Importing…' : 'Import historical source'}</button></> : <p className="quiet-empty">No historical sources are registered in this installation. Upload a CSV instead.</p>}</div><form onSubmit={upload}><h3>Upload a results CSV</h3><label>Dataset name<input maxLength={160} value={name} onChange={event => setName(event.target.value)} placeholder="Optional; defaults to the filename" /></label><label>CSV file<input type="file" accept=".csv,text/csv" onChange={event => setFile(event.target.files?.[0] || null)} required /></label><p className="caption">Up to 8 MiB / 50,000 rows. Required columns: repo_name, mutant_id, operator_id, operator_category, test_status, validate_status.</p><button type="submit" disabled={busy || !file}><Icon name="upload" />{busy ? 'Importing…' : 'Import uploaded CSV'}</button></form></div>{error && <ErrorNotice message={error} />}</section>;
}
