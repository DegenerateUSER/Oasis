"""Safe repo-scoped orchestration with content-verified completion manifests.

Dirty trees are refused, never repaired. Existing artifacts are immutable: only
an identical configuration and completed/checksummed manifest permit resume.
Use a new output path to rerun incomplete or differently configured work.
"""
from __future__ import annotations

import csv
import json
import logging
import shlex
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import state
from .classifier import classify_outcomes
from .metrics import summarize
from .mutators import CATALOG, Operator
from .parser import find_test_module_dirs
from .provenance import can_resume, configuration_inputs, configuration_signature, resume_context_is_known, write_manifest
from .reporter import CSV_COLUMNS, _atomic_stream, read_csv, write_csv, write_summary
from .runner import Runner, binary_version, check_pinned_version
from .scope import command_options, selected_test_files

log = logging.getLogger(__name__)


@dataclass
class RepoResult:
    repo: str
    status: str  # completed | skipped | failed
    n_mutants: int = 0
    reason: str = ""
    csv_path: str = ""
    manifest_path: str = ""
    summary_path: str = ""


def _csv_path(output_dir: Path, repo_name: str) -> Path:
    return output_dir / f"{repo_name}.csv"


def _log_path(output_dir: Path, repo_name: str) -> Path:
    return output_dir / f"{repo_name}.log"


def _fail(output_dir: Path, repo_name: str, reason: str) -> RepoResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with _log_path(output_dir, repo_name).open("x") as stream:
            stream.write(reason + "\n")
    except FileExistsError:
        pass  # Never overwrite evidence from a previous attempt.
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
    init_timeout: int = 300,
    init_attempts: int = 3,
    budget_seconds: float | None = None,
    max_mutants: int | None = None,
    output_csv: Path | None = None,
) -> RepoResult:
    """Run one repo (or subtree), isolating failures without discarding any work.

    Budget and mutant limits apply across the selected modules, not separately to
    each one. Raw output may contain engine-emitted sensitive values; keep it local.
    """
    repo_path, output_dir = Path(repo_path).resolve(), Path(output_dir)
    repo_name = repo_path.name
    csv_path = Path(output_csv) if output_csv is not None else _csv_path(output_dir, repo_name)
    manifest_path = csv_path.with_suffix(".manifest.json")
    summary_path = csv_path.with_suffix(".summary.json")
    raw_dir = csv_path.with_suffix(".raw")
    started = time.perf_counter()
    try:
        repo_root = state.repo_root_of(repo_path).resolve()
        state.require_clean(repo_root)
        revision = state._git(repo_root, "rev-parse", "HEAD")
        if revision.returncode != 0:
            raise RuntimeError("target repository needs an existing source commit")
        source_commit = revision.stdout.strip()
        if timeout <= 0 or init_timeout <= 0 or init_attempts < 1:
            raise ValueError("timeout/init-timeout must be positive and init-attempts at least 1")
        if budget_seconds is not None and budget_seconds <= 0:
            raise ValueError("budget-seconds must be positive")
        if max_mutants is not None and max_mutants <= 0:
            raise ValueError("max-mutants must be positive")
        if csv_path.exists() and not manifest_path.is_file():
            raise RuntimeError("existing CSV lacks a completion manifest; use a new output path")
        tokens = shlex.split(test_cmd)
        if not tokens:
            raise ValueError("test command is empty")
        binary = tokens[0]
        version_check = check_pinned_version(binary)
        if not version_check.ok and not allow_version_drift:
            raise RuntimeError(f"version check failed: {version_check.message}")
        engine_version = binary_version(binary)
        ops = list(CATALOG.values()) if operators is None else operators
        options = {"target": str(repo_path.relative_to(repo_root)), "test_cmd": tokens,
                   "timeout": timeout, "init_timeout": init_timeout, "init_attempts": init_attempts,
                   "budget_seconds": budget_seconds, "max_mutants": max_mutants,
                   "operators": sorted(op.id for op in ops),
                   "plugin_cache_dir": str(Path(plugin_cache_dir).expanduser().resolve()) if plugin_cache_dir else None,
                   "allow_version_drift": allow_version_drift,
                   "engine_versions": {binary: engine_version}}
        signature = configuration_signature(repo_root, options)
        configuration = configuration_inputs(repo_root, options)
        initial_context_known = resume_context_is_known(repo_root)
        if any(path.exists() for path in (csv_path, manifest_path, summary_path, raw_dir)):
            if engine_version is not None and can_resume(manifest_path, csv_path, signature):
                if not resume_context_is_known(repo_root):
                    raise RuntimeError("external variable/workspace inputs prevent safe resume; use a new output path")
                previous = read_csv(csv_path)
                if any(row.get("test_status") == "baseline_fail" for row in previous):
                    raise RuntimeError("baseline-failure results are not automatically reusable; use a new output path")
                summary = summarize(previous)
                return RepoResult(repo_name, "skipped", summary["generated_mutants"],
                                  "verified completed manifest and CSV checksum", str(csv_path),
                                  str(manifest_path), str(summary_path))
            raise RuntimeError("existing artifacts do not match a completed manifest/configuration/checksum; use a new output path")
        test_directory, _ = command_options(test_cmd)
        module_dirs = [md for md in find_test_module_dirs(repo_path, test_directory)
                       if md.resolve().is_relative_to(repo_root)
                       and selected_test_files(md, test_cmd)]
        if not module_dirs:
            raise RuntimeError("no selected .tftest.hcl test modules found")
        raw_dir.mkdir(parents=True, exist_ok=False)
        all_outcomes, modules = [], []
        for index, md in enumerate(module_dirs):
            elapsed = time.perf_counter() - started
            remaining_budget = None if budget_seconds is None else budget_seconds - elapsed
            if remaining_budget is not None and remaining_budget <= 0:
                modules.append({"module_dir": str(md.relative_to(repo_root)), "status": "budget_exhausted", "not_run": True})
                continue
            remaining_mutants = None if max_mutants is None else max(0, max_mutants - summarize(all_outcomes)["generated_mutants"])
            if remaining_mutants == 0:
                modules.append({"module_dir": str(md.relative_to(repo_root)), "status": "limit_reached", "not_run": True})
                continue
            module_logs = raw_dir / f"module-{index:04d}"
            runner = Runner(module_dir=md, repo_root=repo_root, test_cmd=test_cmd, timeout=timeout,
                            operators=ops, plugin_cache_dir=plugin_cache_dir,
                            init_timeout=init_timeout, init_attempts=init_attempts,
                            budget_seconds=remaining_budget, max_mutants=remaining_mutants,
                            log_dir=module_logs)
            module_started = time.perf_counter()
            evidence = {"module_dir": str(md.relative_to(repo_root)), "log_dir": str(module_logs.resolve())}
            try:
                outcomes = runner.run_module()
                classify_outcomes(outcomes, [p.read_text() for p in selected_test_files(md, test_cmd)])
                all_outcomes.extend(outcomes)
                evidence["status"] = "completed"
            finally:
                evidence.update(duration_seconds=time.perf_counter() - module_started,
                                command_events=getattr(runner, "command_events", []),
                                scope_warnings=getattr(runner, "scope_warnings", []),
                                default_binding_events=getattr(runner, "default_binding_events", []),
                                provider_versions=getattr(runner, "provider_versions", {}),
                                provider_lock_sha256=getattr(runner, "provider_lock_sha256", ""))
                modules.append(evidence)
                with _atomic_stream(module_logs / "events.json") as stream:
                    json.dump(evidence, stream, sort_keys=True, indent=2, allow_nan=False)
                    stream.write("\n")
        state.require_clean(repo_root)
        if configuration_signature(repo_root, options) != signature:
            raise RuntimeError("configuration changed during run; refusing completion")
        write_csv(all_outcomes, csv_path)
        report = write_summary(all_outcomes, summary_path)
        write_manifest(manifest_path, signature, csv_path,
                       {"state": "completed", "repo": str(repo_root), "source_commit": source_commit, "configuration": configuration,
                        "resume_allowed": initial_context_known and resume_context_is_known(repo_root),
                        "artifact_paths": [summary_path, *(p for p in raw_dir.rglob("*") if p.is_file())],
                        "modules": modules, "duration_seconds": time.perf_counter() - started,
                        "summary_path": str(summary_path.resolve())})
        return RepoResult(repo_name, "completed", report["overall"]["generated_mutants"],
                          csv_path=str(csv_path), manifest_path=str(manifest_path), summary_path=str(summary_path))
    except Exception as exc:  # noqa: BLE001 -- batch isolation, not automatic destructive recovery
        return _fail(output_dir, repo_name,
                     f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


def run_batch(repo_paths: list[Path], output_dir: Path, **kwargs) -> list[RepoResult]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for repo_path in repo_paths:
        try:
            result = run_repo(repo_path, output_dir, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("orchestrator-level failure for %s: %s", repo_path, exc)
            result = RepoResult(Path(repo_path).name, "failed", reason=f"orchestrator error: {exc}")
        results.append(result)
        log.info("[%s] %s%s", result.status, result.repo, f" ({result.reason})" if result.reason else "")
    return results


def verify_all_clean(repo_paths: list[Path]) -> dict[str, bool]:
    report = {}
    for repo_path in repo_paths:
        repo_path = Path(repo_path)
        try:
            report[repo_path.name] = state.is_clean(state.repo_root_of(repo_path))
        except RuntimeError:
            report[repo_path.name] = False
    return report


def aggregate_master_csv(output_dir: Path, master_path: Path) -> int:
    """Aggregate only completed/checksummed current-schema per-repo artifacts.

    Configuration is not recomputed: this reports a historical completed run,
    rather than asserting that today's source tree still matches that run.
    """
    output_dir, master_path = Path(output_dir), Path(master_path)
    rows = []
    for csv_file in sorted(output_dir.glob("*.csv")):
        if csv_file.resolve() == master_path.resolve():
            continue
        manifest = csv_file.with_suffix(".manifest.json")
        try:
            payload = json.loads(manifest.read_text())
            signature = payload["signature"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"missing/invalid completion manifest: {manifest}") from exc
        if not can_resume(manifest, csv_file, signature, require_resumable=False):
            raise ValueError(f"incomplete or checksum-mismatched CSV: {csv_file}")
        with csv_file.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != CSV_COLUMNS:
                raise ValueError(f"incompatible CSV schema: {csv_file}")
            rows.extend(reader)
    count = write_csv(rows, master_path)
    write_summary(rows, master_path.with_suffix(".summary.json"))
    return count
