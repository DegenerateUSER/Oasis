"""Scanner adapters must distinguish findings from execution failures."""
import subprocess
from types import SimpleNamespace

from tfmutate import scanner


def test_non_json_scanner_output_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout="failed to load config", stderr="error"))
    result = scanner.scan_tfsec(tmp_path, "tfsec", timeout=1)
    assert result["status"] == "scanner_error"
    assert result["findings"] == []
    assert result["stdout"] == "failed to load config"


def test_timeout_is_not_reported_as_clean(tmp_path, monkeypatch):
    def timed_out(*a, **kw):
        raise subprocess.TimeoutExpired("tfsec", 1, output=b"partial")
    monkeypatch.setattr(subprocess, "run", timed_out)
    result = scanner.scan_tfsec(tmp_path, "tfsec", timeout=1)
    assert result["status"] == "timeout"


def test_findings_are_mapped_only_to_the_matching_file_and_line(tmp_path):
    source = tmp_path / "main.tf"
    source.write_text("# source")
    findings = [{"rule_id": "X", "location": {"filename": str(source), "start_line": 3, "end_line": 5}},
                {"rule_id": "Y", "location": {"filename": str(tmp_path / "other.tf"), "start_line": 3, "end_line": 5}}]
    assert [r["rule_id"] for r in scanner.findings_at_site(findings, source, 4, tmp_path)] == ["X"]
    assert scanner.findings_at_site(findings, source, 8, tmp_path) == []


def test_real_small_scanner_comparison_restores_source(tmp_path):
    import os
    import shutil
    import pytest
    binary = os.environ.get("TFSEC_BIN") or shutil.which("tfsec")
    if not binary:
        pytest.skip("set TFSEC_BIN to run the tiny offline scanner check")
    from tfmutate.mutators import MUT_SEC_002
    root = tmp_path / "tiny"
    root.mkdir()
    source = root / "main.tf"
    source.write_text('resource "aws_ebs_volume" "data" {\n availability_zone = "us-east-1a"\n size = 8\n encrypted = true\n kms_key_id = "arn:aws:kms:us-east-1:123456789012:key/example"\n}\n')
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True, timeout=10)
    subprocess.run(["git", "-C", str(root), "add", "main.tf"], check=True, capture_output=True, timeout=10)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "tiny"], check=True, capture_output=True, timeout=10)
    original = source.read_bytes()
    report = scanner.compare_repo(root, tmp_path / "results", binary=binary,
                                  operators=[MUT_SEC_002], timeout=10,
                                  budget_seconds=20, max_mutants=1)
    assert source.read_bytes() == original
    assert report["baseline"]["status"] == "completed"
    assert len(report["mutants"]) == 1
    assert report["mutants"][0]["scan"]["status"] == "completed"
    assert report["mutants"][0]["new_site_rule_ids"]
