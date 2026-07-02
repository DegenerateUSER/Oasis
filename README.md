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
- Phases 2–7 — not started.

## Layout

```
src/tfmutate/
  parser.py      # locates mutation targets (python-hcl2 read-only + line scan)
  mutators.py    # operator catalog; applies one operator via regex → mutant file
  cli.py         # `tfmutate preview` — inspect mutants as unified diffs
fixtures/phase0/ # hand-written mock_provider example proving the toolchain works
tests/           # unit tests for the mutation logic
corpus/          # cloned Cohort A target repos (git-ignored)
```

## Develop

```bash
uv sync                 # create venv + install deps
uv run pytest           # run the unit tests
uv run tfmutate preview <file.tf>    # preview mutants for a .tf file
```
