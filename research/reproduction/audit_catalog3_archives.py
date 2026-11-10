"""Stream archived evidence without extracting it or launching native commands.

Verifies archive/member hashes, source snapshots, manifests and raw CSV totals.
Only active scope paths count; preserved interrupted attempts are hashed but
excluded from scientific counts. --reuse still freshly hashes every archive,
then reuses an audit only for identical archive bytes and completion metadata.
"""
from pathlib import Path, PurePosixPath
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import os
import re
import shlex
import sys
import tarfile
import time

ROOT = Path(sys.argv[1]).resolve()
REUSE = '--reuse' in sys.argv[2:]
VERSION = 'archive-integrity-audit-v1'
SCORED = {'killed_assert', 'killed_error', 'survived'}
CSV_PATH = re.compile(r'results/scope-(\d{4})/core/results[.]csv')
MANIFEST_PATH = re.compile(r'results/scope-(\d{4})/core/results[.]manifest[.]json')
CAPTURE = re.compile(r'results/scope-\d{4}/job[.]json')
MAX_METADATA = 32 * 1024**2
sys.dont_write_bytecode = True


def read(path):
    return json.loads(path.read_text())


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            hasher.update(block)
    return hasher.hexdigest()


def metadata_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def one(receipt, report, freeze, destination):
    archive = Path(receipt['archive'])
    assert archive.stat().st_size == receipt['bytes']
    archive_hash = digest(archive)
    assert archive_hash == receipt['sha256']
    report_hash = metadata_digest(report)
    if REUSE and destination.exists():
        previous = read(destination)
        if (previous.get('status') == 'verified' and previous.get('audit_version') == VERSION
                and previous.get('sha256') == archive_hash and previous.get('completion_sha256') == report_hash):
            return {**previous, 'fresh_archive_hash_epoch': time.time(), 'member_audit_reused_for_identical_bytes': True}
    observed = {}
    captured = {}
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and str(path) == member.name
            assert member.name not in observed
            if member.isdir():
                raise AssertionError('Unexpected unlisted directory member: ' + member.name)
            if member.issym():
                record = {'path': member.name, 'type': 'symlink', 'target': member.linkname}
            elif member.islnk():
                target = observed[member.linkname]
                assert target['type'] == 'file'
                record = {'path': member.name, 'type': 'file', 'bytes': target['bytes'], 'sha256': target['sha256']}
            else:
                assert member.isfile()
                wanted = (member.name in {'archive-inventory.json', 'results/source-snapshot.json', 'results/completion.json'}
                          or CSV_PATH.fullmatch(member.name) or MANIFEST_PATH.fullmatch(member.name)
                          or CAPTURE.fullmatch(member.name))
                if wanted:
                    assert member.size <= MAX_METADATA
                stream = tar.extractfile(member)
                hasher = hashlib.sha256()
                chunks = []
                size = 0
                while True:
                    block = stream.read(1024**2)
                    if not block:
                        break
                    hasher.update(block)
                    size += len(block)
                    if wanted:
                        chunks.append(block)
                assert size == member.size
                record = {'path': member.name, 'type': 'file', 'bytes': size, 'sha256': hasher.hexdigest()}
                if wanted:
                    captured[member.name] = b''.join(chunks)
            observed[member.name] = {**record, 'tar_mode': member.mode}
    inventory = json.loads(captured['archive-inventory.json'])
    expected = {row['path']: row for row in inventory['files']}
    assert len(expected) == len(inventory['files'])
    assert set(observed) == set(expected) | {'archive-inventory.json'}
    assert len(expected) == receipt['verified_members']
    for name, expected_record in expected.items():
        actual = {key: value for key, value in observed[name].items() if key != 'tar_mode'}
        assert actual == expected_record, 'Member mismatch: ' + name
    assert json.loads(captured['results/completion.json']) == report == receipt['summary']
    snapshot = json.loads(captured['results/source-snapshot.json'])
    source_records = snapshot.get('source_files', snapshot.get('files'))
    assert source_records is not None
    source_paths = set()
    for record in source_records:
        relative = PurePosixPath(record['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        assert str(relative) not in source_paths
        source_paths.add(str(relative))
        actual = observed['source/' + str(relative)]
        if 'symlink' in record:
            assert actual['type'] == 'symlink' and actual['target'] == record['symlink']
        elif record.get('mode') == 120000:
            assert actual['type'] == 'symlink'
            assert hashlib.sha256(actual['target'].encode()).hexdigest() == record['sha256']
        else:
            assert actual['type'] == 'file' and actual['sha256'] == record['sha256'], 'Source changed: ' + str(relative)
            executable = record.get('executable', record.get('mode') == 100755)
            assert bool(actual['tar_mode'] & 0o111) == bool(executable), 'Source executable mode changed: ' + str(relative)
    snapshot_commit = snapshot.get('private_snapshot_commit', snapshot.get('snapshot_commit'))
    totals = Counter()
    operators = defaultdict(Counter)
    cases = set()
    per_scope = {}
    configuration_manifests = 0
    missing_csv_scopes = []
    for scope in report['scopes']:
        index = scope['scope_index']
        prefix = f'results/scope-{index:04d}/core/'
        csv_name = prefix + 'results.csv'
        counts = Counter()
        if csv_name not in captured:
            missing_csv_scopes.append(index)
            assert not scope['row_status_counts']
            per_scope[str(index)] = {}
            continue
        rows = list(csv.DictReader(io.StringIO(captured[csv_name].decode('utf-8-sig'))))
        for row in rows:
            counts[row['test_status']] += 1
            if row.get('record_type') == 'mutant':
                assert row['catalog_version'] == '3'
                case = (scope['module'], scope['test_directory'], row['mutant_id'])
                assert case not in cases, 'Duplicate case: ' + repr(case)
                cases.add(case)
                operators[row['operator_id']][row['test_status']] += 1
                if row['test_status'] in SCORED:
                    assert row['validate_status'] == 'valid'
                    assert scope['native_gates']['baseline'] == 'passed'
        assert counts == Counter(scope['row_status_counts'])
        totals.update(counts)
        per_scope[str(index)] = dict(counts)
        manifest_name = prefix + 'results.manifest.json'
        if manifest_name in captured:
            manifest = json.loads(captured[manifest_name])
            configuration = manifest['configuration']
            assert configuration['catalog_version'] == '3' and configuration['tool_version'] == freeze['tool_version']
            assert manifest['source_commit'] == snapshot_commit
            assert manifest['signature'] == metadata_digest(configuration)
            assert configuration['tool_code_sha256'] == freeze['code_sha256']
            options = configuration['options']
            assert options['max_mutants'] is None and options['budget_seconds'] is None
            job = json.loads(captured[f'results/scope-{index:04d}/job.json'])
            assert options['target'] == job['relative_module'] and options['test_cmd'] == shlex.split(job['test_cmd'])
            assert manifest['csv_sha256'] == observed[csv_name]['sha256']
            for name, expected_hash in manifest['artifacts_sha256'].items():
                relative = PurePosixPath(name)
                assert not relative.is_absolute() and '..' not in relative.parts
                assert observed[prefix + str(relative)]['sha256'] == expected_hash
            configuration_manifests += 1
        else:
            assert not sum(counts[status] for status in SCORED)
    assert totals == Counter(report['row_status_counts'])
    assert {name: dict(count) for name, count in operators.items()} == report['operator_outcomes']
    assert sum(totals[status] for status in SCORED) == report['scored_mutants']
    active_csvs = {name for name in captured if CSV_PATH.fullmatch(name)}
    assert len(active_csvs) + len(missing_csv_scopes) == report['scope_count']
    return {'audit_version': VERSION, 'status': 'verified', 'repository': report['repository'],
            'catalog_version': '3', 'tool_version': freeze['tool_version'], 'archive': str(archive),
            'sha256': archive_hash, 'completion_sha256': report_hash, 'verified_epoch': time.time(),
            'fresh_archive_hash_epoch': time.time(), 'verified_members': len(expected),
            'source_files_verified': len(source_records), 'scope_attempts': report['scope_count'],
            'configuration_manifests_verified': configuration_manifests,
            'missing_csv_unscored_scopes': missing_csv_scopes, 'unique_mutant_cases': len(cases),
            'scored_mutants': report['scored_mutants'], 'row_status_counts': dict(totals),
            'preserved_interrupted_csvs_excluded': sum('/interrupted-attempts/' in name and name.endswith('/results.csv') for name in observed),
            'per_scope_status_counts': per_scope,
            'member_audit_reused_for_identical_bytes': False}


def main():
    freeze = read(ROOT / 'control/catalog3-freeze.json')
    for name, expected_hash in freeze['code_sha256'].items():
        assert digest(ROOT / 'framework-v3/src/tfmutate' / name) == expected_hash
    config = read(ROOT / 'control/ssd-config.json')
    archive_root = Path(config['archive_root'])
    assert archive_root.stat().st_dev == config['external_device']
    entries = {e['repository']: e for e in read(ROOT / 'control/expansion-plan.json')['repositories']}
    states = read(ROOT / 'control/expansion-status.json')['repositories']
    output = archive_root / 'reports/integrity'
    results = []
    for name, state in sorted(states.items()):
        if state['state'] != 'archived':
            continue
        assert name in entries and state['archive_verified']
        key = name.replace('/', '__')
        receipt = read(archive_root / 'control/receipts' / (key + '__catalog3.json'))
        report = read(archive_root / 'reports/repositories' / (key + '.json'))
        assert report['entry'] == entries[name] and receipt['sha256'] == state['archive_sha256']
        destination = output / (key + '__catalog3.json')
        try:
            result = one(receipt, report, freeze, destination)
        except Exception as exc:
            save(output / (key + '__catalog3-error.json'), {'repository': name, 'epoch': time.time(), 'error': repr(exc)})
            raise
        old_error = output / (key + '__catalog3-error.json')
        if old_error.exists():
            history = output / 'audit-error-history' / (str(int(time.time())) + '-' + old_error.name)
            history.parent.mkdir(exist_ok=True)
            old_error.replace(history)
        save(destination, result)
        results.append(result)
    summary = {'epoch': time.time(), 'audit_version': VERSION, 'status': 'interim_archived_subset_verified',
               'repositories_verified': len(results), 'scored_repositories': sum(r['scored_mutants'] > 0 for r in results),
               'scored_mutants_verified': sum(r['scored_mutants'] for r in results),
               'source_files_verified': sum(r['source_files_verified'] for r in results),
               'members_verified': sum(r['verified_members'] for r in results),
               'scope_attempts_verified': sum(r['scope_attempts'] for r in results),
               'unique_mutant_cases_within_repository_scope': sum(r['unique_mutant_cases'] for r in results),
               'policy': 'Fresh archive SHA256 plus streamed member/source/manifest/raw-case checks. Incomplete repos excluded; interrupted attempts preserved but uncounted. Final campaign audit remains pending.',
               'repositories': results}
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(summary['epoch']))
    save(output / (stamp + '-summary.json'), summary)
    save(output / 'summary.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'repositories'}))


if __name__ == '__main__':
    main()
