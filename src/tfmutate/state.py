"""Git-based state management (PROJECT_SPEC.md §5.2, §6.1).

The one non-negotiable correctness rule of the mutation cycle: *every* path -- survived,
killed, invalid, timeout, or a crash -- must restore the mutated file before the next cycle,
or mutations stack and corrupt every later result. We use ``git checkout -- <file>`` rather
than a hand-rolled backup so restore is guaranteed by git, and wrap it in a context manager
whose ``finally`` runs unconditionally.

``terraform init`` also rewrites the tracked ``.terraform.lock.hcl``; :func:`checkout` with
``"."`` cleans that up per module. ``.terraform/`` itself is git-ignored, so it does not dirty
``git status``.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from pathlib import Path


def _git(repo_root: Path, *args: str, git: str = "git") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [git, "-C", str(repo_root), *args], capture_output=True, text=True
    )


def repo_root_of(path: Path | str, git: str = "git") -> Path:
    """The git top-level directory containing ``path``."""
    start = Path(path)
    start = start if start.is_dir() else start.parent
    result = _git(start, "rev-parse", "--show-toplevel", git=git)
    if result.returncode != 0:
        raise RuntimeError(f"{path} is not inside a git repo: {result.stderr.strip()}")
    return Path(result.stdout.strip())


def checkout(repo_root: Path, pathspec: str = ".", git: str = "git") -> None:
    """Restore ``pathspec`` (default: everything) to its committed state."""
    result = _git(repo_root, "checkout", "--", pathspec, git=git)
    if result.returncode != 0:
        raise RuntimeError(f"git checkout failed for {pathspec}: {result.stderr.strip()}")


def is_clean(repo_root: Path, git: str = "git") -> bool:
    """True if the working tree has no *tracked* changes.

    Untracked files don't count -- e.g. a `data "archive_file"` (or similar) data source
    materializes a real file on disk as a side effect of `terraform plan` alone, independent
    of anything we mutated, and not every real-world module's own `.gitignore` happens to
    cover its own build byproducts. Our correctness contract is specifically about not
    leaving *tracked* source content mutated; a target repo's untracked-file hygiene is its
    own business (PHASE5_NOTES.md).
    """
    result = _git(repo_root, "status", "--porcelain", "--untracked-files=no", git=git)
    return result.returncode == 0 and result.stdout.strip() == ""


@contextmanager
def restored(repo_root: Path, file_path: Path, git: str = "git"):
    """Guarantee ``git checkout -- <file>`` runs on exit, even on exception.

    The caller mutates ``file_path`` inside the ``with`` block; restore is unconditional.
    """
    rel = Path(file_path).resolve().relative_to(Path(repo_root).resolve())
    try:
        yield
    finally:
        checkout(repo_root, str(rel), git=git)
