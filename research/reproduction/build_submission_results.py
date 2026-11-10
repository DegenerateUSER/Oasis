"""Generate submission tables/exports from verified archived catalog3 evidence.

Never launches scientific jobs or changes sources. Interim PDFs remain labelled
until the user's two final repositories are archived and independently audited.
"""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv, hashlib, io, json, math, os, re, statistics, sys, tarfile, time

ROOT = Path('/Users/tusharteotia/Documents/Codex/2026-11-07/get-a/work/oasis37-ssd-20261108/phase3')
ARCHIVE = Path('/Volumes/ HD/tushar/Oasis-37-direct-exfat-20261108/ssd-run/phase3')
OUTPUT = ROOT.parents[2] / 'outputs/oasis-submission-20261109'
SCORED = {'killed_assert', 'killed_error', 'survived'}


def read(f): return json.loads(f.read_text())
def sha(f): return hashlib.sha256(f.read_bytes()).hexdigest()
def tex(s):
    return str(s).replace('\\', r'\textbackslash{}').replace('&', r'\&').replace('%', r'\%').replace('_', r'\_').replace('#', r'\#')
def pct(x): return 'n.a.' if x is None else f'{100*x:.1f}\\%'
def number(x): return f'{x:,}' if isinstance(x, int) else str(x)
def save(f, data):
    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(f.name + '.tmp')
    with tmp.open('w') as out: json.dump(data, out, indent=2); out.write('\n'); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, f)
def text(f, s):
    f.parent.mkdir(parents=True, exist_ok=True); tmp = f.with_name(f.name + '.tmp'); tmp.write_text(s); os.replace(tmp, f)
def write_csv(f, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r)); f.parent.mkdir(parents=True, exist_ok=True)
    with f.open('w', newline='') as out:
        w = csv.DictWriter(out, fields); w.writeheader(); w.writerows(rows)
def table(f, caption, label, columns, header, rows, footer=''):
    body = '\n'.join(' & '.join(map(str, r)) + r'\\' for r in rows)
    text(OUTPUT/f, '\\begin{table}[ht]\n\\caption{'+caption+'}\\label{'+label+'}\n\\small\\begin{tabularx}{\\linewidth}{@{}'+columns+'@{}}\\toprule\n'+header+r'\\\midrule'+'\n'+body+'\n'+r'\bottomrule\end{tabularx}'+'\n'+footer+'\n\\end{table}\n')


def evidence(report, archive, checksum):
    cache = ARCHIVE / 'reports/submission-cache' / (report['repository'].replace('/', '__') + '.json')
    if cache.exists():
        d = read(cache)
        if d.get('archive_sha256') == checksum: return d
    commands = []; cases = []; edits = set()
    with tarfile.open(archive, 'r:gz') as tf:
        for member in tf:
            match = re.fullmatch(r'results/scope-(\d+)/core/results\.(manifest\.json|csv)', member.name)
            if not match: continue
            index = int(match[1]); scope = report['scopes'][index]
            stream = tf.extractfile(member)
            if match[2] == 'csv':
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8')):
                    if row.get('record_type') != 'mutant': continue
                    row = {k: v.replace(str(ROOT), '[campaign-root]') if isinstance(v, str) else v for k, v in row.items()}
                    row.update(repository=report['repository'], scope_index=index, selected_module=scope['module'], archive_sha256=checksum)
                    cases.append(row)
                    if row['test_status'] in SCORED: edits.add(row['mutant_id'])
            else:
                manifest = json.load(stream)
                for module in manifest.get('modules', []):
                    first_test = False; first_validation = False
                    for i, event in enumerate(module.get('command_events', [])):
                        cmd = event['argv'][1] if len(event.get('argv', [])) > 1 else 'other'
                        if cmd == 'init': phase = 'Initialization'
                        elif cmd == 'test' and not first_test: phase = 'Unmutated test'; first_test = True
                        elif cmd == 'validate' and not first_validation: phase = 'Unmutated validation'; first_validation = True
                        elif cmd == 'validate': phase = 'Mutant validation'
                        elif cmd == 'test': phase = 'Mutant test'
                        else: phase = 'Other'
                        commands.append({'repository': report['repository'], 'scope_index': index, 'module': scope['module'],
                                         'event_index': i, 'phase': phase, 'command': ' '.join(event['argv']),
                                         'duration_seconds': event.get('duration_seconds'), 'returncode': event.get('returncode'),
                                         'timed_out': event.get('timed_out', False), 'archive_sha256': checksum})
    d = {'archive_sha256': checksum, 'commands': commands, 'cases': cases, 'distinct_scored_edit_ids': sorted(edits)}
    save(cache, d); return d


def main():
    assert ARCHIVE.stat().st_dev == 16777239
    analysis = read(ARCHIVE/'reports/analysis/catalog3-interim.json'); audit = read(ARCHIVE/'reports/integrity/summary.json')
    states = read(ROOT/'control/expansion-status.json')['repositories']; current = read(ROOT/'control/expansion-current.json')
    cutoff = read(ROOT/'control/user-deadline-cutoff.json'); plan = read(ROOT/'control/expansion-plan.json')['repositories']
    freeze = read(ROOT/'control/catalog3-freeze.json')
    for f, expected in freeze['code_sha256'].items(): assert sha(ROOT/'framework-v3/src/tfmutate'/f) == expected
    reports = [read(f) for f in (ARCHIVE/'reports/repositories').glob('*.json') if not f.name.startswith('._') and states.get(read(f)['repository'], {}).get('state') == 'archived']
    assert len(reports) == analysis['archived_repositories'] == audit['repositories_verified']
    assert analysis['all_operators']['scored_mutants'] == audit['scored_mutants_verified']
    reports.sort(key=lambda r: r['repository'].lower()); primary = {r['repository'].lower() for r in reports if r['scored_mutants'] > 0}
    all_cases = []; commands = []; scope_rows = []; edit_ids = set(); repos = []
    audit_by_name = {r['repository']: r for r in audit['repositories']}
    for report in reports:
        name = report['repository']; state = states[name]; audited = audit_by_name[name]
        assert state['archive_sha256'] == audited['sha256']
        d = evidence(report, Path(state['archive']), state['archive_sha256'])
        all_cases.extend(d['cases']); commands.extend(d['commands']); edit_ids.update((name, m) for m in d['distinct_scored_edit_ids'])
        repos.append({'repository': name, 'cohort': report['entry']['kind'], 'engine': state.get('engine'),
                      'upstream_commit': report['entry'].get('commit'), 'historically_adapted_revision': report['entry'].get('adapted_revision', ''),
                      'selected_scopes': report['scope_count'], 'baseline_passed': report['baseline_passed'],
                      'baseline_blocked': report['baseline_blocked_or_unavailable'], 'scored_mutants': report['scored_mutants'],
                      'all_selected_baselines_passed': report['baseline_passed'] == report['scope_count'], 'archive_sha256': state['archive_sha256']})
        for s in report['scopes']:
            scope_rows.append({'repository': name, 'scope_index': s['scope_index'], 'module': s['module'], 'test_directory': s['test_directory'],
                               'baseline': s['native_gates']['baseline'], 'source_restored': s['source_restored'],
                               'row_status_counts': json.dumps(s['row_status_counts'], sort_keys=True)})
    counts = Counter(r['test_status'] for r in all_cases)
    n = sum(counts[k] for k in SCORED); assert n == analysis['all_operators']['scored_mutants']
    generated = len(all_cases); excluded = generated - n
    complete = all(states.get(name, {}).get('state') == 'archived' for name in cutoff['allowed_remaining_repositories']) and current.get('pid') is None and current['state'] == 'authorized_cutoff_native_evaluation_finished'
    full = sum(r['scored_mutants'] > 0 and r['all_selected_baselines_passed'] for r in repos)
    partial = len(primary) - full; no_score = len(repos) - len(primary)
    started = len(states); unrun = len(plan) - started; preparation_failed = sum(s['state'] == 'failed' for s in states.values())
    baseline_pass = sum(r['baseline_passed'] for r in repos); baseline_blocked = sum(r['baseline_blocked'] for r in repos)
    identity = read(ARCHIVE/'reports/analysis/version-separated-identities.json'); historical = set(identity['historical_catalog2_identities'])
    subset = {'legacy12': analysis['legacy12_subset'], 'new4': analysis['new4_subset']}
    status = 'Final deadline-cutoff dataset' if complete else 'INTERIM: final authorized runs remain in progress; not submission-ready'
    values = {'DatasetStatus': status, 'PlannedRepos': len(plan), 'ArchivedRepos': len(repos), 'ScoredRepos': len(primary),
              'FullCoverageRepos': full, 'PartialCoverageRepos': partial, 'UnscoredRepos': no_score,
              'TriedRepos': started, 'UnrunRepos': unrun, 'PreparationFailedRepos': preparation_failed,
              'CompletedScopes': len(scope_rows), 'PassingBaselines': baseline_pass, 'BlockedBaselines': baseline_blocked,
              'GeneratedCases': generated, 'NScored': n, 'AssertionKills': counts['killed_assert'], 'RuntimeKills': counts['killed_error'],
              'Survivors': counts['survived'], 'ExcludedCases': excluded, 'NoopCases': counts['no_op'],
              'UnresolvedCases': counts['scope_unresolved'], 'TimeoutCases': counts['timeout'],
              'OtherExcluded': excluded - counts['no_op'] - counts['scope_unresolved'] - counts['timeout'],
              'AssertionPct': pct(counts['killed_assert']/n if n else None), 'CombinedPct': pct((counts['killed_assert']+counts['killed_error'])/n if n else None),
              'UnionScoredRepos': len(primary|historical), 'DistinctScoredEdits': len(edit_ids),
              'LegacyScored': subset['legacy12']['scored_mutants'], 'NewScored': subset['new4']['scored_mutants'],
              'BooleanScored': analysis['per_operator']['MUT-CFG-001']['scored_mutants'],
              'BooleanShare': pct(analysis['per_operator']['MUT-CFG-001']['scored_mutants']/n if n else None),
              'VerifiedSourceFiles': audit['source_files_verified'], 'VerifiedArchiveMembers': audit['members_verified'],
              'MacroPct': pct(analysis['macro_combined_kill_fraction']), 'MedianRepoPct': pct(analysis['median_repository_combined_kill_fraction'])}
    text(OUTPUT/'metrics.tex', '% Generated only from independently verified archived catalog3 evidence.\n'+'\n'.join('\\newcommand{\\'+k+'}{'+str(v)+'}' for k,v in values.items())+'\n')
    table('primary-overview.tex', 'Primary catalog3 dataset at the declared time cutoff; only archived repositories enter mutation totals.', 'tab:overview', 'Xr', 'Disposition & Count',
          [('Planned unique repositories', len(plan)), ('Archived completed repository attempts', len(repos)), ('Scored repositories: all selected baselines pass', full), ('Scored repositories: some selected baselines blocked', partial), ('Completed attempts without scored mutants', no_score), ('Active repository attempts', sum(d['state'] not in {'archived','failed'} for d in states.values())), ('Preparation failures (retries cancelled)', preparation_failed), ('Repositories not started before cutoff', unrun), ('Passing / blocked completed-scope baselines', f'{baseline_pass} / {baseline_blocked}'), ('Scored / excluded mutant cases', f'{n} / {excluded}')])
    table('primary-families.tex', 'Operator-family outcomes within catalog3. A: assertion kill; E: runtime-error kill; S: survivor. These rows partition scored cases.', 'tab:families', 'Xrrrrr', r'Family & $N$ & $A$ & $E$ & $S$ & $D_A$',
          [(tex(k.title()), d['scored_mutants'], d['assertion_kills'], d['runtime_kills'], d['survivors'], pct(d['assertion_kill_fraction'])) for k,d in analysis['per_family'].items()])
    table('primary-subsets.tex', 'Catalog3 subsets share the same execution environment and binding resolver. This is not a catalog2-versus-catalog3 rerun.', 'tab:subsets', 'Xrrrrr', r'Subset & $N$ & $A$ & $E$ & $S$ & $MS$',
          [(label, d['scored_mutants'], d['assertion_kills'], d['runtime_kills'], d['survivors'], pct(d['combined_kill_fraction'])) for label,d in [('Retained 12 operators',subset['legacy12']),('Added 4 operators',subset['new4'])]])
    table('primary-operators.tex', 'All 16 catalog 3 operator identifiers, including operators with no scored cases. Excl. includes no-op, unresolved, invalid, timeout or execution-error mutant records, as applicable; module dispositions are excluded.', 'tab:operatorresults', 'Xrrrrrr', r'Identifier & Generated & $N$ & $A$ & $E$ & $S$ & Excl.',
          [(r'\code{'+tex(k)+'}', sum(d['status_counts'].values()), d['scored_mutants'], d['assertion_kills'], d['runtime_kills'], d['survivors'],sum(d['status_counts'].values())-d['scored_mutants']) for k,d in analysis['per_operator'].items()])
    labels = {'original23_adapted':'Historical23, adapted sources', 'original37':'Original37 additions', 'reserve':'Technically prequalified reserves'}
    table('primary-cohorts.tex', 'Completed primary-study repositories by pre-existing admission cohort. Cohorts are not randomized or matched.', 'tab:cohorts', 'Xrrrr', r'Admission cohort & Completed & Scored repos & Cases $N$ & $D_A$',
          [(labels[k],d['repositories'],d['scored_repositories'],d['scored_mutants'],pct(d['assertion_kill_fraction'])) for k,d in analysis['cohorts'].items()])
    costs = defaultdict(list)
    for r in commands:
        if isinstance(r['duration_seconds'], (int,float)): costs[r['phase']].append(r['duration_seconds'])
    cost_rows = []; cost_data = {}
    for label in ['Initialization','Unmutated test','Unmutated validation','Mutant validation','Mutant test']:
        x = sorted(costs[label]); d = {'commands':len(x),'sum_seconds':sum(x),'median_seconds':statistics.median(x) if x else None,'p95_seconds':x[max(0,math.ceil(.95*len(x))-1)] if x else None};cost_data[label]=d
        cost_rows.append((label,len(x),f'{sum(x):,.1f}',f'{statistics.median(x):.2f}' if x else 'n.a.',f'{d["p95_seconds"]:.2f}' if x else 'n.a.'))
    table('primary-costs.tex', 'Observed primary-study native command costs in seconds, including failed commands and timeouts. Interrupted attempts and the separate baseline probe are excluded. Sums overlap across lanes and are not wall time.', 'tab:costs','Xrrrr','Phase & Commands & Sum (s) & Median (s) & P95 (s)',cost_rows)
    dispositions=[]
    for entry in plan:
        name=entry['repository'];state=states.get(name);r=next((r for r in repos if r['repository']==name),None)
        dispositions.append({'repository':name,'cohort':entry['kind'],'upstream_commit':entry.get('commit'),'disposition':'not_run_user_deadline_cutoff' if state is None else state['state'], 'retry_cancelled':bool(state and state['state']=='failed'),'scored_mutants':r['scored_mutants'] if r else '', 'selected_scope_attempts_completed':r['selected_scopes'] if r else state.get('completed_scopes',0) if state else 0})
    data_dir=OUTPUT/'catalog3-study';data_dir.mkdir(exist_ok=True)
    for name,rows in [('repositories.csv',repos),('all95-dispositions.csv',dispositions),('scopes.csv',scope_rows),('mutant-cases.csv',all_cases),('command-events.csv',commands)]:write_csv(data_dir/name,rows)
    summary={'epoch':time.time(),'status':'final' if complete else 'interim_pending_final_authorized_repositories','submission_ready':complete,'frozen_tool_version':'0.3.0-research.1','catalog_version':'3','counts':values,'mutant_status_counts':dict(counts),'costs':cost_data,'integrity_audit':{k:v for k,v in audit.items() if k!='repositories'},'version_policy':'Primary catalog3, historical catalog2 and matched123 remain separate. Union repository identity count is not a pooled mutation denominator.','source_export_policy':'Native CSV content retained; campaign-local absolute paths replaced with[campaign-root] in publication exports; original bytes preserved in SHA-verified external archives.','cutoff_policy':'Time-based user cutoff set before final LangChainGCP/n8n outcomes; original95plan preserved, pending repairs and other repositories not continued.','cancelled_retry_reports':['AzureproviderHTTP504','CircleCI-Public/server-terraform','Worklytics/psoxy','stardog-oss/stardog-terraform-starters']}
    save(data_dir/'summary.json',summary);save(ARCHIVE/'reports/submission/latest-summary.json',summary)
    save(data_dir/'catalog3-freeze.json',freeze)
    text(OUTPUT/'DATASET-STATUS.txt',status+'\nGenerated UTC '+datetime.now(timezone.utc).isoformat()+'\nPrimary totals include only archived and independently verified completed repository attempts.\n')
    print(json.dumps({'status':summary['status'],'archived':len(reports),'scored_repositories':len(primary),'scored_mutants':n,'excluded_mutants':excluded,'case_exports':len(all_cases),'command_exports':len(commands),'output':str(OUTPUT)}),flush=True)


if __name__=='__main__':main()
