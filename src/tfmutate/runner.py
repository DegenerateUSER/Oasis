"""The single-mutation cycle and per-module driver (PROJECT_SPEC.md §5.2).

Per module:
  1. ``terraform init`` (once; idempotent).
  2. **Green-baseline gate** -- run the unmutated suite; if it does not pass, the module is
     skipped as BASELINE_FAIL (with a sub-reason) because its kill/survive results would be
     meaningless noise.
  3. For each mutant: static NO_OP discard (variable-default shadowed by a test override) ->
     apply to disk -> ``terraform validate`` (invalid -> discard) -> ``terraform test`` with a
     hard timeout -> classify -> **restore in `finally`** -> record.
  4. Restore only owned file bytes and init's lock-file writes, never the Git index.

Classification of a non-zero ``terraform test`` distinguishes ``killed_assert`` (an assertion
caught the fault -- real test rigor) from ``killed_error`` (terraform errored -- the engine, not
the test, rejected the mutation). The parsing helpers are pure and unit-tested.

Engine-agnostic: ``test_cmd`` (e.g. ``"terraform test"`` or ``"tofu test"``) drives everything;
the binary (its first token) is reused for ``init``/``validate``/``fmt``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import state
from .mutators import CATALOG, CATALOG_VERSION, Mutant, Operator, generate_mutants
from .noop import default_is_shadowed
from .parser import is_valid_hcl
from .scope import command_options, resolve_scope

log = logging.getLogger(__name__)

_INIT_TIMEOUT = 300  # provider downloads can be slow; separate from the per-mutant timeout


# --- engine version pin -----------------------------------------------------------------
# These engines were verified against native JSON test summaries and diagnostic
# records. Pinning prevents silently interpreting an unreviewed schema/version.
# Diagnostic detail/error_message text is never assertion-failure evidence.
# Unknown engines retain an explicit "no policy" notice; use them cautiously.
PINNED_VERSIONS = {
    "terraform": "1.15.7",
    "tofu": "1.12.3",
}

_VERSION_LINE = re.compile(r"^(?:Terraform|OpenTofu) v(?P<version>\S+)")


def binary_version(binary: str, timeout: int = 15) -> str | None:
    """The resolved version string for `<binary> version` (e.g. "1.15.7"), or None."""
    try:
        r = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    first_line = r.stdout.splitlines()[0] if r.stdout else ""
    m = _VERSION_LINE.match(first_line)
    return m.group("version") if m else None


@dataclass
class VersionCheck:
    ok: bool
    message: str


def check_pinned_version(binary: str) -> VersionCheck:
    """Verify ``binary`` matches its recorded pin, if any policy exists for it."""
    pinned = PINNED_VERSIONS.get(binary)
    if pinned is None:
        return VersionCheck(True, f"no pinned version policy for '{binary}'; version drift is possible")
    actual = binary_version(binary)
    if actual is None:
        return VersionCheck(False, f"could not determine '{binary}' version (is it on PATH?)")
    if actual != pinned:
        return VersionCheck(
            False,
            f"'{binary}' version drift: pinned={pinned}, actual={actual} -- the "
            "killed_assert/killed_error split depends on this engine's exact CLI wording",
        )
    return VersionCheck(True, f"'{binary}' {actual} matches the pinned version")


# --- result records --------------------------------------------------------------------

@dataclass
class MutantOutcome:
    """One row of the dataset (PROJECT_SPEC.md §9)."""

    repo_name: str
    file_mutated: str
    mutant_id: str
    operator_id: str
    operator_category: str
    surface: str
    resource_or_var: str
    attribute: str
    original_value: str
    mutated_value: str
    validate_status: str  # valid | invalid | n/a
    test_status: str  # survived | killed_assert | killed_error | timeout | no_op | baseline_fail
    survival_reason: str  # n/a in Phase 2 (classifier is Phase 4)
    test_output_snippet: str
    record_type: str = "mutant"
    module_dir: str = ""
    catalog_version: str = CATALOG_VERSION
    variable_name: str = ""
    validate_seconds: float = 0.0
    test_seconds: float = 0.0
    total_seconds: float = 0.0
    log_paths: str = ""
    source_sha256: str = ""


@dataclass
class BaselineResult:
    green: bool
    reason: str  # ok | timeout | assertion_failure | init_or_provider_error
    output: str = ""


# --- pure classifiers (unit-tested without terraform) ----------------------------------

def _json_events(output: str) -> list[dict]:
    events = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def classify_test(returncode: int, output: str, timed_out: bool = False) -> str:
    """Use authoritative engine JSON fields, never user-controlled diagnostic text."""
    if timed_out:
        return "timeout"
    events = _json_events(output)
    errors = [event["diagnostic"] for event in events
              if event.get("type") == "diagnostic"
              and isinstance(event.get("diagnostic"), dict)
              and event["diagnostic"].get("severity") == "error"]
    if returncode != 0:
        if any(error.get("summary") == "Test assertion failed" for error in errors):
            return "killed_assert"
        return "killed_error" if errors else "execution_error"
    summaries = [event["test_summary"] for event in events
                 if event.get("type") == "test_summary" and isinstance(event.get("test_summary"), dict)]
    if not summaries or errors:
        return "execution_error"
    summary = summaries[-1]
    if not all(type(summary.get(key)) is int and summary[key] >= 0 for key in ("passed", "failed", "errored", "skipped")):
        return "execution_error"
    if summary["failed"] or summary["errored"] or summary.get("status") not in {"pass", "skip"}:
        return "execution_error"
    return "survived" if summary["passed"] > 0 else "no_tests"


def classify_baseline(returncode: int, output: str, timed_out: bool, init_ok: bool) -> BaselineResult:
    if not init_ok:
        return BaselineResult(False, "init_or_provider_error", output)
    status = classify_test(returncode, output, timed_out)
    reasons = {"survived": "ok", "killed_assert": "assertion_failure", "killed_error": "error"}
    return BaselineResult(status == "survived", reasons.get(status, status), output)


def _snippet(output: str, limit: int = 300) -> str:
    """A stable, bounded tail of terraform output for the CSV (deterministic run-to-run)."""
    lines = [ln.rstrip() for ln in output.splitlines() if ln.strip()]
    return " | ".join(lines[-3:])[:limit]


def _decode(x: str | bytes | None) -> str:
    """Normalize a subprocess stream capture to ``str`` regardless of its actual type."""
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode(errors="replace")
    return x


# --- the runner ------------------------------------------------------------------------

@dataclass
class Runner:
    module_dir: Path
    repo_root: Path
    test_cmd: str = "terraform test"
    timeout: int = 60
    git: str = "git"
    operators: list[Operator] = field(default_factory=lambda: list(CATALOG.values()))
    plugin_cache_dir: Path | None = None  # shared provider cache -> offline, deterministic init
    init_attempts: int = 3  # tolerate transient network flakes downloading providers
    init_timeout: int = _INIT_TIMEOUT
    log_dir: Path | None = None
    budget_seconds: float | None = None
    max_mutants: int | None = None
    command_events: list[dict] = field(default_factory=list, init=False)
    scope_warnings: list[str] = field(default_factory=list, init=False)
    _deadline: float | None = field(default=None, init=False)
    _discovery_rows: list[MutantOutcome] = field(default_factory=list, init=False)
    provider_versions: dict[str, str] = field(default_factory=dict, init=False)
    provider_lock_sha256: str = field(default="", init=False)

    def __post_init__(self):
        limits: list[int | float] = [self.timeout, self.init_timeout, self.init_attempts]
        limits.extend(value for value in (self.budget_seconds, self.max_mutants) if value is not None)
        if any(value <= 0 for value in limits):
            raise ValueError("timeouts, budgets, attempts and limits must be positive")
        self.module_dir, self.repo_root = Path(self.module_dir), Path(self.repo_root)

    @property
    def _binary(self) -> str:
        return shlex.split(self.test_cmd)[0]

    @property
    def _test_argv(self) -> list[str]:
        tokens = [token for token in shlex.split(self.test_cmd)
                  if token != "-json" and not token.startswith("-json=")]
        return [*tokens, "-no-color", "-json"]

    @property
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.plugin_cache_dir:
            env["TF_PLUGIN_CACHE_DIR"] = str(self.plugin_cache_dir)
        return env

    def _exec(self, argv: list[str], timeout: int | float) -> tuple[int, str, bool]:
        """Run a command in the module dir; return (returncode, combined_output, timed_out)."""
        started = time.perf_counter()
        if self._deadline is not None:
            timeout = min(timeout, max(0.001, self._deadline - started))
        code, out, timed_out = 127, "", False
        try:
            r = subprocess.run(
                argv, cwd=self.module_dir, capture_output=True, text=True,
                timeout=timeout, env=self._env,
            )
            code, out = r.returncode, r.stdout + r.stderr
        except subprocess.TimeoutExpired as e:
            # CPython's partial-output capture on a timeout doesn't reliably apply the
            # `text=True` decoding to both streams -- one can come back as `bytes` while the
            # other is `str` (or None), so each must be decoded independently rather than
            # concatenated blind (a real crash this surfaced: "can't concat str to bytes",
            # PHASE5_NOTES.md).
            code, out, timed_out = 124, _decode(e.stdout) + _decode(e.stderr), True
        except OSError as exc:
            code, out = 127, f"process launch failure: {exc}"
        elapsed = time.perf_counter() - started
        event = {"argv": argv, "cwd": str(self.module_dir), "duration_seconds": elapsed,
                 "returncode": code, "timed_out": timed_out, "log_path": ""}
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"{len(self.command_events):04d}.log"
            log_path.write_text(out)
            event["log_path"] = str(log_path.resolve())
        self.command_events.append(event)
        return code, out, timed_out

    def init(self) -> bool:
        directory, _ = command_options(self.test_cmd)
        argv = [self._binary, "init", "-no-color", "-backend=false"]
        if directory != "tests":
            argv.append("-test-directory=" + directory)
        for attempt in range(1, self.init_attempts + 1):
            code, out, timed_out = self._exec(argv, self.init_timeout)
            if code == 0:
                return True
            log.warning("init attempt %d/%d failed in %s: %s",
                        attempt, self.init_attempts, self.module_dir, _snippet(out))
            # Do not delete the caller's .terraform directory to recover failed init.
            if timed_out or (self._deadline is not None and time.perf_counter() >= self._deadline):
                break
        return False

    def baseline(self, init_ok: bool) -> BaselineResult:
        if not init_ok:
            return classify_baseline(0, "", False, init_ok=False)
        code, out, to = self._exec(self._test_argv, self.timeout)
        return classify_baseline(code, out, to, init_ok=True)

    def run_mutant(self, mutant: Mutant) -> MutantOutcome:
        """Apply -> validate -> test -> restore (in finally). Assumes the module is init'd."""
        started = time.perf_counter()
        event_start = len(self.command_events)
        path = Path(mutant.file)
        validate_status, test_status, snippet = "n/a", "n/a", ""
        with state.restored(self.repo_root, path, git=self.git):
            path.write_bytes(mutant.mutated_text.encode("utf-8"))
            vcode, vout, vtimeout = self._exec([self._binary, "validate", "-no-color"], self.timeout)
            if vtimeout:
                validate_status, test_status, snippet = "timeout", "timeout", _snippet(vout)
            elif vcode != 0:
                validate_status = "invalid" if re.search(r"(?m)^\s*Error:", vout) else "execution_error"
                test_status, snippet = validate_status, _snippet(vout)
            else:
                validate_status = "valid"
                tcode, tout, to = self._exec(
                    self._test_argv, self.timeout
                )
                test_status, snippet = classify_test(tcode, tout, to), _snippet(tout)
        row = self._to_outcome(mutant, validate_status, test_status, snippet)
        events = self.command_events[event_start:]
        row.validate_seconds = sum(e["duration_seconds"] for e in events if len(e["argv"]) > 1 and e["argv"][1] == "validate")
        row.test_seconds = sum(e["duration_seconds"] for e in events if len(e["argv"]) > 1 and e["argv"][1] == "test")
        row.total_seconds = time.perf_counter() - started
        row.log_paths = ";".join(e["log_path"] for e in events if e["log_path"])
        return row

    def run_module(self) -> list[MutantOutcome]:
        state.require_clean(self.repo_root, git=self.git)
        started = time.perf_counter()
        self._deadline = started + self.budget_seconds if self.budget_seconds is not None else None
        self.command_events.clear()
        self._discovery_rows.clear()
        if any(key.startswith("TF_CLI_ARGS") for key in os.environ):
            return [self._module_row("scope_error", "implicit TF_CLI_ARGS inputs are unsupported; pass explicit --test-cmd flags")]
        try:
            scope = resolve_scope(self.module_dir, self.repo_root, self.test_cmd)
        except ValueError as exc:
            return [self._module_row("scope_error", str(exc))]
        self.scope_warnings = scope.warnings
        if not scope.has_runs:
            return [self._module_row("no_tests", "no runnable run blocks in selected test files")]
        # Init can rewrite a lock file. Restore only that owned file, not the repo.
        with state.preserved_files(self.repo_root, [self.module_dir / ".terraform.lock.hcl"]):
            init_ok = self.init()
            lock_path = self.module_dir / ".terraform.lock.hcl"
            if lock_path.exists():
                lock = lock_path.read_bytes()
                self.provider_lock_sha256 = hashlib.sha256(lock).hexdigest()
                self.provider_versions = dict(re.findall(r'provider\s+"([^"]+)"\s*\{.*?\bversion\s*=\s*"([^"]+)"', lock.decode(), re.DOTALL))
                if self.log_dir:
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    (self.log_dir / "provider-lock.hcl").write_bytes(lock)
            base = self.baseline(init_ok)
            if not base.green:
                row = self._baseline_row(base)
                row.total_seconds = time.perf_counter() - started
                return [row]
            outcomes = []
            tftest_texts = [p.read_text() for p in scope.test_files]
            mutants = self._mutants()
            if self.max_mutants is not None and len(mutants) > self.max_mutants:
                outcomes.append(self._module_row("limit_reached", f"selected {self.max_mutants} of {len(mutants)} generated mutants"))
                outcomes.extend(self._to_outcome(m, "n/a", "not_executed", "max-mutants limit") for m in mutants[self.max_mutants:])
                mutants = mutants[:self.max_mutants]
            for index, mutant in enumerate(mutants):
                if self._deadline is not None and time.perf_counter() >= self._deadline:
                    outcomes.append(self._module_row("budget_exhausted", "remaining mutants not executed"))
                    outcomes.extend(self._to_outcome(m, "n/a", "not_executed", "time budget exhausted") for m in mutants[index:])
                    break
                variable_name = (mutant.resource_address or "").removeprefix("variable.")
                root_default = Path(mutant.file).parent.resolve() == self.module_dir.resolve() and scope.roots == [self.module_dir]
                if mutant.surface == "V" and not root_default:
                    outcomes.append(self._to_outcome(mutant, "n/a", "scope_unresolved", "child/alternate-module default override scope is unresolved"))
                    continue
                if mutant.surface == "V" and default_is_shadowed(variable_name, tftest_texts):
                    outcomes.append(self._to_outcome(mutant, "n/a", "no_op", "override-shadowed default"))
                    continue
                external_inputs = (f"TF_VAR_{variable_name}" in os.environ
                                   or any(self.module_dir.glob("*.auto.tfvars*"))
                                   or any((self.module_dir / name).exists() for name in ("terraform.tfvars", "terraform.tfvars.json"))
                                   or any(token == "-var" or token.startswith("-var=") for token in shlex.split(self.test_cmd)))
                if mutant.surface == "V" and external_inputs:
                    outcomes.append(self._to_outcome(mutant, "n/a", "scope_unresolved", "external variable input influence is unresolved"))
                    continue
                outcomes.append(self.run_mutant(mutant))
            outcomes.extend(self._discovery_rows)
            if not mutants and not self._discovery_rows:
                outcomes.append(self._module_row("no_targets", "no eligible literal mutation sites"))
            return outcomes

    def _module_row(self, status: str, message: str) -> MutantOutcome:
        row = self._baseline_row(BaselineResult(False, "n/a", message))
        row.record_type = "module"
        row.test_status = status
        row.mutant_id = f"({status})@{row.file_mutated}"
        row.operator_id = "(module)"
        return row

    # -- helpers ---------------------------------------------------------------------------

    def _mutants(self) -> list[Mutant]:
        mutants: list[Mutant] = []
        scope = resolve_scope(self.module_dir, self.repo_root, self.test_cmd)
        for tf in scope.files:
            text = tf.read_bytes().decode("utf-8")
            if not is_valid_hcl(text, self._binary):
                row = self._module_row("skipped_file", "source failed engine syntax gate")
                row.record_type, row.file_mutated = "file", self._rel(str(tf))
                row.mutant_id = f"(skipped_file)@{row.file_mutated}"
                self._discovery_rows.append(row)
                continue
            mutants.extend(generate_mutants(tf, text, self.operators))
        return mutants

    def _rel(self, path: str) -> str:
        return str(Path(path).resolve().relative_to(self.repo_root.resolve()))

    def _to_outcome(self, m: Mutant, validate_status: str, test_status: str, snippet: str) -> MutantOutcome:
        rel = self._rel(m.file)
        return MutantOutcome(
            repo_name=self.repo_root.name,
            file_mutated=rel,
            mutant_id=f"{m.operator_id}@{rel}:{m.line}:{hashlib.sha256(m.mutated_text.encode()).hexdigest()[:12]}",
            operator_id=m.operator_id,
            operator_category=m.category,
            surface=m.surface,
            resource_or_var=m.resource_address or "",
            attribute=m.attribute,
            original_value=m.original_value,
            mutated_value=m.mutated_value,
            validate_status=validate_status,
            test_status=test_status,
            survival_reason="n/a",
            test_output_snippet=snippet,
            module_dir=self._rel(str(self.module_dir)),
            variable_name=(m.resource_address or "").removeprefix("variable.") if m.surface == "V" else "",
            source_sha256=hashlib.sha256(Path(m.file).read_bytes()).hexdigest(),
        )

    def _baseline_row(self, base: BaselineResult) -> MutantOutcome:
        return MutantOutcome(
            repo_name=self.repo_root.name,
            file_mutated=self._rel(str(self.module_dir)),
            mutant_id=f"(baseline)@{self._rel(str(self.module_dir))}",
            operator_id="(baseline)",
            operator_category="n/a",
            surface="n/a",
            resource_or_var="",
            attribute="",
            original_value="",
            mutated_value="",
            validate_status="n/a",
            test_status="baseline_fail",
            survival_reason=base.reason,
            test_output_snippet=_snippet(base.output),
            record_type="module_baseline",
            module_dir=self._rel(str(self.module_dir)),
            log_paths=";".join(e["log_path"] for e in self.command_events if e["log_path"]),
        )
