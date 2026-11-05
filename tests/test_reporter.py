"""Reporting uses the same score population as the runner/CLI, never invented rows."""
import csv
import json

import pytest

from tfmutate import reporter
from tfmutate.mutators import CATALOG
from tfmutate.runner import MutantOutcome


def outcome(status="killed_assert", **changes):
    values = dict(repo_name="tiny", file_mutated="main.tf", mutant_id="m1",
                  operator_id="MUT-RES-002", operator_category="resilience", surface="R",
                  resource_or_var="x.y", attribute="x", original_value="1", mutated_value="2",
                  validate_status="valid", test_status=status, survival_reason="n/a",
                  test_output_snippet="")
    values.update(changes)
    return MutantOutcome(**values)


def test_csv_publication_is_atomic_on_serialization_failure(tmp_path):
    path = tmp_path / "results.csv"
    path.write_bytes(b"previous artifact\n")
    class Broken:
        pass
    with pytest.raises((TypeError, ValueError)):
        reporter.write_csv([outcome(), Broken()], path)
    assert path.read_bytes() == b"previous artifact\n"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_csv_round_trips_all_outcome_fields(tmp_path):
    path = tmp_path / "nested" / "results.csv"
    row = outcome(test_output_snippet='comma, quote" and\nnewline')
    assert reporter.write_csv([row], path) == 1
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == reporter.CSV_COLUMNS
        records = list(reader)
    assert records[0]["test_output_snippet"] == row.test_output_snippet
    assert records[0]["record_type"] == "mutant"


def test_json_summary_shares_scoring_and_includes_zero_target_operators(tmp_path):
    rows = [outcome(), outcome("timeout", mutant_id="m2"),
            outcome("no_op", mutant_id="m3"), outcome("invalid", mutant_id="m4"),
            outcome("survived", mutant_id="m5", survival_reason="no_coverage"),
            outcome("baseline_fail", record_type="module_baseline", repo_name="baseline-only",
                    operator_id="(baseline)", validate_status="n/a")]
    path = tmp_path / "summary.json"
    data = reporter.write_summary(rows, path)
    assert json.loads(path.read_text()) == data
    assert data["overall"]["scored_mutants"] == 2
    assert data["overall"]["mutation_score"] == .5
    assert data["overall"]["assertion_score"] == .5
    assert data["overall"]["generated_mutants"] == 5
    assert data["overall"]["module_baseline_records"] == 1
    assert data["by_repo"]["baseline-only"]["mutation_score"] is None
    assert data["by_category"]["resilience"]["scored_mutants"] == 2
    assert set(CATALOG).issubset(data["by_operator"])
    assert data["by_operator"]["MUT-RES-002"]["scored_mutants"] == 2
    empty = next(key for key in CATALOG if key != "MUT-RES-002")
    assert data["by_operator"][empty]["mutation_score"] is None
    assert data["by_operator"][empty]["generated_mutants"] == 0


def test_read_csv_and_summary_accept_legacy_rows(tmp_path):
    path = tmp_path / "legacy.csv"
    path.write_text("repo_name,operator_id,test_status\ntiny,(baseline),baseline_fail\n")
    data = reporter.summary_data(reporter.read_csv(path))
    assert data["overall"]["generated_mutants"] == 0
    assert data["overall"]["module_baseline_records"] == 1
    assert data["overall"]["mutation_score"] is None
