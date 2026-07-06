"""Static NO_OP detection for variable-default mutants.

A mutant that changes a ``variable {} default`` is **inert** if the test that would exercise
it overrides that variable in its ``variables {}`` block -- the default is never read, so the
mutant cannot be killed for any reason related to test quality. Counting it as SURVIVED would
silently inflate the "tests missed this" numbers, so such mutants are classified ``NO_OP`` (a
category distinct from INVALID and from SURVIVED/KILLED) and discarded before testing.

We detect this **statically** by parsing the repo's ``.tftest.hcl`` files: mock_provider and
per-run ``variables {}`` only exist inside ``terraform test``, so a standalone plan cannot
reproduce the override -- static analysis is both correct here and fast (PROJECT_SPEC.md §6).

Scope: this catches the *override* class of no-op (the one that actually occurs in practice).
A dynamic ``terraform test -verbose`` plan-diff can be added in Phase 2 if non-override
no-ops are observed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import hcl2

from .parser import is_ignored_path

log = logging.getLogger(__name__)


def _assigned_var_names(variables_blocks: object) -> set[str]:
    """Collect variable names assigned across a list of ``variables {}`` blocks."""
    names: set[str] = set()
    if isinstance(variables_blocks, list):
        for block in variables_blocks:
            if isinstance(block, dict):
                names.update(block.keys())
    return names


def default_is_shadowed(var_name: str, tftest_texts: list[str]) -> bool:
    """True if every test run that could use ``var_name``'s default overrides it instead.

    Returns False if any run leaves the variable unset (the default is live there), and False
    if there are no runs at all (no override signal -- that is a coverage question, not a
    no-op). File-level ``variables {}`` applies to every run in that file unless the run
    overrides it too.
    """
    saw_run = False
    for text in tftest_texts:
        try:
            doc = hcl2.loads(text)
        except Exception as exc:  # noqa: BLE001 - malformed test file: ignore for this check
            log.warning("skipping unparseable .tftest.hcl: %s", exc)
            continue
        file_level = _assigned_var_names(doc.get("variables"))
        # hcl2 wraps labeled blocks as {label: body}, so each `run "x" {}` is {"x": {...}}.
        for run_item in doc.get("run") or []:
            if not isinstance(run_item, dict):
                continue
            for body in run_item.values():
                saw_run = True
                run_level = _assigned_var_names(body.get("variables")) if isinstance(body, dict) else set()
                if var_name not in run_level and var_name not in file_level:
                    return False  # this run uses the default -> mutant is not a no-op
    return saw_run


def read_tftest_files(root: Path) -> list[str]:
    """Return the text of every ``.tftest.hcl`` file under ``root`` (excluding vendored
    third-party module code under ``.terraform/``)."""
    return [
        p.read_text() for p in sorted(root.rglob("*.tftest.hcl"))
        if p.is_file() and not is_ignored_path(p)
    ]


def is_noop(mutant, repo_root: Path) -> bool:
    """Whether a mutant is an override no-op. Only variable-default (V-surface) mutants can be."""
    if getattr(mutant, "surface", None) != "V":
        return False
    return default_is_shadowed(mutant.attribute, read_tftest_files(repo_root))
