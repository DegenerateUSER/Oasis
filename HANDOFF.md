# Handoff — read this first if you have no memory of prior sessions

## 1. Current status

**Phases 0–5 are complete and user-approved. Phase 6 (analysis + report) has not started.**
Do not re-open Phases 0–5's decisions without a specific reason — see Section 4 below for
the list of decisions that are final. If something looks off in the data, re-derive from
`batch_results/master.csv` and the notes files before assuming a bug; several "bugs" found
during Phase 5 turned out to require careful empirical verification before concluding
anything (see `PHASE5_NOTES.md`).

The tool itself (`src/tfmutate/`) is a working Python CLI (`uv run tfmutate preview|run`)
plus a batch orchestrator (`scripts/run_batch.py`) that produced the empirical dataset Phase
6 will analyze. 75 unit tests pass (`uv run pytest`); some shell out to real `terraform`/
`tofu` binaries and take a few minutes.

## 2. Pointer to every existing doc

- **`PROJECT_SPEC.md`** — the master spec and methodology document. Originally written as
  the project's design intent (Sections 1–5, 7, 10, 11 largely unchanged); Sections 6.4,
  6.5, and 9 have been extended in place with **as-built methodology** that diverged from
  the original plan (synonym-based operator matching, NO_OP detection, target-discovery
  rules, engine selection, the exact mutation-score formula). Section 12 is the phase
  tracker — every phase 0–5 entry has an explicit `✅ done` note with its done-condition
  evidence. **Read this first**; it is the document the eventual report's methodology
  section will be built from, and it is kept in sync with reality on purpose.
- **`PHASE1_NOTES.md`** — why the operator catalog deviates from Section 7's original table:
  the `MUT-SEC-004a–d` atomic split (four independent public-access-block flags instead of
  one compound operator) and its rationale, the `hcl2` → `terraform fmt` validity-gate bug
  and fix (hcl2's grammar is stricter than Terraform's and silently rejected valid files),
  the tag-map scoping fix for `MUT-TAG-002` (a false-positive guard), and the empirically
  confirmed finding that `MUT-SEC-001`/`MUT-SEC-003`'s literal target patterns are
  essentially absent from real `terraform test` repos (with `gh` code-search evidence).
- **`PHASE2_NOTES.md`** — the engine-version-pin rationale (`killed_assert` vs
  `killed_error` classification depends on matching Terraform's exact CLI wording, so a
  silent version drift could corrupt that split) and the addition of `-c/--category`
  operator filtering alongside `--operator`.
- **`PHASE5_NOTES.md`** — the longest and most important notes file for Phase 6. Contains:
  the full corpus-selection methodology (158 raw `gh` search candidates → 18 selected, with
  scoring and exclusions per Section 10's rubric); all five real bugs found running the
  actual 18-repo batch (vendored-path mutation, `is_clean()` semantics, a `str`/`bytes`
  subprocess crash, wrong-engine-for-OpenTofu, and the two-round directory-resolution bug)
  with root cause, fix, and regression tests for each; the **complete final accounting** of
  all 164 rows in `master.csv` by status (with `baseline_fail` sub-reasons); a **per-repo**
  reason (not a summary) for every one of the 9 repos that produced zero scored mutants,
  each individually verified; and the category/operator-level findings. **Read this second.**
- **`OPERATOR_SYNONYMS.md`** — the citable, paper-droppable methodology reference for the
  operator catalog: which attribute synonyms each operator matches, its resource-type
  scoping, which surface(s) (R/V/L) it targets, and a CORPUS-vs-FIXTURE validation column
  per operator (10/12 corpus-validated; `MUT-SEC-001`/`MUT-SEC-003` fixture-validated only —
  see Section 4).
- **`evidence/`** — raw `gh` code-search output backing the Phase 1 disjointness finding and
  the Phase 5 corpus selection: `acl_private_repos.txt` (86 repos with the literal
  `acl = "private"`), `cohortA_repos.txt` (46 repos with `mock_provider` in a `.tftest.hcl`,
  zero overlap with the previous list), `gh_search_candidates_raw.txt` (the 158-repo Phase 5
  candidate pool before filtering).
- **`fixtures/`** — hand-written fixtures used to validate specific behaviors on synthetic
  input: `phase0/` (the Phase 0 smoke test proving `terraform test` + `mock_provider` work
  at all), `phase1_demo/` and `thin_operators/` (fixture-validation for `MUT-SEC-001`/`003`),
  `classifier_boundary/` (a constructed, git-committed fixture proving the classifier's
  `plan_only_no_assert` boundary is genuinely reachable, modeled on a real `override_resource`
  pattern found in the corpus — see PHASE5_NOTES.md "Check 1").
- **`README.md`** — short, current-state summary of what's built per phase; less detailed
  than the notes files, good for a 30-second orientation.
- **`corpus/`** — the 18 cloned target repos (git-ignored, not committed). If missing on a
  fresh checkout, re-clone per the list in `PHASE5_NOTES.md`'s corpus-selection section.
- **`batch_results/`** — one CSV per repo plus `master.csv` (the aggregated dataset) and any
  `<repo>.log` for a repo that failed entirely. This is the actual empirical output Phase 6
  analyzes. Git-ignored; regenerate via `uv run python scripts/run_batch.py` if missing
  (resumable — skips any repo that already has a CSV).

## 3. Final, load-bearing dataset facts

- **`batch_results/master.csv`: 164 data rows**, spanning all 18 corpus repos, every repo
  verified `git status` clean after the run (not spot-checked).
- **Full status breakdown**:

  | `test_status` | count |
  |---|---|
  | `survived` | 71 |
  | `baseline_fail` | 61 |
  | `killed_assert` | 27 |
  | `invalid` | 3 |
  | `killed_error` | 2 |
  | `timeout` | 0 |
  | `no_op` | 0 |
  | **total** | **164** |

  `baseline_fail` sub-reasons (`survival_reason` column): `error` 28,
  `init_or_provider_error` 27, `assertion_failure` 6.

- **Overall mutation score: 29.0%** (29/100). **Exact formula (final, stated methodological
  decision — cite `PROJECT_SPEC.md` §9, not this file):**

  ```
  mutation score = (killed_assert + killed_error) / (killed_assert + killed_error + survived)
  ```

  `baseline_fail`, `invalid`, `timeout`, and `no_op` are excluded from **both** the numerator
  and denominator, not just the numerator. Reasoning: a module whose unmutated test suite
  doesn't pass green (`baseline_fail`) can't yield a meaningful per-mutant result — there's
  no "caught the fault" vs. "missed the fault" to measure without a passing baseline, and
  counting these as survived would conflate "broken/unrunnable test suite" with "weak test
  suite," which the report must not blur together. `invalid` mutants failed
  `terraform validate` (a property of the mutation, not the test suite). `timeout` is
  inconclusive. `no_op` mutations demonstrably never took effect.
- **9 of 18 repos produced zero scored mutants.** Two (`conf-data-processing-architecture-reference`,
  `terraform-duplocloud-components`) failed baseline on every module for genuine,
  repo-specific reasons (broken git submodules, missing cloud credentials, an interactive
  variable prompt, incompatible version constraints). The other seven were **empirically
  verified** — not inferred — to have zero fireable mutator targets against real,
  substantial `.tf` content (10–30 files each): full parameterization through
  variables/locals, matching Phase 1's own established finding at corpus scale. Full
  per-repo detail in `PHASE5_NOTES.md`.
- **Category**: security n=75 (32.0% killed), resource n=24 (20.8% killed), compliance n=1
  (too small to read anything into).
- **Operator-level highlights**: `MUT-SEC-002` (storage encryption) 100% killed (3/3).
  `MUT-RES-001` (instance sizing) 0% killed (0/5) — nobody in this sample asserts on
  instance size/class. The four `MUT-SEC-004a–d` (public-access-block flags) all sit in a
  consistent 22–33% kill-rate band — uniformly weak coverage of that resource, not one
  outlier flag.
- **Survival reasons** (the classifier's §8 output): `no_coverage` 60, `weak_assertion` 11,
  `plan_only_no_assert` 0 in the real batch (this category is real — proven reachable on a
  constructed fixture with live signal, see `fixtures/classifier_boundary/` — but rare).

## 4. Methodological decisions that are FINAL — do not silently revisit

These were deliberated, tested, and user-approved. If evidence later suggests one is wrong,
surface it explicitly and get a decision — don't quietly change the behavior.

1. **Green-baseline gating.** A module's unmutated test suite must pass before any of its
   mutants are scored; otherwise the whole module is recorded as `baseline_fail` with a
   sub-reason and excluded from the mutation score. (`runner.py`, `classify_baseline`)
2. **`killed_assert` vs `killed_error` split**, discriminated on the literal string
   `"Test assertion failed"` in the test engine's CLI output (present verbatim in both
   Terraform and OpenTofu, empirically verified against both real binaries). A non-zero
   exit without that marker is `killed_error` (the engine rejected the mutation, not the
   test). (`runner.py`, `classify_test`)
3. **`MUT-SEC-001`/`MUT-SEC-003` findings refined**: S3 ACL (`MUT-SEC-001`) target literals
   (`acl = "private"`) are actually structurally present in 2/23 repos (`platform-tools`
   and `terraform-aws-static-site`) in `aws_s3_bucket_acl` resources. However, they remain
   **unscored (invalid)** because the current operator mutates `"private"` to `"public"`,
   which is an invalid canned ACL value in the AWS provider S3 bucket schema, failing
   `terraform validate`. Thus, `MUT-SEC-001` remains corpus-unscored, and the disjointness
   finding is refined: target literals are rare (2/23 repos) and their mutations produce
   schema-invalid HCL under default rules. `MUT-SEC-003` remains structurally absent from the
   corpus. (`OPERATOR_SYNONYMS.md`, `PHASE1_NOTES.md`, `evidence/`)
4. **`terraform fmt` is the HCL validity gate, not `python-hcl2`.** hcl2's grammar is
   stricter than Terraform's own and silently rejected real, valid files (a `for`-expression
   bug). `python-hcl2` is used only for parsing `.tftest.hcl` files in `noop.py`, never as a
   gate. (`parser.py`, `is_valid_hcl`)
5. **Module-directory resolution for `.tftest.hcl` files is content-based, not name-based.**
   Check for actual `.tf` file presence (climb one level to the parent if the immediate
   directory has none and the parent does); never match directory names like `tests`/`test`
   — real repos use other names (`e2e-tests`) that a name-based rule misses. A `.tftest.hcl`
   with no `.tf` files at either level is excluded from discovery, not misresolved to an
   arbitrary ancestor. This was corrected twice in Phase 5 (first attempt was still
   name-based) and re-verified against all 18 repos, not just the previously-affected ones,
   before being accepted. (`parser.py`, `find_test_module_dirs`)
6. **`git checkout -- <file>`-based restore**, wrapped so it runs unconditionally
   (`finally`), is the only mutation-restore mechanism — no hand-rolled backup/diff. Applied
   per-mutant and per-module (to clear `terraform init`'s lock-file writes).
   (`state.py`, `restored`/`checkout`)
7. **`is_clean()` counts only tracked-file changes** (`git status --porcelain
   --untracked-files=no`) — a general git flag, not a check against any specific
   filename/pattern. Untracked build byproducts (e.g. a `data "archive_file"`-generated zip
   that a repo's own `.gitignore` doesn't happen to cover) are not corruption; the
   correctness contract is specifically about not leaving *tracked* source mutated.
   (`state.py`, `is_clean`)
8. **Vendored third-party module code (`.terraform/modules/...`) is excluded from every
   file-tree scan**, via one shared predicate (`parser.is_ignored_path`) applied identically
   in all three functions that ever walk a repo (`read_tf_files`, `find_test_module_dirs`,
   `noop.read_tftest_files`) — never a point patch limited to wherever it first crashed.
9. **Engine selection (`terraform` vs `tofu`) is per-repo**, not batch-global — the two
   engines maintain separate provider registries and running the wrong one fails outright.
   Each has its own version pin in `runner.PINNED_VERSIONS`, both verified against real CLI
   output before being trusted (`tests/test_tofu_engine.py`).
10. **Mutation score formula**: see Section 3 above — `killed / (killed + survived)`,
    `baseline_fail`/`invalid`/`timeout`/`no_op` excluded from both numerator and denominator.

## 5. What Phase 6 needs to produce (PROJECT_SPEC.md §11)

**Goal:** the written report. Structure per §11: Introduction → Mutation operators for IaC →
Tool design → Empirical study → Discussion of survived mutants → Threats to validity →
Related work → Conclusion.

Required content, all traceable to `batch_results/master.csv` (§14's definition of done: "no
unsupported claims" — every number in the report must trace back to a row or aggregation of
rows):

1. **Per-repo and aggregate mutation scores**, broken down by operator category
   (security/resource/compliance), using the exact formula in Section 3/§9 — do not
   recompute a different one.
2. **The survived-mutant classification breakdown** (`no_coverage` / `plan_only_no_assert` /
   `weak_assertion`) — per §8, this is "the actual research contribution," not the raw
   mutation score. The current data: 60 `no_coverage`, 11 `weak_assertion`, 0
   `plan_only_no_assert` in the real batch.
3. **Threats to validity** (§11.3): the operator catalog is not exhaustive; the sample is
   curated, not random (18 vetted repos, not "all Terraform test suites"); `mock_provider`
   limitations exclude some real-world patterns (submodules, `azurerm` without `features{}`
   — both documented in §10's known gotchas and observed directly in the Phase 5 batch logs).
   Also worth stating honestly: 9 of 18 repos contributed zero scored mutants (Section 3 /
   `PHASE5_NOTES.md` has the specific reason for each) — this bears on how the aggregate
   score should be read (it is not evenly sourced across the whole corpus).
4. **Related work** (§11.4): native `terraform test` docs, Terratest/kitchen-terraform,
   static analysis tools (tflint, checkov) — explicitly distinguish "checks for violations"
   (those tools) from "checks test *effectiveness*" (this project's contribution).
5. A **specific, falsifiable headline finding** (§12 Phase 6's own done-condition) — not
   just "mutation testing works." Candidates already visible in the current data: the
   uniform 22–33% weak-coverage band across all four `MUT-SEC-004a–d` public-access-block
   flags (suggesting the whole resource is under-tested, not one flag); the 100%/0% contrast
   between `MUT-SEC-002` (encryption, always caught) and `MUT-RES-001` (sizing, never
   caught); or the Phase 1 finding (structurally absent legacy-pattern operators) combined
   with the Phase 5 finding (half the corpus has zero literal mutation targets at all) as a
   joint statement about how thoroughly modern IaC modules parameterize away the textbook
   misconfiguration patterns mutation testing traditionally targets.

Phase 6 has **not** been scoped or started. No code changes are expected for it (it's
analysis + writing), but if generating charts/tables reveals a need to re-derive something
from `master.csv` in a new way, that's expected and fine — just don't restate the mutation
score formula differently than Section 3 without flagging the change explicitly.
