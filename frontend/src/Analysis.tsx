import { useMemo, useState } from 'react';
import type { Dataset, FilterKey, Filters, Metrics } from './types';
import { formatScore, runtimeData, survivalData } from './data';
import { statusLabels } from './ui';

type Select = (key: FilterKey, value: string) => void;
const outcomeColors = ['var(--assert)', 'var(--engine)', 'var(--survived)'];
const outcomes = ['killed_assert', 'killed_error', 'survived'] as const;

function Flow({ metrics: m, select, filters }: { metrics: Metrics; select: Select; filters: Filters }) {
  const total = m.generated_mutants, excluded = total - m.scored_mutants;
  const scale = total ? 166 / total : 0;
  const values = [m.killed_assert, m.killed_error, m.survived];
  const ribbon = (x1: number, x2: number, start: number, end: number, h: number) => `M${x1},${start}C${(x1+x2)/2},${start} ${(x1+x2)/2},${end} ${x2},${end}L${x2},${end+h}C${(x1+x2)/2},${end+h} ${(x1+x2)/2},${start+h} ${x1},${start+h}Z`;
  let used = 0;
  let destination = 62;
  return <section className="flow-section"><div className="section-heading"><h2>From generated to scored</h2><span>Select an outcome to inspect its evidence</span></div>
    <svg className="flow" viewBox="0 0 850 360" role="group" aria-labelledby="flow-title flow-description"><title id="flow-title">Mutation outcome flow</title><desc id="flow-description">{total} generated mutants. {m.scored_mutants} scored: {m.killed_assert} assertion kills, {m.killed_error} engine-error kills and {m.survived} survivors. {excluded} excluded. Flow widths are proportional to generated counts.</desc>
      <text x="14" y="23" className="svg-label">Generated</text><text x="14" y="45" className="svg-value">{total.toLocaleString()}</text>
      <text x="302" y="23" className="svg-label">Scored denominator</text><text x="302" y="45" className="svg-value">{m.scored_mutants.toLocaleString()}</text>
      {total > 0 && <><path d={ribbon(34, 314, 62, 62, m.scored_mutants * scale)} fill="var(--accent)" opacity=".14" /><rect x="14" y="62" width="20" height="166" rx="3" fill="var(--accent)" /><rect x="314" y="62" width="17" height={m.scored_mutants * scale} rx="2" fill="var(--accent)" />
        {excluded > 0 && <><path d={ribbon(34, 314, 62 + m.scored_mutants * scale, 82 + m.scored_mutants * scale, excluded * scale)} fill="var(--excluded)" opacity=".23" /><rect x="314" y={82 + m.scored_mutants * scale} width="17" height={excluded * scale} rx="2" fill="var(--excluded)" /></>}
        {values.map((count, i) => {
          const start = 62 + used * scale; const end = destination; used += count;
          destination += Math.max(count * scale, 40) + 12;
          const choose = () => select('status', filters.status === outcomes[i] ? '' : outcomes[i]);
          return <g key={outcomes[i]} role="button" tabIndex={0} aria-label={`${statusLabels[outcomes[i]]}: ${count}. Filter these records.`} aria-pressed={filters.status === outcomes[i]} onClick={choose} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } }} style={{ cursor: 'pointer' }}><path d={ribbon(331, 616, start, end, count * scale)} fill={outcomeColors[i]} opacity=".22" /><rect x="616" y={end} width="15" height={count * scale} rx="2" fill={outcomeColors[i]} /><text x="646" y={end + 12} className="svg-label">{statusLabels[outcomes[i]]}</text><text x="646" y={end + 34} className="svg-value" fill={outcomeColors[i]}>{count.toLocaleString()}</text></g>;
        })}</>}
      {!total && <text x="14" y="115" className="svg-label">No generated mutants in this selection.</text>}
    </svg>
    <div className="mobile-flow" role="group" aria-label="Mobile mutation outcome flow">
      <dl className="mobile-flow-totals"><div><dt>Generated</dt><dd>{total.toLocaleString()}</dd></div><div><dt>Scored denominator</dt><dd>{m.scored_mutants.toLocaleString()}</dd></div></dl>
      <p className="caption">Outcome bars share the generated-mutant denominator.</p>
      <div className="mobile-flow-outcomes">{outcomes.map((status, i) => <button key={status} className="mobile-flow-outcome" aria-label={`${statusLabels[status]}: ${m[status]}. Filter these records.`} aria-pressed={filters.status === status} onClick={() => select('status', filters.status === status ? '' : status)}><span className="mobile-flow-label">{statusLabels[status]}<b>{m[status].toLocaleString()}</b></span><span className="mobile-flow-bar" aria-hidden="true"><i style={{ background: outcomeColors[i], width: total ? `${m[status] / total * 100}%` : '0%' }} /></span></button>)}</div>
      {!total && <p className="caption">No generated mutants in this selection.</p>}
    </div>
    <div className="flow-legend">{outcomes.map((status, i) => <button key={status} className={`legend-button ${filters.status === status ? 'selected' : ''}`} aria-pressed={filters.status === status} onClick={() => select('status', filters.status === status ? '' : status)}><i style={{ background: outcomeColors[i] }} />{statusLabels[status]}<b>{m[status]}</b></button>)}</div>
    <div className="excluded-line"><span><i className="swatch excluded" />{excluded.toLocaleString()} excluded from score</span><div>{Object.entries(m.excluded_statuses).map(([status, count]) => <button key={status} aria-pressed={filters.status === status} onClick={() => select('status', filters.status === status ? '' : status)}>{statusLabels[status] || status}<b>{count}</b></button>)}</div></div>
    {m.module_baseline_records > 0 && <p className="caption">{m.module_baseline_records} module baseline record(s) are separate from generated mutants.</p>}
  </section>;
}

function Comparison({ title, groups, field, filters, select }: { title: string; groups: Record<string, Metrics>; field: FilterKey; filters: Filters; select: Select }) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(groups).filter(([, m]) => m.total_records > 0).sort((a, b) => b[1].generated_mutants - a[1].generated_mutants || a[0].localeCompare(b[0]));
  const maximum = Math.max(0, ...entries.map(([, m]) => m.generated_mutants));
  return <section className="comparison"><div className="section-heading"><h2>{title}</h2><span>{entries.length} with records</span></div>
    {!entries.length ? <p className="muted">No matching groups.</p> : <><div className="bar-axis"><span>Generated count</span><div><span>0</span><span>{(maximum/2).toLocaleString(undefined, { maximumFractionDigits: 1 })}</span><span>{maximum.toLocaleString()}</span></div><span>Score</span></div><div className="bar-list">{entries.slice(0, expanded ? undefined : 7).map(([name, m]) => <button className={`comparison-row ${filters[field] === name ? 'selected' : ''}`} aria-pressed={filters[field] === name} key={name} onClick={() => select(field, filters[field] === name ? '' : name)} title={`${name || 'Unnamed'}: ${m.generated_mutants} generated, ${m.scored_mutants} scored. Mutation score ${formatScore(m.mutation_score)}`}><span className="group-name">{name || '(unnamed)'}</span><span className="bar-track"><span className="bar-total" style={{ width: maximum ? `${m.generated_mutants / maximum * 100}%` : '0%' }}>{outcomes.map((status, i) => <i key={status} style={{ width: m.generated_mutants ? `${m[status] / m.generated_mutants * 100}%` : '0%', background: outcomeColors[i] }} />)}<i style={{ flex: 1, background: 'var(--excluded)' }} /></span></span><span className="group-score">{formatScore(m.mutation_score)}<small>{m.killed_assert + m.killed_error} / {m.scored_mutants}</small></span></button>)}</div>{entries.length > 7 && <button className="text-button" onClick={() => setExpanded(v => !v)}>{expanded ? 'Show fewer' : `Show all ${entries.length}`}</button>}</>}
  </section>;
}

export function Analysis({ dataset: data, filters, select, showMutants }: { dataset: Dataset; filters: Filters; select: Select; showMutants: () => void }) {
  const m = data.summary.overall;
  const reasons = useMemo(() => survivalData(data.rows), [data.rows]);
  const timing = useMemo(() => runtimeData(data.rows), [data.rows]);
  const slowest = useMemo(() => [...timing].sort((a, b) => b.seconds - a.seconds).slice(0, 6), [timing]);
  const maxSeconds = slowest[0]?.seconds || 0;
  return <>
    <div className="metric-strip"><div><strong>{formatScore(m.mutation_score)}</strong><span>Mutation score</span><small>{m.killed_assert + m.killed_error} / {m.scored_mutants} scored</small></div><div><strong>{formatScore(m.assertion_score)}</strong><span>Assertion score</span><small>{m.killed_assert} / {m.scored_mutants} scored</small></div><div><strong className="survivor-number">{m.survived.toLocaleString()}</strong><span>Survivors to investigate</span><small>Passed tests after mutation</small></div><div><strong>{(m.generated_mutants - m.scored_mutants).toLocaleString()}</strong><span>Excluded</span><small>Not in the denominator</small></div></div>
    <div className="analysis-primary"><Flow metrics={m} select={select} filters={filters} /><aside className="survivor-reasons"><div className="section-heading"><h2>Why mutations survived</h2></div><p className="caption">Recorded static classifications. Not runtime coverage or proof a fault is equivalent.</p>{reasons.length ? reasons.map(reason => <button className="reason" key={reason.label} onClick={() => { select('status', 'survived'); showMutants(); }}><span>{reason.label.replaceAll('_', ' ')}</span><strong>{reason.count}</strong></button>) : <p className="quiet-empty">No survivors in this selection.</p>}<button className="text-button" onClick={() => { select('status', 'survived'); showMutants(); }}>Inspect survivor evidence</button></aside></div>
    <p className="scoring-note">Mutation score includes assertion and engine-error kills. Assertion score counts assertion kills only. A missing denominator is shown as —, never zero percent.</p>
    <div className="comparisons"><Comparison title="By mutation category" groups={data.summary.by_category} field="category" filters={filters} select={select} /><Comparison title="By repository" groups={data.summary.by_repo} field="repo" filters={filters} select={select} /></div>
    <div className="comparisons"><Comparison title="By operator" groups={data.summary.by_operator} field="operator" filters={filters} select={select} /><section className="runtime"><div className="section-heading"><h2>Recorded runtime</h2><span>seconds per record</span></div>{timing.length ? <><p className="caption">{timing.length.toLocaleString()} of {data.rows.length.toLocaleString()} selected records contain total_seconds. Slowest recorded rows; not a time series.</p><div className="runtime-axis"><span>0 s</span><span>{maxSeconds.toLocaleString(undefined, { maximumFractionDigits: 2 })} s</span></div>{slowest.map((item, index) => <div className="runtime-row" key={`${item.label}-${index}`}><span title={item.label}>{item.label}</span><div><i style={{ width: maxSeconds ? `${item.seconds / maxSeconds * 100}%` : '0%' }} /></div><strong>{item.seconds.toFixed(2)} s</strong></div>)}</> : <p className="quiet-empty">No timing fields were recorded. Runtime is unavailable, not zero.</p>}</section></div>
  </>;
}
