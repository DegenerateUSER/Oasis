"""Actual isolated, provider-free execution and durable GUI job records."""
import json
import os
import shutil
import time

import pytest

from test_gui_validation import SOURCE, git, tiny_repo as tiny_repo


def wait_for(manager, identifier, predicate, seconds=25):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = manager.get(identifier)
        if predicate(last):
            return last
        time.sleep(0.05)
    pytest.fail(f'job did not reach expected state: {last}')


@pytest.mark.engine_smoke
def test_builtin_terraform_job_is_isolated_verified_persistent_and_restored(tmp_path, tiny_repo):
    if not shutil.which('terraform'):
        pytest.skip('terraform unavailable')
    from tfmutate.gui.jobs import JobManager
    from tfmutate.gui.store import DatasetStore
    from tfmutate.reporter import summary_data
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit({'target_path': str(tiny_repo), 'engine': 'terraform',
                              'operators': ['MUT-RES-002'], 'max_mutants': 1,
                              'budget_seconds': 20, 'timeout': 5, 'init_timeout': 5,
                              'acknowledge_execution': True})
        assert job['state'] in {'queued', 'running'}
        completed = wait_for(manager, job['id'], lambda value: value['state'] in {'completed', 'failed'})
        assert completed['state'] == 'completed', completed
        assert completed['duration_seconds'] > 0
        assert completed['progress']['completed_commands'] >= 4
        assert completed['progress']['phase'] == 'completed'
        assert completed['log_tail']
        dataset = store.get(completed['dataset_id'])
        assert dataset['provenance']['kind'] == 'verified'
        assert dataset['summary'] == summary_data(dataset['rows'])
        assert dataset['summary']['overall']['killed_assert'] == 1
        assert dataset['summary']['overall']['excluded_statuses']['not_executed'] == 1
        row = next(row for row in dataset['rows'] if row['test_status'] == 'killed_assert')
        log_path = row['log_paths'].split(';')[0]
        evidence = store.log(dataset['id'], log_path)
        assert isinstance(evidence['text'], str) and evidence['text']
        assert evidence['truncated'] is False
        with pytest.raises(ValueError):
            store.log(dataset['id'], '/etc/passwd')
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout == ''
    finally:
        manager.close()
    reopened = JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        assert reopened.get(job['id'])['dataset_id'] == dataset['id']
        assert reopened.list()[0]['state'] == 'completed'
    finally:
        reopened.close()


@pytest.fixture
def synthetic_engine(tmp_path, monkeypatch):
    """A real subprocess test double, NOT evidence of a native Terraform run."""
    binary_dir = tmp_path / 'bin'
    binary_dir.mkdir()
    engine = binary_dir / 'terraform'
    engine.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
command = sys.argv[1]
if command == 'version':
    print('Terraform v1.15.7')
elif command == 'fmt':
    time.sleep(float(os.environ.get('OASIS_TEST_FMT_SLEEP', '0')))
    print(sys.stdin.read())
elif command == 'test':
    if 'count = 1' in pathlib.Path('main.tf').read_text():
        time.sleep(float(os.environ.get('OASIS_TEST_SLEEP', '0')))
    print(json.dumps({'type': 'test_summary', 'test_summary': {'passed': 1, 'failed': 0, 'errored': 0, 'skipped': 0, 'status': 'pass'}}))
''')
    engine.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary_dir) + os.pathsep + os.environ['PATH'])
    return engine


def job_body(root, **changes):
    return {'target_path': str(root), 'engine': 'terraform', 'operators': ['MUT-RES-002'],
            'max_mutants': 1, 'budget_seconds': 15, 'timeout': 10, 'init_timeout': 5,
            'acknowledge_execution': True, **changes}


def test_cancel_signals_isolated_group_and_confirms_source_restoration(tmp_path, tiny_repo, synthetic_engine, monkeypatch):
    from tfmutate.gui.jobs import JobConflict, JobManager
    from tfmutate.gui.store import DatasetStore
    monkeypatch.setenv('OASIS_TEST_SLEEP', '20')
    manager = JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        job = manager.submit(job_body(tiny_repo))
        wait_for(manager, job['id'], lambda value: value['progress']['phase'] == 'test'
                 and 'count = 1' in (tiny_repo / 'main.tf').read_text())
        assert manager._process.pid != os.getpid()
        assert os.getpgid(manager._process.pid) == manager._process.pid
        with pytest.raises(JobConflict):
            manager.submit(job_body(tiny_repo))
        requested = manager.cancel(job['id'])
        assert requested['state'] == 'cancelling'
        manager.cancel(job['id'])  # idempotent: never interrupt restoration a second time
        cancelled = wait_for(manager, job['id'], lambda value: value['state'] not in {'running', 'cancelling'})
        assert cancelled['state'] == 'cancelled', cancelled
        assert cancelled['dataset_id'] is None
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout == ''
    finally:
        manager.close()


def test_budget_is_bounded_without_killing_restoration(tmp_path, tiny_repo, synthetic_engine, monkeypatch):
    from tfmutate.gui.jobs import JobManager
    from tfmutate.gui.store import DatasetStore
    monkeypatch.setenv('OASIS_TEST_SLEEP', '20')
    manager = JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=1))
        ended = wait_for(manager, job['id'], lambda value: value['state'] in {'failed', 'completed'}, seconds=8)
        assert ended['duration_seconds'] < 6
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
    finally:
        manager.close()


def test_wall_budget_also_bounds_core_syntax_gate(tmp_path, tiny_repo, synthetic_engine, monkeypatch):
    from tfmutate.gui.jobs import JobManager
    from tfmutate.gui.store import DatasetStore
    monkeypatch.setenv('OASIS_TEST_FMT_SLEEP', '6')
    manager = JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=1))
        ended = wait_for(manager, job['id'], lambda value: value['state'] == 'failed', seconds=4)
        assert 'budget' in ended['error'].lower()
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
    finally:
        manager.close()


def test_tampered_owned_raw_logs_lose_verified_provenance(tmp_path, tiny_repo, synthetic_engine):
    from tfmutate.gui.jobs import JobManager
    from tfmutate.gui.store import DatasetStore
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo))
        ended = wait_for(manager, job['id'], lambda value: value['state'] in {'completed', 'failed'})
        assert ended['state'] == 'completed', ended
        dataset = store.get(ended['dataset_id'])
        row = next(row for row in dataset['rows'] if row['log_paths'])
        path = row['log_paths'].split(';')[0]
        from pathlib import Path
        Path(path).write_text('tampered')
        assert store.get(dataset['id'])['provenance']['kind'] == 'unverified'
        with pytest.raises(ValueError, match='verified|evidence'):
            store.log(dataset['id'], path)
    finally:
        manager.close()


def test_restart_marks_abandoned_jobs_interrupted_and_honors_live_worker_lock(tmp_path):
    from tfmutate.gui.jobs import JobConflict, JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore, write_json
    store = DatasetStore(tmp_path / 'state', sources={})
    identifier = 'a' * 32
    directory = store.root / 'jobs' / identifier
    directory.mkdir(parents=True)
    write_json(directory / 'job.json', {'id': identifier, 'state': 'running', 'created_at': '2026-01-01T00:00:00Z'})
    manager = JobManager(store)
    try:
        assert manager.get(identifier)['state'] == 'interrupted'
        assert json.loads((directory / 'job.json').read_text())['state'] == 'interrupted'
        with pytest.raises(JobConflict):
            JobManager(store)
        lock = execution_lock(store.root)
        try:
            with pytest.raises(JobConflict):
                execution_lock(store.root)
        finally:
            lock.close()
    finally:
        manager.close()
