# Oasis 🌿

[![Release](https://img.shields.io/github/v/release/DegenerateUSER/Oasis?logo=github)](https://github.com/DegenerateUSER/Oasis/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python)](https://www.python.org/)

**Oasis** is an open-source mutation testing framework for Terraform and OpenTofu Infrastructure-as-Code (IaC) test suites.

Rather than relying on basic code coverage metrics, Oasis evaluates the **semantic quality** of your `terraform test` assertions. It injects small, logical faults ("mutants") into `.tf` resource configurations, runs your test suite against each mutant, and reports whether your assertions successfully detect (kill) the injected failure—producing a **mutation score** that quantifies how rigorous your IaC tests actually are.

---

## 📊 Benchmarks — Tested on 23 Real-World Repositories

Oasis was empirically evaluated against a curated corpus of **23 public Terraform repositories** from GitHub. The full evaluation report and raw data live in [`/benchmarks`](./benchmarks/).

### Aggregate Results

| Metric | Value |
|---|---|
| Total mutants generated | 242 |
| Scored mutants (valid, ran to completion) | **177** |
| Killed (caught by test assertions) | 44 |
| Survived (missed by tests) | 133 |
| **Overall mutation score** | **24.9%** |
| Baseline failures (credential/env issues) | 61 |

A 24.9% overall mutation score indicates that the large majority of public Terraform test suites verify a successful apply but rarely assert on the specific attribute values that security and correctness actually depend on — meaning semantic faults slip through undetected even when all tests pass.

> **On baseline failures**: 61 rows could not be scored because `terraform test` requires live cloud provider credentials or other environment setup (e.g. AWS/GCP auth) that was not available in the evaluation environment. This is a real constraint: Oasis can generate and validate mutants offline, but executing the test suite requires the same credentials the repo's CI would use. Repos that need cloud auth will show `baseline_fail` until run in an authenticated environment.

### Per-Repository Breakdown

**Repositories with sufficient sample size (n ≥ 5)**

| Repository | Scored Mutants | Mutation Score |
|---|---|---|
| `aws-platform-starter` | 38 | 13% |
| `aws-terraform-infrastructure` | 5 | 80% |
| `eks-vulnerable-infra` | 5 | 40% |
| `genai-idp-terraform` | 8 | 0% |
| `platform-design` | 32 | 41% |
| `platform-tools` | 37 | 24% |
| `psoxy` | 9 | 0% |
| `server-terraform` | 5 | 0% |
| `serverless-architecture-patterns` | 19 | 21% |
| `terraform-aws-static-site` | 10 | 0% |
| `tofu-modules` | 5 | 100% |

**Low-sample repositories (n < 5, indicative only)**

| Repository | Scored Mutants | Mutation Score |
|---|---|---|
| `cloud-native-deployment-platform` | 1 | 100% * |
| `terraform-aws-sonarqube` | 2 | 50% * |
| `terraform-mongodbatlas-project` | 1 | 0% * |

\* Sample size too small for a reliable percentage; shown for completeness only.

### Why Survived Mutants Matter
Of the 133 surviving mutants, the classifier identified:
- **104 (78%)** as `no_coverage` — the mutated resource was never exercised by any test.
- **29 (22%)** as `weak_assertion` — the test executed but lacked an assertion checking the mutated attribute.

→ **Full analysis**: [`benchmarks/report_draft.md`](./benchmarks/report_draft.md) | **Raw data**: [`benchmarks/batch_results/master.csv`](./benchmarks/batch_results/master.csv)

---

## 🚀 Key Features

- **12 Specialized Mutation Operators** targeting variables, resource dependencies (`depends_on`), conditionals, lifecycle rules, security enums, and tag casing.
- **Zero-Drift State Management** — a `restored` context manager guarantees your git repository state is cleanly reverted (`git checkout`) after every test, even on crash or keyboard interrupt.
- **Survival Reason Classifier** — every surviving mutant is automatically classified into `no_coverage`, `plan_only_no_assert`, or `weak_assertion` to give you actionable signal, not just a number.
- **Self-Managing CLI** — `oasis update` self-updates from GitHub Releases; `oasis uninstall` removes itself cleanly.
- **No Python Runtime Required** — distributed as compiled native binaries for macOS, Linux, and Windows.

---

## 📦 Installation

### Option 1 — One-Command Installer (macOS & Linux)

```bash
curl -sSfL https://raw.githubusercontent.com/DegenerateUSER/Oasis/master/bin/install.sh | sh
```

**Verify before running** (recommended): Check the script's SHA-256 digest against the published value to confirm it hasn't been tampered with in transit.

```bash
# Download first, verify, then run
curl -sSfL https://raw.githubusercontent.com/DegenerateUSER/Oasis/master/bin/install.sh -o install.sh
shasum -a 256 install.sh
# Expected: 9444074f20ee7c331dca5d9dc8fffe40f7026a22a4e1fa57309f785855d0460d  install.sh
sh install.sh && rm install.sh
```

> The checksum above matches the installer at the time of the current release. After any update to `install.sh`, the new digest will be published here and in the release notes.

### Option 2 — Native Package Installers

Download from the [GitHub Releases](https://github.com/DegenerateUSER/Oasis/releases) page:

| Platform | File | How to Install |
|---|---|---|
| **macOS (Apple Silicon)** | `oasis-macos-arm64.pkg` | Double-click → macOS installer wizard |
| **Linux (Ubuntu / Debian)** | `oasis-linux-amd64.deb` | `sudo dpkg -i oasis-linux-amd64.deb` |
| **Windows** | `oasis-windows-amd64.zip` | Extract `.exe`, add to `PATH` |

### Option 3 — Build from Source

```bash
git clone https://github.com/DegenerateUSER/Oasis.git
cd Oasis
pip install .
```

---

## 🛠️ Usage

### Preview Mutants (dry-run, no files modified)

```bash
oasis preview /path/to/terraform-module/
```

Shows exactly what mutations would be injected, as unified diffs, without touching any files.

### Run Mutation Tests

```bash
oasis run /path/to/repo/ --output results.csv
```

Runs the full mutation cycle: initializes the module, establishes a green baseline, injects each mutant, runs `terraform test`, classifies the outcome, and restores git state — for every mutant.

### Key Options for `oasis run`

| Flag | Default | Description |
|---|---|---|
| `--output` | `results.csv` | Path for the output CSV report |
| `--test-cmd` | `terraform test` | Use `"tofu test"` for OpenTofu |
| `--timeout` | `60` | Per-test timeout in seconds |
| `-c <category>` | all | Only run operators in `security`, `logic`, `variables`, or `tags` |
| `--allow-version-drift` | off | Skip the Terraform version pin check |
| `--plugin-cache-dir` | `~/.cache/` | Shared provider plugin cache for faster init |

### Manage Oasis Itself

```bash
oasis --version      # show installed version
oasis update         # download and install the latest release
oasis uninstall      # remove Oasis from this system
```

---

## 📈 Understanding the Output

The `results.csv` report contains one row per mutant:

| Column | Description |
|---|---|
| `repo_name` | Target repository |
| `operator_id` | Mutation operator applied (e.g. `MUT-SEC-004a`) |
| `file_mutated` | Source `.tf` file that was changed |
| `test_status` | `killed_assert` / `killed_error` / `survived` / `baseline_fail` / `invalid` |
| `survival_reason` | For `survived` rows: `no_coverage`, `plan_only_no_assert`, or `weak_assertion` |
| `test_output_snippet` | Relevant excerpt from `terraform test` output |

**Mutation Score** = `(killed_assert + killed_error) / (all scored mutants) × 100%`

---

## 🔬 Mutation Operators

| Operator | Category | What it mutates |
|---|---|---|
| `MUT-RES-001` | Logic | Deletes `depends_on` resource dependencies |
| `MUT-RES-002` | Logic | Swaps boolean attribute values (`true` ↔ `false`) |
| `MUT-RES-003` | Logic | Inverts `count` conditions (`0` ↔ `1`) |
| `MUT-SEC-001` | Security | Swaps private ACL to `public-read` |
| `MUT-SEC-002` | Security | Disables encryption-at-rest settings |
| `MUT-SEC-003` | Security | Deletes security group ingress rules |
| `MUT-SEC-004a` | Security | Flips `block_public_acls` lifecycle flags |
| `MUT-SEC-004b` | Security | Flips `block_public_policy` lifecycle flags |
| `MUT-SEC-004c` | Security | Flips `ignore_public_acls` lifecycle flags |
| `MUT-SEC-004d` | Security | Flips `restrict_public_buckets` lifecycle flags |
| `MUT-TAG-001` | Tags | Swaps string values inside `tags`/`labels` maps |
| `MUT-TAG-002` | Tags | Alters tag key casing |

---

## 🏗️ Project Layout

```
src/tfmutate/
  parser.py       # locates mutation targets + terraform-fmt validity gate
  mutators.py     # 12-operator catalog; applies one operator per mutant
  noop.py         # static NO_OP (variable-override) detection
  state.py        # git checkout restore, finally-guaranteed
  runner.py       # init → baseline gate → validate → test → classify
  classifier.py   # survival_reason for every SURVIVED mutant
  reporter.py     # CSV writer
  cli.py          # oasis preview / run / update / uninstall

benchmarks/       # full pilot study dataset and report
  batch_results/  # per-repo CSVs + master.csv
  report_draft.md # empirical evaluation report
  README.md       # how to reproduce

fixtures/         # hand-written fixtures (phase0 smoke, thin-operator tests)
tests/            # unit tests
evidence/         # GitHub code-search results (saved as JSON/CSV) confirming that the two security operators MUT-SEC-001 and MUT-SEC-003 target legacy misconfiguration patterns (S3 ACL strings, bare ingress rules) that are structurally absent from the modern terraform-test population — supporting the paper's finding that zero corpus matches is a property of the target population, not a bug in the operators.
```

---

## 🤝 Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for how to file issues, run tests locally, and what kinds of contributions are welcome.

---

## 📄 License

Released under the [MIT License](./LICENSE). Copyright © 2026 Tushar Teotia.
