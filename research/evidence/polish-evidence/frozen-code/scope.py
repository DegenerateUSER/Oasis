"""Conservative, explicit module/test scope. Never recurse into arbitrary examples.

Only repository-local module sources are eligible. Remote modules are noted, not
mutated. This is source/dependency discovery, not runtime coverage instrumentation.
"""
from __future__ import annotations

import json
import shlex
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import hcl2


class ScopeError(ValueError):
    pass


def literal(value: object) -> str | None:
    """Normalize hcl2 v4-v8 quoted literals; reject interpolation expressions."""
    if not isinstance(value, str) or "${" in value or "%{" in value:
        return None
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, str) else None
        except (ValueError, TypeError):
            return None
    return value


def command_options(test_cmd: str) -> tuple[str, list[str]]:
    tokens = shlex.split(test_cmd)
    if len(tokens) < 2 or tokens[1] != "test":
        raise ScopeError("test command must be '<terraform-or-tofu> test [options]'")
    directory, filters = "tests", []
    i = 2
    while i < len(tokens):
        token = tokens[i]
        for option in ("-test-directory", "-filter"):
            if token == option:
                i += 1
                if i >= len(tokens):
                    raise ScopeError(f"missing value for {option}")
                value = tokens[i]
            elif token.startswith(option + "="):
                value = token.split("=", 1)[1]
            else:
                continue
            if option == "-test-directory":
                directory = value
            else:
                filters.append(value)
        if token.startswith("-chdir") or token.startswith("-var-file"):
            raise ScopeError("-chdir/-var-file require explicit scope handling and are unsupported")
        i += 1
    if Path(directory).is_absolute() or ".." in Path(directory).parts:
        raise ScopeError("test directory must stay within the module")
    return directory, filters


def configuration_files(root: Path, binary: str = "terraform") -> list[Path]:
    root = Path(root)
    files = {p.name: p for p in root.glob("*.tf") if not p.name.startswith(".")}
    if Path(binary).name == "tofu":
        for p in root.glob("*.tofu"):
            if not p.name.startswith("."):
                files.pop(p.name[:-5] + ".tf", None)
                files[p.name] = p
    return sorted(files.values())


def selected_test_files(module_dir: Path, test_cmd: str = "terraform test") -> list[Path]:
    directory, filters = command_options(test_cmd)
    module_dir = Path(module_dir)
    binary = shlex.split(test_cmd)[0]
    files = set()
    for folder in {module_dir, module_dir / directory}:
        byname = {p.name:p for p in folder.glob("*.tftest.hcl") if not p.name.startswith(".")}
        if Path(binary).name == "tofu":
            for p in folder.glob("*.tofutest.hcl"):
                if not p.name.startswith("."):
                    byname.pop(p.name[:-len(".tofutest.hcl")] + ".tftest.hcl", None)
                    byname[p.name] = p
        files.update(byname.values())
    if filters:
        wanted = {str(Path(f)) for f in filters}
        files = {p for p in files if str(p.relative_to(module_dir)) in wanted}
        missing = wanted - {str(p.relative_to(module_dir)) for p in files}
        if missing:
            raise ScopeError(f"test filter did not match discovered files: {sorted(missing)}")
    return sorted(p for p in files if p.is_file())


@dataclass
class MutationScope:
    files: list[Path]
    test_files: list[Path]
    roots: list[Path]
    has_runs: bool = False
    warnings: list[str] = field(default_factory=list)


def _native_module_document(path: Path, binary: str) -> dict:
    """Parse only dependency edges after the native engine validates all syntax."""
    from .parser import code_mask, find_blocks
    if path.suffix not in {".tf", ".tofu"}:
        raise ScopeError("Native source fallback does not infer test run blocks")
    formatted = subprocess.run([binary, "fmt", "-"], input=path.read_text(),
                               capture_output=True, text=True, timeout=30)
    if formatted.returncode:
        raise ScopeError("Native engine rejected source syntax")
    lines = formatted.stdout.splitlines(keepends=True)
    result = []
    for block in find_blocks(formatted.stdout):
        if block.kind != "module":
            continue
        text = "".join(lines[block.start_line - 1:block.end_line])
        masked = code_mask(text)
        sources = []
        for match in re.finditer(r"\bsource\s*=", masked):
            prefix = masked[:match.start()]
            if prefix.count("{") - prefix.count("}") != 1:
                continue
            end = match.end()
            while end < len(masked) and masked[end] not in "\r\n}":
                end += 1
            source = hcl2.loads(text[match.start():end]).get("source")
            sources.append(source)
        if len(sources) != 1:
            raise ScopeError("Module must have exactly one source attribute")
        result.append({block.name: {"source": sources[0]}})
    return {"module": result}


def _load(path: Path, binary: str = "terraform") -> dict:
    try:
        return hcl2.loads(path.read_text())
    except TypeError:
        # python-hcl2 8 can parse valid numeric expression expansions but fail
        # while serializing unrelated locals/assertions. Scope only depends on
        # module sources and run/module blocks; still parse the entire file.
        try:
            tree = hcl2.parses(path.read_text())

            def modules(body):
                result = []
                for block in body.children:
                    labels = getattr(block, "labels", [])
                    if labels and labels[0].serialize() == "module":
                        sources = [item.serialize() for item in block.body.children
                                   if getattr(item, "identifier", None) is not None
                                   and item.identifier.serialize() == "source"]
                        result.append({"source": sources[0]["source"]} if sources else {})
                return result

            result = {"module": [{str(i): body} for i, body in enumerate(modules(tree.body))]}
            result["run"] = []
            for block in tree.body.children:
                labels = getattr(block, "labels", [])
                if labels and labels[0].serialize() == "run":
                    result["run"].append({str(len(result["run"])): {"module": modules(block.body)}})
            return result
        except Exception as exc:
            raise ScopeError(f"cannot determine scope from {path}: {exc}") from exc
    except Exception as exc:
        try:
            return _native_module_document(path, binary)
        except Exception as fallback:
            raise ScopeError(f"cannot determine scope from {path}: {exc}; native fallback: {fallback}") from fallback


def _local(source: object, caller: Path, repo_root: Path, warnings: list[str]) -> Path | None:
    source = literal(source)
    if source is None:
        raise ScopeError("unresolved module source; refusing to guess test scope")
    if not source.startswith(("./", "../")):
        warnings.append(f"remote module excluded: {source}")
        return None
    root = (caller / source).resolve()
    if not root.is_relative_to(repo_root.resolve()):
        raise ScopeError(f"local module resolves outside repository: {root}")
    if not root.is_dir():
        raise ScopeError(f"missing local module: {root}")
    return root


def resolve_scope(module_dir: Path, repo_root: Path, test_cmd: str = "terraform test") -> MutationScope:
    module_dir, repo_root = Path(module_dir), Path(repo_root)
    tests = selected_test_files(module_dir, test_cmd)
    binary = shlex.split(test_cmd)[0]
    roots: set[Path] = set()
    warnings: list[str] = []
    has_runs = False
    for test in tests:
        if not test.resolve().is_relative_to(repo_root.resolve()):
            raise ScopeError(f"test file outside repository: {test}")
        for item in _load(test, binary).get("run", []):
            for body in item.values():
                if not isinstance(body, dict):
                    continue
                has_runs = True
                modules = body.get("module", [])
                if not modules:
                    roots.add(module_dir)
                for block in modules:
                    root = _local(block.get("source"), module_dir, repo_root, warnings)
                    if root is not None:
                        roots.add(root)
    if not has_runs:
        roots.add(module_dir)  # useful to preview scope; Runner rejects empty suites
    seen: set[Path] = set()
    files: set[Path] = set()

    def visit(root: Path) -> None:
        resolved = root.resolve()
        if resolved in seen:
            return
        if not resolved.is_relative_to(repo_root.resolve()):
            raise ScopeError(f"module outside repository: {root}")
        seen.add(resolved)
        for tf in configuration_files(root, binary):
            if not tf.resolve().is_relative_to(repo_root.resolve()):
                raise ScopeError(f"source file outside repository: {tf}")
            files.add(tf)
            for item in _load(tf, binary).get("module", []):
                for body in item.values():
                    if isinstance(body, dict):
                        child = _local(body.get("source"), root, repo_root, warnings)
                        if child is not None:
                            visit(child)
        if list(root.glob("*.tf.json")):
            warnings.append(f"JSON configuration not a supported mutation surface: {root}")

    for root in sorted(roots):
        visit(root)
    return MutationScope(sorted(files), tests, sorted(roots), has_runs, warnings)
