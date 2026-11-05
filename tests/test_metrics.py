from tfmutate import metrics


def row(status, identity="x", **extra):
    return dict(repo_name="tiny", mutant_id=identity, operator_id="MUT-RES-002",
                test_status=status, validate_status="valid", survival_reason="no_coverage", **extra)


def test_only_explicit_conclusive_mutant_statuses_are_scored():
    rows = [row(s, s) for s in ("killed_assert", "killed_error", "survived", "timeout", "invalid", "no_op", "execution_error", "scope_unresolved")]
    result = metrics.summarize(rows)
    assert result["scored_mutants"] == 3
    assert result["killed_assert"] == 1 and result["killed_error"] == 1
    assert result["mutation_score"] == 2 / 3
    assert result["assertion_score"] == 1 / 3


def test_legacy_baseline_records_are_not_generated_mutants():
    result = metrics.summarize([dict(operator_id="(baseline)", test_status="baseline_fail"), row("survived")])
    assert result["generated_mutants"] == 1
    assert result["module_baseline_records"] == 1


def test_unknown_score_is_null_and_absent_operators_are_reported():
    assert metrics.summarize([])["mutation_score"] is None
    groups = metrics.grouped_summary([], "operator_id", known=["MUT-SEC-001"])
    assert groups["MUT-SEC-001"]["scored_mutants"] == 0


def test_dataset_validator_reports_duplicate_and_invalid_scoring():
    bad = row("survived")
    bad["validate_status"] = "invalid"
    problems = metrics.validate_dataset([bad, bad])
    assert any("duplicate" in p for p in problems)
    assert any("validation" in p for p in problems)


def test_repository_with_only_baseline_failure_is_still_reported():
    groups = metrics.grouped_summary([dict(repo_name="blocked", operator_id="(baseline)", test_status="baseline_fail")], "repo_name")
    assert groups["blocked"]["module_baseline_records"] == 1
    assert groups["blocked"]["scored_mutants"] == 0


def test_explicit_unexecuted_mutant_is_excluded_not_invalid():
    result = metrics.summarize([row("not_executed")])
    assert result["generated_mutants"] == 1
    assert result["scored_mutants"] == 0
    assert metrics.validate_dataset([row("not_executed")]) == []
