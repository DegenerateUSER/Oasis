"""Batch orchestrator: run the full mutation cycle across many repos, unattended
(PROJECT_SPEC.md §5.1, §12 Phase 5).

Design constraints, all load-bearing for an overnight unattended run:

- **Repo-scoped, resumable.** Each repo's outcomes are written to its own CSV
  (``<output_dir>/<repo_name>.csv``) only once that repo *fully* completes (all modules run,
  git verified clean). A restarted batch skips any repo whose CSV already exists rather than
  re-running it -- the resume granularity is the repo, not the module, matching
  PROJECT_SPEC.md §9's "append-only and repo-scoped" note. A repo that crashes mid-way
  leaves no CSV, so it is retried in full next time (safe: every mutation cycle already
  restores itself via ``state.restored``).
- **Per-repo isolation.** Any per-repo fatal condition -- version drift, init failure, no
  test modules, an unexpected exception mid-cycle -- is caught, logged to
  ``<output_dir>/<repo_name>.log``, and recorded as a FAILED result. The batch loop *never*
  raises out because of one repo; it always proceeds to the next.
- **Self-healing precondition.** Before processing a repo, its git tree is unconditionally
  restored (``git checkout -- .``) in case a previous crashed run left it mutated --
  "ensures each is a clean git checkout before starting" (PROJECT_SPEC.md §5.1).
- **Verified clean afterward, for every repo -- not just the ones just run.** After the
  batch loop, every repo passed in (including ones skipped as already-completed) is
  re-checked with ``git status``, and the full clean/dirty table is returned so a caller can
  assert on it rather than spot-check.
"""

from __future__ import annotations

import csv
import logging
import shlex
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import state
from .classifier import classify_outcomes
from .mutators import CATALOG, Operator
from .noop import read_tftest_files
from .parser import find_test_module_dirs
from .reporter import CSV_COLUMNS, write_csv
from .runner import Runner, check_pinned_version

log = logging.getLogger(__name__)


@dataclass
class RepoResult:
    repo: str
    status: str  # completed | skipped | failed
    n_mutants: int = 0
    reason: str = ""


def _csv_path(output_dir: Path, repo_name: str) -> Path:
    return output_dir / f"{repo_name}.csv"


def _log_path(output_dir: Path, repo_name: str) -> Path:
    return output_dir / f"{repo_name}.log"


def _fail(output_dir: Path, repo_name: str, reason: str) -> RepoResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    _log_path(output_dir, repo_name).write_text(reason + "\n")
    log.warning("repo %s FAILED: %s", repo_name, reason)
    return RepoResult(repo_name, "failed", reason=reason)


def run_repo(
    repo_path: Path,
    output_dir: Path,
    *,
    test_cmd: str = "terraform test",
    timeout: int = 60,
    operators: list[Operator] | None = None,
    plugin_cache_dir: Path | None = None,
    allow_version_drift: bool = False,
) -> RepoResult:
    """Run the full mutation cycle for one repo. Never raises: every failure mode is caught,
    logged, and returned as a FAILED result so the caller (``run_batch``) can move on."""
    repo_path = Path(repo_path).resolve()
    repo_name = repo_path.name
    csv_path = _csv_path(output_dir, repo_name)

    if csv_path.exists():
        return RepoResult(repo_name, "skipped", reason="already completed (CSV exists)")

    try:
        repo_root = state.repo_root_of(repo_path)
    except RuntimeError as exc:
        return _fail(output_dir, repo_name, f"not a git repo: {exc}")

    # Self-healing: undo any mutation left behind by a previous crashed run before starting.
    try:
        state.checkout(repo_root, ".")
    except RuntimeError as exc:
        return _fail(output_dir, repo_name, f"could not restore starting state: {exc}")

    binary = shlex.split(test_cmd)[0]
    version = check_pinned_version(binary)
    if not version.ok and not allow_version_drift:
        # This is the mid-batch version-drift case: skip + log, never halt the batch.
        return _fail(output_dir, repo_name, f"version check failed: {version.message}")

    module_dirs = find_test_module_dirs(repo_path)
    if not module_dirs:
        return _fail(output_dir, repo_name, "no .tftest.hcl test modules found")

    ops = operators if operators is not None else list(CATALOG.values())
    all_outcomes = []
    try:
        for md in module_dirs:
            runner = Runner(
                module_dir=md, repo_root=repo_root, test_cmd=test_cmd, timeout=timeout,
                operators=ops, plugin_cache_dir=plugin_cache_dir,
            )
            outcomes = runner.run_module()
            classify_outcomes(outcomes, read_tftest_files(md))
            all_outcomes.extend(outcomes)
    except Exception as exc:  # noqa: BLE001 -- per-repo isolation is the whole point here
        try:
            state.checkout(repo_root, ".")  # best-effort restore even on a crash
        except Exception:
            log.error("post-crash restore also failed for %s", repo_name)
        return _fail(
            output_dir, repo_name,
            f"unexpected exception: {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )

    # Final safety net: clear any lock-file drift, then verify -- a repo is only ever marked
    # completed (and thus skippable on resume) once this is confirmed clean.
    state.checkout(repo_root, ".")
    if not state.is_clean(repo_root):
        return _fail(output_dir, repo_name, "git working tree not clean after run")

    write_csv(all_outcomes, csv_path)
    return RepoResult(repo_name, "completed", n_mutants=len(all_outcomes))


def run_batch(repo_paths: list[Path], output_dir: Path, **kwargs) -> list[RepoResult]:
    """Run every repo in ``repo_paths``. A failing repo never aborts the batch."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for repo_path in repo_paths:
        try:
            result = run_repo(repo_path, output_dir, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- absolute last-resort guard around run_repo
            log.error("orchestrator-level failure for %s: %s", repo_path, exc)
            result = RepoResult(Path(repo_path).name, "failed", reason=f"orchestrator error: {exc}")
        results.append(result)
        log.info("[%s] %s%s", result.status, result.repo, f" ({result.reason})" if result.reason else "")
    return results


def verify_all_clean(repo_paths: list[Path]) -> dict[str, bool]:
    """git-status-clean check for EVERY repo passed in, not just the ones just run."""
    report = {}
    for repo_path in repo_paths:
        repo_path = Path(repo_path)
        try:
            root = state.repo_root_of(repo_path)
            report[repo_path.name] = state.is_clean(root)
        except RuntimeError:
            report[repo_path.name] = False
    return report


def aggregate_master_csv(output_dir: Path, master_path: Path) -> int:
    """Concatenate every completed repo's per-repo CSV into one master dataset."""
    output_dir, master_path = Path(output_dir), Path(master_path)
    rows = []
    for csv_file in sorted(output_dir.glob("*.csv")):
        if csv_file.resolve() == master_path.resolve():
            continue
        with open(csv_file, newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            rows.extend(reader)
    with open(master_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return len(rows)
