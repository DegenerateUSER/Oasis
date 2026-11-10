"""Child-only runner integration. Native engine output remains private local evidence."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .. import orchestrator, runner
from ..mutators import CATALOG
from .jobs import execution_lock
from .store import private_dir, read_bytes, safe_path, write_json
from .validation import test_command, validate_job


def _group_members() -> set[int]:
    """Live members of this dedicated POSIX worker group, not full ancestry.

    The worker stays group leader until ownership is released. Never run this
    from a signal handler, and exclude both the worker and our temporary ps.
    Trusted code that escapes with setsid/setpgid is outside this boundary.
    """
    owner = os.getpid()
    if os.getpgrp() != owner:
        raise RuntimeError('worker is not the leader of its isolated process group')
    with subprocess.Popen(['/bin/ps', '-axo', 'pid=,pgid=,stat='],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as probe:
        try:
            output, error = probe.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            probe.kill()  # Only our ps probe, never the restoration worker.
            probe.communicate()
            raise RuntimeError('process-group inspection timed out') from None
        if probe.returncode:
            raise RuntimeError(f'process-group inspection failed: {error.strip()}')
        members = set()
        for line in output.splitlines():
            fields = line.split()
            if len(fields) != 3:
                raise RuntimeError('invalid process-group inspection output')
            pid, group = map(int, fields[:2])
            if group != owner or pid in {owner, probe.pid}:
                continue
            # Reap direct children left by interrupted subprocess.run calls.
            # Orphan zombies cannot execute or write source and may be reaped
            # only by their new parent; do not wait forever for those.
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not fields[2].startswith('Z'):
                members.add(pid)
    return members


def _drain_descendants() -> bool:
    """After restoration, TERM then bounded KILL of same-group members only.

    Return whether there were live descendants. Failure is not permission to
    release execution.lock: the caller retains ownership and retries instead.
    """
    owner = os.getpid()
    seen = False
    terminated = set()
    for escalation, seconds in ((False, 1.0), (True, 2.0)):
        deadline = time.monotonic() + seconds
        killed = set()
        while True:
            members = _group_members()
            if not members:
                return seen
            seen = True
            for pid in members:
                if pid == owner:
                    raise RuntimeError('refusing to signal the restoration worker')
                signum = signal.SIGTERM if pid not in terminated else signal.SIGKILL
                if pid in terminated and (not escalation or pid in killed):
                    continue
                try:
                    # Recheck membership immediately before signalling a PID.
                    if os.getpgid(pid) != owner:
                        continue
                    os.kill(pid, signum)
                except ProcessLookupError:
                    continue
                if signum == signal.SIGTERM:
                    terminated.add(pid)
                else:
                    killed.add(pid)
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
    raise RuntimeError('same-group descendants have not stopped after TERM/KILL; execution ownership retained')


def run(directory: Path) -> None:
    directory = safe_path(directory)
    root = directory.parent.parent
    lock = execution_lock(root)
    budget_expired = False
    was_interrupted = False
    config = None

    def interrupted(signum, frame):
        # A second interrupt must not interrupt the restoration finally blocks.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_REAL, 0)
        raise KeyboardInterrupt

    def deadline(signum, frame):
        nonlocal budget_expired
        budget_expired = True
        os.killpg(os.getpgrp(), signal.SIGINT)

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGALRM, deadline)
    progress = {'phase': 'checking', 'completed_commands': 0}
    write_json(directory / 'progress.json', progress)
    original = runner.Runner._exec

    def tracked(self, argv, timeout):
        progress['phase'] = argv[1] if len(argv) > 1 else 'command'
        write_json(directory / 'progress.json', progress)
        result = original(self, argv, timeout)
        progress['completed_commands'] += 1
        write_json(directory / 'progress.json', progress)
        print(f"Completed command {progress['completed_commands']}: {progress['phase']}", flush=True)
        return result

    runner.Runner._exec = tracked
    result = {'state': 'failed', 'error': 'Worker did not finish'}
    try:
        config = json.loads(read_bytes(directory / 'request.json', 64 * 1024))
        signal.setitimer(signal.ITIMER_REAL, min(7200, max(1, config['budget_seconds'])))
        write_json(directory / 'ready.json', {'ready': True})
        if (directory / 'cancel.json').is_file():
            raise KeyboardInterrupt
        config = validate_job(config, root)
        artifacts = private_dir(directory / 'artifacts')
        outcome = orchestrator.run_repo(Path(config['target_path']), artifacts,
            test_cmd=test_command(config), operators=[CATALOG[op] for op in config['operators']],
            timeout=config['timeout'], init_timeout=config['init_timeout'], init_attempts=config['init_attempts'],
            budget_seconds=config['budget_seconds'], max_mutants=config['max_mutants'],
            output_csv=artifacts / 'results.csv')
        result = {'state': 'completed' if outcome.status in {'completed', 'skipped'} else 'failed',
                  'error': outcome.reason[:4000] or None, 'outcome': asdict(outcome)}
    except KeyboardInterrupt:
        was_interrupted = True
        result = {'state': 'failed' if budget_expired else 'cancelled',
                  'error': 'Wall-clock execution budget exhausted; owned source restoration finished.' if budget_expired else None}
    except Exception as exc:
        result = {'state': 'failed', 'error': f'{type(exc).__name__}: {exc}'[:4000]}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        runner.Runner._exec = original
        # Core restoration finally blocks have finished before TERM/KILL can
        # reach any descendants. Keep this worker, its group ID and its flock
        # alive until draining is confirmed, even if the GUI server restarts.
        progress['phase'] = 'draining'
        try:
            write_json(directory / 'progress.json', progress)
        except OSError:
            pass  # A progress-write failure must not bypass descendant draining.
        cleanup_failed = False
        while True:
            try:
                drained = _drain_descendants()
                break
            except Exception as exc:
                cleanup_failed = True
                result = {'state': 'failed', 'error': f'Descendant cleanup failed before retry: {exc}'[:4000]}
                progress.update(phase='cleanup_blocked', error=result['error'] + '; execution ownership retained until cleanup is confirmed')
                try:
                    write_json(directory / 'progress.json', progress)
                except OSError:
                    pass  # Inspection failure must not make us drop the flock.
                time.sleep(0.5)
        # A descendant's shutdown handler may itself have written source after
        # restoration. Confirm tracked/index cleanliness only once it is stopped.
        if config and (was_interrupted or drained or cleanup_failed):
            from .validation import _git
            try:
                repo = Path(_git(Path(config['target_path']), 'rev-parse', '--show-toplevel'))
                if _git(repo, 'status', '--porcelain', '--untracked-files=no'):
                    raise ValueError('tracked changes remain after cleanup; inspect the repository before rerunning')
            except Exception as exc:
                result = {'state': 'failed', 'error': f'Restoration could not be confirmed: {exc}'}
        write_json(directory / 'result.json', result)
        lock.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    run(Path(sys.argv[1]))
