# Oasis — Mutation Testing for Infrastructure-as-Code

A Python CLI that performs **mutation testing on Terraform modules**: it injects small,
realistic faults ("mutants") into `.tf` files, runs the module's `terraform test` suite
against each mutant, and reports whether the suite *caught* the fault. The output is a
**mutation score** — a quantitative measure of how rigorous an IaC test suite actually is,
not merely how much code it executes.

See [`PROJECT_SPEC.md`](./PROJECT_SPEC.md) for the full project spec, motivation, and phased plan.

## Status

Built incrementally by phase (see `PROJECT_SPEC.md` §12):

- **Phase 0 — Environment** ✅ Terraform 1.15.7 installed; a trivial `mock_provider`
  fixture passes `terraform test` (`fixtures/phase0/`).
- **Phase 1 — Mutator core** ✅ `parser.py` (read-only target location + brace-aware block
  detection + `terraform fmt` validity gate) + `mutators.py` (the full §7 catalog as
  synonym-based, resource-scoped, multi-surface operators, incl. the `MUT-SEC-004a–d` atomic
  split) + `noop.py` (static override NO_OP detection). Methodology in
  [`OPERATOR_SYNONYMS.md`](./OPERATOR_SYNONYMS.md); rationale + findings in
  [`PHASE1_NOTES.md`](./PHASE1_NOTES.md); code-search evidence in [`evidence/`](./evidence/).
  **All 12 operators produce valid HCL mutants: 10 CORPUS-validated on real Cohort A files,
  2 (`MUT-SEC-001`, `MUT-SEC-003`) FIXTURE-validated** — their targets are structurally absent
  from the terraform-test population (a headline finding).
- **Phase 2 — Test runner + git state management** ✅ `runner.py` (init → green-baseline gate →
  per-mutant validate/test/classify, distinguishing `killed_assert` from `killed_error`) +
  `state.py` (`git checkout --` restore, `finally`-guaranteed) + `reporter.py` (§9 CSV) +
  `tfmutate run`. Verified: running the same module **twice** produces a **byte-identical
  CSV**, and every corpus repo's `git status` is clean afterward — across `killed_assert`,
  `survived`, and `baseline_fail` outcomes on real modules. Engine version is **pinned and
  checked at runtime** (`--allow-version-drift` to override) since the assert/error split
  depends on terraform's exact CLI wording; see [`PHASE2_NOTES.md`](./PHASE2_NOTES.md).
- **Phase 3 — Full operator catalog** ✅ satisfied inside Phase 1 (all 12 operators, not
  just 8; per-category toggling added in Phase 2's `-c/--category`) — see
  `PROJECT_SPEC.md` §12 Phase 3 for the explicit accounting.
- **Phase 4 — Classifier** ✅ `classifier.py` fills `survival_reason` (`no_coverage` /
  `plan_only_no_assert` / `weak_assertion`) for every SURVIVED mutant, wired straight into
  `tfmutate run`. **Ground-truth verified against real `terraform test` signal** on two
  Cohort A modules: `platform-design/aws-config` (`no_coverage`, all 4 mutants) and
  `platform-design/aws-ml-artifact-store` (`weak_assertion`, the one flag out of four with
  no matching assertion) — both locked in as regression tests.
- **Phase 5 — Batch orchestrator + repo corpus** ✅ `orchestrator.py` (resumable per-repo
  CSVs, per-repo isolation, self-healing pre-run restore, whole-corpus clean verification)
  + a vetted 23-repo corpus (§10 rubric applied to 158 real `gh`-search candidates). Found
  and fixed real bugs surfaced by real-world batches—most significantly,
  `.tftest.hcl` files in nested test-only subdirectories resolving to the wrong working
  directories; the fix is content-based (checks for real `.tf` files), and was verified
  across the entire corpus. `batch_results/master.csv` contains **242 total rows** (**177 scored valid mutants**),
  all repositories verified clean. Full accounting in [`PHASE5_NOTES.md`](./PHASE5_NOTES.md).
- **Phase 6 — Evaluation Report** ✅ Compiled and completed the evaluation report at [`Docs/report_draft.md`](./Docs/report_draft.md). The report frames this work as an independent empirical pilot study evaluating HCL test suite adequacy, detailing aggregate categories, operator-level performance, and classifier outcomes.
- **Phase 7 — Extension** (Not started).

## Layout

```
src/tfmutate/
  parser.py      # locates mutation targets + terraform-fmt validity gate
  mutators.py    # operator catalog; applies one operator via regex → mutant file
  noop.py        # static NO_OP (variable-override) detection
  state.py       # git checkout restore, finally-guaranteed
  runner.py      # init → baseline gate → validate → test → classify, per module
  classifier.py  # survival_reason for every SURVIVED mutant (§8)
  reporter.py    # §9 CSV writer
  cli.py         # `tfmutate preview` (Phase 1) and `tfmutate run` (Phases 2 & 4)
fixtures/        # hand-written fixtures (phase0 smoke test, thin-operator validation)
tests/           # unit tests
corpus/          # cloned Cohort A target repos (git-ignored)
evidence/        # saved gh code-search results backing the Phase 1 disjointness finding
```

## Develop

```bash
uv sync                              # create venv + install deps
uv run pytest                        # run the unit tests
uv run tfmutate preview <file.tf>    # preview mutants for a .tf file (Phase 1)
uv run tfmutate run <repo-or-dir>    # run the full mutation cycle, write results.csv (Phase 2)
```
