"""Shared, explicit score accounting for current and legacy CSV records."""
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

SCORED_STATUSES = frozenset({"killed_assert", "killed_error", "survived"})
KILLED_STATUSES = frozenset({"killed_assert", "killed_error"})


def row_dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("dataset rows must be dataclass instances or mappings")


def record_type(row):
    row = row_dict(row)
    if row.get("record_type"):
        return row["record_type"]
    if row.get("operator_id") == "(baseline)" or row.get("test_status") == "baseline_fail":
        return "module_baseline"
    return "mutant"


def summarize(rows):
    rows = [row_dict(r) for r in rows]
    mutants = [r for r in rows if record_type(r) == "mutant"]
    scored = [r for r in mutants if r.get("test_status") in SCORED_STATUSES]
    tally = Counter(r.get("test_status", "") for r in scored)
    n, assertions, errors = len(scored), tally["killed_assert"], tally["killed_error"]
    return {"total_records": len(rows), "generated_mutants": len(mutants),
            "module_baseline_records": sum(record_type(r) == "module_baseline" for r in rows),
            "scored_mutants": n, "killed_assert": assertions, "killed_error": errors,
            "survived": tally["survived"],
            "mutation_score": (assertions + errors) / n if n else None,
            "assertion_score": assertions / n if n else None,
            "status_counts": dict(sorted(Counter(r.get("test_status", "") for r in rows).items())),
            "excluded_statuses": dict(sorted(Counter(r.get("test_status", "") for r in mutants if r.get("test_status") not in SCORED_STATUSES).items()))}


def grouped_summary(rows, field, known=()):
    rows = [row_dict(r) for r in rows]
    keys = set(known) | {r.get(field, "") for r in rows if field != "operator_id" or record_type(r) == "mutant"}
    return {key: summarize(r for r in rows if r.get(field) == key) for key in sorted(keys)}


def validate_dataset(rows):
    problems, identities = [], set()
    excluded = {"invalid", "timeout", "no_op", "execution_error", "scope_unresolved", "not_executed", "no_tests"}
    for index, row in enumerate(rows, 2):
        row = row_dict(row)
        if record_type(row) != "mutant":
            continue
        identity = (row.get("repo_name"), row.get("module_dir", ""), row.get("mutant_id"))
        if not identity[-1]:
            problems.append(f"row {index}: missing mutant_id")
        elif identity in identities:
            problems.append(f"row {index}: duplicate mutant identity {identity}")
        identities.add(identity)
        status = row.get("test_status")
        if status not in SCORED_STATUSES | excluded:
            problems.append(f"row {index}: unknown mutant status {status!r}")
        if status in SCORED_STATUSES and row.get("validate_status") != "valid":
            problems.append(f"row {index}: scored mutant was not validation-valid")
        if status == "survived" and row.get("survival_reason") in (None, "", "n/a"):
            problems.append(f"row {index}: survivor lacks classification")
    return problems
