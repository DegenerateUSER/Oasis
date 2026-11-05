"""Reporting entry points must share accounting and accept explicit datasets."""
import csv
import json
from pathlib import Path
import subprocess
import sys


def test_report_script_excludes_timeouts_and_baseline_records(tmp_path):
    source = tmp_path / "tiny.csv"
    fields = ["repo_name", "mutant_id", "operator_id", "operator_category", "test_status", "validate_status", "survival_reason"]
    with source.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            dict(repo_name="tiny", mutant_id="a", operator_id="MUT-RES-002", operator_category="resource", test_status="killed_assert", validate_status="valid", survival_reason="n/a"),
            dict(repo_name="tiny", mutant_id="b", operator_id="MUT-RES-002", operator_category="resource", test_status="timeout", validate_status="valid", survival_reason="n/a"),
            dict(repo_name="tiny", mutant_id="baseline", operator_id="(baseline)", operator_category="n/a", test_status="baseline_fail", validate_status="n/a", survival_reason="error")])
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_report_data.py"
    result = subprocess.run([sys.executable, str(script), str(source), "--format", "json"], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["overall"]["scored_mutants"] == 1
    assert summary["overall"]["module_baseline_records"] == 1
    assert summary["overall"]["generated_mutants"] == 2
    assert "MUT-SEC-001" in summary["by_operator"]
