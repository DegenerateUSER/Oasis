"""The single-mutation cycle and per-module driver (PROJECT_SPEC.md §5.2).

Per module:
  1. ``terraform init`` (once; idempotent).
  2. **Green-baseline gate** -- run the unmutated suite; if it does not pass, the module is
     skipped as BASELINE_FAIL (with a sub-reason) because its kill/survive results would be
     meaningless noise.
  3. For each mutant: static NO_OP discard (variable-default shadowed by a test override) ->
     apply to disk -> ``terraform validate`` (invalid -> discard) -> ``terraform test`` with a
     hard timeout -> classify -> **restore in `finally`** -> record.
  4. ``git checkout -- .`` to clear init's lock-file writes.

Classification of a non-zero ``terraform test`` distinguishes ``killed_assert`` (an assertion
caught the fault -- real test rigor) from ``killed_error`` (terraform errored -- the engine, not
the test, rejected the mutation). The parsing helpers are pure and unit-tested.

Engine-agnostic: ``test_cmd`` (e.g. ``"terraform test"`` or ``"tofu test"``) drives everything;
the binary (its first token) is reused for ``init``/``validate``/``fmt``.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import state
from .mutators import CATALOG, Mutant, Operator, generate_mutants
from .noop import default_is_shadowed, read_tftest_files
from .parser import is_valid_hcl, read_tf_files

log = logging.getLogger(__name__)

_INIT_TIMEOUT = 300  # provider downloads can be slow; separate from the per-mutant timeout


# --- engine version pin -----------------------------------------------------------------
# classify_test's assert-vs-error split depends on matching a literal "Error: Test assertion
# failed" string in CLI output. That wording is emitted by whatever binary happens to be
# resolved on PATH; if the installed version silently changes (e.g. a later `brew upgrade`),
# the match could drift without anything erroring loudly. We pin the version each engine's
# dataset was collected against and refuse to run on drift by default (PHASE2_NOTES.md).
# Only binaries with a recorded pin are checked; a genuinely unvetted engine runs with a
# logged "no policy" notice instead of failing.
#
# `tofu` (OpenTofu 1.12.3) was verified against real assertion-failure and real engine-error
# output before being added here: both print the identical "Error: Test assertion failed" /
# "Error: <other>" wording Terraform does, so classify_test's string match is safe for it too
# (PHASE5_NOTES.md).
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


@dataclass
class BaselineResult:
    green: bool
    reason: str  # ok | timeout | assertion_failure | init_or_provider_error
    output: str = ""


# --- pure classifiers (unit-tested without terraform) ----------------------------------

# terraform prints this exact header when an `assert` block's condition is false. Any other
# "Error:" is a runtime/plan error (the engine rejected the mutation, not the test's rigor).
_ASSERT_MARKER = "Test assertion failed"


def _is_assertion_failure(output: str) -> bool:
    """True if the non-zero result is (at least partly) a failed assertion, not only an error."""
    return _ASSERT_MARKER in output


def classify_test(returncode: int, output: str, timed_out: bool = False) -> str:
    """Map a `terraform test` result to a test_status."""
    if timed_out:
        return "timeout"
    if returncode == 0:
        return "survived"
    # Non-zero: a failed assertion (real test rigor) vs the engine erroring. A run can both
    # assert-fail and error, but an assert failing at all means the test *did* catch the fault.
    if _is_assertion_failure(output):
        return "killed_assert"
    return "killed_error" if "Error:" in output else "killed_assert"


def classify_baseline(returncode: int, output: str, timed_out: bool, init_ok: bool) -> BaselineResult:
    if not init_ok:
        return BaselineResult(False, "init_or_provider_error", output)
    if timed_out:
        return BaselineResult(False, "timeout", output)
    if returncode == 0:
        return BaselineResult(True, "ok", output)
    if _is_assertion_failure(output):
        return BaselineResult(False, "assertion_failure", output)
    return BaselineResult(False, "error" if "Error:" in output else "assertion_failure", output)


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

    @property
    def _binary(self) -> str:
        return shlex.split(self.test_cmd)[0]

    @property
    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.plugin_cache_dir:
            env["TF_PLUGIN_CACHE_DIR"] = str(self.plugin_cache_dir)
        return env

    def _exec(self, argv: list[str], timeout: int) -> tuple[int, str, bool]:
        """Run a command in the module dir; return (returncode, combined_output, timed_out)."""
        try:
            r = subprocess.run(
                argv, cwd=self.module_dir, capture_output=True, text=True,
                timeout=timeout, env=self._env,
            )
            return r.returncode, r.stdout + r.stderr, False
        except subprocess.TimeoutExpired as e:
            # CPython's partial-output capture on a timeout doesn't reliably apply the
            # `text=True` decoding to both streams -- one can come back as `bytes` while the
            # other is `str` (or None), so each must be decoded independently rather than
            # concatenated blind (a real crash this surfaced: "can't concat str to bytes",
            # PHASE5_NOTES.md).
            out = _decode(e.stdout) + _decode(e.stderr)
            return 124, out, True

    def init(self) -> bool:
        for attempt in range(1, self.init_attempts + 1):
            code, out, _ = self._exec([self._binary, "init", "-no-color", "-backend=false"], _INIT_TIMEOUT)
            if code == 0:
                return True
            log.warning("init attempt %d/%d failed in %s: %s",
                        attempt, self.init_attempts, self.module_dir, _snippet(out))
            # A stale/partial local .terraform/ (e.g. left behind by a previous crashed run,
            # or a provider-symlink collision from re-initializing against the shared plugin
            # cache) makes every retry fail identically. It is untracked and safe to remove;
            # do so before the next attempt so a retry actually starts from a clean slate
            # instead of repeating the same broken command (PHASE5_NOTES.md).
            if attempt < self.init_attempts:
                shutil.rmtree(self.module_dir / ".terraform", ignore_errors=True)
        return False

    def baseline(self, init_ok: bool) -> BaselineResult:
        if not init_ok:
            return classify_baseline(0, "", False, init_ok=False)
        code, out, to = self._exec([*shlex.split(self.test_cmd), "-no-color"], self.timeout)
        return classify_baseline(code, out, to, init_ok=True)

    def run_mutant(self, mutant: Mutant) -> MutantOutcome:
        """Apply -> validate -> test -> restore (in finally). Assumes the module is init'd."""
        path = Path(mutant.file)
        validate_status, test_status, snippet = "n/a", "n/a", ""
        with state.restored(self.repo_root, path, git=self.git):
            path.write_text(mutant.mutated_text)
            vcode, vout, _ = self._exec([self._binary, "validate", "-no-color"], self.timeout)
            if vcode != 0:
                validate_status, test_status, snippet = "invalid", "invalid", _snippet(vout)
            else:
                validate_status = "valid"
                tcode, tout, to = self._exec(
                    [*shlex.split(self.test_cmd), "-no-color"], self.timeout
                )
                test_status, snippet = classify_test(tcode, tout, to), _snippet(tout)
        return self._to_outcome(mutant, validate_status, test_status, snippet)

    def run_module(self) -> list[MutantOutcome]:
        init_ok = self.init()
        base = self.baseline(init_ok)
        try:
            if not base.green:
                return [self._baseline_row(base)]
            outcomes = []
            tftest_texts = read_tftest_files(self.module_dir)
            for mutant in self._mutants():
                if mutant.surface == "V" and default_is_shadowed(mutant.attribute, tftest_texts):
                    outcomes.append(self._to_outcome(mutant, "n/a", "no_op", "override-shadowed default"))
                    continue
                outcomes.append(self.run_mutant(mutant))
            return outcomes
        finally:
            # Clear init's lock-file writes (and any stray mutation) so git is clean.
            state.checkout(self.repo_root, ".", git=self.git)

    # -- helpers ---------------------------------------------------------------------------

    def _mutants(self) -> list[Mutant]:
        mutants: list[Mutant] = []
        for tf in read_tf_files(self.module_dir):
            text = tf.read_text()
            if not is_valid_hcl(text, self._binary):
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
            mutant_id=f"{m.operator_id}@{rel}:{m.line}",
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
        )
