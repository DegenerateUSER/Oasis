"""Unit tests for the pure classification logic in runner.py (no terraform required)."""

from __future__ import annotations

import subprocess
import json

from tfmutate.runner import PINNED_VERSIONS, Runner, check_pinned_version, classify_baseline, classify_test


def _summary_json():
    return json.dumps({"type": "test_summary", "test_summary": {"status": "pass", "passed": 1, "failed": 0, "errored": 0, "skipped": 0}})


def _diagnostic_json(summary):
    return json.dumps({"type": "diagnostic", "diagnostic": {"severity": "error", "summary": summary, "detail": "diagnostic detail"}})


# --- classify_test ---------------------------------------------------------------------

def test_zero_exit_is_survived():
    assert classify_test(0, _summary_json()) == "survived"


def test_timeout_wins_over_returncode():
    assert classify_test(124, "partial output", timed_out=True) == "timeout"


def test_assertion_failure_is_killed_assert():
    out = _diagnostic_json("Test assertion failed")
    assert classify_test(1, out) == "killed_assert"


def test_terraform_error_is_killed_error():
    out = _diagnostic_json("Invalid value for variable")
    assert classify_test(1, out) == "killed_error"


def test_non_zero_without_error_marker_is_inconclusive():
    assert classify_test(1, "run failed somehow") == "execution_error"


# --- classify_baseline -----------------------------------------------------------------

def test_baseline_green():
    b = classify_baseline(0, _summary_json(), False, init_ok=True)
    assert b.green and b.reason == "ok"


def test_baseline_init_failure():
    b = classify_baseline(0, "", False, init_ok=False)
    assert not b.green and b.reason == "init_or_provider_error"


def test_baseline_timeout():
    b = classify_baseline(124, "", True, init_ok=True)
    assert not b.green and b.reason == "timeout"


def test_baseline_assertion_failure_vs_error():
    assert classify_baseline(1, _diagnostic_json("Test assertion failed"), False, True).reason == "assertion_failure"
    assert classify_baseline(1, _diagnostic_json("bad provider config"), False, True).reason == "error"


# --- check_pinned_version ---------------------------------------------------------------

def test_no_policy_for_unpinned_binary_is_ok():
    check = check_pinned_version("some-unpinned-engine-xyz")
    assert check.ok and "no pinned version policy" in check.message


def test_drift_from_pinned_version_is_blocked(monkeypatch):
    import tfmutate.runner as runner_mod

    monkeypatch.setitem(PINNED_VERSIONS, "terraform", "0.0.0-not-real")
    monkeypatch.setattr(runner_mod, "binary_version", lambda binary, timeout=15: "1.15.7")
    check = check_pinned_version("terraform")
    assert not check.ok and "version drift" in check.message


def test_matching_version_is_ok(monkeypatch):
    import tfmutate.runner as runner_mod

    monkeypatch.setitem(PINNED_VERSIONS, "terraform", "1.15.7")
    monkeypatch.setattr(runner_mod, "binary_version", lambda binary, timeout=15: "1.15.7")
    assert check_pinned_version("terraform").ok


# --- _exec timeout handling --------------------------------------------------------------
# Real batch bug: CPython's partial-output capture on subprocess.TimeoutExpired doesn't
# reliably apply text-mode decoding to both streams -- one can come back as `bytes` while the
# other is `str`/None, and naively concatenating them raised "can't concat str to bytes",
# crashing a whole repo instead of gracefully recording an init timeout (PHASE5_NOTES.md).

def test_exec_handles_timeout_with_mixed_str_and_bytes_output(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["terraform", "init"], timeout=300,
            output=b"partial bytes stdout",  # bytes
            stderr="partial str stderr",     # str
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = Runner(module_dir=tmp_path, repo_root=tmp_path)
    code, out, timed_out = runner._exec(["terraform", "init"], 300)
    assert timed_out is True
    assert code == 124
    assert "partial bytes stdout" in out
    assert "partial str stderr" in out


def test_exec_handles_timeout_with_none_streams(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["terraform", "init"], timeout=300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = Runner(module_dir=tmp_path, repo_root=tmp_path)
    code, out, timed_out = runner._exec(["terraform", "init"], 300)
    assert timed_out is True
    assert out == ""
