"""Unit tests for the batch orchestrator: resumability and per-repo isolation.

These use throwaway git repos and monkeypatched runner internals rather than real terraform
executions, so they run fast and don't depend on network/provider state -- the properties
under test (skip-on-resume, one repo's failure doesn't kill the batch, final clean-check
covers every repo) are orchestration logic, not mutation-engine behavior.
"""

from __future__ import annotations

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

def test_run_repo_skips_when_csv_already_exists(tmp_path, three_repos, monkeypatch):
    repo = three_repos[0]
    out = tmp_path / "out"
    out.mkdir()
    (out / f"{repo.name}.csv").write_text("repo_name\n")  # pre-existing "completed" marker

    called = {"n": 0}

    def fake_check(binary):
        called["n"] += 1
        raise AssertionError("should never reach version check for an already-completed repo")

    monkeypatch.setattr(orchestrator, "check_pinned_version", fake_check)
    result = orchestrator.run_repo(repo, out)
    assert result.status == "skipped"
    assert called["n"] == 0


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
    state.checkout(three_repos[1], ".")  # cleanup


# --- aggregation ---------------------------------------------------------------------

def test_aggregate_master_csv_concatenates_repo_csvs(tmp_path):
    from tfmutate.reporter import CSV_COLUMNS

    out = tmp_path / "out"
    out.mkdir()
    header = ",".join(CSV_COLUMNS)
    row_a = ",".join(["repoA"] + [""] * (len(CSV_COLUMNS) - 1))
    row_b = ",".join(["repoB"] + [""] * (len(CSV_COLUMNS) - 1))
    (out / "repoA.csv").write_text(f"{header}\n{row_a}\n")
    (out / "repoB.csv").write_text(f"{header}\n{row_b}\n")

    master = tmp_path / "master.csv"
    n = orchestrator.aggregate_master_csv(out, master)
    assert n == 2
    lines = master.read_text().splitlines()
    assert lines[0] == header
    assert lines[1:] == [row_a, row_b]
