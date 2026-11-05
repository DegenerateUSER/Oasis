"""The expensive batch entry point must require an explicit scope decision."""
from pathlib import Path
import subprocess
import sys


def test_batch_refuses_implicit_full_corpus():
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_batch.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "--confirm-full-corpus" in result.stderr


def test_quick_check_rejects_over_two_minute_budget():
    script = Path(__file__).resolve().parents[1] / "scripts" / "quick_check.py"
    result = subprocess.run([sys.executable, str(script), "--seconds", "121"], capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "at most 120" in result.stderr
