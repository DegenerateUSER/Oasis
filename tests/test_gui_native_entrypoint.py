"""Source-level native-launch regressions; these do NOT build a native binary."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_gui_descendants import (
    assert_completion_follows_exit,
    descendant_engine as descendant_engine,
    gone,
    wait_until,
)
from test_gui_jobs import job_body, synthetic_engine as synthetic_engine, wait_for
from test_gui_validation import SOURCE, git, tiny_repo as tiny_repo

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / 'src' / 'entrypoint.py'
WORKER_FLAG = '--_oasis-gui-worker'

pytestmark = pytest.mark.skipif(os.name != 'posix', reason='GUI workers require POSIX process groups')


def test_private_entrypoint_dispatches_exact_argv_to_real_worker(tmp_path, tiny_repo):
    # Pre-cancellation reaches the real worker without executing an engine.
    directory = tmp_path / 'state with spaces' / 'jobs' / ('a' * 32)
    directory.mkdir(parents=True)
    (directory / 'request.json').write_text(json.dumps({
        'budget_seconds': 5, 'target_path': str(tiny_repo),
    }))
    (directory / 'cancel.json').write_text('{}')
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    result = subprocess.run([sys.executable, str(ENTRYPOINT), WORKER_FLAG, str(directory)],
                            cwd=directory, env=env, start_new_session=True,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads((directory / 'result.json').read_text()) == {
        'state': 'cancelled', 'error': None,
    }
    assert json.loads((directory / 'ready.json').read_text()) == {'ready': True}
    assert json.loads((directory / 'progress.json').read_text())['phase'] == 'draining'


@pytest.fixture
def simulated_compiled_worker(tmp_path, monkeypatch):
    """Only emulate Nuitka's sentinel/executable; dispatch and worker are real."""
    import tfmutate.gui.jobs as jobs

    executable = tmp_path / 'native binary with spaces'
    script = (
        'import json, pathlib, runpy, sys\n'
        'sys.argv = sys.argv[1:]\n'
        "pathlib.Path('launch-argv.json').write_text(json.dumps(sys.argv))\n"
        f'runpy.run_path({str(ENTRYPOINT)!r}, run_name="__main__")\n'
    )
    # A shell exec also handles Python installations whose paths contain spaces.
    executable.write_text(
        '#!/bin/sh\n'
        f'exec {shlex.quote(sys.executable)} -c {shlex.quote(script)} "$0" "$@"\n'
    )
    executable.chmod(0o755)
    monkeypatch.setattr(jobs, '__compiled__', object(), raising=False)
    # Patch only this module, not the process-wide sys.executable used by tools.
    monkeypatch.setattr(jobs, 'sys', SimpleNamespace(executable=str(executable)))
    return executable


def test_compiled_job_constructs_private_argv_and_completes_via_real_dispatcher(
        tmp_path, tiny_repo, synthetic_engine, simulated_compiled_worker):
    from tfmutate.gui.jobs import JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore

    store = DatasetStore(tmp_path / 'state with spaces', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo))
        directory = store.root / 'jobs' / job['id']
        ended = wait_for(manager, job['id'], lambda value: value['state'] not in {'running', 'cancelling'})
        assert ended is not None
        assert json.loads((directory / 'launch-argv.json').read_text()) == [
            str(simulated_compiled_worker), WORKER_FLAG, str(directory),
        ]
        assert ended['state'] == 'completed', ended
        assert ended['dataset_id'] is not None
        assert ended['progress']['completed_commands'] >= 4
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout == ''
        execution_lock(store.root).close()
    finally:
        manager.close()


def test_compiled_dispatch_cancels_group_restores_source_and_retains_cleanup_lock(
        tmp_path, tiny_repo, descendant_engine, simulated_compiled_worker):
    from tfmutate.gui.jobs import JobConflict, JobManager, execution_lock
    from tfmutate.gui.store import DatasetStore

    control = descendant_engine
    store = DatasetStore(tmp_path / 'state', sources={})
    manager = JobManager(store)
    try:
        job = manager.submit(job_body(tiny_repo, budget_seconds=45, timeout=30))
        directory = store.root / 'jobs' / job['id']
        process = manager._process
        assert process is not None
        assert process.args == [str(simulated_compiled_worker), WORKER_FLAG, str(directory)]
        wait_until(lambda: (control / 'child.json').exists())
        child = json.loads((control / 'child.json').read_text())
        assert child['pgid'] == process.pid == os.getpgid(process.pid)
        assert manager.cancel(job['id'])['state'] == 'cancelling'
        assert manager.cancel(job['id'])['state'] == 'cancelling'
        wait_until(lambda: (control / 'term.json').exists() or (directory / 'result.json').exists())
        assert (control / 'term.json').exists()
        assert json.loads((control / 'term.json').read_text()) == {'source': SOURCE, 'locked': True}
        assert process.poll() is None
        assert not (directory / 'result.json').exists()
        with pytest.raises(JobConflict):
            execution_lock(store.root)
        (control / 'allow_exit').touch()
        assert_completion_follows_exit(directory, store.root, child['pid'])
        ended = wait_for(manager, job['id'], lambda value: value['state'] == 'cancelled')
        assert ended is not None
        assert ended['dataset_id'] is None
        assert gone(child['pid'])
        assert (tiny_repo / 'main.tf').read_text() == SOURCE
        assert git(tiny_repo, 'status', '--porcelain', '--untracked-files=no').stdout == ''
        execution_lock(store.root).close()
    finally:
        (control / 'allow_exit').touch()
        manager.close()


def test_python_job_retains_exact_module_command_and_completes(
        tmp_path, tiny_repo, synthetic_engine, monkeypatch):
    import tfmutate.gui.jobs as jobs
    from tfmutate.gui.store import DatasetStore

    launched = []
    original = jobs.subprocess.Popen

    def launch(argv, *args, **kwargs):
        if argv[1:3] == ['-m', 'tfmutate.gui.worker']:
            launched.append(list(argv))
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(jobs.subprocess, 'Popen', launch)
    manager = jobs.JobManager(DatasetStore(tmp_path / 'state', sources={}))
    try:
        job = manager.submit(job_body(tiny_repo))
        directory = manager.root / job['id']
        assert launched == [[sys.executable, '-m', 'tfmutate.gui.worker', str(directory)]]
        ended = wait_for(manager, job['id'], lambda value: value['state'] not in {'running', 'cancelling'})
        assert ended is not None
        assert ended['state'] == 'completed', ended
        assert ended['dataset_id'] is not None
    finally:
        manager.close()


@pytest.mark.parametrize('argv', [['--help'], ['gui', '--help'], ['--version']])
def test_native_entrypoint_preserves_public_cli(argv):
    result = subprocess.run([sys.executable, str(ENTRYPOINT), *argv],
                            env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert WORKER_FLAG not in result.stdout
    assert 'oasis' in result.stdout


@pytest.mark.parametrize('extra', [[], ['extra']])
def test_private_dispatch_rejects_missing_or_extra_arguments(tmp_path, extra):
    argv = [WORKER_FLAG] if not extra else [WORKER_FLAG, str(tmp_path), *extra]
    result = subprocess.run([sys.executable, str(ENTRYPOINT), *argv],
                            env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'usage: oasis' in result.stderr
    assert not (tmp_path / 'ready.json').exists()
    assert not (tmp_path / 'result.json').exists()


def test_nuitka_release_includes_frontend_at_runtime_package_path():
    workflow = (ROOT / '.github' / 'workflows' / 'release.yml').read_text()
    compile_step = workflow.split('- name: Compile with Nuitka\n', 1)[1]
    command = compile_step.split('        run: |\n', 1)[1].split('        env:\n', 1)[0]
    argv = shlex.split(command.replace('\\\n', ''))
    inclusion = '--include-data-dir=src/tfmutate/gui/static=tfmutate/gui/static'
    assert inclusion in argv
    static = ROOT / 'src' / 'tfmutate' / 'gui' / 'static'
    assert (static / 'index.html').is_file()
    assert any((static / 'assets').glob('*.js'))
    assert any((static / 'assets').glob('*.css'))
