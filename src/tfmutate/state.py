"""Repository discovery and non-destructive mutation restoration.

Execution requires clean tracked/index state. Owned files are restored byte-for-byte
without resetting unrelated work or the index. Python finally blocks cover ordinary
exceptions and KeyboardInterrupt, not SIGKILL, interpreter termination or power loss.
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


def require_clean(repo_root: Path, git: str = "git") -> None:
    """Refuse dirty tracked/index state; never auto-discard someone else's work."""
    if not is_clean(repo_root, git=git):
        raise RuntimeError("dirty tracked/index state: commit/stash changes or use an isolated worktree")


@contextmanager
def preserved_files(repo_root: Path, paths: list[Path]):
    """Restore only owned files byte-for-byte, without touching the Git index.

    This covers exceptions/KeyboardInterrupt, not SIGKILL or power loss. Abandoned
    mutations make the tree dirty and are refused on the next run, never discarded.
    """
    snapshots = []
    root = Path(repo_root).resolve()
    for path in paths:
        path = Path(path)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise RuntimeError(f"unsafe restoration path: {path}")
        snapshots.append((path, path.read_bytes() if path.exists() else None,
                          path.stat().st_mode if path.exists() else None))
    try:
        yield
    finally:
        for path, content, mode in snapshots:
            if path.is_symlink():
                raise RuntimeError(f"restoration target became a symlink: {path}")
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
                path.chmod(mode)


@contextmanager
def restored(repo_root: Path, file_path: Path, git: str = "git"):
    """Restore the exact pre-mutation bytes and permissions, preserving staged work."""
    with preserved_files(repo_root, [file_path]):
        yield
