"""Interim, version-separated analysis of archived catalog3 repositories.

Read-only with respect to execution and sources. No native jobs are launched.
The legacy12 view is a subset of catalog3 outcomes, not a catalog2 rerun.
Writer receipts are checked here; fresh archive-byte/member audits remain a
separate final requirement. Incomplete repositories never enter these totals.
"""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import io
import json
import os
import statistics
import sys
import time

ROOT = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'framework-v3/src'))
SCORED = ('killed_assert', 'killed_error', 'survived')


def read(path):
    return json.loads(path.read_text())


def canonical(name):
    return name.removeprefix('https://github.com/').removesuffix('.git').strip('/').casefold()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def metrics(counts):
    scored = sum(counts.get(status, 0) for status in SCORED)
    assertion = counts.get('killed_assert', 0)
    runtime = counts.get('killed_error', 0)
    return {'status_counts': dict(sorted(counts.items())), 'scored_mutants': scored,
            'assertion_kills': assertion, 'runtime_kills': runtime,
            'survivors': counts.get('survived', 0),
            'assertion_kill_fraction': assertion / scored if scored else None,
            'combined_kill_fraction': (assertion + runtime) / scored if scored else None}


def main():
    freeze = read(ROOT / 'control/catalog3-freeze.json')
    assert freeze['catalog_version'] == '3'
    for relative, digest in freeze['code_sha256'].items():
        assert hashlib.sha256((ROOT / 'framework-v3/src/tfmutate' / relative).read_bytes()).hexdigest() == digest
    from tfmutate.mutators import CATALOG, CATALOG_VERSION
    assert CATALOG_VERSION == freeze['catalog_version'] and len(CATALOG) == 16
    new_ids = set(freeze['new_operators'])
    legacy_ids = set(CATALOG) - new_ids
    assert len(new_ids) == 4 and len(legacy_ids) == 12
    config = read(ROOT / 'control/ssd-config.json')
    archive = Path(config['archive_root'])
    assert archive.stat().st_dev == config['external_device']
    plan = read(ROOT / 'control/expansion-plan.json')
    entries = {canonical(e['repository']): e for e in plan['repositories']}
    assert len(entries) == len(plan['repositories']) == 95
    state = read(ROOT / 'control/expansion-status.json')
    states = {canonical(name): value for name, value in state['repositories'].items()}
    global_counts = Counter()
    per_operator = {name: Counter() for name in CATALOG}
    operator_repos = {name: set() for name in CATALOG}
    per_family = {}
    family_repos = {}
    cohorts = {}
    repositories = []
    seen = set()
    pending_reports = []
    for path in sorted((archive / 'reports/repositories').glob('*.json')):
        if path.name.startswith('._'):
            continue
        report = read(path)
        name = report['repository']
        identity = canonical(name)
        assert identity in entries and identity not in seen
        seen.add(identity)
        assert report['catalog_version'] == '3' and report['tool_version'] == freeze['tool_version']
        assert report['entry'] == entries[identity]
        assert report['status'] == 'all_selected_scope_attempts_completed'
        assert report['assertions_changed_in_this_phase'] is False
        assert len(report['scopes']) == report['scope_count']
        assert all(s['source_restored'] for s in report['scopes'])
        assert sum(s['native_gates']['baseline'] == 'passed' for s in report['scopes']) == report['baseline_passed']
        assert report['baseline_passed'] + report['baseline_blocked_or_unavailable'] == report['scope_count']
        receipt_path = archive / 'control/receipts' / (name.replace('/', '__') + '__catalog3.json')
        recorded_state = states.get(identity, {})
        if recorded_state.get('state') != 'archived' or not receipt_path.exists():
            pending_reports.append(name)
            continue
        receipt = read(receipt_path)
        assert recorded_state['archive_verified']
        assert receipt['sha256'] == recorded_state['archive_sha256']
        assert Path(receipt['archive']).stat().st_size == receipt['bytes']
        assert receipt['verified_members'] > 0
        assert receipt['summary'] == report
        totals = Counter(report['row_status_counts'])
        mutant_totals = Counter()
        legacy = Counter()
        added = Counter()
        for operator, outcomes in report['operator_outcomes'].items():
            assert operator in CATALOG
            assert all(isinstance(v, int) and v >= 0 for v in outcomes.values())
            count = Counter(outcomes)
            mutant_totals.update(count)
            per_operator[operator].update(count)
            (legacy if operator in legacy_ids else added).update(count)
            family = CATALOG[operator].category
            per_family.setdefault(family, Counter()).update(count)
            if metrics(count)['scored_mutants']:
                operator_repos[operator].add(identity)
                family_repos.setdefault(family, set()).add(identity)
        measured = metrics(mutant_totals)
        assert measured['scored_mutants'] == report['scored_mutants'] == metrics(totals)['scored_mutants']
        assert metrics(legacy)['scored_mutants'] + metrics(added)['scored_mutants'] == measured['scored_mutants']
        global_counts.update(totals)
        cohort = report['entry']['kind']
        group = cohorts.setdefault(cohort, {'repositories': 0, 'scored_repositories': 0, 'counts': Counter()})
        group['repositories'] += 1
        group['scored_repositories'] += measured['scored_mutants'] > 0
        group['counts'].update(mutant_totals)
        repositories.append({'repository': name, 'canonical_identity': identity, 'cohort': cohort,
                             'scope_count': report['scope_count'], 'baseline_passed': report['baseline_passed'],
                             'baseline_blocked': report['baseline_blocked_or_unavailable'],
                             'all_operators': measured, 'legacy12_subset': metrics(legacy),
                             'new4_subset': metrics(added), 'archive_sha256': receipt['sha256']})

    legacy_counts = Counter()
    new_counts = Counter()
    for operator, outcomes in per_operator.items():
        (legacy_counts if operator in legacy_ids else new_counts).update(outcomes)
    scored_repositories = [r for r in repositories if r['all_operators']['scored_mutants']]
    macro = [r['all_operators']['combined_kill_fraction'] for r in scored_repositories]
    data = {'epoch': time.time(), 'status': 'interim_archived_repositories_only',
            'catalog_version': '3', 'tool_version': freeze['tool_version'],
            'admitted_unique_repositories': len(entries), 'archived_repositories': len(repositories),
            'scored_repositories': len(scored_repositories),
            'completed_scope_attempts': sum(r['scope_count'] for r in repositories),
            'baseline_passed': sum(r['baseline_passed'] for r in repositories),
            'baseline_blocked': sum(r['baseline_blocked'] for r in repositories),
            'all_operators': metrics(global_counts),
            'legacy12_subset': {**metrics(legacy_counts), 'operator_ids': sorted(legacy_ids),
                                'scored_repositories': sum(r['legacy12_subset']['scored_mutants'] > 0 for r in repositories)},
            'new4_subset': {**metrics(new_counts), 'operator_ids': sorted(new_ids),
                            'scored_repositories': sum(r['new4_subset']['scored_mutants'] > 0 for r in repositories)},
            'per_operator': {operator: {**metrics(outcomes), 'family': CATALOG[operator].category,
                                      'scored_repositories': len(operator_repos[operator])}
                             for operator, outcomes in sorted(per_operator.items())},
            'per_family': {family: {**metrics(outcomes), 'scored_repositories': len(family_repos.get(family, set()))}
                           for family, outcomes in sorted(per_family.items())},
            'cohorts': {name: {'repositories': group['repositories'], 'scored_repositories': group['scored_repositories'],
                               **metrics(group['counts'])} for name, group in sorted(cohorts.items())},
            'macro_combined_kill_fraction': statistics.mean(macro) if macro else None,
            'median_repository_combined_kill_fraction': statistics.median(macro) if macro else None,
            'repositories': repositories, 'reports_awaiting_verified_archive': pending_reports,
            'recorded_state_counts': dict(Counter(s['state'] for s in states.values())),
            'policies': ['Legacy12 is an operator subset under the same catalog3 engine/resolver/inputs; it is not an independent catalog2 rerun.',
                         'New4 and legacy12 scored mutant counts partition outcomes; their repository counts overlap and must not be added.',
                         'Zero scored denominator yields null, not a zero mutation percentage.',
                         'Assertion and runtime kills remain separate; timeouts, unresolved, invalid and no-op outcomes are unscored.',
                         'Canaries, interrupted attempts, migration fixtures and unarchived results are excluded.',
                         'Historically adapted original23 sources are grouped separately. Historical catalog2 and matched123-case results are not pooled.',
                         'Recorded writer receipts are checked here. A fresh archive-byte/member and raw-case/source audit is still required.',
                         'Convenience sampling and clustered ownership/providers limit generalizability.']}
    assert data['all_operators']['scored_mutants'] == metrics(legacy_counts)['scored_mutants'] + metrics(new_counts)['scored_mutants']
    output = archive / 'reports/analysis'
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(data['epoch']))
    payload = json.dumps(data, indent=2, allow_nan=False) + '\n'
    write(output / (stamp + '-catalog3-interim.json'), payload)
    write(output / 'catalog3-interim.json', payload)
    table = io.StringIO()
    writer = csv.writer(table)
    writer.writerow(['repository', 'cohort', 'completed_scopes', 'baseline_passed', 'baseline_blocked',
                     'scored_mutants', 'assertion_kills', 'runtime_kills', 'survivors',
                     'legacy12_scored', 'new4_scored'])
    for row in repositories:
        m = row['all_operators']
        writer.writerow([row['repository'], row['cohort'], row['scope_count'], row['baseline_passed'],
                         row['baseline_blocked'], m['scored_mutants'], m['assertion_kills'], m['runtime_kills'],
                         m['survivors'], row['legacy12_subset']['scored_mutants'], row['new4_subset']['scored_mutants']])
    write(output / 'catalog3-interim-repositories.csv', table.getvalue())
    print(json.dumps({'archived': len(repositories), 'scored_repositories': len(scored_repositories),
                      'scored_mutants': data['all_operators']['scored_mutants'],
                      'legacy12': data['legacy12_subset'], 'new4': data['new4_subset'],
                      'per_family': data['per_family']}))


if __name__ == '__main__':
    main()
