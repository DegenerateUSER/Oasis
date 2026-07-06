"""Post-processing classifier for SURVIVED mutants (PROJECT_SPEC.md §8).

This is the actual research contribution -- not the mutation score alone, but *why* a test
suite failed to catch a fault. For every SURVIVED mutant, determine one of:

  no_coverage           -- the mutated resource is never referenced anywhere in any test file.
  plan_only_no_assert   -- the resource is referenced somewhere (the module participates in a
                           `command = plan` run) but no `assert` block's condition mentions it.
  weak_assertion        -- an `assert` condition does reference the resource, but never
                           together with the mutated attribute -- the test checks a DIFFERENT
                           attribute of the same resource (spec's example: "checks the bucket
                           exists but not its acl").

Per PROJECT_SPEC.md §8, v1 is deliberately a straightforward string/regex match of the
mutated resource address and attribute name against `.tftest.hcl` content -- it does not need
to be a sophisticated static analyzer to produce a valid, useful finding.
"""

from __future__ import annotations

import re

# The raw body of every `assert { ... }` block, across possibly-nested braces one level deep
# (assert bodies contain `condition = ...` and `error_message = ...`, no further nesting).
_ASSERT_BLOCK = re.compile(r"assert\s*\{([^{}]*)\}", re.DOTALL)

# Whether the file exercises the module at all via a `command = plan` (or `apply`) run.
_RUN_COMMAND = re.compile(r"\brun\s+\"[^\"]+\"\s*\{")


def _assert_conditions(tftest_texts: list[str]) -> list[str]:
    """Every `assert { ... }` block's raw body text, across all of a module's test files."""
    return [m.group(1) for text in tftest_texts for m in _ASSERT_BLOCK.finditer(text)]


def _has_any_run(tftest_texts: list[str]) -> bool:
    return any(_RUN_COMMAND.search(text) for text in tftest_texts)


def classify_survival(resource_or_var: str, attribute: str, tftest_texts: list[str]) -> str:
    """Return a survival_reason for one SURVIVED mutant."""
    full_text = "\n".join(tftest_texts)
    conditions = _assert_conditions(tftest_texts)
    asserts_on_resource = [c for c in conditions if resource_or_var and resource_or_var in c]

    if not asserts_on_resource:
        # Nothing asserts on this resource at all. If it's at least mentioned somewhere (a
        # run/override/variable) and the module is exercised via a run, the fault had a
        # chance to surface but nothing was checking for it; otherwise it's simply untested.
        if resource_or_var and resource_or_var in full_text and _has_any_run(tftest_texts):
            return "plan_only_no_assert"
        return "no_coverage"

    # The resource IS asserted on somewhere; a genuinely-covering assert would have killed the
    # mutant, so its absence here -- even if the attribute name happens to co-occur in some
    # unrelated condition -- means the existing assertion(s) check a different property.
    return "weak_assertion"


def classify_outcomes(outcomes: list, tftest_texts: list[str]) -> list:
    """Fill ``survival_reason`` on every SURVIVED outcome in place; return the same list."""
    for outcome in outcomes:
        if outcome.test_status == "survived":
            outcome.survival_reason = classify_survival(
                outcome.resource_or_var, outcome.attribute, tftest_texts
            )
    return outcomes
