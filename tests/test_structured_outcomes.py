"""Review regressions: authoritative JSON, positive execution, no hidden arguments."""
import json
import pytest
from tfmutate import state
from tfmutate.runner import Runner, classify_baseline, classify_test


def diagnostic(summary, detail=""):
    return json.dumps({"type": "diagnostic", "diagnostic": {"severity": "error", "summary": summary, "detail": detail}})


def summary(passed=1):
    return json.dumps({"type": "test_summary", "test_summary": {"status": "pass", "passed": passed, "failed": 0, "errored": 0, "skipped": 0}})


def test_user_detail_cannot_spoof_assertion_failure():
    output = diagnostic("Resource precondition failed", "Error: Test assertion failed")
    assert classify_test(1, output) == "killed_error"


def test_real_json_assertion_failure_is_distinguished():
    assert classify_test(1, diagnostic("Test assertion failed")) == "killed_assert"


def test_unstructured_diagnostic_text_is_not_authoritative():
    output = "Error: Resource precondition failed\n\nError: Test assertion failed"
    assert classify_test(1, output) == "execution_error"


def test_zero_executed_tests_are_not_survival_evidence():
    assert classify_test(0, summary(0)) == "no_tests"
    baseline = classify_baseline(0, summary(0), False, True)
    assert not baseline.green and baseline.reason == "no_tests"


def test_nonzero_summary_without_execution_diagnostics_is_inconclusive():
    assert classify_test(1, summary()) == "execution_error"


@pytest.mark.parametrize("key", ["TF_CLI_ARGS", "TF_CLI_ARGS_test"])
def test_implicit_cli_arguments_are_rejected_before_execution(tmp_path, monkeypatch, key):
    (tmp_path / "main.tf").write_text('resource "terraform_data" "x" {\n count = 2\n}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n command = plan\n}\n')
    monkeypatch.setenv(key, "-filter=missing.tftest.hcl")
    monkeypatch.setattr(state, "is_clean", lambda *a, **kw: True)
    runner = Runner(tmp_path, tmp_path)
    monkeypatch.setattr(runner, "init", lambda: pytest.fail("hidden arguments must be rejected before init"))
    result = runner.run_module()
    assert result[0].test_status == "scope_error"
