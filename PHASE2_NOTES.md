# Phase 2 notes

## Engine version: one fixed binary, pinned and checked at runtime

**Question:** is one fixed `terraform` binary version used across every corpus repo, or is
each repo resolved via its own declared `required_version`?

**Answer: one fixed binary.** There is a single `terraform` on `PATH` (currently
**v1.15.7**, installed as the official `darwin_arm64` release binary — see
`README.md`/session history for why the Homebrew formula was avoided). `tfmutate` does not
run a per-repo version manager (no `tfenv`, no reading of each repo's `required_version` to
select a matching binary); every module's `init`/`validate`/`test` runs through whatever
binary `test_cmd`'s first token resolves to.

**Why this matters.** `runner.classify_test` distinguishes `killed_assert` from
`killed_error` by matching terraform's literal `Error: Test assertion failed` string in CLI
output (see below). That exact wording is emitted by *this specific binary*, not by the
HCL spec — if the installed version changes (e.g. a later `brew upgrade terraform`), the
wording could silently change and the assert/error split would drift without anything
erroring loudly, quietly corrupting every subsequent `killed_assert` vs `killed_error` count.

**Are the corpus repos' own `required_version` constraints satisfied by 1.15.7?** Yes —
confirmed both by reading and by direct `terraform init` test. Constraints found in the
corpus: `>= 1.3`, `>= 1.5(.0)`, `>= 1.6(.0)`, `>= 1.7.0`, `~> 1.7`, `~> 1.11`. Terraform's
`~>` "pessimistic constraint" operator, given a **two-part** version spec (`~> 1.7`), only
pins the *major* version and allows any minor/patch at or above the given minor — i.e.
`~> 1.7` means `>= 1.7.0, < 2.0.0`, not `< 1.8.0` (that stricter reading only applies to a
**three-part** spec like `~> 1.7.0`). Verified empirically: a scratch module declaring
`required_version = "~> 1.7"` and one declaring `"~> 1.11"` both `terraform init` cleanly
against v1.15.7. No corpus module's declared constraint is violated by the pinned binary.

**What we did about it.** `runner.py` records `PINNED_VERSIONS = {"terraform": "1.15.7"}`
and `check_pinned_version(binary)` compares the resolved `<binary> version` against the pin.
`tfmutate run` calls this once per invocation and **refuses to run on a mismatch** (exit
code 2) unless `--allow-version-drift` is passed explicitly. A binary with no recorded pin
(e.g. `tofu`, not yet vetted against this project) runs with a logged notice instead of
failing, since there is no policy to violate.

**If the pin ever needs to move** (e.g. deliberately upgrading terraform for a later phase):
update `PINNED_VERSIONS` in `runner.py` and re-verify the `killed_assert`/`killed_error`
string match (`Error: Test assertion failed`) still holds for the new version before trusting
new data against old data in the same CSV.

## Category-level operator toggling

PROJECT_SPEC.md §7 requires operators to be independently toggleable "so the report can
break down mutation score *per category*, not just overall" — this was implemented as
`--operator ID` (single operator, exact ID) and `-c/--category CATEGORY [CATEGORY ...]`
(one or more of `security`/`resource`/`compliance`), mutually exclusive, on both
`tfmutate preview` and `tfmutate run`. Selection logic lives in
`mutators.select_operators()` so both commands share one implementation and one set of
error messages.
