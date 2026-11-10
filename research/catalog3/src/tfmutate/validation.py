"""Recreate test-supplied caller aliases for standalone engine validation."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
from .scope import configuration_files
import re
import shlex
import tempfile

import hcl2

from .parser import code_mask, find_blocks
from .scope import selected_test_files


def _aliases(text: str, kinds: set[str]) -> set[tuple[str, str]]:
    result = set()
    tree = hcl2.parses_to_tree(text)
    for node in tree.children[0].children:
        if getattr(node, "data", None) != "block":
            continue
        kind = str(node.children[0].children[0])
        if kind not in kinds:
            continue
        label = node.children[1]
        name = json.loads(text[label.meta.start_pos:label.meta.end_pos])
        body = next(c for c in node.children if getattr(c, "data", None) == "body")
        for attr in body.children:
            if getattr(attr, "data", None) != "attribute" or str(attr.children[0].children[0]) != "alias":
                continue
            raw = text[attr.meta.start_pos:attr.meta.end_pos].split("=", 1)[1].strip()
            alias = json.loads(raw)
            if not isinstance(alias, str):
                raise ValueError("provider aliases must be literal strings")
            result.add((name, alias))
    return result


def caller_aliases(module_dir: Path, test_cmd: str) -> list[tuple[str, str]]:
    """Only supply test-declared aliases referenced by this root configuration.

    Child modules must still receive their configurations through their actual
    module calls. Existing source configurations are never replaced.
    """
    supplied = set()
    for test in selected_test_files(module_dir, test_cmd):
        supplied.update(_aliases(test.read_text(), {"provider", "mock_provider"}))
    if not supplied:
        return []
    configured, masked = set(), []
    for source in configuration_files(Path(module_dir), shlex.split(test_cmd)[0]):
        text = source.read_text()
        masked.append(code_mask(text))
        lines = text.splitlines(keepends=True)
        # Parse provider fragments, not unrelated source grammar or expressions.
        for block in find_blocks(text):
            if block.kind == "provider":
                fragment = "".join(lines[block.start_line - 1:block.end_line])
                configured.update(_aliases(fragment, {"provider"}))
    code = "\n".join(masked)
    return sorted((name, alias) for name, alias in supplied - configured
                  if re.search(r"(?<![\w-])" + re.escape(name + "." + alias) + r"(?![\w-])", code))


@contextmanager
def provider_alias_context(module_dir: Path, test_cmd: str, log_dir: Path | None = None):
    """Create owned, temporary empty configurations during validate only.

    These stand in for the caller configurations that test supplies. No real
    credentials or test mock defaults are copied. The actual test runs after
    cleanup and continues to use its original provider/mock configurations.
    """
    aliases = caller_aliases(module_dir, test_cmd)
    if not aliases:
        yield []
        return
    content = "\n".join('provider ' + json.dumps(name) + ' {\n  alias = ' + json.dumps(alias) + '\n}\n'
                        for name, alias in aliases)
    fd, filename = tempfile.mkstemp(prefix="oasis_validate_", suffix=".tf", dir=module_dir)
    path = Path(filename)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "validation-provider-context.log").write_text(content)
        yield [name + "." + alias for name, alias in aliases]
    finally:
        path.unlink(missing_ok=True)
