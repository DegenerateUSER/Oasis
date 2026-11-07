import json

import pytest

from tfmutate.runner import Runner
from tfmutate.validation import caller_aliases, provider_alias_context


def test_only_referenced_missing_test_aliases_are_supplied(tmp_path):
    (tmp_path / "main.tf").write_text('''provider "aws" {
  alias = "west"
}
resource "aws_s3_bucket" "x" {
  provider = aws.east
}
# aws.comment_only is not a provider reference
locals { description = "aws.string_only" }
''')
    tests = tmp_path / "test"
    tests.mkdir()
    (tests / "main.tftest.hcl").write_text('''mock_provider "aws" { alias = "east" }
mock_provider "aws" { alias = "west" }
mock_provider "aws" { alias = "comment_only" }
mock_provider "aws" { alias = "string_only" }
run "plan" { command = plan }
''')
    assert caller_aliases(tmp_path, "terraform test -test-directory=test") == [("aws", "east")]


def test_temporary_alias_configuration_is_removed_on_failure(tmp_path):
    original = 'resource "aws_s3_bucket" "x" { provider = aws.east }\n'
    source = tmp_path / "main.tf"
    source.write_text(original)
    (tmp_path / "main.tftest.hcl").write_text('mock_provider "aws" { alias = "east" }\nrun "plan" { command = plan }\n')
    with pytest.raises(RuntimeError):
        with provider_alias_context(tmp_path, "terraform test", tmp_path / "logs") as aliases:
            assert aliases == ["aws.east"]
            files = list(tmp_path.glob("oasis_validate_*.tf"))
            assert len(files) == 1 and 'alias = "east"' in files[0].read_text()
            raise RuntimeError("native command failed")
    assert not list(tmp_path.glob("oasis_validate_*.tf"))
    assert source.read_text() == original
    assert not list((tmp_path / "logs").glob("*.tf"))


def test_preexisting_validation_failure_is_not_attributed_to_mutants(tmp_path, monkeypatch):
    runner = Runner(tmp_path, tmp_path)
    calls = []

    def execute(argv, timeout):
        calls.append(argv)
        if argv[1] == "test":
            return 0, json.dumps({"type": "test_summary", "test_summary": {"status": "pass", "passed": 1, "failed": 0, "errored": 0, "skipped": 0}}), False
        return 1, "Error: preexisting invalid configuration", False

    monkeypatch.setattr(runner, "_exec", execute)
    result = runner.baseline(True)
    assert not result.green and result.reason == "validation_error"
    assert [argv[1] for argv in calls] == ["test", "validate"]


def test_validate_keeps_custom_test_directory(tmp_path, monkeypatch):
    runner = Runner(tmp_path, tmp_path, test_cmd="terraform test -test-directory=e2e-tests")
    calls = []
    monkeypatch.setattr(runner, "_exec", lambda argv, timeout: (calls.append(argv) or (0, "valid", False)))
    assert runner.validate()[0] == 0
    assert calls == [["terraform", "validate", "-no-color", "-test-directory=e2e-tests"]]
