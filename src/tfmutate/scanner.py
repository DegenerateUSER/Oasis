"""Offline tfsec adapter. Policy findings are not mutation-test kills."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


def _text(value):
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def scan_tfsec(root: Path, binary: str = "tfsec", *, timeout: float = 60) -> dict:
    argv = [binary, str(Path(root).resolve()), "--format", "json", "--no-color",
            "--no-module-downloads", "--exclude-downloaded-modules", "--single-thread", "--no-code"]
    started = time.perf_counter()
    result = {"argv": argv, "status": "scanner_error", "returncode": None,
              "stdout": "", "stderr": "", "findings": []}
    try:
        process = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        result.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
        document = json.loads(process.stdout)
        findings = document.get("results")
        if isinstance(findings, list) and all(isinstance(f, dict) and isinstance(f.get("location"), dict) for f in findings) and process.returncode in (0, 1):
            result.update(status="completed", findings=findings)
    except subprocess.TimeoutExpired as exc:
        result.update(status="timeout", stdout=_text(exc.stdout), stderr=_text(exc.stderr))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        result["stderr"] += f"\nscanner adapter error: {exc}"
    result["duration_seconds"] = time.perf_counter() - started
    return result


def findings_at_site(findings: list[dict], source: Path, line: int, root: Path) -> list[dict]:
    """Line-overlap association only, not causal or semantic equivalence."""
    matches = []
    for finding in findings:
        location = finding.get("location", {})
        filename = Path(location.get("filename", ""))
        filename = filename if filename.is_absolute() else root / filename
        try:
            start, end = int(location.get("start_line", 0)), int(location.get("end_line", 0))
        except (TypeError, ValueError):
            continue
        if filename.resolve() == source.resolve() and start <= line <= end:
            matches.append(finding)
    return matches


def compare_repo(root: Path, output_dir: Path, *, binary: str = "tfsec", operators=None,
                 timeout: float = 30, budget_seconds: float = 120, max_mutants: int = 3,
                 outcomes_csv: Path | None = None) -> dict:
    """Compare baseline and bounded individual mutants without running cloud tests.

    A finding's line overlap is an association, not proof of semantic equivalence.
    Existing test outcomes are attached only with matching source/catalog/site data.
    """
    import csv
    import hashlib
    from . import state
    from .mutators import CATALOG_VERSION, generate_mutants
    from .scope import resolve_scope

    root, output_dir = Path(root).resolve(), Path(output_dir).resolve()
    if output_dir.is_relative_to(root):
        raise ValueError("scanner output must be outside the scanned repository")
    if max_mutants < 1 or timeout <= 0 or budget_seconds <= 0:
        raise ValueError("scanner limits must be positive")
    if (output_dir / "comparison.json").exists():
        raise ValueError("comparison already exists; choose a fresh output directory")
    repo_root = state.repo_root_of(root)
    state.require_clean(repo_root)
    scope = resolve_scope(root, repo_root)
    started = time.perf_counter()
    deadline = started + budget_seconds
    output_dir.mkdir(parents=True, exist_ok=True)
    version = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             timeout=min(timeout, budget_seconds))
    revision = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    baseline = scan_tfsec(root, binary, timeout=max(0.001, min(timeout, deadline - time.perf_counter())))
    report = {"schema_version": 1, "repository": str(repo_root), "commit": revision,
              "catalog_version": CATALOG_VERSION,
              "scanner_version_output": version.stdout + version.stderr,
              "scope_warnings": scope.warnings, "baseline": baseline, "mutants": [],
              "association_method": "same-file source-line overlap; not semantic equivalence",
              "limits": {"max_mutants": max_mutants, "budget_seconds": budget_seconds}}
    existing = []
    if outcomes_csv:
        with Path(outcomes_csv).open(newline="") as stream:
            existing = list(csv.DictReader(stream))
    generated = [m for path in scope.files for m in generate_mutants(path, path.read_bytes().decode(), operators)]
    report["generated_mutants"] = len(generated)
    report["limit_reached"] = len(generated) > max_mutants
    if baseline["status"] == "completed":
        for index, mutant in enumerate(generated[:max_mutants]):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                report["budget_exhausted"] = True
                break
            source = Path(mutant.file)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            with state.restored(repo_root, source):
                source.write_bytes(mutant.mutated_text.encode())
                scan = scan_tfsec(root, binary, timeout=min(timeout, remaining))
            old = findings_at_site(baseline["findings"], source, mutant.line, root)
            current = findings_at_site(scan["findings"], source, mutant.line, root)
            rule = lambda finding: finding.get("rule_id") or finding.get("long_id") or "unknown"
            verified = [row for row in existing if row.get("catalog_version") == CATALOG_VERSION
                        and row.get("source_sha256") == source_hash
                        and row.get("file_mutated") == str(source.relative_to(repo_root))
                        and row.get("operator_id") == mutant.operator_id
                        and row.get("original_value") == mutant.original_value
                        and row.get("mutated_value") == mutant.mutated_value
                        and row.get("mutant_id") == f"{mutant.operator_id}@{source.relative_to(repo_root)}:{mutant.line}:{hashlib.sha256(mutant.mutated_text.encode()).hexdigest()[:12]}"]
            report["mutants"].append({"operator_id": mutant.operator_id,
                "file": str(source.relative_to(repo_root)), "line": mutant.line,
                "source_sha256": source_hash, "scan": scan,
                "site_findings": current,
                "new_site_rule_ids": sorted({rule(f) for f in current} - {rule(f) for f in old}),
                "verified_test_outcome": verified[0] if len(verified) == 1 else None})
    report["duration_seconds"] = time.perf_counter() - started
    (output_dir / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
