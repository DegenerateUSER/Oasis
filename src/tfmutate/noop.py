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
from lark import Tree

from .parser import is_ignored_path

log = logging.getLogger(__name__)


def _literal_override(value: object) -> bool:
    """Recognize only non-null literal input, never evaluate Terraform expressions."""
    if isinstance(value, str):
        # hcl2 8 preserves quotes on literal strings; bare identifiers and ${...}
        # are expressions. Templates are unresolved even inside a quoted string.
        return value.startswith('"') and value.endswith('"') and "${" not in value and "%{" not in value
    if isinstance(value, list):
        return all(_literal_override(item) for item in value)
    if isinstance(value, dict):
        # Parenthesized/dynamic keys become ${...} in hcl2's dictionary view.
        return all(isinstance(key, str) and "${" not in key and "%{" not in key
                   and _literal_override(item) for key, item in value.items())
    return isinstance(value, (bool, int, float))


def _variable_assignments(blocks: object) -> dict | None:
    if blocks is None:
        return {}
    if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict):
        return None
    return {name: value for name, value in blocks[0].items() if name != "__is_block__"}


def default_is_shadowed(var_name: str, tftest_texts: list[str]) -> bool:
    """Prove every parsed run overrides the actual variable with a non-null literal.

    File-level variables are inherited, then run-level assignments take precedence.
    Missing runs, malformed files, unresolved inputs, and alternate module sources
    prevent proof; none is silently discarded to manufacture a NO_OP result.
    """
    if not var_name:
        return False
    saw_run = False
    for text in tftest_texts:
        try:
            parsed = hcl2.parses(text)
            tree = parsed.to_lark() if hasattr(parsed, "to_lark") else parsed
            root_body = tree.children[0]
            bodies = [(root_body, {"run", "variables"})]
            for child in root_body.children:
                if (isinstance(child, Tree) and child.data == "block"
                        and str(child.children[0].children[0]) == "run"):
                    run_body = next(item for item in child.children
                                    if isinstance(item, Tree) and item.data == "body")
                    bodies.append((run_body, {"variables"}))
            # hcl2's dictionary view cannot distinguish a block from a list of
            # objects with the same shape. Only actual run/variables blocks
            # can establish override evidence.
            if any(isinstance(child, Tree) and child.data == "attribute"
                   and str(child.children[0].children[0]) in reserved
                   for body, reserved in bodies for child in body.children):
                return False
            doc = hcl2.loads(text)
        except Exception as exc:  # noqa: BLE001 - absence of evidence cannot prove a no-op
            log.warning("cannot prove override for unparseable .tftest.hcl: %s", exc)
            return False
        file_level = _variable_assignments(doc.get("variables"))
        runs = doc.get("run", [])
        if file_level is None or not isinstance(runs, list):
            return False
        for run_item in runs:
            if not isinstance(run_item, dict) or len(run_item) != 1:
                return False
            body = next(iter(run_item.values()))
            if not isinstance(body, dict) or "module" in body:
                return False
            saw_run = True
            run_level = _variable_assignments(body.get("variables"))
            if run_level is None:
                return False
            effective = file_level | run_level
            if var_name not in effective or not all(_literal_override(value) for value in effective.values()):
                # Other unresolved inputs can read the original default too.
                return False
    return saw_run


def read_tftest_files(root: Path, test_directory: str | Path = "tests") -> list[str]:
    """Read only root tests and the selected test directory, never nested modules.

    ``root`` is the module under test, not a repository-wide recursive search.
    Read errors propagate so callers cannot mistake a partial suite for evidence.
    """
    root = Path(root)
    directory = Path(test_directory)
    if directory.is_absolute() or ".." in directory.parts:
        raise ValueError("test directory must stay within the module")
    selected = root / directory
    paths = set(root.glob("*.tftest.hcl")) | set(selected.glob("*.tftest.hcl"))
    return [p.read_text() for p in sorted(paths) if p.is_file() and not is_ignored_path(p)]


def is_noop(mutant, repo_root: Path, *, module_dir: Path | None = None,
            test_directory: str | Path = "tests") -> bool:
    """Whether a mutant is an override no-op. Only variable-default (V-surface) mutants can be."""
    if getattr(mutant, "surface", None) != "V":
        return False
    var_name = getattr(mutant, "variable_name", None)
    if not var_name:
        address = getattr(mutant, "resource_address", None)
        if isinstance(address, str) and address.startswith("variable."):
            var_name = address.removeprefix("variable.")
    if not isinstance(var_name, str) or not var_name or "." in var_name:
        return False
    root = Path(repo_root) / module_dir if module_dir is not None else Path(repo_root)
    try:
        texts = read_tftest_files(root, test_directory)
    except (OSError, UnicodeError) as exc:
        log.warning("cannot prove override from unreadable test suite: %s", exc)
        return False
    return default_is_shadowed(var_name, texts)
