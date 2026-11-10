"""Conservative variable-default binding analysis for selected native test runs.

This establishes whether a default can be consulted, not runtime coverage or
semantic equivalence. Expressions whose nullability is unresolved stay excluded.
"""
from pathlib import Path
import os
import hcl2
from .scope import _load, _local, configuration_files, selected_test_files
from .noop import _literal_override, _variable_assignments
import shlex


def default_binding_scope(variable, target, module_dir, repo_root, test_cmd):
    target, module_dir, repo_root = map(lambda p: Path(p).resolve(), (target, module_dir, repo_root))
    binary = shlex.split(test_cmd)[0]
    records = []
    documents = {}

    def docs(root):
        if root not in documents:
            if list(root.glob('*.tf.json')) or list(root.glob('*.tofu.json')):
                raise ValueError('JSON variable/caller bindings require explicit analysis')
            # Scope's syntax fallback retains module sources only. It cannot
            # prove omitted inputs or nullability, so never use it here.
            documents[root] = [hcl2.loads(p.read_text()) for p in configuration_files(root, binary)]
        return documents[root]

    def nullable(root):
        for doc in docs(root):
            for item in doc.get("variable", []):
                for name, body in item.items():
                    if name.strip('"') == variable:
                        return body.get("nullable", True) is not False
        return True

    def emit(test, run, path, disposition, reason):
        records.append({"test": str(test.relative_to(repo_root)), "run": run,
                        "module_path": path, "disposition": disposition, "reason": reason})

    def visit(root, seen, test, run, prefix):
        if root in seen:
            return
        seen = seen | {root}
        for doc in docs(root):
            for item in doc.get("module", []):
                for label, body in item.items():
                    warnings = []
                    child = _local(body.get("source"), root, repo_root, warnings)
                    if child is None:
                        continue
                    child = child.resolve()
                    path = prefix + [label]
                    if child == target:
                        if variable not in body:
                            emit(test, run, path, "active", "caller omits input; child default can be consulted")
                        elif body[variable] is None:
                            if nullable(child):
                                emit(test, run, path, "shadowed", "explicit null replaces nullable child default")
                            else:
                                emit(test, run, path, "active", "explicit null falls back to non-nullable child default")
                        elif _literal_override(body[variable]):
                            emit(test, run, path, "shadowed", "caller supplies independent non-null literal")
                        elif nullable(child):
                            # A caller cannot read this child's own input default;
                            # an explicit nullable input replaces it even when null.
                            emit(test, run, path, "shadowed", "explicit caller expression replaces nullable child default")
                        else:
                            emit(test, run, path, "unresolved", "caller expression may be null for a non-nullable input")
                    visit(child, seen, test, run, path)

    try:
        for test in selected_test_files(module_dir, test_cmd):
            doc = hcl2.loads(test.read_text())
            file_vars = _variable_assignments(doc.get("variables"))
            for item in doc.get("run", []):
                for run, body in item.items():
                    roots = []
                    for block in body.get("module", []):
                        root = _local(block.get("source"), module_dir, repo_root, [])
                        if root is not None:
                            roots.append(root.resolve())
                    if not body.get("module"):
                        roots = [module_dir]
                    run_vars = _variable_assignments(body.get("variables"))
                    for root in roots:
                        if root == target:
                            if file_vars is None or run_vars is None:
                                emit(test, run, [], "unresolved", "unparseable run input assignments")
                            else:
                                inputs = file_vars | run_vars
                                external = (f"TF_VAR_{variable}" in os.environ
                                            or any(module_dir.glob("*.auto.tfvars*"))
                                            or any((module_dir / n).exists() for n in ("terraform.tfvars", "terraform.tfvars.json"))
                                            or any(x == "-var" or x.startswith("-var=") for x in shlex.split(test_cmd)))
                                if variable in inputs:
                                    if (inputs[variable] is not None and _literal_override(inputs[variable])
                                            and all(_literal_override(v) for v in inputs.values())):
                                        emit(test, run, [], "shadowed", "test supplies independent non-null literal")
                                    elif inputs[variable] is None and not nullable(root):
                                        emit(test, run, [], "active", "test null falls back to non-nullable root default")
                                    else:
                                        emit(test, run, [], "unresolved", "test input expression/null influence is unresolved")
                                elif external:
                                    emit(test, run, [], "unresolved", "external root input influence is unresolved")
                                else:
                                    emit(test, run, [], "active", "selected run targets this module without overriding input")
                        visit(root, set(), test, run, [])
    except Exception as exc:
        return "unresolved", [{"reason": "binding analysis failed: " + str(exc)}]
    dispositions = {r["disposition"] for r in records}
    if "active" in dispositions:
        return "active", records
    if dispositions == {"shadowed"}:
        return "shadowed", records
    return "unresolved", records or [{"reason": "no binding path established for selected runs"}]
