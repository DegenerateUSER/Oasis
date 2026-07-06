"""Locate mutation targets in Terraform source, and gate files on validity.

This module is deliberately **read-only** w.r.t. the .tf content. Target location is done
with a cheap brace-aware raw-text scan (see ``find_blocks``): this is robust regardless of
any third-party parser's grammar coverage and exposes the source line numbers hcl2 does not.
The actual mutation is a regex text edit (see ``mutators.py``).

**Validity gate.** Whether a file is valid HCL is decided by ``terraform fmt`` -- the *same
engine that runs the tests* -- not by ``python-hcl2``. hcl2's grammar is stricter than
Terraform's (e.g. it rejects some ``for`` expressions Terraform accepts), so using it as the
gate silently drops real, valid files. ``terraform fmt`` cannot have that false-rejection gap
(PROJECT_SPEC.md §6.1; PHASE1_NOTES.md).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Default binary; the runner may pass an explicit one for OpenTofu (`tofu`).
_FMT_CMD = "terraform"


# `.terraform/` holds provider binaries and, for remote module sources, a full local copy of
# vendored third-party module code fetched by `terraform init`. It is gitignored and
# untracked -- mutating a file under it and then trying `git checkout --` to restore fails
# outright (no git record to restore from), and even where it wouldn't fail, it isn't part of
# the repo under study. Every scan that could become a mutation or test target must skip it.
_IGNORED_DIR_NAMES = {".terraform", ".git"}


def is_ignored_path(path: Path) -> bool:
    return not _IGNORED_DIR_NAMES.isdisjoint(path.parts)


def read_tf_files(root: Path) -> list[Path]:
    """Return every ``.tf`` file under ``root``, sorted for deterministic ordering."""
    return sorted(p for p in root.rglob("*.tf") if p.is_file() and not is_ignored_path(p))


# Terraform's own test-discovery convention (developer.hashicorp.com/terraform/language/tests):
# `terraform test` is run from the MODULE ROOT and auto-discovers test files both alongside
# the module's own .tf files AND inside a nested test-only subdirectory dedicated to tests
# (conventionally `tests/`, but real repos use other names too -- `test/`, `e2e-tests/`, etc.).
# The directory *containing* a `.tftest.hcl` file is therefore not always the correct
# `init`/`test` working directory. The rule is deliberately **not** name-based (matching only
# `tests`/`test` missed real repos using `e2e-tests` in the Phase 5 batch): a directory with
# zero `.tf` files of its own can never have anything to plan/test locally, regardless of what
# it's called, so the real module root -- if there is one -- is its immediate parent.
#
# Climbing is bounded to exactly one level, and a `.tftest.hcl` whose directory has no `.tf`
# files AND whose parent doesn't either is **excluded** entirely rather than resolved further
# up an arbitrary ancestor chain. Terraform's own convention only recognizes this one-level
# nesting; climbing further risks silently resolving to an unrelated, wrong module. A real
# corpus example of this exclusion case: a Bazel-based test-harness directory (`BUILD`, `.bzl`
# files, a `.tftest.hcl` *template*) that is tooling, not an actual module under test --
# PHASE5_NOTES.md.
def _module_root_for_test_file(tftest_path: Path) -> Path | None:
    parent = tftest_path.parent
    if any(parent.glob("*.tf")):
        return parent
    grandparent = parent.parent
    if any(grandparent.glob("*.tf")):
        return grandparent
    return None  # no .tf files at this level or one level up -- not a real module; exclude


def find_test_module_dirs(root: Path) -> list[Path]:
    """Module root directories under ``root`` that should be run through `init`/`test`,
    resolved from every ``.tftest.hcl`` file found (see ``_module_root_for_test_file``),
    sorted and deduplicated. A ``.tftest.hcl`` that resolves to no real module (no ``.tf``
    files at its own level or one level up) is excluded, not misresolved."""
    return sorted({
        root_dir
        for p in root.rglob("*.tftest.hcl") if p.is_file() and not is_ignored_path(p)
        if (root_dir := _module_root_for_test_file(p)) is not None
    })


def is_valid_hcl(text: str, fmt_cmd: str = _FMT_CMD) -> bool:
    """True if ``text`` is valid HCL, per ``terraform fmt`` (the authoritative engine).

    ``terraform fmt -`` reads stdin and exits non-zero on a genuine syntax error. Files that
    fail here have a real syntax error (rare) and are logged + skipped, not silently dropped
    -- see the SKIPPED_FILE handling in the CLI/orchestrator.
    """
    try:
        result = subprocess.run(
            [fmt_cmd, "fmt", "-"], input=text, capture_output=True, text=True
        )
    except FileNotFoundError:
        log.error("%s not found on PATH; cannot validate HCL", fmt_cmd)
        raise
    if result.returncode != 0:
        log.warning("skipping file that failed `%s fmt`: %s", fmt_cmd, result.stderr.strip())
        return False
    return True


# --- Top-level block detection (kinds + ranges) ----------------------------------------
# Needed for resource-type scoping and for targeting the variable/locals surfaces
# (PROJECT_SPEC.md §6-7). We only track TOP-LEVEL blocks: a resource's type is fixed by its
# header regardless of how deeply an attribute is nested inside it, so top-level extents are
# sufficient to attribute any line to its enclosing block.

_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_LINE_COMMENT = re.compile(r"(#|//).*$")

_BLOCK_HEADERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'^\s*resource\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"'), "resource"),
    (re.compile(r'^\s*data\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"'), "data"),
    (re.compile(r'^\s*variable\s+"(?P<name>[^"]+)"'), "variable"),
    (re.compile(r'^\s*module\s+"(?P<name>[^"]+)"'), "module"),
    (re.compile(r'^\s*output\s+"(?P<name>[^"]+)"'), "output"),
    (re.compile(r'^\s*provider\s+"(?P<name>[^"]+)"'), "provider"),
    (re.compile(r"^\s*locals\s*\{"), "locals"),
    (re.compile(r"^\s*terraform\s*\{"), "terraform"),
]


@dataclass(frozen=True)
class Block:
    """A top-level HCL block with its source extent (1-based, inclusive)."""

    kind: str  # resource | data | variable | module | output | provider | locals | terraform
    type: str | None  # resource/data type, else None
    name: str | None  # block label, else None
    start_line: int
    end_line: int

    @property
    def address(self) -> str:
        if self.kind in ("resource", "data") and self.type and self.name:
            return f"{self.type}.{self.name}"
        if self.name:
            return f"{self.kind}.{self.name}"
        return self.kind


def _net_braces(line: str) -> int:
    """Net brace delta for a line, ignoring braces inside strings and line comments."""
    stripped = _LINE_COMMENT.sub("", _STRING.sub('""', line))
    return stripped.count("{") - stripped.count("}")


def find_blocks(text: str) -> list[Block]:
    """Return every top-level block with its kind, labels, and line range.

    Uses line-level brace counting (heredocs are not handled, but they do not appear in the
    attribute assignments operators target). Well-formed HCL — which `terraform fmt`
    guarantees for real repos — is parsed reliably.
    """
    blocks: list[Block] = []
    depth = 0
    current: dict | None = None
    for i, line in enumerate(text.splitlines(), start=1):
        if depth == 0 and current is None:
            for rx, kind in _BLOCK_HEADERS:
                if m := rx.match(line):
                    gd = m.groupdict()
                    current = {
                        "kind": kind,
                        "type": gd.get("type"),
                        "name": gd.get("name"),
                        "start": i,
                    }
                    break
        depth += _net_braces(line)
        if current is not None and depth <= 0:
            blocks.append(
                Block(current["kind"], current["type"], current["name"], current["start"], i)
            )
            current = None
            depth = 0
    return blocks


def enclosing_block(blocks: list[Block], line: int) -> Block | None:
    """The top-level block containing ``line`` (blocks do not overlap)."""
    for block in blocks:
        if block.start_line <= line <= block.end_line:
            return block
    return None


# A `tags = {` / `labels = {` / `*_tags = {` / `*_labels = {` map opener. Used to scope
# deletion-style tag operators to genuine tag/label maps, so a functional attribute that
# merely shares a synonym name (e.g. an `owner` field on aws_config_config_rule) is not
# mistaken for a required tag.
_TAG_MAP_OPEN = re.compile(r"^\s*(?:[A-Za-z0-9_]+_)?(?:tags|labels)\s*=\s*\{")


def find_tag_maps(text: str) -> list[tuple[int, int]]:
    """Return (start_line, end_line) ranges of every tag/label map literal (1-based)."""
    regions: list[tuple[int, int]] = []
    start: int | None = None
    depth = 0
    for i, line in enumerate(text.splitlines(), start=1):
        if start is None:
            if _TAG_MAP_OPEN.match(line):
                start, depth = i, _net_braces(line)
                if depth <= 0:  # single-line `tags = { ... }`
                    regions.append((i, i))
                    start = None
            continue
        depth += _net_braces(line)
        if depth <= 0:
            regions.append((start, i))
            start = None
    return regions


def in_regions(regions: list[tuple[int, int]], line: int) -> bool:
    return any(start <= line <= end for start, end in regions)
