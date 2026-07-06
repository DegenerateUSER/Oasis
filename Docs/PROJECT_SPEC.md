# Mutation Testing for Infrastructure-as-Code

## Project spec for agent-driven implementation

---

## 1. What we are building

A **Python CLI tool** that performs **mutation testing on Terraform modules**, plus the **empirical study** that uses it.

Mutation testing is a well-established technique from application-code testing (Java: Pitest, JS: Stryker, Python: MutPy). It works like this: automatically inject small, realistic faults ("mutants") into code, then run the existing test suite against each mutant. If the test suite still passes despite the injected fault, the test suite is **blind to that fault** — it's a "surviving" mutant. The ratio of caught ("killed") mutants to total mutants is the **mutation score**, a standard, quantitative measure of how good a test suite actually is (as opposed to how much of the code it merely executes, which is what coverage measures).

**This technique has never been applied to Infrastructure-as-Code.** Terraform shipped a native test framework (`terraform test`, GA since v1.6, mock providers since v1.7) that lets you write `.tftest.hcl` unit tests with `mock_provider` blocks — no cloud credentials, no cost, fully local. Real-world adoption of this framework is growing (confirmed via live GitHub code search: ~4.6k files, real usage from Google-adjacent, IBM, Microsoft, and government-affiliated repos) but nobody has measured whether these test suites actually catch real infrastructure misconfigurations, or whether they're just "does `terraform apply` not crash" smoke tests wearing a unit-test costume.

We are building the first tool to measure this, and running it across a real sample of open-source repositories to produce the first empirical data on IaC test suite quality.

---

## 2. Why we are building this (motivation / novelty)

- **Confirmed gap, not assumed:** We searched for "mutation testing" + "Terraform"/"IaC" and found zero prior tools or papers doing fault-injection mutation testing against Terraform test suites. (One paper uses the word "mutation" in an unrelated LLM-config-editing sense — different concept, same word, not prior art.)
- **Confirmed viable population, not assumed:** Live GitHub code search (not estimated, actually run) found a real, non-trivial population of repositories using `.tftest.hcl` + `mock_provider` (Cohort A — our primary target) and a separate, larger, higher-quality population using Terratest with real `testify`-based assertions from orgs like IBM, Google, Microsoft, and UK government (Cohort B — stretch goal, not in initial scope, see Section 4).
- **The metric is unambiguous.** Mutation score doesn't rely on a noisy external proxy (unlike, e.g., correlating code smells with GitHub issue labels, which is a real weakness in adjacent "IaC debt" research ideas we rejected). A test either catches the injected fault or it doesn't. This makes the empirical claim easy to defend.
- **IaC mutation testing has a genuine methodological advantage over imperative-language mutation testing:** the classic "equivalent mutant" problem (a mutation that's syntactically different but behaviorally identical — a major headache in Java/Python mutation testing) is much smaller here, because `.tftest.hcl` assertions check specific resource attribute values directly. Most surviving mutants in IaC won't be true equivalent mutants — they'll be **uncovered mutants** (the test suite simply never asserts on that attribute). This is a cleaner, more defensible research setting than application-code mutation testing.
- **We deliberately rejected several other project ideas after live research showed them to be saturated:** predictive/HPA-style Kubernetes autoscaling (saturated since ~2015, CNCF/KEDA already do this), causal root-cause-analysis for microservices (saturated, dedicated PhD-level benchmark suites exist — RCAEval), and CI/CD pipeline threat modeling (saturated — zizmor, TaintAWI, stride-gpt, Mercari's ATT&CK-for-CI/CD matrix already exist and are actively maintained). This idea is the one that survived actual due diligence.

---

## 3. Use case / who this is for

- **Practitioners:** platform/DevOps engineers who write `.tftest.hcl` tests today have no way to know if their tests are actually rigorous. This tool gives them a mutation score for their own module, plus a breakdown of *which* attributes are untested — directly actionable.
- **This project's owner (a 4th-year BTech DevOps engineer):** a portfolio-grade, technically rigorous project demonstrating original tool-building + empirical research skill, scoped to be completable solo in a few weeks on a MacBook M1 Air with zero budget, with a realistic path to a workshop paper / arXiv preprint (not a top-tier venue — be honest about that ceiling).

---

## 4. Scope — read this section twice

### In scope (build this first, build this well)
- **Cohort A only**: repositories using native `terraform test` with `.tftest.hcl` files and `mock_provider`.
- A CLI tool, run locally, that mutates one repo's `.tf` files, runs `terraform test`, classifies results, and outputs a CSV/report.
- A batch runner that repeats this across ~15–20 hand-picked repos.
- A survived-mutant classifier that explains *why* tests failed to catch faults.
- A written report (research-paper structure) summarizing findings.

### Explicitly out of scope for v1 (do not build these unless Phase 5 is fully done with time remaining)
- **Cohort B (Terratest / real cloud `apply`)** — a real comparative study, but it requires a Go toolchain, live cloud credentials, real spend, and much slower test cycles. This is a stretch goal only, attempted after Cohort A is fully working and evaluated. Do not interleave the two.
- Any GUI, web dashboard, or SaaS product. This is a CLI tool. Nothing else.
- Any GPU/LLM-inference-serving work (a different idea explored and abandoned earlier — irrelevant here).
- Multi-cloud (AWS/GCP/Azure) breadth for its own sake. Depth on a curated repo list beats breadth across a scraped, unfiltered one.
- Semantic/AST-based HCL rewriting. Use regex-based text mutation (see Section 6). `python-hcl2` may be used read-only, to *locate* mutation targets, never to rewrite files (it does not round-trip HCL formatting reliably).

**Guardrail for the agent: if a task doesn't clearly serve "get Cohort A working end-to-end on a handful of repos, then scale to ~15-20," stop and flag it rather than build it.**

---

## 5. Architecture

### 5.1 System-level (three stages)

```
┌─────────────────────────────────────────────────────────────┐
│                     Research pipeline                        │
│                 (runs across cloned repos)                   │
│                                                               │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐ │
│  │ Orchestrator  │───▶│ Mutator engine│───▶│  Classifier   │ │
│  │ Loops repo    │    │ Mutate and    │    │ Scores        │ │
│  │ list          │    │ test          │    │ mutants       │ │
│  └───────────────┘    └───────────────┘    └───────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

- **Orchestrator**: iterates the list of target repos, ensures each is a clean git checkout before starting, invokes the mutator engine per repo, collects per-repo CSVs into one master dataset, logs progress so an overnight unattended run is resumable/debuggable.
- **Mutator engine**: the core, single-repo pipeline (detailed in 5.2).
- **Classifier**: post-processing stage over the master dataset — for every SURVIVED mutant, determines *why* (see Section 8).

### 5.2 Mutator engine — single mutation cycle (this is the inner loop, run once per mutation operator per file per repo)

```
Apply mutation (regex edit on file)
        │
        ▼
Terraform validate ──(invalid)──▶ Invalid mutant → discarded, not counted
        │ (valid)
        ▼
Terraform test
        │
   ┌────┴────┐
   ▼         ▼
Survived   Killed
(still     (test now
 passes)    fails)
   │         │
   └────┬────┘
        ▼
Restore file (git checkout — see note below)
        │
        ▼
Log result to dataset
```

**Critical correctness rule, non-negotiable:** *every* path through this diagram — survived, killed, AND invalid/discarded — must pass through "restore file" before the next mutation begins. If invalid mutants are discarded without restoring the file first, mutations stack on top of each other and every subsequent result in that run is corrupted. Use `git checkout -- <file>` after every single cycle, not a hand-rolled backup/restore mechanism — git guarantees a clean revert with no custom state-tracking code to get wrong.

**Also non-negotiable:** wrap the whole cycle in `try/finally` so a crash mid-mutation (timeout, hung mock provider, disk issue) cannot leave the target repo in a mutated state.

---

## 6. How exactly we are building this (implementation detail)

### 6.1 Tech stack
- **Language**: Python 3.x for the tool itself (CLI, mutation logic, orchestration, reporting).
- **Target under test**: Terraform (v1.7+, for `mock_provider` support) — or OpenTofu, which uses the same `.tftest.hcl` format via `tofu test`.
- **Validity gate**: `terraform fmt -` (the same engine that runs the tests) decides whether a `.tf` file is valid HCL and thus eligible for mutation. `python-hcl2` is **not** used for this — its grammar is stricter than Terraform's and silently rejected valid files (a `for`-expression false-rejection bug; see PHASE1_NOTES.md). A file that genuinely fails `fmt` is logged as `SKIPPED_FILE`, never dropped silently.
- **Target location**: a brace-aware raw-text scanner (`parser.find_blocks`) locates blocks (resource/variable/locals/…), their types, and line ranges. This is independent of any third-party parser's grammar coverage and exposes source line numbers hcl2 does not. `python-hcl2` is used only in `noop.py`, to parse `.tftest.hcl` files for override detection (§6.4).
- **Mutation writing**: regex-based text replacement directly on the raw `.tf` file content. This guarantees the file stays syntactically valid HCL (modulo the mutation itself) and preserves formatting/comments, which `python-hcl2`'s dict round-trip does not.
- **Test execution**: Python `subprocess.run(["terraform", "test"], cwd=<repo>, capture_output=True, timeout=<N>)`. Exit code 0 = mutant survived. Non-zero = mutant killed.
- **State management**: `git`. Every target repo must be a git checkout. Restore via `git checkout -- <file>`.
- **Reporting**: CSV as the source of truth (see schema in Section 9), Markdown for the human-readable report.
- **No GUI, no web framework, no Docker requirement for v1.**

### 6.2 CLI shape (what running it looks like)

```bash
python mutate.py --target ./repo-name --test-cmd "terraform test" --output results.csv

[+] Parsing Terraform files...
[+] Found 14 .tf files.
[+] Generating mutants...
[+] Mutant MUT-SEC-001 (acl: private -> public) injected.
[+] Running tests... PASSED. Mutant SURVIVED.
[+] Mutant MUT-RES-001 (count: 3 -> 1) injected.
[+] Running tests... FAILED. Mutant KILLED.
...
[+] Done. Mutation score: 34%. Results saved to results.csv.
```

Batch mode wraps this per-repo invocation in an outer loop reading a repo list file.

### 6.3 Internal modules (build as separate files/classes)
1. `parser.py` — locates mutation targets using `python-hcl2` (read-only).
2. `mutators.py` — the operator catalog (Section 7); applies one operator via regex to produce a mutant file.
3. `runner.py` — subprocess execution of `terraform validate` then `terraform test`, with timeout handling.
4. `state.py` — git-based backup/restore (`git checkout -- <file>`), wrapped in try/finally.
5. `classifier.py` — post-processing over survived mutants (Section 8).
6. `orchestrator.py` — batch loop across repos, calls the above per repo, aggregates results.
7. `reporter.py` — writes CSV + generates the final Markdown report.
8. `noop.py` — static NO_OP (override) detection (see §6.4).

### 6.4 Mutation surface, synonym scoping, and NO_OP validity (as built in Phase 1)

Empirical reality of modern Cohort A repos reshaped the naive "one attribute, one literal"
model. The authoritative mapping lives in **`OPERATOR_SYNONYMS.md`**; the rules:

- **Attribute synonyms.** Each operator matches a *curated set* of attribute names, not one
  literal (e.g. sizing ∈ {`instance_type`, `instance_class`, `node_type`, `machine_type`}),
  because real modules use synonyms.
- **Resource-type scoping.** On the resource body, a synonym only matches when its enclosing
  **resource type** is in the operator's allowed set — scoping is `(resource_type, attribute)`,
  never attribute-in-isolation, so `encrypted` on an unrelated resource is not mutated as if
  it were storage encryption.
- **Three surfaces.** Modern modules keep literals in variable/locals defaults, not resource
  bodies, so operators may target **R** (resource body), **V** (`variable {} default`,
  scoped by variable name), and **L** (`locals {}`/tag maps). Every mutant records the exact
  attribute, line, resource/var/local, and surface, so analysis granularity lives in the CSV
  regardless of operator-ID count.
- **NO_OP validity (non-negotiable).** A mutant on a **V**-surface default is *inert* if a
  `.tftest.hcl` `run` block overrides that variable (the default is never read). Such mutants
  are classified **`NO_OP`** — a category distinct from `INVALID` and from
  `SURVIVED`/`KILLED` — and discarded before testing, so they never inflate the
  "tests missed this" numbers. Detection is **static** (parse the test files' `run` /
  file-level `variables {}` blocks): `mock_provider` and per-run `variables {}` exist only
  inside `terraform test`, so a standalone plan cannot reproduce the override. A dynamic
  `terraform test -verbose` plan-diff may be added in Phase 2 only if non-override no-ops
  surface.

### 6.5 Target discovery, git-clean semantics, and engine selection (as built in Phase 5)

Running against a real, heterogeneous 18-repo corpus (not the small Phase 1–4 sample)
surfaced correctness gaps in three previously-implicit rules. All three are now general,
corpus-wide policies — not point patches applied only where they first crashed — and are
exercised by unit tests (`tests/test_mutators.py`, `tests/test_noop.py`,
`tests/test_state.py`).

- **Vendored third-party code is excluded from every scan, everywhere.** `terraform init`
  vendors remote module sources on disk under `.terraform/modules/...` — untracked,
  gitignored, and not part of the repo under study. A single shared predicate,
  `parser.is_ignored_path` (any path component in `{".terraform", ".git"}`), is applied
  identically in all three functions that ever walk a repo's file tree looking for mutation
  or test targets: `parser.read_tf_files`, `parser.find_test_module_dirs`, and
  `noop.read_tftest_files`. Mutating vendored code and then trying to `git checkout --`
  restore it fails outright (no git record for an untracked path exists to restore from).
- **Module-root resolution for `.tftest.hcl` is content-based, not name-based.**
  Terraform's own test-discovery convention (developer.hashicorp.com/terraform/language/tests)
  lets test files live in a nested subdirectory dedicated to tests, separate from the
  module's own `.tf` files — `terraform test`/`tofu test` is still run from the **module
  root**. `parser.find_test_module_dirs` resolves each `.tftest.hcl` file's true working
  directory by checking for **actual `.tf` file presence**, not by matching a directory name
  like `tests`/`test` (real repos use other names too, e.g. `e2e-tests/` — a name-based rule
  missed these). Climbing is bounded to exactly one level: if neither the containing
  directory nor its parent has any `.tf` files, the `.tftest.hcl` is **excluded** from
  discovery entirely (it is not a real, runnable module — e.g. a Bazel test-harness template
  found in the real corpus) rather than misresolved to an arbitrary, unrelated ancestor.
- **`state.is_clean` counts only tracked-file changes.** `git status --porcelain
  --untracked-files=no` — a general git flag, not a filename/pattern check — so an untracked
  build byproduct a module's own `.gitignore` doesn't happen to cover (e.g. a
  `data "archive_file"`-generated zip, which `terraform plan` alone materializes on disk) is
  never mistaken for mutation-induced corruption. The correctness contract this tool makes
  is specifically about not leaving *tracked* source content mutated; a target repo's own
  untracked-file hygiene is out of scope.
- **Engine selection is per-repo, not batch-global.** A repo's test suite is written for
  either `terraform test` or `tofu test` — the two engines maintain separate provider
  registries/lock formats, so running the wrong one fails outright ("unknown provider"),
  not as a flaky error. The batch driver (`scripts/run_batch.py`) partitions the corpus by
  engine and calls `orchestrator.run_batch` once per engine with the matching `test_cmd`;
  `runner.PINNED_VERSIONS` carries a version pin per binary (`terraform`, `tofu`) so a drift
  in either is caught the same way (§6.1, §12 Phase 2).

---

## 7. Mutation operator catalog (v1 — implement these first, in this order)

> **As-built note (Phase 1).** The table below is the original design intent and its IDs are
> preserved (no renumbering mid-project — deferred to Phase 3). What actually ships is
> specified in `OPERATOR_SYNONYMS.md` per §6.4, with two documented changes: (1) MUT-SEC-001's
> literal `acl = "private"` is empirically near-absent in Cohort A (inline `acl` deprecated in
> AWS provider v4+), so its modern equivalent ships as **four atomic operators**
> `MUT-SEC-004a–d` (one `aws_s3_bucket_public_access_block` guard flag each — see
> `PHASE1_NOTES.md`); (2) operators are synonym-based and resource-scoped, not single-literal.
> 10/12 operators are validated on real Cohort A files; MUT-SEC-001 and MUT-SEC-003 remain
> empirically scarce (a finding), pending targeted repos.

Start with these 3, get them fully working end-to-end on one real repo before adding the rest:

| Operator ID | Category | Original | Mutated | Fault simulated |
|---|---|---|---|---|
| MUT-SEC-001 | Security | `acl = "private"` | `acl = "public"` | Accidental public exposure |
| MUT-RES-002 | Resource | `count = 3` | `count = 1` | Under-provisioning |
| MUT-TAG-002 | Compliance | `team = "platform"` | *(attribute deleted)* | Missing required tag |

Then extend to the full v1 catalog:

| Operator ID | Category | Original | Mutated | Fault simulated |
|---|---|---|---|---|
| MUT-SEC-001 | Security | `acl = "private"` | `acl = "public"` | Accidental public exposure |
| MUT-SEC-002 | Security | `encrypt = true` | `encrypt = false` | Disabled encryption |
| MUT-SEC-003 | Security | `cidr = "10.0.0.0/8"` | `cidr = "0.0.0.0/0"` | Overly permissive firewall |
| MUT-RES-001 | Resource | `instance_type = "t3.micro"` | `instance_type = "t3.2xlarge"` | Cost misconfiguration |
| MUT-RES-002 | Resource | `count = 3` | `count = 1` | Under-provisioning |
| MUT-RES-003 | Resource | `replicas = 2` | `replicas = 0` | Total provisioning failure |
| MUT-TAG-001 | Compliance | `env = "production"` | `env = "development"` | Wrong environment tag |
| MUT-TAG-002 | Compliance | `team = "platform"` | *(deleted)* | Missing required tag |

Each operator must be independently toggleable (so the report can break down mutation score *per category*, not just overall).

---

## 8. The classifier — this is what makes it research, not just a tool

For every mutant marked SURVIVED, the classifier must determine *why*, by checking the repo's `.tftest.hcl` files:

1. **No coverage**: no `run` block in any test file references the mutated resource/attribute at all.
2. **Plan-only, no assertion on this attribute**: the test runs (`command = plan`) but no `assert` block's `condition` references the mutated attribute.
3. **Weak assertion**: an assertion references the resource but checks a different attribute than the one mutated (e.g., checks the bucket exists but not its `acl`).

v1 implementation of this can be a straightforward string/regex match of the mutated attribute name against the content of the repo's `.tftest.hcl` files — this does not need to be a sophisticated static analyzer to produce a valid, useful finding.

**This classification breakdown — not the mutation score alone — is the actual research contribution.** "The average mutation score across sampled repos is X%" is a fine headline number. "Y% of surviving mutants are attributes with zero test coverage, and the security-category mutants have the lowest coverage of any category" is the finding that makes this a paper instead of a tool demo.

---

## 9. Data / reporting schema

CSV columns (one row per mutant, per repo):

```
repo_name, file_mutated, mutant_id, operator_id, operator_category,
surface (R/V/L), resource_or_var, attribute, original_value, mutated_value,
validate_status (valid/invalid), test_status (killed/survived/timeout/no_op),
survival_reason (no_coverage/plan_only_no_assert/weak_assertion/n/a), test_output_snippet
```

`test_status = no_op` marks a mutant discarded by static override-detection (§6.4): the
mutated variable default was shadowed by a test `run`'s `variables {}` block, so the mutation
never took effect. NO_OP mutants are excluded from the mutation-score denominator (they are
neither killed nor survived). The `surface`, `resource_or_var`, and `attribute` columns carry
per-mutant granularity so synonym-based operators remain analysable per attribute.

**Mutation score formula (final, stated methodological decision — not to be
reverse-engineered from the CSV by a reader).** For any slice of rows (overall, per-repo, per
category, per operator):

```
mutation score = (killed_assert + killed_error) / (killed_assert + killed_error + survived)
```

`baseline_fail`, `invalid`, `timeout`, and `no_op` rows are **deliberately excluded from both
the numerator and the denominator**, not just from the numerator. The reasoning:

- **`baseline_fail`**: a module whose *unmutated* test suite doesn't pass green cannot yield a
  meaningful mutation result for any of its mutants — there is no "the test suite caught the
  fault" or "missed the fault" to measure when the test suite doesn't even establish a
  passing baseline. Counting these as survived would conflate "the test suite is broken/can't
  run" with "the test suite is weak," which are different findings the report must not blur
  together (§12 Phase 2's green-baseline gate exists specifically to prevent this).
- **`invalid`**: the mutation itself failed `terraform validate` — this is a property of the
  mutation (or an operator/repo interaction), not of the test suite's rigor, so it carries no
  test-quality signal either way.
- **`timeout`**: an inconclusive result (the test didn't finish within the timeout budget),
  not evidence the test suite caught or missed anything.
- **`no_op`**: the mutation demonstrably never took effect (§6.4), so there was nothing for
  the test suite to catch or miss.

Concretely, for the Phase 5 batch (`batch_results/master.csv`, 164 rows): scored =
`killed_assert` (27) + `killed_error` (2) + `survived` (71) = **100**; killed = 27 + 2 = 29;
**mutation score = 29/100 = 29.0%**. The other 64 rows (`baseline_fail` 61, `invalid` 3) are
excluded from this calculation entirely, per the rule above -- not folded into either side.
This is the exact, final formula the Phase 6 report must use and cite; see
`PHASE5_NOTES.md` for the full accounting these numbers are drawn from.

This single CSV is the entire empirical dataset the final report is built from. Keep it append-only and repo-scoped so a crashed batch run can resume without re-processing completed repos.

---

## 10. Repo selection (Cohort A) — how targets were found and how to pick more

**Confirmed via live GitHub code search** (query: `path:*.tftest.hcl mock_provider`) — real, non-trivial hit count, not a scraped estimate. Known strong candidates already identified:

- `google-ads-confidential-computing/conf-data-processing-architecture-reference` — mature custom mock-provider tooling across dozens of modules. Strong primary case study.
- `100rd/platform-design` — GPU inference HPA, bare-metal GPU operator, Rook-Ceph, `mock_provider "kubernetes"`/`"helm"`.
- `Worklytics/psoxy`, `MPeets/cloud-native-deployment-platform`, `CloudverveGmbH/terraform-azurerm-policy-based-dns` — real production-looking repos.

**Scoring rubric for adding more repos** (score 1–5 each; only include repos scoring 3+):

| Criteria | 1 (bad) | 5 (ideal) |
|---|---|---|
| Assertion depth | Only checks `apply` doesn't error | Checks specific attribute values |
| Module complexity | 50+ resources (too slow to mutate) | 2–10 resources |
| Mutation surface | All values hardcoded | Uses variables/locals |
| Test isolation | Depends on pre-existing state | Creates/destroys its own state |

**Target sample size: 15–20 repos scoring 3+.** Do not aim for 50+ — depth of analysis on a smaller, well-vetted sample is more publishable than shallow analysis on a large noisy one. Explicitly discard: forks, archived repos, one-file tutorial/demo repos with a single trivial `mock_provider "x" {}` and no real assertions (these will dominate raw search results — filter them out deliberately).

**Known tooling gotchas to expect and handle, not be surprised by:**
- `mock_provider` fails on providers requiring a config block (e.g., `azurerm` needs `features {}}` — open HashiCorp bug, no workaround yet). Repos using `azurerm` may simply fail to run under mocking; log and exclude, don't spend time working around a confirmed upstream bug.
- No submodule mocking support yet (open feature request). Repos with heavy submodule composition may need to be excluded or handled at the root-module level only.

---

## 11. Evaluation plan / what the final report contains

1. **Per-repo and aggregate mutation scores**, broken down by operator category (security/resource/compliance).
2. **Survived-mutant classification breakdown** (no coverage / plan-only-no-assert / weak assertion) — the key finding.
3. **Threats to validity**: operator catalog is not exhaustive; sample is curated, not random, so results aren't strictly generalizable to "all Terraform test suites"; `mock_provider` limitations exclude some real-world patterns (noted above).
4. **Related work**: native `terraform test` docs, Terratest/kitchen-terraform, static analysis tools (tflint, checkov — explicitly note these check for *violations*, not test *effectiveness*, which is the distinction this project's contribution rests on).
5. Report structure: Introduction → Mutation operators for IaC → Tool design → Empirical study → Discussion of survived mutants → Threats to validity → Related work → Conclusion.

---

## 12. Phased goals for the agent

Each phase has an explicit "done" condition. Do not start a phase until the previous one's done-condition is met. Do not silently expand scope mid-phase — if something outside the phase's goal seems necessary, flag it rather than build it.

### Phase 0 — Environment setup
**Goal:** working local environment.
- Install Terraform (or OpenTofu) v1.7+, confirm `terraform test` and `mock_provider` work with a trivial hand-written example.
- Set up Python project structure per Section 6.3.
- **Done when:** a hand-written 5-line `.tf` file + `.tftest.hcl` with `mock_provider` runs successfully via `terraform test` on this machine.

### Phase 1 — Mutator core (single file, single operator)
**Goal:** one mutation operator, working end-to-end, on one hand-picked real repo.
- Implement `parser.py` (locate targets) and `mutators.py` (MUT-SEC-001 only).
- Implement regex-based mutation writing.
- Manually verify the mutant is syntactically valid HCL.
- **Done when:** MUT-SEC-001 successfully mutates a real `.tf` file from a Cohort A repo, and the mutation is visually confirmed correct.

### Phase 2 — Test runner + git state management ✅ done
**Goal:** full single-mutation cycle working per the Section 5.2 diagram.
- Implemented `runner.py` (`terraform validate` → `terraform test`, with timeout, plus a
  **green-baseline gate**: a module whose unmutated suite doesn't pass green is skipped as
  `baseline_fail` with a sub-reason -- `timeout` / `assertion_failure` / `error` /
  `init_or_provider_error` -- rather than producing meaningless kill/survive noise).
- Implemented `state.py` (`git checkout --` restore per mutant, wrapped in `contextlib`'s
  `finally`-guaranteed context manager; `git checkout -- .` per module clears
  `terraform init`'s lock-file writes).
- `test_status` distinguishes `killed_assert` (an `assert` block's condition caught the
  fault -- real test rigor) from `killed_error` (terraform errored; the engine rejected the
  mutation, not the test) -- discriminated on terraform's `Error: Test assertion failed`
  marker.
- A shared `TF_PLUGIN_CACHE_DIR` plus init retries eliminate transient network flakiness so
  determinism holds across repos with real network-dependent provider installs.
- Ran the full cycle across real modules from two Cohort A repos, exercising every
  `test_status` path: `killed_assert` (`cloud-native-deployment-platform/rds`, SEC-002),
  `survived` (`platform-design/aws-config`, all 4 SEC-004 flags — a genuine coverage gap),
  and `baseline_fail` (`platform-design/rds`, an external registry submodule errors at
  plan).
- **Done:** each module run **twice** in a row produced a **byte-identical CSV** both times,
  and `git status` was clean on every corpus repo (`psoxy`,
  `cloud-native-deployment-platform`, `platform-design`) after every run.
- **Engine version is pinned and checked at runtime** (`runner.check_pinned_version`,
  `--allow-version-drift` to override) so the `killed_assert`/`killed_error` split — which
  depends on matching terraform's literal CLI wording — can't silently drift if the
  installed binary changes. Per-category operator toggling (`-c/--category`, alongside
  `--operator`) added per this section's requirement. Details in `PHASE2_NOTES.md`.

### Phase 3 — Full operator catalog ✅ done (satisfied inside Phase 1, per instruction)
**Goal:** all 8 operators from Section 7 implemented and working.
- Extend `mutators.py` to the full catalog.
- Add per-category toggling.
- **Done when:** all 8 operators run successfully (produce either KILLED, SURVIVED, or correctly-discarded INVALID) against 2–3 hand-picked repos.

**Status note:** this phase's goal was explicitly pulled forward and completed as part of
Phase 1, on direct instruction ("once the atomic split is done, keep going on Phase 1 with
the rest of the operators"), rather than being skipped. What was actually delivered exceeds
this phase's literal goal: not 8 but **12 operators** (the `MUT-SEC-004` split into four
atomic `004a`–`004d` flags — see `PHASE1_NOTES.md` §"Why four atomic operators"), each
independently toggleable by ID (`--operator`) **and** now by category
(`-c/--category security|resource|compliance`, added in Phase 2 — see `PHASE2_NOTES.md`).
10/12 run successfully against real Cohort A repos (KILLED/SURVIVED, no bogus INVALID);
the remaining 2 (`MUT-SEC-001`, `MUT-SEC-003`) are FIXTURE-validated because their targets
are empirically absent from the terraform-test population — see `OPERATOR_SYNONYMS.md`'s
CORPUS/FIXTURE validation table and the `evidence/` code-search results. Full accounting in
`PHASE1_NOTES.md`.

### Phase 4 — Classifier ✅ done
**Goal:** every SURVIVED mutant gets a `survival_reason`.
- Implemented `classifier.py`: a straightforward string/regex match of the mutated
  resource address and attribute name against `.tftest.hcl` content (per this section's own
  "does not need to be a sophisticated static analyzer" guidance), producing `no_coverage` /
  `plan_only_no_assert` / `weak_assertion`.
- Wired into `tfmutate run`: every module's outcomes are classified in place immediately
  after the mutation cycle, before the CSV is written; the CLI also prints a
  survived-mutant reason breakdown.
- **Ground-truth verified against real `terraform test` signal** (not just synthetic
  fixtures) on two Cohort A modules:
  - `platform-design/aws-config`: all 4 `MUT-SEC-004*` mutants come back SURVIVED; the
    classifier independently derives `no_coverage` for all 4 -- the mutated resource is
    never referenced anywhere in the test file at all.
  - `platform-design/aws-ml-artifact-store`: only `MUT-SEC-004c` (`ignore_public_acls`)
    survives -- the other three public-access-block flags are explicitly asserted true. The
    classifier derives `weak_assertion`, the spec's own example pattern ("checks the bucket
    exists but not its acl") reproduced on a real repo.
  Both cases are locked in as regression tests in `tests/test_classifier.py`.
- **Done:** classifier output matches manual inspection on both real cases above (exceeding
  the 10-mutant spot-check bar with two independently-verified real-repo categories, plus
  unit tests covering all three reasons synthetically).

### Phase 5 — Batch orchestrator + repo corpus ✅ done
**Goal:** unattended run across 15–20 vetted repos.
- Implemented `orchestrator.py`: per-repo CSV (resumable -- a repo with an existing CSV is
  skipped, not re-run), per-repo isolation (any fatal condition is caught, logged to
  `<repo>.log`, and the batch proceeds), a self-healing pre-run `git checkout -- .`, and a
  final `verify_all_clean` pass across every repo (not spot-checked).
- Finalized the repo list via the §10 rubric + authenticated `gh` code search (158 unique
  candidates → 18 selected after exclusions). Full methodology, scoring, and exclusions in
  `PHASE5_NOTES.md`.
- Ran the full batch across all 18 repos (280 correctly-resolved test modules). Found and
  fixed five real bugs surfaced only by running against a real, messy 18-repo corpus (not
  caught by the smaller Phase 1-4 corpus): (1) mutating vendored third-party module code
  under `.terraform/modules/` that can't be `git checkout`-restored (untracked); (2)
  `is_clean()` being stricter than intended, flagging untracked build byproducts (e.g. a
  `data "archive_file"` zip) as dirty; (3) a mixed `str`/`bytes` crash in subprocess timeout
  handling; (4) the OpenTofu repo being run with the wrong engine (`terraform test` instead
  of `tofu test`), silently zeroing its entire dataset; (5) **major** -- `.tftest.hcl` files
  living in a nested test-only subdirectory (a real Terraform convention) resolving to the
  wrong working directory, running `init`/`test` in an empty directory with zero `.tf`
  files. The first fix for (5) matched only directories literally named `tests`/`test` and
  missed real repos using other names (`e2e-tests/`); re-verifying discovery against **all**
  18 repos (not just the originally-affected 10) caught this gap, and the rule was
  generalized to be content-based (does the directory have `.tf` files?) rather than
  name-based. 9 of 18 repos were affected by (5) in total, several 100%. All five fixed and
  locked in as regression tests; §6.5 documents each as a general, corpus-wide policy. Full
  accounting in `PHASE5_NOTES.md`.
- **Done:** `batch_results/master.csv` contains **164 rows** (the fully-corrected figure,
  after both rounds of the tests/-subdirectory fix) across all **18** repos (exceeding the
  15–20 target), and **every one of the 18 repos verified `git status` clean**
  (`verify_all_clean`, not spot-checked) after the full run. Full accounting of all 164 rows
  by status (including `baseline_fail` sub-reasons) and a per-repo reason for every repo
  that produced zero scored mutants is in `PHASE5_NOTES.md` -- 7 of those repos were
  empirically confirmed (by directly running mutant generation against their real,
  substantial `.tf` content) to have zero fireable operator targets, not a residual
  discovery bug. Overall mutation score:
  **29.0%** (29/100 scored mutants killed). Full breakdown in `PHASE5_NOTES.md`.

### Phase 6 — Analysis + report
**Goal:** the written report described in Section 11.
- Aggregate stats, generate charts/tables from the CSV.
- Write the report following the Section 11 structure.
- **Done when:** the report contains a defensible, specific, falsifiable headline finding (not just "mutation testing works") — e.g., "Security-category mutants survive at 2x the rate of resource-category mutants, driven almost entirely by zero test coverage rather than weak assertions."

### Phase 7 — Stretch goal (only if Phases 0–6 are complete with time remaining)
Cohort B (Terratest) extension — do not start this until Phase 6 is fully done. Re-scope at that point based on remaining time.

---

## 13. Risks and mitigations (known in advance, don't rediscover these the hard way)

| Risk | Mitigation |
|---|---|
| `python-hcl2` fails to parse some real-world HCL (dynamic blocks, `jsonencode`, etc.) | Parser only needs to *locate* targets, not fully round-trip. If a file fails to parse, skip it and log — don't block the whole run. |
| `terraform test` hangs on a misconfigured mock provider | Hard timeout on every `subprocess.run` call (start at 30s, tune per repo). Timeout = discard mutant, log as TIMEOUT, move on. |
| Invalid mutants counted as false "killed" results | Always run `terraform validate` before `terraform test`; discard anything that fails validation before it reaches the test stage. |
| File left in mutated state after a crash | `try/finally` around every mutation cycle; git checkout restore is unconditional. Verify with `git status` after every repo. |
| `azurerm`/submodule mocking bugs silently produce bad data | Known upstream limitations (Section 10) — detect and exclude affected repos rather than debug indefinitely. |
| Scope creep toward Cohort B or a GUI mid-build | Re-read Section 4 before adding anything not explicitly in the current phase's goal. |

---

## 14. Definition of done for the whole project

- A working CLI tool implementing the full mutation cycle (Section 5.2) with the complete operator catalog (Section 7).
- A classifier producing survival reasons (Section 8).
- A master CSV covering 15–20 vetted Cohort A repos.
- A written report with the structure in Section 11, containing at least one specific, quantified, falsifiable finding.
- Every claim in the report traceable back to a row (or aggregation of rows) in the CSV — no unsupported claims.