"""One private child process per run; state survives a UI/server restart."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .store import ID, MAX_LOG_BYTES, DatasetStore, private_dir, read_bytes, safe_path, utc_now, write_json
from .validation import engine_path, validate_job

ACTIVE = {'queued', 'running', 'cancelling'}


class JobConflict(RuntimeError):
    """Another job or server already owns local execution."""


def execution_lock(root: Path):
    path = safe_path(root / 'execution.lock', root)
    stream = path.open('a+b')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise JobConflict('another local worker still owns execution; wait for restoration and descendant cleanup to finish') from exc
    return stream


class JobManager:
    def __init__(self, store: DatasetStore):
        self.store, self.root = store, private_dir(store.root / 'jobs')
        self._mutex = threading.RLock()
        self._snapshot_revision = 0
        self._closed = False
        self._process = None
        self._active_id = None
        self._jobs = {}
        self._instance = safe_path(store.root / 'server.lock', store.root).open('a+b')
        try:
            fcntl.flock(self._instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._instance.close()
            raise JobConflict('another Oasis server owns this state directory') from exc
        try:
            for directory in sorted(self.root.iterdir()):
                if ID.fullmatch(directory.name) and directory.is_dir():
                    path = safe_path(directory / 'job.json', self.root)
                    job = json.loads(read_bytes(path, 128 * 1024))
                    if job.get('state') in ACTIVE:
                        job.update(state='interrupted', finished_at=utc_now(),
                                   error='Server restarted before completion was confirmed; inspect the repository before rerunning.')
                        write_json(path, job)
                    self._jobs[directory.name] = job
        except BaseException:
            self._instance.close()
            raise
        self._stop = threading.Event()
        self._monitor = threading.Thread(target=self._watch, name='oasis-job-monitor', daemon=True)
        self._monitor.start()

    def _directory(self, identifier: str) -> Path:
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise KeyError('unknown job')
        return safe_path(self.root / identifier, self.root)

    def _save(self, job: dict) -> None:
        write_json(self._directory(job['id']) / 'job.json', job)

    def submit(self, body: dict) -> dict:
        with self._mutex:
            self._refresh()
            if self._process is not None:
                raise JobConflict('one job is already active; cancel or wait for it to finish')
            config = validate_job(body, self.store.root)
            if self._closed:
                raise JobConflict('job manager is closed')
            if self._process is not None:
                raise JobConflict('one job is already active; cancel or wait for it to finish')
            probe = execution_lock(self.store.root)
            probe.close()
            identifier = uuid.uuid4().hex
            directory = private_dir(self._directory(identifier))
            job = {'id': identifier, 'state': 'queued', 'config': config, 'created_at': utc_now(),
                   'started_at': None, 'finished_at': None, 'dataset_id': None, 'error': None,
                   'progress': {'phase': 'queued', 'completed_commands': 0}, 'log_tail': '', 'duration_seconds': 0.0}
            self._jobs[identifier] = job
            self._save(job)
            write_json(directory / 'request.json', config)
            env = dict(os.environ)
            env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
            # Use the validated engine's directory, never a relative/cwd PATH entry.
            executable = engine_path(config['engine'])
            env['PATH'] = os.pathsep.join(dict.fromkeys([str(Path(executable).parent),
                *(part for part in os.get_exec_path() if part and Path(part).is_absolute())]))
            env.update(CHECKPOINT_DISABLE='1', TF_IN_AUTOMATION='1', TF_INPUT='0', PYTHONUNBUFFERED='1')
            # Nuitka marks compiled modules with __compiled__, not sys.frozen.
            # Its executable cannot interpret Python's -m invocation (and may
            # reject it before entrypoint dispatch as accidental self-execution).
            command = ([sys.executable, '--_oasis-gui-worker', str(directory)]
                       if '__compiled__' in globals() else
                       [sys.executable, '-m', 'tfmutate.gui.worker', str(directory)])
            try:
                with (directory / 'console.log').open('xb') as console:
                    self._process = subprocess.Popen(command,
                        cwd=directory, env=env, stdin=subprocess.DEVNULL, stdout=console,
                        stderr=subprocess.STDOUT, start_new_session=True, shell=False)
                self._active_id = identifier
                self._cancel_sent = False
                job.update(state='running', started_at=utc_now())
            except OSError as exc:
                self._process = None
                job.update(state='failed', finished_at=utc_now(), error=f'worker launch failed: {exc}')
            self._save(job)
            return self.get(identifier)

    def _refresh(self) -> None:
        if self._process is None:
            return
        job = self._jobs[self._active_id]
        directory = self._directory(job['id'])
        try:
            progress = json.loads(read_bytes(directory / 'progress.json', 8192))
            job['progress'] = progress
            if progress.get('phase') == 'cleanup_blocked':
                # This is a failed cleanup attempt, not confirmed completion.
                # The live worker retains execution.lock while it retries.
                job['error'] = str(progress.get('error') or 'Descendant cleanup is blocked; execution ownership retained')[:4000]
        except FileNotFoundError:
            pass
        try:
            job['log_tail'] = read_bytes(directory / 'console.log', MAX_LOG_BYTES, tail=True).decode('utf-8', errors='replace')
        except FileNotFoundError:
            pass
        if job['started_at']:
            job['duration_seconds'] = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(job['started_at'].replace('Z', '+00:00'))).total_seconds())
        code = self._process.poll()
        if code is None:
            self._signal_cancellation(job)
            return
        try:
            result = json.loads(read_bytes(directory / 'result.json', 64 * 1024))
            status = result['state']
            if status not in {'completed', 'failed', 'cancelled'}:
                raise ValueError('invalid worker completion state')
            job.update(state=status, error=result.get('error'))
            if status == 'completed':
                dataset = self.store.publish_job(job['id'], Path(job['config']['target_path']).name + ' local run')
                job['dataset_id'] = dataset['id']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            job.update(state='failed', error=f'worker exited {code}; completion/evidence not verified: {exc}')
        job['finished_at'] = utc_now()
        job['progress']['phase'] = job['state']
        self._save(job)
        self._process.wait()
        self._process, self._active_id = None, None

    def _watch(self) -> None:
        while not self._stop.wait(0.1):
            with self._mutex:
                try:
                    self._refresh()
                except (OSError, ValueError, KeyError, TypeError):
                    # HTTP polling can surface malformed private state without killing the monitor.
                    continue

    def _snapshot(self, job: dict) -> dict:
        """Construct a detached response while the caller holds self._mutex."""
        snapshot = copy.deepcopy(job)
        self._snapshot_revision += 1
        snapshot['snapshot_revision'] = self._snapshot_revision
        return snapshot

    def get(self, identifier: str) -> dict:
        self._directory(identifier)
        with self._mutex:
            self._refresh()
            if identifier not in self._jobs:
                raise KeyError('unknown job')
            return self._snapshot(self._jobs[identifier])

    def list(self) -> list[dict]:
        with self._mutex:
            self._refresh()
            return [self._snapshot(job) for job in sorted(self._jobs.values(), key=lambda value: value['created_at'], reverse=True)]

    def cancel(self, identifier: str) -> dict:
        with self._mutex:
            job = self.get(identifier)
            if job['state'] not in ACTIVE:
                return job
            owned = self._jobs[identifier]
            owned['state'] = 'cancelling'
            write_json(self._directory(identifier) / 'cancel.json', {'requested_at': utc_now()})
            self._save(owned)
            self._signal_cancellation(owned)
            return self._snapshot(owned)

    def _signal_cancellation(self, job: dict) -> None:
        if (job['state'] == 'cancelling' and self._process is not None
                and not getattr(self, '_cancel_sent', False)
                and (self._directory(job['id']) / 'ready.json').is_file()):
            try:
                os.killpg(self._process.pid, signal.SIGINT)
                self._cancel_sent = True
            except ProcessLookupError:
                pass

    def close(self) -> None:
        with self._mutex:
            self._closed = True
            if self._process:
                self.cancel(self._active_id)
            process = self._process
        if process is not None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Never SIGKILL while source restoration might be in progress.
                # The worker retains execution.lock, preventing a concurrent run.
                pass
        with self._mutex:
            self._refresh()
        self._stop.set()
        self._monitor.join(timeout=2)
        self._instance.close()
