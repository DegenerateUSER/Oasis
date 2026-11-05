"""Unit tests for git-based state management, using a throwaway repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tfmutate import state


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init")
    git("config", "user.email", "t@e.st")
    git("config", "user.name", "t")
    (tmp_path / "main.tf").write_text('acl = "private"\n')
    git("add", "-A")
    git("commit", "-m", "init")
    return tmp_path


def test_repo_root_and_is_clean(git_repo: Path):
    assert state.repo_root_of(git_repo / "main.tf").resolve() == git_repo.resolve()
    assert state.is_clean(git_repo) is True


def test_restored_undoes_mutation_even_on_exception(git_repo: Path):
    f = git_repo / "main.tf"
    with pytest.raises(ValueError):
        with state.restored(git_repo, f):
            f.write_text('acl = "public"\n')
            assert not state.is_clean(git_repo)  # dirty inside the block
            raise ValueError("boom")  # restore must still run
    assert f.read_text() == 'acl = "private"\n'
    assert state.is_clean(git_repo) is True


def test_checkout_dot_restores_everything(git_repo: Path):
    (git_repo / "main.tf").write_text("mutated\n")
    state.checkout(git_repo, ".")
    assert state.is_clean(git_repo)


def test_untracked_build_byproduct_does_not_count_as_dirty(git_repo: Path):
    # e.g. a `data "archive_file"` materializes a real zip file as a side effect of
    # `terraform plan` alone -- not something we mutated, and not every real-world module's
    # own .gitignore happens to cover its own build output (PHASE5_NOTES.md).
    (git_repo / "lambda.zip").write_bytes(b"not a real zip, just a stray byproduct")
    assert state.is_clean(git_repo) is True


def test_modified_tracked_file_still_counts_as_dirty(git_repo: Path):
    (git_repo / "main.tf").write_text("mutated\n")
    assert state.is_clean(git_repo) is False


def test_restored_preserves_preexisting_unstaged_bytes(git_repo: Path):
    source = git_repo / "main.tf"
    source.write_bytes(b"# user change\r\n")
    with state.restored(git_repo, source):
        source.write_text("temporary mutant\n")
    assert source.read_bytes() == b"# user change\r\n"


def test_run_module_refuses_dirty_tree_before_init(tmp_path, monkeypatch):
    from tfmutate.runner import Runner
    runner = Runner(tmp_path, tmp_path)
    monkeypatch.setattr(state, "is_clean", lambda *a, **kw: False)
    monkeypatch.setattr(runner, "init", lambda: pytest.fail("init must not run on dirty tree"))
    with pytest.raises(RuntimeError, match="dirty"):
        runner.run_module()
