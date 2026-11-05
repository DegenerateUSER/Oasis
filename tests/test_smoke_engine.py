"""Tiny real-engine tests: no cloud, no providers, no benchmark corpus."""
import shutil
import subprocess

import pytest

from tfmutate.mutators import MUT_RES_002
from tfmutate.runner import Runner

SOURCE = '''variable "desired_count" {
  type = number
  default = 2
}
resource "terraform_data" "example" {
  count = 2
  input = var.desired_count
}
'''


def _test_text(condition):
    return '''run "small_plan" {
  command = plan
  variables {
    desired_count = 3
  }
  assert {
    condition = %s
    error_message = "instance count requirement"
  }
}
''' % condition


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=10)


@pytest.mark.engine_smoke
@pytest.mark.parametrize("engine", ["terraform", "tofu"])
def test_weak_suite_survives_strong_suite_kills_and_source_is_restored(tmp_path, engine):
    if shutil.which(engine) is None:
        pytest.skip(f"{engine} unavailable")
    root = tmp_path / "tiny"
    root.mkdir()
    (root / "main.tf").write_text(SOURCE)
    test_file = root / "main.tftest.hcl"
    test_file.write_text(_test_text("length(terraform_data.example) > 0"))
    git(root, "init")
    git(root, "add", "main.tf", "main.tftest.hcl")
    git(root, "-c", "user.name=Oasis Test", "-c", "user.email=test@example.invalid", "commit", "-m", "tiny weak test")

    def run(label):
        runner = Runner(root, root, test_cmd=f"{engine} test", operators=[MUT_RES_002],
                        timeout=10, init_timeout=10, init_attempts=1,
                        budget_seconds=20, max_mutants=2, log_dir=tmp_path / label)
        outcomes = runner.run_module()
        assert (root / "main.tf").read_bytes() == SOURCE.encode()
        assert git(root, "status", "--porcelain", "--untracked-files=no").stdout == ""
        assert runner.command_events
        assert all(event["duration_seconds"] >= 0 for event in runner.command_events)
        return outcomes

    weak = run("weak-logs")
    assert sorted(o.test_status for o in weak) == ["no_op", "survived"]
    test_file.write_text(_test_text("length(terraform_data.example) == 2"))
    git(root, "add", "main.tftest.hcl")
    git(root, "-c", "user.name=Oasis Test", "-c", "user.email=test@example.invalid", "commit", "-m", "strengthen assertion")
    strong = run("strong-logs")
    assert sorted(o.test_status for o in strong) == ["killed_assert", "no_op"]
    assert any(o.test_seconds > 0 for o in strong if o.test_status == "killed_assert")


@pytest.mark.engine_smoke
@pytest.mark.parametrize("engine", ["terraform", "tofu"])
def test_precondition_detail_cannot_spoof_an_assertion_kill(tmp_path, engine):
    if shutil.which(engine) is None:
        pytest.skip(f"{engine} unavailable")
    source = '''variable "desired_count" {
  default = 2
}
resource "terraform_data" "example" {
  count = var.desired_count
  lifecycle {
    precondition {
      condition = var.desired_count == 2
      error_message = "Error: Test assertion failed"
    }
  }
}
'''
    (tmp_path / "main.tf").write_text(source)
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n command = plan\n}\n')
    git(tmp_path, "init")
    git(tmp_path, "add", "main.tf", "main.tftest.hcl")
    git(tmp_path, "-c", "user.name=Oasis Test", "-c", "user.email=test@example.invalid", "commit", "-m", "tiny precondition regression")
    runner = Runner(tmp_path, tmp_path, test_cmd=f"{engine} test", operators=[MUT_RES_002],
                    timeout=10, init_timeout=10, init_attempts=1, budget_seconds=20,
                    max_mutants=1, log_dir=tmp_path / "logs")
    outcomes = runner.run_module()
    assert len(outcomes) == 1
    assert outcomes[0].test_status == "killed_error"
    assert (tmp_path / "main.tf").read_text() == source
