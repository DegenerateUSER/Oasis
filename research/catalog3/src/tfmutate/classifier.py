"""Conservative static explanations for mutants already known to have SURVIVED.

These labels describe test source, never runtime execution coverage:

* ``no_coverage`` is the legacy label for **no direct test reference** only.
* ``plan_only_no_assert`` requires a direct reference outside assertions in a
  ``command = plan`` run (or a file-level reference inherited by such a run).
* ``weak_assertion`` means a condition references the resource, but not the
  mutated attribute.
* ``attribute_asserted_survived`` means that attribute is directly referenced
  by a condition despite the passing test result; no causal claim is implied.
* ``unknown`` means parsing or indirect reference resolution prevents a safe
  explanation. This module does not evaluate expressions or resolve aliases.
"""

from __future__ import annotations

import re
from pathlib import Path

import hcl2
from lark import Tree


def _walk(node: Tree):
    yield node
    for child in node.children:
        if isinstance(child, Tree):
            yield from _walk(child)


def _name(node: Tree) -> str:
    return str(node.children[0].children[0])


def _body(block: Tree) -> Tree:
    return next(child for child in block.children if isinstance(child, Tree) and child.data == "body")


def _blocks(body: Tree, kind: str) -> list[Tree]:
    return [child for child in body.children
            if isinstance(child, Tree) and child.data == "block" and _name(child) == kind]


def _attributes(body: Tree) -> dict[str, Tree]:
    return {_name(child): child.children[2] for child in body.children
            if isinstance(child, Tree) and child.data == "attribute"}


def _traversal(node: Tree) -> tuple[str, ...] | None:
    if node.data == "identifier":
        return (str(node.children[0]),)
    if node.data == "expr_term" and len(node.children) == 1 and isinstance(node.children[0], Tree):
        return _traversal(node.children[0])
    if (node.data == "expr_term" and len(node.children) == 3
            and str(node.children[0]) == "(" and str(node.children[2]) == ")"):
        return _traversal(node.children[1])
    if node.data == "get_attr_expr_term":
        base = _traversal(node.children[0])
        member = node.children[1]
        identifier = next(child for child in member.children
                          if isinstance(child, Tree) and child.data == "identifier")
        if base:
            return (*base, str(identifier.children[0]))
    if node.data == "index_expr_term":
        # Instance selectors do not change the resource declaration being read.
        return _traversal(node.children[0])
    if node.data in {"attr_splat_expr_term", "full_splat_expr_term"}:
        base = _traversal(node.children[0])
        if base:
            members = [str(child.children[-1].children[0]) for child in node.children[1].children
                       if isinstance(child, Tree) and child.data == "get_attr"]
            return (*base, *members)
    return None


def _references(node: Tree) -> list[tuple[str, ...]]:
    """Read maximal traversals, while retaining dependencies in index selectors.

    A reference to ``resource.name.acl`` is not also a whole-resource read.
    Keeping its prefixes would hide the distinction between direct attribute
    assertions and unresolved selection of an attribute from the whole object.
    """
    if node.data in {"heredoc_template", "heredoc_template_trim"}:
        # hcl2 exposes the entire heredoc as an opaque token, not expression
        # nodes. An active template may contain references we cannot inspect.
        if any(re.search(r"(?<!\$)\$\{|(?<!%)%\{", str(child)) for child in node.children):
            raise ValueError("unresolved heredoc template references")
        return []
    kinds = {"get_attr_expr_term", "index_expr_term", "attr_splat_expr_term", "full_splat_expr_term"}
    if node.data in kinds and (path := _traversal(node)) is not None:
        selectors = [path for child in _walk(node) if child.data == "braces_index"
                     for item in child.children if isinstance(item, Tree)
                     for path in _references(item)]
        return [path, *selectors]
    return [path for child in node.children if isinstance(child, Tree) for path in _references(child)]


def _aliases(node: Tree) -> set[str]:
    return {str(child.children[0]) for intro in _walk(node)
            if intro.data in {"for_intro", "template_for"}
            for child in intro.children if isinstance(child, Tree) and child.data == "identifier"}


def _indirect_condition(node: Tree) -> bool:
    """Alias/output reads may assert the target indirectly; do not guess their origin."""
    roots = {"output", "module", "run", "local", "locals"} | _aliases(node)
    return any(path[0] in roots for path in _references(node))


def _outside_assertions(node: Tree) -> list[tuple[str, ...]]:
    if node.data == "block" and _name(node) == "assert":
        return []
    if node.data == "attribute":
        return _references(node.children[2])
    return [path for child in node.children if isinstance(child, Tree)
            for path in _outside_assertions(child)]


def _matches(path: tuple[str, ...], address: tuple[str, ...]) -> bool:
    return path[:len(address)] == address


def classify_survival(resource_or_var: str, attribute: str, tftest_texts: list[str]) -> str:
    """Explain static references for a survivor, without inferring runtime coverage."""
    if not resource_or_var or not tftest_texts:
        return "unknown"
    address = tuple(resource_or_var.split("."))
    if address[0] == "variable":
        address = ("var", *address[1:])
    variable_default = address[0] == "var" and attribute == "default"
    condition_paths: list[tuple[str, ...]] = []
    outside_paths: list[tuple[str, ...]] = []
    plan_reference = False
    indirect_condition = False
    try:
        for text in tftest_texts:
            parsed = hcl2.parses(text)
            tree = parsed.to_lark() if hasattr(parsed, "to_lark") else parsed
            body = tree.children[0]
            runs = _blocks(body, "run")
            file_paths = [path for child in body.children if isinstance(child, Tree) and child not in runs
                          for path in _outside_assertions(child)]
            outside_paths.extend(file_paths)
            for run in runs:
                run_body = _body(run)
                paths = _outside_assertions(run_body)
                outside_paths.extend(paths)
                command = _attributes(run_body).get("command")
                if command is not None and _traversal(command) == ("plan",):
                    plan_reference |= any(_matches(path, address) for path in file_paths + paths)
                for assertion in _blocks(run_body, "assert"):
                    condition = _attributes(_body(assertion)).get("condition")
                    if condition is None:
                        return "unknown"
                    # Loop bindings can shadow even a resource namespace (or var).
                    # Exclude such roots rather than crediting a reference to a
                    # local loop value as an assertion of the mutated resource.
                    aliases = _aliases(condition)
                    condition_paths.extend(path for path in _references(condition) if path[0] not in aliases)
                    indirect_condition |= _indirect_condition(condition)
    except Exception:  # noqa: BLE001 - malformed/unsupported syntax cannot supply evidence
        return "unknown"

    resource_conditions = [path for path in condition_paths if _matches(path, address)]
    if (variable_default and resource_conditions) or any(
        path[len(address):len(address) + 1] == (attribute,) for path in resource_conditions
    ):
        return "attribute_asserted_survived"
    if indirect_condition:
        return "unknown"
    if address in resource_conditions:
        return "unknown"  # whole-object equality/lookup/indexing may inspect the mutated field
    if resource_conditions:
        return "weak_assertion"
    if plan_reference:
        return "plan_only_no_assert"
    if any(_matches(path, address) for path in outside_paths):
        return "unknown"
    return "no_coverage"


def classify_outcomes(outcomes: list, tftest_texts: list[str]) -> list:
    """Fill ``survival_reason`` on every SURVIVED outcome in place; return the same list."""
    for outcome in outcomes:
        if outcome.test_status == "survived":
            module_dir = getattr(outcome, "module_dir", "")
            source = getattr(outcome, "file_mutated", "")
            if module_dir and (not source or Path(source).parent != Path(module_dir)):
                # Bare addresses in test conditions belong to the execution
                # module, not a child/alternate module's source namespace.
                outcome.survival_reason = "unknown"
                continue
            outcome.survival_reason = classify_survival(
                outcome.resource_or_var, outcome.attribute, tftest_texts
            )
    return outcomes
