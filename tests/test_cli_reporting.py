"""Exercise the real CLI on one provider-free repository, never the corpus."""
import csv
import json
import shutil
import subprocess

import pytest
from tfmutate.cli import main


@pytest.fixture
def tiny_repo(tmp_path):
    root = tmp_path / "tiny"
    root.mkdir()
    (root / "main.tf").write_text('resource "terraform_data" "example" {\n count = 2\n}\n')
    (root / "main.tftest.hcl").write_text('run "x" {\n command = plan\n assert {\n condition = length(terraform_data.example) > 0\n error_message = "count"\n }\n}\n')
    for args in (["init"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "tiny"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=10)
    return root


@pytest.mark.engine_smoke
@pytest.mark.parametrize("test_directory", [".", "checks"])
def test_cli_publishes_verified_artifacts_and_resumes_identical_run(tmp_path, tiny_repo, test_directory):
    if not shutil.which("terraform"):
        pytest.skip("terraform unavailable")
    if test_directory != ".":
        (tiny_repo / test_directory).mkdir()
        (tiny_repo / "main.tftest.hcl").rename(tiny_repo / test_directory / "main.tftest.hcl")
        subprocess.run(["git", "-C", str(tiny_repo), "add", "."], check=True, capture_output=True, timeout=10)
        subprocess.run(["git", "-C", str(tiny_repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "custom tests"], check=True, capture_output=True, timeout=10)
    output = tmp_path / "result.csv"
    argv = ["run", str(tiny_repo), "--output", str(output), "--operator", "MUT-RES-002",
            "--timeout", "10", "--init-timeout", "10", "--init-attempts", "1",
            "--budget-seconds", "30", "--max-mutants", "1"]
    if test_directory != ".":
        argv += ["--test-cmd", f"terraform test -test-directory={test_directory}"]
    assert main(argv) == 0
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["test_status"] == "survived"
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert manifest["completed"] is True
    assert manifest["modules"][0]["command_events"]
    assert summary["overall"]["scored_mutants"] == 1
    assert not summary["validation_problems"]
    before = output.read_bytes()
    assert main(argv) == 0
    assert output.read_bytes() == before
    changed = list(argv)
    changed[changed.index("--timeout") + 1] = "9"
    assert main(changed) != 0
    assert output.read_bytes() == before


def test_cli_refuses_dirty_tree_without_discarding_edits(tmp_path, tiny_repo):
    source = tiny_repo / "main.tf"
    source.write_text(source.read_text() + "# user change\n")
    before = source.read_bytes()
    assert main(["run", str(tiny_repo), "--output", str(tmp_path / "dirty.csv")]) != 0
    assert source.read_bytes() == before
