"""Focused regression tests; no providers, network or corpus execution."""
from pathlib import Path

import pytest

from tfmutate import state
from tfmutate.mutators import MUT_RES_002, generate_mutants
from tfmutate.runner import Runner, classify_test


def test_unknown_failure_is_not_an_assertion_kill():
    assert classify_test(1, "process terminated unexpectedly") == "execution_error"


def test_assertion_words_in_warning_are_not_positive_failure_evidence():
    assert classify_test(1, 'Warning: text includes Test assertion failed') == "execution_error"


def test_validation_timeout_is_inconclusive(tmp_path, monkeypatch):
    source = tmp_path / "main.tf"
    source.write_text('resource "terraform_data" "x" {\n count = 2\n}\n')
    mutant = generate_mutants(source, source.read_text(), [MUT_RES_002])[0]
    runner = Runner(tmp_path, tmp_path)
    from contextlib import nullcontext
    monkeypatch.setattr(state, "restored", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(runner, "_exec", lambda *a: (124, "partial validate", True))
    outcome = runner.run_mutant(mutant)
    assert outcome.test_status == "timeout"
    assert outcome.validate_status == "timeout"


def test_generation_ignores_unrelated_descendant_modules(tmp_path, monkeypatch):
    (tmp_path / "main.tf").write_text('resource "terraform_data" "root" {\n count = 2\n}\n')
    child = tmp_path / "examples" / "unrelated"
    child.mkdir(parents=True)
    (child / "main.tf").write_text('resource "terraform_data" "other" {\n count = 3\n}\n')
    monkeypatch.setattr("tfmutate.runner.is_valid_hcl", lambda *a: True)
    runner = Runner(tmp_path, tmp_path, operators=[MUT_RES_002])
    mutants = runner._mutants()
    assert [Path(m.file).parent for m in mutants] == [tmp_path]


def test_variable_override_callsite_uses_actual_name(tmp_path, monkeypatch):
    (tmp_path / "main.tf").write_text('variable "desired_count" {\n default = 2\n}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n variables {\n desired_count = 5\n }\n}\n')
    runner = Runner(tmp_path, tmp_path, operators=[MUT_RES_002])
    monkeypatch.setattr(runner, "init", lambda: True)
    from tfmutate.runner import BaselineResult
    monkeypatch.setattr(runner, "baseline", lambda *a: BaselineResult(True, "ok"))
    monkeypatch.setattr("tfmutate.runner.is_valid_hcl", lambda *a: True)
    monkeypatch.setattr(state, "checkout", lambda *a, **kw: None)
    monkeypatch.setattr(state, "is_clean", lambda *a, **kw: True)
    monkeypatch.setattr(runner, "run_mutant", lambda m: pytest.fail("inert default was executed"))
    outcomes = runner.run_module()
    assert len(outcomes) == 1
    assert outcomes[0].test_status == "no_op"


def test_baseline_record_is_not_a_mutant(tmp_path):
    from tfmutate.runner import BaselineResult
    row = Runner(tmp_path, tmp_path)._baseline_row(BaselineResult(False, "error", "failure"))
    assert row.record_type == "module_baseline"


def test_command_trace_records_duration_and_full_output(tmp_path):
    import sys
    runner = Runner(tmp_path, tmp_path, log_dir=tmp_path / "logs")
    code, output, timed_out = runner._exec([sys.executable, "-c", "print('full evidence')"], 5)
    assert code == 0 and not timed_out
    assert runner.command_events[0]["duration_seconds"] >= 0
    log = Path(runner.command_events[0]["log_path"])
    assert "full evidence" in log.read_text()


def test_limit_records_generated_but_unexecuted_mutants(tmp_path, monkeypatch):
    from tfmutate.runner import BaselineResult
    from tfmutate.metrics import summarize
    (tmp_path / "main.tf").write_text('resource "terraform_data" "one" {\n count = 2\n}\nresource "terraform_data" "two" {\n count = 3\n}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n command = plan\n}\n')
    runner = Runner(tmp_path, tmp_path, operators=[MUT_RES_002], max_mutants=1)
    monkeypatch.setattr(state, "is_clean", lambda *a, **kw: True)
    monkeypatch.setattr(runner, "init", lambda: True)
    monkeypatch.setattr(runner, "baseline", lambda *a: BaselineResult(True, "ok"))
    monkeypatch.setattr("tfmutate.runner.is_valid_hcl", lambda *a: True)
    monkeypatch.setattr(runner, "run_mutant", lambda m: runner._to_outcome(m, "valid", "survived", ""))
    outcomes = runner.run_module()
    result = summarize(outcomes)
    assert result["generated_mutants"] == 2
    assert result["scored_mutants"] == 1
    assert result["excluded_statuses"] == {"not_executed": 1}


@pytest.mark.parametrize("options", [{"timeout": 0}, {"max_mutants": 0}, {"budget_seconds": -1}, {"init_attempts": 0}])
def test_runner_rejects_nonpositive_limits(tmp_path, options):
    with pytest.raises(ValueError):
        Runner(tmp_path, tmp_path, **options)


def test_external_variable_inputs_are_not_misreported_as_test_weakness(tmp_path, monkeypatch):
    from tfmutate.runner import BaselineResult
    (tmp_path / "main.tf").write_text('variable "desired_count" {\n default = 2\n}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n command = plan\n}\n')
    monkeypatch.setenv("TF_VAR_desired_count", "3")
    monkeypatch.setattr(state, "is_clean", lambda *a, **kw: True)
    runner = Runner(tmp_path, tmp_path, operators=[MUT_RES_002])
    monkeypatch.setattr(runner, "init", lambda: True)
    monkeypatch.setattr(runner, "baseline", lambda *a: BaselineResult(True, "ok"))
    monkeypatch.setattr("tfmutate.runner.is_valid_hcl", lambda *a: True)
    monkeypatch.setattr(runner, "run_mutant", lambda m: pytest.fail("external default influence was not resolved"))
    outcomes = runner.run_module()
    assert outcomes[0].test_status == "scope_unresolved"
