# Phase 5 notes

## Check 1: is `plan_only_no_assert` reachable in practice, or only in theory?

**Finding: it never fired naturally in the 3-repo corpus.** An exhaustive scan of every
mutant generated across every test module in `psoxy`, `cloud-native-deployment-platform`,
and `platform-design` (85 classified sites, treating each as if it survived) produced only
`no_coverage` (68) and `weak_assertion` (17) — **zero** `plan_only_no_assert`.

**Why, structurally.** `plan_only_no_assert` requires a resource address to appear
*somewhere* in a test file *outside* an `assert` condition (proving the test suite "knows
about" the resource) while never being asserted on. In real `.tftest.hcl` files, the
construct that does this is `override_resource { target = <address> }` — used to supply a
computed value (e.g. an ARN or ID) a plan needs. The corpus has several real examples
(`platform-design/secret-rotation`'s `override_resource { target = aws_iam_role.rotation }`,
`ml-artifact-store`'s overrides on `google_service_account.mlflow` /
`google_storage_bucket.mlflow_artifacts`, etc.) — but in every case, the *overridden*
attribute is either computed (`arn`, `id`, `email` — not something our operators mutate) or
a variable reference (e.g. `tags = var.tags`, which our operators correctly skip since they
only mutate literals). The overlap needed — a resource that is `override_resource`-targeted
**and** has a literal, catalog-matching attribute our operators fire on — simply didn't
occur in this specific 3-repo sample.

**Resolution.** Per instruction, constructed a realistic fixture
(`fixtures/classifier_boundary/`) combining the exact real `override_resource` pattern with
a resource that has a literal `MUT-SEC-004` target, and ran it through the **actual**
mutation cycle (`tfmutate run`, real `terraform test` execution, not a hypothetical
classifier call):

- `MUT-SEC-004a`–`d` on the `override_resource`-targeted-but-never-asserted resource: all 4
  **genuinely SURVIVE** real `terraform test`, and the classifier correctly derives
  `plan_only_no_assert` for all 4.
- `MUT-SEC-002`/`MUT-RES-001` on a sibling resource never mentioned anywhere: both
  **genuinely SURVIVE**, and the classifier correctly derives `no_coverage` — in the *same*
  run, proving the two categories are genuinely distinguishable, not just theoretically
  defined.

This is locked in as `test_ground_truth_plan_only_no_assert_boundary` in
`tests/test_classifier.py`. **Watch for this at scale**: if `plan_only_no_assert` remains
rare or absent across the full 15–20 repo corpus, that scarcity is itself a finding worth
reporting (similar to the SEC-001/SEC-003 disjointness finding from Phase 1) — it would
suggest real IaC test suites either cover a resource properly or not at all, with little
middle ground of "acknowledged but unchecked."

## Check 2: orchestrator behavior on mid-batch version drift

`orchestrator.py`'s `run_repo` catches every per-repo fatal condition (version drift, no
test modules, init failure, an unexpected exception mid-cycle) and returns a `FAILED`
`RepoResult` with a logged reason instead of raising; `run_batch` wraps each `run_repo` call
in its own try/except as a last-resort backstop and always proceeds to the next repo.
Verified two ways:

- **Unit tests** (`tests/test_orchestrator.py`): a batch of 3 repos where the middle one is
  forced to fail (simulated version drift, simulated mid-module exception) completes all 3,
  with repo 1 and repo 3's results intact and repo 2 marked failed with a reason logged to
  `<repo>.log`.
- **Real, non-mocked smoke test**: a batch of `[genuinely-broken-repo-with-no-.tftest.hcl,
  real-rds-module]` — the broken repo fails and logs `"no .tftest.hcl test modules found"`,
  and the real module still completes its full mutation cycle immediately after (confirmed
  by an actual `killed_assert` result matching the known Phase 2 ground truth for
  `MUT-SEC-002`/`storage_encrypted`). `verify_all_clean` confirms both repos clean
  afterward.

## Bug found and fixed while smoke-testing: stale `.terraform/` breaks init retries

The first real smoke-test attempt on `rds` failed with `baseline_fail` /
`init_or_provider_error`: `terraform init` errored with *"target directory ... because it is
a symlink"* on all 3 retry attempts. Root cause: that module directory had been
`terraform init`'d many times during this session (manually, and via earlier cli.py runs)
before the shared `TF_PLUGIN_CACHE_DIR` was introduced, leaving a stale/partially-populated
local `.terraform/providers/...` tree that collided with the cache's symlink-based install.
Blindly retrying the identical `init` command 3 times did nothing, because retries don't fix
a persistent *local* state problem the way they fix a transient *network* one.

**Fix:** `Runner.init()` now removes the module's local `.terraform/` directory (untracked,
safe to delete) before each retry, so a retry actually starts from a clean slate instead of
repeating the same broken command. This matters specifically for Phase 5's resumability
requirement: a crashed/interrupted orchestrator run can leave a module partially
initialized, and the next attempt (whether an immediate retry or a batch restart) must not
get stuck in the same failure forever. Re-verified: after the fix, the same `rds` module
completes cleanly with a real `killed_assert` result, no retries needed.

## Corpus selection methodology (§10)

**Search.** Authenticated `gh search code 'mock_provider extension:tftest.hcl'` (the
`path:*.tftest.hcl` glob syntax the web UI accepts is not supported by the API `gh` uses;
`extension:` is the correct qualifier for the same intent). Two batches (100 + 300 hits,
spaced apart to respect the code-search endpoint's strict secondary rate limit) yielded
**158 unique repositories**. Raw list: `evidence/gh_search_candidates_raw.txt`.

**Filtering pipeline:**
1. Excluded the tool's own repo (a self-match) — 157 remain.
2. Zero forks, zero archived repos in this pool (checked via `gh api repos/<repo>` for
   every candidate).
3. Name/description heuristic exclusion (tutorials, bootcamps, "-demo", templates,
   portfolios, homelabs, personal sandbox repos, and non-Terraform false positives like
   `hashicorp/terraform` itself and unrelated apps that happened to match) — 112 remain.
4. **Content inspection**: fetched the actual matched `.tftest.hcl` file(s) for ~40
   priority candidates (known orgs/companies, government-affiliated, spec-hinted, OpenTofu
   examples) via `gh api repos/<repo>/contents/<path>`, then scored:
   - **Assertion depth**: regex-counted `assert { condition = ... }` blocks and classified
     each as a real value check (`== "literal"` / `== <number>` / `== true|false`) vs a weak
     check (`!= null`, `can(...)`, bare `length()` comparisons). Repos with 0 or only-weak
     assertions across their sampled file(s) were deprioritized (score 1-2).
   - **`azurerm` gotcha (§10)**: flagged any file with `mock_provider "azurerm" {}` and no
     `features` block. Confirmed two edge cases by hand: `Azure/terraform-azurerm-avm-ptn-alz`
     mocks `alz`/`azapi`/`modtm`, not `azurerm`, so it's clear; `nearform/terraform-azure-sonarqube`
     does mock `azurerm` with no visible `features{}` — excluded (its AWS sibling,
     `nearform/terraform-aws-sonarqube`, scores higher anyway, so no loss). Every other
     `azurerm`-flagged repo (`aztfmod/terraform-azurerm-caf`, the 4
     `canada-ca-terraform-modules/*`, `cloudeteer/terraform-azurerm-{launchpad,vm}`,
     `equinor/terraform-azurerm-key-vault`, `microsoft/physical-ai-toolchain`,
     `schubergphilis-ep/terraform-azure-mcaf-vwan`) excluded per this section's own
     instruction not to spend time working around a confirmed upstream bug.
   - **Module complexity**: listed the `.tf` files in the module directory containing each
     matched test (walking up past `tests/`/`test/`/`unit/` wrapper dirs) via
     `gh api repos/<repo>/contents/<dir>`. `worldcoin/terraform-aws-eks` (43 `.tf` files —
     a full production EKS platform module) was excluded despite strong assertion depth
     (48 asserts, 36 real value checks) as exactly the "50+ resources, too slow to mutate"
     case this section warns against.
   - **Test isolation / mutation surface**: both score uniformly high across this pool by
     construction — Cohort A membership already requires `mock_provider` (no live-cloud
     dependency), and every inspected module parameterizes through variables (matches
     Phase 1's own finding that modern modules keep literals in variable defaults).

## OpenTofu engine verification (`nullplatform/tofu-modules`)

`nullplatform/tofu-modules` runs via `tofu test`, not `terraform test`. Since
`classify_test`'s `killed_assert`/`killed_error` split depends on matching a literal
`"Error: Test assertion failed"` string, this could NOT be assumed safe for a different
binary without checking — the same class of risk PHASE2_NOTES.md raised for a terraform
*version* upgrade applies equally to a different *engine*.

**Verified, not assumed.** Installed OpenTofu 1.12.3 (official release binary) and ran two
real cases:
- A deliberately-wrong assertion → `tofu test` prints the *identical* `Error: Test
  assertion failed` header Terraform does → `classify_test` correctly returns
  `killed_assert`.
- A genuine engine error (a required argument missing) → `tofu test` prints `Error: Missing
  required argument` (no assertion-failure marker) → `classify_test` correctly returns
  `killed_error`.

Both are locked in as real (non-mocked) regression tests in `tests/test_tofu_engine.py`,
which shell out to the actual `tofu` binary. `PINNED_VERSIONS["tofu"] = "1.12.3"` was added
to `runner.py` so a future OpenTofu upgrade is caught by the same drift guard as Terraform,
rather than silently changing this repo's classification.

## Bugs found running the real 18-repo batch

**Bug: mutating vendored third-party module code under `.terraform/`.** `read_tf_files`,
`find_test_module_dirs` (parser.py), and `read_tftest_files` (noop.py) all did an unfiltered
`root.rglob(...)`, which recurses into `.terraform/modules/...` — a local copy of any
*remote*-sourced module's code that `terraform init` downloads and vendors on disk. This is
gitignored and untracked. Two real batch repos hit it:
`conf-data-processing-architecture-reference` (a vendored `serverless-connector` example) and
`platform-design` (a vendored `terraform-aws-modules/eks` example) — both generated mutants
against downloaded dependency code that isn't part of the repo under study, and when the
per-mutant `git checkout --` tried to restore it, git had no record of that path to restore
from, raising an unhandled exception. **Per-repo isolation worked correctly** — the batch
caught it, logged the repo as `failed`, and moved on to the next repo without crashing —
but those two repos need a full re-run once fixed. Fix: a shared `is_ignored_path()` helper
(parser.py) excludes any path containing a `.terraform` or `.git` component; all three scan
functions now use it. Locked in with tests in `test_mutators.py`/`test_noop.py`. The two
repos' stray `.terraform/` trees were deleted (safe — fully regenerable) so their retry
starts from a clean re-download rather than a corrupted vendored copy.

**Bug (semantic): `is_clean()` was stricter than its own documented contract.** Its docstring
already said "ignored files don't count," but the implementation checked plain
`git status --porcelain`, which *does* report untracked-and-not-ignored files (`??` lines).
`platform-design`'s `auto-shutdown` module uses a `data "archive_file"` that materializes a
real zip file on disk as a side effect of `terraform plan` alone — independent of anything we
mutated — and that repo's own `.gitignore` doesn't happen to cover it. Our correctness
contract is about not leaving *tracked* source mutated, not about a target repo's own
untracked-file hygiene. Fixed by adding `--untracked-files=no` to the `git status` call in
`state.is_clean()`. Locked in with tests in `test_state.py` (a stray untracked file no longer
counts as dirty; a genuinely modified tracked file still does).

**Bug: mixed `str`/`bytes` on a subprocess timeout crashed a whole repo.**
`terraform-duplocloud-components` hit a genuine `terraform init` timeout (300s -- likely a
slow provider/module fetch) on the real overnight batch run. `Runner._exec`'s
`except subprocess.TimeoutExpired` handler assumed `e.stdout`/`e.stderr` would already be
`str` (since `text=True` was passed to `subprocess.run`), and concatenated them directly.
CPython's partial-output capture on a timeout doesn't reliably apply text-mode decoding to
both streams in every case -- one came back as `bytes` while the other was `str`, and
`bytes + str` raised `TypeError: can't concat str to bytes`, crashing the whole repo instead
of gracefully recording an `init_or_provider_error` `baseline_fail` (the outcome this was
supposed to produce). Fixed with a small `_decode()` helper applied independently to each
stream. Locked in with two regression tests in `test_runner.py` (mixed str/bytes, and
all-None streams) that reproduce the exact crash via a monkeypatched `subprocess.run`.
Per-repo isolation still worked correctly around this bug -- the batch logged the failure
and moved on to the remaining repos rather than aborting.

**Bug: wrong test engine for the OpenTofu repo.** `scripts/run_batch.py` hardcoded
`test_cmd="terraform test"` for the entire batch, including `nullplatform/tofu-modules` --
which needs `tofu test` (Terraform and OpenTofu maintain separate provider registries/lock
formats, so running the wrong engine fails outright with "unknown provider", not a flaky
error). All 39 of its modules were silently getting a uniform, meaningless `baseline_fail`.
Fixed by giving the batch script a per-repo engine override (`TOFU_REPOS` set), splitting
the batch into two `run_batch()` calls with different `test_cmd`s.

**Bug (major, corpus-wide): `.tftest.hcl` files inside a `tests/` subdirectory resolved to
the wrong working directory.** Terraform's own test-discovery convention
(developer.hashicorp.com/terraform/language/tests) allows test files to live in a nested
`tests/`/`test/` subdirectory *separate* from the module's own `.tf` files -- `terraform
test` is still run from the module root, not from inside `tests/`. `find_test_module_dirs`
was treating the directory *containing* the `.tftest.hcl` file as the working directory
unconditionally, which meant running `init`/`test` in a directory with **zero `.tf` files**
whenever this convention was used -- producing "OpenTofu/Terraform initialized in an empty
directory" and, worse, *silently* degenerate/meaningless results (some modules "passed"
vacuously with nothing to test) rather than a loud failure. A corpus-wide scan after finding
this in `tofu-modules` showed **9 of the 18 repos affected**, several (`genai-idp-terraform`,
`server-terraform`, `terraform-aws-compliance`, `terraform-datadog-users`,
`terraform-mongodbatlas-project`, `terraform-postgres-config-dbs-users-roles`,
`tofu-modules`) **100% affected** -- their entire dataset before this fix was not
trustworthy. Fixed: `find_test_module_dirs` now climbs from a bare `tests/`/`test/`
directory (no `.tf` files of its own) up to its parent when the parent has real module
source, and stays put when the `tests/` directory is itself a genuine self-contained fixture
module. Locked in with 4 regression tests covering both directions plus the no-op-to-climb
cases. All 10 affected repos' stale CSVs were deleted and re-run from scratch (module-root
resolution changed, so partial/incremental correction wasn't possible or desirable).

**Result after all fixes**: all 18 repos completed successfully.
`terraform-duplocloud-components` in particular hit two more genuine real-world conditions
on its corrected re-run -- an interactive variable prompt (`bucket`, no default, causing a
non-interactive `init` to hang until timeout) and two submodules with a `required_version`
constraint incompatible with our pinned 1.15.7 -- both correctly recorded as per-module
`baseline_fail` rather than crashing. `master.csv`: **171 rows** (the corrected figure;
supersedes the earlier, partially-wrong 197). Every one of the 18 repos verified
`git status` clean via `verify_all_clean` (not spot-checked) -- satisfying Phase 5's
done-condition.

## Second round of the directory-resolution bug: the first fix was still name-based

Before accepting Phase 5 as done, the fix for bug (5) was re-verified against **all 18
repos**, not just the 10 originally known to be affected (`parser.find_test_module_dirs`
was re-run against the whole corpus and every resolved directory checked for actual `.tf`
file presence). This caught a **second gap in the fix itself**: the original version only
climbed out of a directory literally named `tests` or `test`, matching the convention as
documented -- but two real repos use a *different* name for the same pattern:
`platform-tools` has six `.../<module>/e2e-tests/` directories, and
`conf-data-processing-architecture-reference` has one `tools/tftesting/` directory. Both
resolved to a directory with zero `.tf` files, silently invalidating those specific
sub-results.

Investigating the two cases separately showed they need different handling:
- `platform-tools/terraform/<module>/e2e-tests/` -- climbing **one level up** finds the
  real module (`main.tf` etc. are right there in `<module>/`). This is exactly the same
  pattern as the original `tests/` bug, just under a different name.
- `conf-data-processing-architecture-reference/tools/tftesting/` -- this is **not a
  Terraform module at all**. Its contents are Bazel test-harness tooling (`BUILD`, `.bzl`
  files, shell scripts, and a `.tftest.hcl` that is a *template*, not a real test suite),
  and its parent directory (`tools/`) has no `.tf` files either.

This resolved the fix properly: **the rule was never really about the name `tests`/`test`
-- it's about whether the directory has any `.tf` files of its own.** `_module_root_for_test_file`
was rewritten to check for `.tf` presence directly (no name matching at all), climb at most
one level, and **exclude** (not misresolve) a `.tftest.hcl` that has no real module at
either level -- correctly dropping the Bazel-tooling case instead of guessing at some
distant, unrelated ancestor. Re-verified against all 18 repos again: **zero** directories
with no `.tf` files remain. `conf-data-processing-architecture-reference` and
`platform-tools` were re-run (45 and 27 real module dirs respectively, down from the
misleading raw counts of 46 and 33).

## Full accounting: all 164 rows in the final master.csv

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

`baseline_fail` sub-reasons (the `survival_reason` column): `error` 28, `init_or_provider_error`
27, `assertion_failure` 6.

The 3 `invalid` rows (failed `terraform validate`, correctly discarded before testing, per
§5.2's diagram): `platform-design` (`MUT-RES-003` on `terraform/modules/karpenter/variables.tf`),
`platform-tools` (`MUT-SEC-001` on `terraform/statefile-backend/main.tf`), `server-terraform`
(`MUT-RES-002` on `nomad-aws/server.tf`).

**Confirmed stable across both correction rounds**: the scored set (survived + killed_assert
+ killed_error = 100, with 29 killed) did not change between the 171-row and 164-row
datasets -- both directory-resolution corrections only affected which modules got excluded
or moved between `baseline_fail` buckets, never which mutants were already scored. Overall
mutation score: **29.0%** (29/100).

**Exact formula and reasoning (the authoritative, final statement) is in
`PROJECT_SPEC.md` §9**, under "Mutation score formula" -- `killed / (killed + survived)`,
with `baseline_fail`, `invalid`, `timeout`, and `no_op` deliberately excluded from both the
numerator and denominator, not just the numerator. Cite that section, not this one, in the
report.

## Per-repo reason for every repo with zero scored mutants (not a two-bucket summary)

9 of 18 repos produced no `survived`/`killed_assert`/`killed_error` rows at all. Each was
checked individually to rule out a residual directory-resolution bug:

| Repo | Rows | Reason |
|---|---|---|
| `conf-data-processing-architecture-reference` | 20, all `baseline_fail` | Real submodule-composition failures (`Unreadable module directory`, missing git submodules) and real GCP-credential requirements (`storage.NewClient() failed: ... could not find default credentials`) for its `environments/*` directories -- both documented, expected conditions (§10 gotchas), not directory-resolution artifacts. |
| `terraform-duplocloud-components` | 8, all `baseline_fail` | An interactive variable prompt (`bucket`, no default -- hangs a non-interactive `init` until timeout) and two submodules (`tenant-data-aws`, `vpn-data-aws`) with a `required_version` constraint incompatible with our pinned 1.15.7. Real, module-specific conditions. |
| `terraform-aws-compliance` | 0 | Empirically confirmed: 29 real `.tf` files at the correctly-resolved module root, 0 fireable mutants (`generate_mutants` run directly against the real content). |
| `terraform-aws-lb` | 0 | 30 real `.tf` files, 0 fireable mutants (confirmed directly). |
| `terraform-aws-oidc-github` | 0 | 11 real `.tf` files, 0 fireable mutants (confirmed directly). |
| `terraform-aws-security-group` | 0 | 17 real `.tf` files, 0 fireable mutants (confirmed directly). |
| `terraform-aws-vpc` | 0 | 3 module dirs (`test/basic-usage`, `test/custom-named-subnets`, `test/with-ipv6`), 1 real `.tf` file each (thin example wrappers calling the real module via `source = "../.."`), 0 fireable mutants in any (confirmed directly). |
| `terraform-datadog-users` | 0 | 10 real `.tf` files, 0 fireable mutants (confirmed directly). |
| `terraform-postgres-config-dbs-users-roles` | 0 | 15 real `.tf` files, 0 fireable mutants (confirmed directly). |

The "0 rows, 0 fireable mutants" repos were verified by directly running
`parser.find_test_module_dirs` + `mutators.generate_mutants` against their real,
correctly-resolved module content (not inferred from the CSV) -- each has a substantial,
real Terraform module (10-30 `.tf` files), fully parameterized through variables/locals with
no literal value our operator catalog matches. This is the same pattern Phase 1 already
established (modern IaC modules parameterize almost everything) at corpus scale, not a
residual directory bug.

## Category and operator-level findings (unchanged across both correction rounds)

- **Category**: security n=75, 32.0% killed; resource n=24, 20.8% killed; compliance n=1
  (too small to read anything into).
- **Operator-level**: `MUT-SEC-002` (storage encryption) 100% killed (3/3) -- every
  encryption-disable mutant tested was caught. `MUT-RES-001` (instance sizing) 0% killed
  (0/5) -- nobody in this sample asserts on instance size/class. The four
  `MUT-SEC-004a-d` (public-access-block flags) all sit in a consistent 22-33% kill-rate
  band, suggesting uniformly weak coverage of that whole resource, not one outlier flag.
- **Survival reasons**: `no_coverage` 60, `weak_assertion` 11, `plan_only_no_assert` 0 (this
  matches the earlier finding that this category is real but rare -- see the Check 1 section
  above).
- `no_op` count: 0 across the whole real batch -- the static override-detector never fired
  live. Combined with the `plan_only_no_assert` scarcity, this suggests variable-default
  mutants that collide with a test's explicit override are a genuinely rare pattern in this
  corpus, not just a Phase 1-4 sample-size artifact.

**Separately observed, not a code bug**: the background batch process was found in macOS's
stopped (`T`) process state on two separate occasions (once overnight, once mid-day),
consistent with the machine sleeping (lid closed / display sleep) suspending the background
job — a known `nohup ... &` gotcha on macOS. Sending `SIGCONT` to the process (and to its
process group) did not revive it. Recommended fix for future runs: launch via
`caffeinate -i nohup ... &` so the process itself prevents idle sleep for its own duration.

## Candidate list adjustment

Per instruction, swapped `so1omon563/terraform-aws-secrets-manager` out for
`appvia/terraform-aws-compliance` in — reduces the single-author concentration (now 3 of 18
from `so1omon563` instead of 4) and adds a different org/domain (AWS security/compliance
services: Access Analyzer, Config, Inspector, Macie, Security Hub) for more authorship and
subject-matter diversity in the final sample.

## Refinement of S3 Validate Issue (Phase 5/6 Corpus Addition)

During the targeted corpus addition of 7 repositories, we encountered a static validation failure (`terraform validate` returning code 1) on all 11 mutants of `terraform-aws-static-site`.

* **Cause**: The module uses `configuration_aliases = [aws.us_east_1]` in its `versions.tf` and assigns `provider = aws.us_east_1` to global regional resources like ACM and CloudWatch, but does not declare a default `provider "aws" { alias = "us_east_1" }` block in its root `.tf` files (which is a standard practice for reusable modules where callers supply aliases). Statically, running `terraform validate` directly in the root directory fails because of this missing provider configuration.
* **The Bounded Fix**: We resolved this issue by adding a minimal [providers.tf](file:///Users/tusharteotia/Documents/GitHub/Oasis/corpus/terraform-aws-static-site/providers.tf) directly to `terraform-aws-static-site` containing a dummy declaration for the `aws.us_east_1` provider. This enabled standalone validation to pass, rescuing 10 mutants (including 6 compliance tag mutants) into the valid/scored dataset.
* **Bound Exception Confirmation**: We explicitly confirm that **no other repository in the entire 23-repository corpus received any source modification**. This is a strictly bounded exception to satisfy static HCL validate semantics for this specific regional module.
