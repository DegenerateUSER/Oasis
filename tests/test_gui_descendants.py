"""Synthetic subprocess ownership regressions, NOT native Terraform evidence."""
import json
import os
import signal
import time

import pytest

from test_gui_jobs import job_body, wait_for
from test_gui_validation import SOURCE, git, tiny_repo as tiny_repo

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX process-group ownership')


def wait_until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail('synthetic subprocess did not reach expected checkpoint')


def gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.fixture
def descendant_engine(tmp_path, monkeypatch):
    """Executable test double spawning a real, same-group SIGINT-ignoring child."""
    control = tmp_path / 'descendant'
    control.mkdir()
    child = control / 'child.py'
    child.write_text('''import fcntl, json, os, pathlib, signal, sys, time
control, source, lock_path = map(pathlib.Path, sys.argv[1:])
signal.signal(signal.SIGINT, signal.SIG_IGN)
def publish(name, payload):
    temporary = control / (name + '.tmp')
    temporary.write_text(json.dumps(payload))
    temporary.replace(control / name)
def terminate(signum, frame):
    with lock_path.open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = False
        except BlockingIOError:
            locked = True
    publish('term.json', {'source': source.read_text(), 'locked': locked})
    if (control / 'dirty_on_term').exists():
        source.write_text(source.read_text() + '# synthetic shutdown write\\n')
    while not (control / 'allow_exit').exists():
        time.sleep(0.01)
    sys.exit(0)
signal.signal(signal.SIGTERM, terminate)
publish('child.json', {'pid': os.getpid(), 'pgid': os.getpgrp()})
while True:
    time.sleep(1)
''')
    binary_dir = tmp_path / 'bin'
    binary_dir.mkdir()
    engine = binary_dir / 'terraform'
    engine.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
command = sys.argv[1]
if command == 'version':
    print('Terraform v1.15.7')
elif command == 'fmt':
    print(sys.stdin.read())
elif command == 'test':
    if 'count = 1' in pathlib.Path('main.tf').read_text() and not os.environ.get('OASIS_DESCENDANT_DISABLED'):
        control = pathlib.Path(os.environ['OASIS_DESCENDANT_CONTROL'])
        subprocess.Popen([sys.executable, str(control / 'child.py'), str(control),
                          str(pathlib.Path('main.tf').resolve()), os.environ['OASIS_DESCENDANT_LOCK']],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=(control / 'child.log').open('w'))
        time.sleep(30)
    print(json.dumps({'type': 'test_summary', 'test_summary': {'passed': 1, 'failed': 0, 'errored': 0, 'skipped': 0, 'status': 'pass'}}))
''')
    engine.chmod(0o755)
    monkeypatch.setenv('PATH', str(binary_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('OASIS_DESCENDANT_CONTROL', str(control))
    monkeypatch.setenv('OASIS_DESCENDANT_LOCK', str(tmp_path / 'state' / 'execution.lock'))
    yield control
    # Always clean up the actual synthetic child, including on the pre-fix failure.
    (control / 'allow_exit').touch()
    if (control / 'child.json').exists():
        pid = json.loads((control / 'child.json').read_text())['pid']
        if not gone(pid):
            os.kill(pid, signal.SIGKILL)
        wait_until(lambda: gone(pid))


@pytest.mark.parametrize('release_on_term', [True, False], ids=['term', 'kill-escalation'])
def test_cancel_drains_descendant_after_restoration_before_completion_and_unlock(
        tmp_path, tiny_repo, descendant_engine, monkeypatch, release_on_term):
    from tfmutate.gui.jobs import JobConflict, JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore
    control = descendant_engine
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        directory = store.root / 'jobs' / job['id']
        wait_until(lambda: (control / 'child.json').exists())
        child = json.loads((control / 'child.json').read_text())
        assert child['pgid'] == manager._process.pid
        assert child['pid'] != manager._process.pid
        assert manager.cancel(job['id'])['state'] == 'cancelling'
        wait_until(lambda: (control / 'term.json').exists() or (directory / 'result.json').exists())
        assert (control / 'term.json').exists(), 'completion was published while the SIGINT-ignoring child remained alive'
        observation = json.loads((control / 'term.json').read_text())
        assert observation == {'source': SOURCE, 'locked': True}
        assert not gone(child['pid'])
        assert manager.get(job['id'])['state'] == 'cancelling'
        assert not (directory / 'result.json').exists()
        with pytest.raises(JobConflict):
            execution_lock(store.root)
        with pytest.raises(JobConflict):
            manager.submit(job_body(tiny_repo))
        manager.cancel(job['id'])  # Repeated requests cannot interrupt restoration/draining.
        if release_on_term:
            (control / 'allow_exit').touch()
        assert_completion_follows_exit(directory, store.root, child['pid'])
        ended = wait_for(manager, job['id'], lambda value: value['state'] == 'cancelled')
        assert ended['dataset_id'] is None
        assert gone(child['pid']), 'the descendant must be gone before ownership is freed'
        execution_lock(store.root).close()
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout == ''
        monkeypatch.setenv('OASIS_DESCENDANT_DISABLED', '1')
        next_job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        assert wait_for(manager, next_job['id'], lambda value: value['state'] in {'completed', 'failed'})['state'] == 'completed'
    finally:
        (control / 'allow_exit').touch()
        manager.close()


def assert_completion_follows_exit(directory, root, pid):
    """Observe both completion publication and the independent execution flock."""
    from tfmutate.gui.jobs import JobConflict, execution_lock

    def completed():
        published = (directory / 'result.json').exists()
        if published:
            assert gone(pid), 'completion was published before the descendant exited'
        try:
            lock = execution_lock(root)
        except JobConflict:
            return published
        else:
            lock.close()
            assert gone(pid), 'execution ownership was released before the descendant exited'
            return published

    wait_until(completed)


def inject_worker(monkeypatch, script):
    """Run the actual worker in a separate session with explicit fault injection."""
    import tfmutate.gui.jobs as jobs
    original = jobs.subprocess.Popen

    def launch(argv, *args, **kwargs):
        if argv[1:3] == ['-m', 'tfmutate.gui.worker']:
            argv = [argv[0], '-c', script, argv[3]]
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(jobs.subprocess, 'Popen', launch)


def test_inspection_failure_keeps_worker_lock_across_manager_restart(
        tmp_path, tiny_repo, descendant_engine, monkeypatch):
    from tfmutate.gui.jobs import JobConflict, JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore
    control = descendant_engine
    inject_worker(monkeypatch, '''import os, pathlib, sys
from tfmutate.gui import worker
control = pathlib.Path(os.environ['OASIS_DESCENDANT_CONTROL'])
original = worker._group_members
def inspect():
    if not (control / 'allow_inspection').exists():
        raise OSError('synthetic process inspection failure')
    return original()
worker._group_members = inspect
worker.run(pathlib.Path(sys.argv[1]))
''')
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    reopened = None
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        directory = store.root / 'jobs' / job['id']
        process = manager._process
        wait_until(lambda: (control / 'child.json').exists())
        child = json.loads((control / 'child.json').read_text())
        manager.cancel(job['id'])
        blocked = wait_for(manager, job['id'], lambda value: value['progress']['phase'] == 'cleanup_blocked')
        assert blocked['state'] == 'cancelling'
        assert 'cleanup' in (blocked['error'] or '').lower()
        assert 'synthetic process inspection failure' in blocked['error']
        assert process.poll() is None  # Never kill the restoration/ownership worker.
        assert not gone(child['pid'])
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
        assert not (directory / 'result.json').exists()
        with pytest.raises(JobConflict):
            execution_lock(store.root)
        # Emulate a server disappearing, without shutting down its live worker.
        manager._stop.set()
        manager._monitor.join(timeout=2)
        manager._instance.close()
        reopened = JobManager(store)
        assert reopened.get(job['id'])['state'] == 'interrupted'
        with pytest.raises(JobConflict, match='descendant cleanup'):
            reopened.submit(job_body(tiny_repo))
        (control / 'allow_exit').touch()
        (control / 'allow_inspection').touch()
        assert_completion_follows_exit(directory, store.root, child['pid'])
        process.wait(timeout=8)
        result = json.loads((directory / 'result.json').read_text())
        assert result['state'] == 'failed', result  # A cleanup failure is not clean cancellation.
        assert gone(child['pid'])
        execution_lock(store.root).close()
    finally:
        (control / 'allow_exit').touch()
        (control / 'allow_inspection').touch()
        if reopened:
            reopened.close()
        manager.close()


def test_shutdown_source_write_is_not_reported_as_clean_cancellation(
        tmp_path, tiny_repo, descendant_engine):
    from tfmutate.gui.jobs import JobManager
    from tfmutate.gui.store import DatasetStore
    control = descendant_engine
    (control / 'dirty_on_term').touch()
    (control / 'allow_exit').touch()
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        directory = store.root / 'jobs' / job['id']
        wait_until(lambda: (control / 'child.json').exists())
        child = json.loads((control / 'child.json').read_text())
        manager.cancel(job['id'])
        assert_completion_follows_exit(directory, store.root, child['pid'])
        ended = wait_for(manager, job['id'], lambda value: value['state'] in {'cancelled', 'failed'})
        assert ended['state'] == 'failed', ended
        assert ended['dataset_id'] is None
        assert 'Restoration could not be confirmed' in ended['error']
        assert 'tracked changes remain after cleanup' in ended['error']
        observation = json.loads((control / 'term.json').read_text())
        assert observation == {'source': SOURCE, 'locked': True}
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout
    finally:
        manager.close()


def test_repeated_cancel_does_not_escalate_while_source_restoration_is_in_progress(
        tmp_path, tiny_repo, descendant_engine, monkeypatch):
    from tfmutate.gui.jobs import JobConflict, JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore
    control = descendant_engine
    inject_worker(monkeypatch, '''import contextlib, os, pathlib, sys, time
from tfmutate import state
from tfmutate.gui import worker
control = pathlib.Path(os.environ['OASIS_DESCENDANT_CONTROL'])
original = state.restored
@contextlib.contextmanager
def delayed_restoration(*args, **kwargs):
    with original(*args, **kwargs):
        try:
            yield
        finally:
            (control / 'restoring').touch()
            while not (control / 'allow_restore').exists():
                time.sleep(0.01)
state.restored = delayed_restoration
worker.run(pathlib.Path(sys.argv[1]))
''')
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        directory = store.root / 'jobs' / job['id']
        process = manager._process
        wait_until(lambda: (control / 'child.json').exists())
        child = json.loads((control / 'child.json').read_text())
        assert manager.cancel(job['id'])['state'] == 'cancelling'
        wait_until(lambda: (control / 'restoring').exists())
        assert (tiny_repo / 'main.tf').read_text() != SOURCE
        assert manager.cancel(job['id'])['state'] == 'cancelling'
        assert process.poll() is None
        assert not gone(child['pid'])
        assert not (control / 'term.json').exists()
        assert not (directory / 'result.json').exists()
        with pytest.raises(JobConflict):
            execution_lock(store.root)
        (control / 'allow_restore').touch()
        wait_until(lambda: (control / 'term.json').exists())
        assert json.loads((control / 'term.json').read_text()) == {'source': SOURCE, 'locked': True}
        (control / 'allow_exit').touch()
        assert_completion_follows_exit(directory, store.root, child['pid'])
        ended = wait_for(manager, job['id'], lambda value: value['state'] == 'cancelled')
        assert ended['dataset_id'] is None
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
    finally:
        (control / 'allow_restore').touch()
        (control / 'allow_exit').touch()
        manager.close()
