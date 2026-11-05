"""Unit tests for the batch orchestrator: resumability and per-repo isolation.

These use throwaway git repos and monkeypatched runner internals rather than real terraform
executions, so they run fast and don't depend on network/provider state -- the properties
under test (skip-on-resume, one repo's failure doesn't kill the batch, final clean-check
covers every repo) are orchestration logic, not mutation-engine behavior.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tfmutate import orchestrator, state


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, capture_output=True)
    (path / "main.tf").write_text('resource "x" "y" {}\n')
    (path / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture
def three_repos(tmp_path: Path) -> list[Path]:
    return [_init_repo(tmp_path / f"repo{i}") for i in (1, 2, 3)]


# --- resumability: skip already-completed repos ------------------------------------------

def test_run_repo_rejects_arbitrary_existing_csv_without_touching_it(tmp_path, three_repos, monkeypatch):
    repo = three_repos[0]
    out = tmp_path / "out"
    out.mkdir()
    csv = out / f"{repo.name}.csv"
    csv.write_text("repo_name\n")
    log = out / f"{repo.name}.log"
    log.write_text("previous evidence\n")
    monkeypatch.setattr(orchestrator, "check_pinned_version", lambda _: pytest.fail("must reject first"))
    result = orchestrator.run_repo(repo, out)
    assert result.status == "failed"
    assert "manifest" in result.reason.lower()
    assert csv.read_text() == "repo_name\n"
    assert log.read_text() == "previous evidence\n"


@pytest.mark.parametrize("staged", [False, True])
def test_run_repo_refuses_dirty_tree_without_checkout(tmp_path, three_repos, monkeypatch, staged):
    repo = three_repos[0]
    source = repo / "main.tf"
    source.write_text("user changes\n")
    if staged:
        subprocess.run(["git", "add", "main.tf"], cwd=repo, check=True)
    before_index = subprocess.check_output(["git", "diff", "--cached"], cwd=repo)
    monkeypatch.setattr(state, "checkout", lambda *a, **kw: pytest.fail("no checkout is permitted"))
    result = orchestrator.run_repo(repo, tmp_path / "out")
    assert result.status == "failed"
    assert "dirty" in result.reason
    assert source.read_text() == "user changes\n"
    assert subprocess.check_output(["git", "diff", "--cached"], cwd=repo) == before_index


def test_run_batch_does_not_reprocess_completed_repos(tmp_path, three_repos, monkeypatch):
    # Stub run_repo to track calls -- we're testing run_batch's control flow (iterate every
    # repo exactly once, never abort), not the full mutation cycle.
    calls = []

    def fake_run_repo(repo_path, output_dir, **kwargs):
        calls.append(Path(repo_path).name)
        return orchestrator.RepoResult(Path(repo_path).name, "completed", n_mutants=1)

    monkeypatch.setattr(orchestrator, "run_repo", fake_run_repo)
    results = orchestrator.run_batch(three_repos, tmp_path / "out")
    assert [r.repo for r in results] == [r.name for r in three_repos]
    assert calls == [r.name for r in three_repos]


# --- per-repo isolation: one repo's failure must not abort the batch ---------------------

def test_run_batch_continues_past_a_failing_repo(tmp_path, three_repos, monkeypatch):
    """The core check-2 property: if repo #2 hits a fatal condition (e.g. version drift),
    repo #1 and repo #3 still get processed and their results are intact."""

    def fake_run_repo(repo_path, output_dir, **kwargs):
        name = Path(repo_path).name
        if name == "repo2":
            raise RuntimeError("simulated version drift / fatal repo error")
        return orchestrator.RepoResult(name, "completed", n_mutants=1)

    monkeypatch.setattr(orchestrator, "run_repo", fake_run_repo)
    results = orchestrator.run_batch(three_repos, tmp_path / "out")

    by_name = {r.repo: r for r in results}
    assert len(results) == 3  # the whole batch ran; nothing was lost
    assert by_name["repo1"].status == "completed"
    assert by_name["repo3"].status == "completed"
    assert by_name["repo2"].status == "failed"
    assert "simulated version drift" in by_name["repo2"].reason


def test_run_repo_itself_skips_and_logs_on_version_drift(tmp_path, three_repos, monkeypatch):
    """Below the run_batch layer: run_repo's own version-drift handling must return a
    FAILED result (not raise), so run_batch's try/except is a backstop, not the only guard."""
    from tfmutate.runner import VersionCheck

    monkeypatch.setattr(
        orchestrator, "check_pinned_version",
        lambda binary: VersionCheck(False, "simulated drift: pinned=1.0.0, actual=9.9.9"),
    )
    out = tmp_path / "out"
    result = orchestrator.run_repo(three_repos[0], out)
    assert result.status == "failed"
    assert "drift" in result.reason
    assert (out / f"{three_repos[0].name}.log").exists()  # logged, not silently dropped


def test_unexpected_exception_mid_repo_is_caught_and_logged(tmp_path, three_repos, monkeypatch):
    from tfmutate.runner import VersionCheck

    monkeypatch.setattr(orchestrator, "check_pinned_version", lambda binary: VersionCheck(True, "ok"))

    class ExplodingRunner:
        def __init__(self, **kwargs):
            pass

        def run_module(self):
            raise RuntimeError("boom mid-module")

    monkeypatch.setattr(orchestrator, "Runner", ExplodingRunner)
    out = tmp_path / "out"
    result = orchestrator.run_repo(three_repos[0], out)
    assert result.status == "failed"
    assert "boom mid-module" in result.reason
    # the repo must still be restorable/clean -- best-effort restore ran in the except branch
    assert state.is_clean(three_repos[0])


# --- final clean-check covers every repo, not just the ones just processed --------------

def test_verify_all_clean_covers_every_repo(three_repos):
    report = orchestrator.verify_all_clean(three_repos)
    assert set(report) == {r.name for r in three_repos}
    assert all(report.values())


def test_verify_all_clean_detects_a_dirty_repo(three_repos):
    (three_repos[1] / "main.tf").write_text("mutated\n")
    report = orchestrator.verify_all_clean(three_repos)
    assert report[three_repos[0].name] is True
    assert report[three_repos[1].name] is False
    # The dirty fixture is discarded by pytest; orchestration never resets it.


# --- aggregation ---------------------------------------------------------------------

def test_aggregate_master_csv_concatenates_verified_repo_csvs(tmp_path):
    import csv
    from tfmutate.reporter import CSV_COLUMNS, write_csv
    from tfmutate.provenance import write_manifest

    out = tmp_path / "out"
    out.mkdir()
    rows = [{"repo_name": name, "record_type": "module_baseline", "operator_id": "(baseline)",
             "test_status": "baseline_fail"} for name in ["repoA", "repoB"]]
    for row in rows:
        path = out / f"{row['repo_name']}.csv"
        write_csv([row], path)
        write_manifest(path.with_suffix(".manifest.json"), "fixture", path, {"state": "completed"})
    master = out / "master.csv"
    assert orchestrator.aggregate_master_csv(out, master) == 2
    with master.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == CSV_COLUMNS
        assert [row["repo_name"] for row in reader] == ["repoA", "repoB"]
    assert orchestrator.aggregate_master_csv(out, master) == 2  # does not aggregate itself
    summary = json.loads(master.with_suffix(".summary.json").read_text())
    assert summary["overall"]["generated_mutants"] == 0
    assert summary["overall"]["module_baseline_records"] == 2


@pytest.mark.parametrize("problem", ["header", "missing_manifest", "checksum"])
def test_aggregate_refuses_unverified_or_incompatible_csv_preserving_master(tmp_path, problem):
    from tfmutate.reporter import write_csv
    from tfmutate.provenance import write_manifest
    out = tmp_path / "out"
    out.mkdir()
    path = out / "tiny.csv"
    write_csv([], path)
    if problem == "header":
        path.write_text("wrong,header\na,b\n")
    if problem != "missing_manifest":
        write_manifest(path.with_suffix(".manifest.json"), "fixture", path, {"state": "completed"})
    if problem == "checksum":
        path.write_text("tampered\n")
    master = tmp_path / "master.csv"
    master.write_text("previous master\n")
    with pytest.raises(ValueError):
        orchestrator.aggregate_master_csv(out, master)
    assert master.read_text() == "previous master\n"


def _fake_execution(monkeypatch):
    from tfmutate.runner import MutantOutcome, VersionCheck
    calls = []
    monkeypatch.setattr(orchestrator, "check_pinned_version", lambda _: VersionCheck(True, "fixture engine"))
    monkeypatch.setattr(orchestrator, "binary_version", lambda _: "fixture-1", raising=False)
    monkeypatch.setattr(state, "checkout", lambda *a, **kw: pytest.fail("checkout is forbidden"))
    class FakeRunner:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.command_events = []
            self.scope_warnings = ["fixture warning"]
            self.provider_versions = {"example/provider": "1.0"}
            self.provider_lock_sha256 = "fixture-lock"
            calls.append(self)
        def run_module(self):
            log_dir = self.options.get("log_dir")
            if log_dir is not None:
                log_dir.mkdir(parents=True)
                (log_dir / "0000.log").write_text("raw fixture output\n")
            self.command_events.append({"argv": ["fixture", "test"], "duration_seconds": .25})
            return [MutantOutcome("tiny", "main.tf", "m1", "MUT-RES-002", "resilience", "R",
                                  "x.y", "x", "1", "2", "valid", "killed_assert", "n/a", "")]
    monkeypatch.setattr(orchestrator, "Runner", FakeRunner)
    return calls


def test_completed_manifest_resume_requires_same_configuration_and_checksum(tmp_path, three_repos, monkeypatch):
    calls = _fake_execution(monkeypatch)
    repo = three_repos[0]
    out = tmp_path / "out"
    first = orchestrator.run_repo(repo, out)
    assert first.status == "completed"
    manifest = out / f"{repo.name}.manifest.json"
    payload = json.loads(manifest.read_text())
    assert payload["completed"] is True
    assert payload["source_commit"] == subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert payload["configuration"]["options"]["engine_versions"] == {"terraform": "fixture-1"}
    assert payload["configuration"]["tool_code_sha256"]
    assert (out / f"{repo.name}.summary.json").is_file()
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert orchestrator.run_repo(repo, out).status == "skipped"
    assert len(calls) == 1
    assert all(p.read_bytes() == content for p, content in before.items())
    csv = out / f"{repo.name}.csv"
    csv.write_text("tampered\n")
    assert orchestrator.run_repo(repo, out).status == "failed"
    assert csv.read_text() == "tampered\n"
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["timeout", "engine", "command", "operator", "source"])
def test_resume_rejects_configuration_drift_preserving_outputs(tmp_path, three_repos, monkeypatch, change):
    from tfmutate.mutators import CATALOG
    calls = _fake_execution(monkeypatch)
    repo, out = three_repos[0], tmp_path / "out"
    assert orchestrator.run_repo(repo, out).status == "completed"
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    kwargs = {}
    if change == "timeout":
        kwargs["timeout"] = 12
    elif change == "engine":
        monkeypatch.setattr(orchestrator, "binary_version", lambda _: "fixture-2")
    elif change == "command":
        kwargs["test_cmd"] = "terraform test -filter=main.tftest.hcl"
    elif change == "operator":
        kwargs["operators"] = [next(iter(CATALOG.values()))]
    else:
        (repo / "main.tf").write_text("# new committed source\n")
        subprocess.run(["git", "add", "main.tf"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "changed"], cwd=repo, check=True, capture_output=True)
    result = orchestrator.run_repo(repo, out, **kwargs)
    assert result.status == "failed"
    assert len(calls) == 1
    assert all(p.read_bytes() == content for p, content in before.items())


def test_each_module_has_distinct_raw_logs_events_and_provider_evidence(tmp_path, three_repos, monkeypatch):
    calls = _fake_execution(monkeypatch)
    repo = three_repos[0]
    child = repo / "child"
    child.mkdir()
    (child / "main.tf").write_text('resource "x" "y" {}\n')
    (child / "main.tftest.hcl").write_text('# selected child\n')
    irrelevant = repo / "fixtures" / "deep"
    irrelevant.mkdir(parents=True)
    (irrelevant / "hidden.tftest.hcl").write_text("# MUST NOT CLASSIFY\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "modules"], cwd=repo, check=True, capture_output=True)
    seen_texts = []
    monkeypatch.setattr(orchestrator, "classify_outcomes", lambda rows, texts: seen_texts.extend(texts))
    out = tmp_path / "out"
    result = orchestrator.run_repo(repo, out, init_timeout=7, init_attempts=2,
                                   budget_seconds=9, max_mutants=3)
    assert result.status == "completed"
    assert len(calls) == 2
    dirs = [call.options["log_dir"] for call in calls]
    assert len(set(dirs)) == 2
    assert all((directory / "0000.log").read_text() == "raw fixture output\n" for directory in dirs)
    assert not any("MUST NOT CLASSIFY" in text for text in seen_texts)
    payload = json.loads((out / f"{repo.name}.manifest.json").read_text())
    assert len(payload["modules"]) == 2
    for module in payload["modules"]:
        assert module["command_events"][0]["duration_seconds"] == .25
        assert module["provider_versions"] == {"example/provider": "1.0"}
        assert module["provider_lock_sha256"] == "fixture-lock"
        assert module["scope_warnings"] == ["fixture warning"]
        assert module["duration_seconds"] >= 0
    assert all(c.options["init_timeout"] == 7 and c.options["init_attempts"] == 2 for c in calls)
    assert all(c.options["max_mutants"] <= 3 and c.options["budget_seconds"] <= 9 for c in calls)


def test_global_mutant_limit_does_not_construct_zero_limit_runner(tmp_path, three_repos, monkeypatch):
    calls = _fake_execution(monkeypatch)
    repo = three_repos[0]
    child = repo / "child"
    child.mkdir()
    (child / "main.tf").write_text('resource "x" "y" {}\n')
    (child / "main.tftest.hcl").write_text('run "x" {}\n')
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "child"], cwd=repo, check=True, capture_output=True)
    result = orchestrator.run_repo(repo, tmp_path / "out", max_mutants=1)
    assert result.status == "completed"
    assert len(calls) == 1
    assert calls[0].options["max_mutants"] == 1


def test_resume_is_refused_when_external_variable_inputs_are_untracked(tmp_path, three_repos, monkeypatch):
    calls = _fake_execution(monkeypatch)
    repo, out = three_repos[0], tmp_path / "out"
    monkeypatch.setenv("TF_VAR_example", "synthetic-input")
    assert orchestrator.run_repo(repo, out).status == "completed"
    assert orchestrator.run_repo(repo, out).status == "failed"
    assert len(calls) == 1


def test_resume_refuses_removed_external_input_from_original_run(tmp_path, three_repos, monkeypatch):
    calls = _fake_execution(monkeypatch)
    repo, out = three_repos[0], tmp_path / "out"
    monkeypatch.setenv("TF_VAR_example", "synthetic-input")
    assert orchestrator.run_repo(repo, out).status == "completed"
    monkeypatch.delenv("TF_VAR_example")
    assert orchestrator.run_repo(repo, out).status == "failed"
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["summary", "raw"])
def test_resume_requires_all_completed_evidence(tmp_path, three_repos, monkeypatch, missing):
    calls = _fake_execution(monkeypatch)
    repo, out = three_repos[0], tmp_path / "out"
    assert orchestrator.run_repo(repo, out).status == "completed"
    if missing == "summary":
        (out / f"{repo.name}.summary.json").unlink()
    else:
        next((out / f"{repo.name}.raw").rglob("0000.log")).unlink()
    assert orchestrator.run_repo(repo, out).status == "failed"
    assert len(calls) == 1
