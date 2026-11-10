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


def find_test_module_dirs(root: Path, test_directory: str | Path = "tests") -> list[Path]:
    """Find runnable modules, not arbitrary ancestors of discovered testfiles.

    Each candidate must contain configuration of its own. Only tests alongside
    that configuration and directly inside ``test_directory`` are discovered.
    Repository-wide discovery is not permission to mutate all these modules;
    dependency/mutation scope is resolved separately by ``scope.py``.
    """
    root = Path(root)
    directory = Path(test_directory)
    if directory.is_absolute() or ".." in directory.parts:
        raise ValueError("test directory must stay within the module")
    candidates = {p.parent for p in read_tf_files(root)}
    return sorted(module for module in candidates if any(
        p.is_file() and not is_ignored_path(p)
        for folder in (module, module / directory)
        for p in folder.glob("*.tftest.hcl")
    ))


def is_valid_hcl(text: str, fmt_cmd: str = _FMT_CMD) -> bool:
    """True if ``text`` has valid HCL syntax, per ``terraform fmt``.

    This does not validate provider schemas, attribute values, references, or plans.

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

_HEREDOC_OPEN = re.compile(r"<<(?P<indent>-?)(?P<marker>[\w-]+)[ \t]*\r?\n")


def _heredoc_span(text: str, start: int) -> tuple[int, int, int] | None:
    """Payload start/end and terminator end, or None for a non-heredoc token."""
    opener = _HEREDOC_OPEN.match(text, start)
    if opener is None:
        return None
    indent = r"[ \t]*" if opener.group("indent") else ""
    closer = re.compile(rf"^{indent}{re.escape(opener.group('marker'))}[ \t]*\r?$", re.MULTILINE)
    end = closer.search(text, opener.end())
    if end is None:
        return opener.end(), len(text), len(text)
    return opener.end(), end.start(), end.end()


def _template_end(text: str, start: int) -> int:
    """Skip an interpolation/directive, including nested quoted expressions."""
    depth, i = 1, start
    while i < len(text):
        if text.startswith(("//", "#"), i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        elif text[i] == '"':
            i = min(_quoted_end(text, i) + 1, len(text))
        elif text.startswith("<<", i) and (heredoc := _heredoc_span(text, i)):
            i = heredoc[2]
        else:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
    return i


def _quoted_end(text: str, start: int) -> int:
    """Index of the closing quote, or EOF; template expressions stay inside strings."""
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text.startswith(("$${", "%%{"), i):
            i += 3  # escaped template opener, not an expression
        elif text.startswith(("${", "%{"), i):
            i = _template_end(text, i + 2)
        elif text[i] == '"':
            return i
        else:
            i += 1
    return len(text)


def code_mask(text: str) -> str:
    """Return an offset/newline-preserving lexical view of HCL source.

    Replace comments (including delimiters), quoted-string contents (including all
    nested template expressions), and heredoc payloads with spaces. Preserve every
    other character, including outer quote delimiters, heredoc introducer/terminator,
    and all CR/LF characters. Offsets are Python string indices, not UTF-8 byte indices.
    Unterminated non-code constructs are hidden through EOF. This is a lexical helper,
    not a syntax or provider-schema validator.
    """
    masked = list(text)

    def hide(start: int, end: int) -> None:
        masked[start:end] = [c if c in "\r\n" else " " for c in text[start:end]]

    i = 0
    while i < len(text):
        if text.startswith(("//", "#"), i):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            hide(i, end)
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) if end < 0 else end + 2
            hide(i, end)
            i = end
        elif text[i] == '"':
            end = _quoted_end(text, i)
            hide(i + 1, end)
            i = min(end + 1, len(text))
        elif text.startswith("<<", i) and (heredoc := _heredoc_span(text, i)):
            hide(heredoc[0], heredoc[1])
            i = heredoc[2]
        else:
            i += 1
    return "".join(masked)



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


def _net_braces(masked_line: str) -> int:
    """Net brace delta for a line already processed by ``code_mask``."""
    return masked_line.count("{") - masked_line.count("}")


def find_blocks(text: str) -> list[Block]:
    """Return every top-level block with its kind, labels, and line range.

    Brace counting uses the full-file lexical mask, so comments, string templates,
    and heredoc payloads cannot create fake headers or change block extents.
    """
    blocks: list[Block] = []
    depth = 0
    current: dict | None = None
    for i, (line, masked) in enumerate(zip(text.splitlines(), code_mask(text).splitlines()), start=1):
        if depth == 0 and current is None:
            # Labels are read from raw source, but the header keyword must be code.
            first = len(masked) - len(masked.lstrip())
            for rx, kind in _BLOCK_HEADERS:
                if masked[first:].startswith(kind) and (m := rx.match(line[first:])):
                    gd = m.groupdict()
                    current = {
                        "kind": kind,
                        "type": gd.get("type"),
                        "name": gd.get("name"),
                        "start": i,
                    }
                    break
        depth += _net_braces(masked)
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
_TAG_MAP_OPEN = re.compile(r"(?<![\w-])(?:[A-Za-z0-9_]+_)?(?:tags|labels)\s*=\s*\{")


def find_tag_map_spans(text: str) -> list[tuple[int, int]]:
    """Return half-open source spans of tag/label map literals, in character offsets."""
    regions: list[tuple[int, int]] = []
    masked = code_mask(text)
    for match in _TAG_MAP_OPEN.finditer(masked):
        depth = 1
        for end in range(match.end(), len(masked)):
            if masked[end] == "{":
                depth += 1
            elif masked[end] == "}":
                depth -= 1
                if depth == 0:
                    regions.append((match.start(), end + 1))
                    break
    return regions


def find_tag_maps(text: str) -> list[tuple[int, int]]:
    """Return (start_line, end_line) ranges of every tag/label map literal (1-based)."""
    return [(text.count("\n", 0, start) + 1, text.count("\n", 0, end - 1) + 1)
            for start, end in find_tag_map_spans(text)]


def in_regions(regions: list[tuple[int, int]], line: int) -> bool:
    return any(start <= line <= end for start, end in regions)
