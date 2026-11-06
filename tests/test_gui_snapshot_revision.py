"""Provider-free snapshot ordering using the real manager and detached JSON DTOs."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tfmutate.gui.jobs import JobManager
from tfmutate.gui.store import DatasetStore


@pytest.fixture
def manager(tmp_path):
    instance = JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        yield instance
    finally:
        instance.close()


def seed_job(manager, state='running'):
    job = {
        'id': 'a' * 32, 'state': state,
        'config': {'target_path': '/local/example', 'operators': ['MUT-RES-002']},
        'created_at': '2026-01-01T00:00:00Z', 'started_at': None,
        'finished_at': None, 'dataset_id': None, 'error': None,
        'progress': {'phase': 'init', 'completed_commands': 2},
        'log_tail': 'old worker log', 'duration_seconds': 3,
    }
    manager._directory(job['id']).mkdir()
    with manager._mutex:
        manager._jobs[job['id']] = job
        manager._save(job)
    return job


def read_snapshot(manager, source, identifier):
    return manager.get(identifier) if source == 'detail' else manager.list()[0]


@pytest.mark.parametrize('state', ['running', 'cancelling'])
@pytest.mark.parametrize('first_source', ['list', 'detail'])
def test_get_and_list_issue_ordered_detached_same_state_snapshots(manager, state, first_source):
    owned = seed_job(manager, state)
    older = read_snapshot(manager, first_source, owned['id'])
    with manager._mutex:
        owned.update(progress={'phase': 'restoring', 'completed_commands': 12},
                     log_tail='newer worker log', duration_seconds=15)
        manager._save(owned)
    other_source = 'detail' if first_source == 'list' else 'list'
    newer = read_snapshot(manager, other_source, owned['id'])
    unchanged = read_snapshot(manager, first_source, owned['id'])
    # The revision must survive the actual API's JSON serialization.
    older, newer, unchanged = json.loads(json.dumps([older, newer, unchanged]))
    assert isinstance(older['snapshot_revision'], int)
    assert 0 < older['snapshot_revision'] < newer['snapshot_revision'] < unchanged['snapshot_revision']
    assert older['state'] == newer['state'] == unchanged['state'] == state
    assert older['progress'] == {'phase': 'init', 'completed_commands': 2}
    assert older['log_tail'] == 'old worker log'
    assert older['duration_seconds'] == 3
    assert newer['progress'] == {'phase': 'restoring', 'completed_commands': 12}
    assert newer['log_tail'] == 'newer worker log'
    assert newer['duration_seconds'] == 15
    assert 'snapshot_revision' not in owned
    assert 'snapshot_revision' not in json.loads((manager.root / owned['id'] / 'job.json').read_text())

    detached = read_snapshot(manager, first_source, owned['id'])
    detached['progress']['completed_commands'] = -1
    detached['config']['operators'].append('not-a-real-operator')
    detached['log_tail'] = 'caller modified'
    current = read_snapshot(manager, other_source, owned['id'])
    assert current['progress']['completed_commands'] == 12
    assert current['config']['operators'] == ['MUT-RES-002']
    assert current['log_tail'] == 'newer worker log'
    assert current['snapshot_revision'] > detached['snapshot_revision']


@pytest.mark.parametrize('blocked_source', ['list', 'detail'])
def test_revision_follows_snapshot_under_rlock_not_request_start(manager, monkeypatch, blocked_source):
    import tfmutate.gui.jobs as jobs

    owned = seed_job(manager)
    mutex = manager._mutex
    attempted = threading.Event()
    reader_id = None

    class ObservedLock:
        def __enter__(self):
            if threading.get_ident() == reader_id:
                attempted.set()
            return mutex.__enter__()

        def __exit__(self, *args):
            return mutex.__exit__(*args)

    original_deepcopy = jobs.copy.deepcopy

    def checked_deepcopy(value, *args, **kwargs):
        if value is owned:
            assert mutex._is_owned(), 'snapshot must be copied while the manager RLock is held'
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(manager, '_mutex', ObservedLock())
    monkeypatch.setattr(jobs.copy, 'deepcopy', checked_deepcopy)

    def earlier_request():
        nonlocal reader_id
        reader_id = threading.get_ident()
        return read_snapshot(manager, blocked_source, owned['id'])

    # A request starts first but cannot capture its snapshot until after the
    # reentrant read and mutation here. Its revision must therefore come later.
    with ThreadPoolExecutor(max_workers=1) as executor:
        with manager._mutex:
            blocked = executor.submit(earlier_request)
            assert attempted.wait(2), 'reader did not attempt the manager lock'
            other_source = 'detail' if blocked_source == 'list' else 'list'
            first = read_snapshot(manager, other_source, owned['id'])
            owned.update(progress={'phase': 'restoring', 'completed_commands': 12},
                         duration_seconds=15, log_tail='newer worker log')
        second = blocked.result(timeout=2)
    assert first['snapshot_revision'] < second['snapshot_revision']
    assert first['progress']['completed_commands'] == 2
    assert second['progress']['completed_commands'] == 12
    assert second['duration_seconds'] == 15
    assert second['log_tail'] == 'newer worker log'


@pytest.mark.parametrize('state', ['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted'])
def test_cancel_returns_fresh_detached_snapshots_for_active_and_terminal_jobs(manager, state):
    owned = seed_job(manager, state)
    before = manager.get(owned['id'])
    requested = manager.cancel(owned['id'])
    repeated = manager.cancel(owned['id'])
    after = manager.list()[0]
    expected_state = 'cancelling' if state in {'queued', 'running', 'cancelling'} else state
    assert requested['state'] == repeated['state'] == after['state'] == expected_state
    assert before['snapshot_revision'] < requested['snapshot_revision'] < repeated['snapshot_revision'] < after['snapshot_revision']
    assert before['state'] == state
    requested['progress']['completed_commands'] = -1
    requested['config']['operators'].append('not-a-real-operator')
    assert manager.get(owned['id'])['progress']['completed_commands'] == 2
    assert manager.get(owned['id'])['config']['operators'] == ['MUT-RES-002']
    assert 'snapshot_revision' not in owned
    assert 'snapshot_revision' not in json.loads((manager.root / owned['id'] / 'job.json').read_text())


@pytest.mark.parametrize('launch_error', [False, True])
def test_submit_returns_a_new_snapshot_and_refreshes_real_private_evidence(manager, monkeypatch, launch_error):
    import tfmutate.gui.jobs as jobs
    from tfmutate.gui.store import write_json

    prior = seed_job(manager, 'completed')
    before = manager.get(prior['id'])
    config = {
        'target_path': '/local/example', 'engine': 'terraform', 'operators': ['MUT-RES-002'],
        'test_directory': 'tests', 'max_mutants': 1, 'budget_seconds': 15,
        'timeout': 5, 'init_timeout': 5, 'init_attempts': 1, 'acknowledge_execution': True,
    }
    # Only validation/child launch are stubbed; no engine, provider or network is run.
    monkeypatch.setattr(jobs, 'validate_job', lambda body, root: dict(config))
    monkeypatch.setattr(jobs, 'engine_path', lambda engine: '/test-bin/terraform')

    class InertWorker:
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return self.returncode

    def launch(argv, *, cwd, stdout, **kwargs):
        if launch_error:
            raise OSError('deliberate test launch failure')
        write_json(cwd / 'progress.json', {'phase': 'init', 'completed_commands': 2})
        stdout.write(b'initial worker log')
        stdout.flush()
        return InertWorker()

    monkeypatch.setattr(jobs.subprocess, 'Popen', launch)
    posted = manager.submit(config)
    assert posted['snapshot_revision'] > before['snapshot_revision']
    assert posted['state'] == ('failed' if launch_error else 'running')
    assert posted['id'] != prior['id']
    directory = manager.root / posted['id']
    if not launch_error:
        assert posted['progress'] == {'phase': 'init', 'completed_commands': 2}
        assert posted['log_tail'] == 'initial worker log'
        write_json(directory / 'progress.json', {'phase': 'restoring', 'completed_commands': 12})
        (directory / 'console.log').write_text('newer worker log')
    detail = manager.get(posted['id'])
    listed = next(job for job in manager.list() if job['id'] == posted['id'])
    requested = manager.cancel(posted['id'])
    assert posted['snapshot_revision'] < detail['snapshot_revision'] < listed['snapshot_revision'] < requested['snapshot_revision']
    assert requested['state'] == ('failed' if launch_error else 'cancelling')
    if not launch_error:
        assert detail['progress'] == listed['progress'] == requested['progress'] == {'phase': 'restoring', 'completed_commands': 12}
        assert requested['log_tail'] == 'newer worker log'
        assert posted['progress']['completed_commands'] == 2
        assert posted['log_tail'] == 'initial worker log'
    posted['progress']['completed_commands'] = -1
    posted['config']['operators'].append('not-a-real-operator')
    fresh = manager.get(posted['id'])
    assert fresh['progress']['completed_commands'] != -1
    assert fresh['config']['operators'] == ['MUT-RES-002']
    assert 'snapshot_revision' not in manager._jobs[posted['id']]
    assert 'snapshot_revision' not in json.loads((directory / 'job.json').read_text())
