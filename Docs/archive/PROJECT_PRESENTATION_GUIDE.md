# OASIS 🌿 — Minor Project Presentation & Implementation Guide

> **Project Name**: OASIS (`oasis-tfmutate`)  
> **Repository**: [github.com/DegenerateUSER/Oasis](https://github.com/DegenerateUSER/Oasis)  
> **Target Technology**: Python 3.10+, Terraform 1.15+, OpenTofu 1.12+, HCL2  

---

## 📑 Table of Contents
1. [Project Overview & Core Mission](#1-project-overview--core-mission)
2. [OASIS Full-Form (Backronym) Options](#2-oasis-full-form-backronym-options)
3. [3-Phase Progressive Feature Breakdown](#3-3-phase-progressive-feature-breakdown)
4. [Git History & Commit Checkpoints](#4-git-history--commit-checkpoints)
5. [Complete 12-Slide PPT Content for Presentation 1](#5-complete-12-slide-ppt-content-for-presentation-1)
6. [Key Technical Architecture & Operators Reference](#6-key-technical-architecture--operators-reference)
7. [Benchmark Evaluation Summary (for final presentation reference)](#7-benchmark-evaluation-summary)

---

## 1. Project Overview & Core Mission

**OASIS** is an open-source **mutation testing framework** designed specifically for **Terraform and OpenTofu Infrastructure-as-Code (IaC)** test suites.

### The Problem:
* In Cloud Infrastructure, tests (`terraform test`) often simply run `command = plan` or `command = apply`.
* **Traditional code coverage only tests execution, not verification**: Tests pass as long as infrastructure provisions without syntax errors, even if critical security rules, encryption, or sizing constraints are left unvalidated.

### The Solution:
* **Oasis injects targeted faults ("mutants")** into `.tf` configuration files.
* Runs the test suite against each mutant and checks whether test assertions catch the failure:
  * **Killed mutant**: Test assertions caught the injected fault (High test rigor).
  * **Survived mutant**: Injected fault went completely undetected (Test assertion gap).
  * **Mutation Score**:
    $$\text{Mutation Score} = \frac{\text{Killed Mutants}}{\text{Total Scored Mutants}} \times 100\%$$

---

## 2. OASIS Full-Form (Backronym) Options

### 🌟 Option 1: Most Academic & Direct (Highly Recommended)
> **OASIS**: **O**pen-source **A**ssertion **S**coring for **I**nfrastructure **S**uites
* **O**pen-source (MIT licensed)
* **A**ssertion **S**coring (Quantifying `assert` block quality via mutation score)
* **I**nfrastructure **S**uites (Targets Terraform / OpenTofu test suites)

### 🌟 Option 2: Emphasizing Fault Injection & Semantics
> **OASIS**: **O**rchestrated **A**ssertion & **S**emantic **I**njection **S**ystem

### 🌟 Option 3: Emphasizing IaC Quality Assessment
> **OASIS**: **O**rchestrated **A**ssessment of **S**emantic **I**aC **S**uites

### 🌟 Option 4: Security & State-Focused
> **OASIS**: **O**perational **A**ssertion & **S**ecurity **I**nspection for **S**tate-based IaC

---

## 3. 3-Phase Progressive Feature Breakdown

To present the minor project across 3 college evaluation presentations:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   3-PHASE MINOR PROJECT ROADMAP                        │
├────────────────────────┬───────────────────────┬───────────────────────┤
│    PRESENTATION 1      │    PRESENTATION 2     │    PRESENTATION 3     │
│  Foundation & Engine   │ Execution & Lifecycle │ Classification & Demo │
│                        │                       │                       │
│ • Problem formulation  │ • Green-baseline gate │ • Survival classifier │
│ • HCL parser & gating  │ • Zero-drift Git undo │ • Batch orchestrator  │
│ • 12 mutation operators│ • Static NO_OP filter │ • Benchmark (23 repos)│
│ • `oasis preview` diff │ • `oasis run` pipeline│ • Full binary release │
└────────────────────────┴───────────────────────┴───────────────────────┘
```

### Presentation 1: Foundation & Core Mutation Engine
* **Focus**: Problem formulation, HCL parsing without rigid ASTs, 12 domain-specific mutation operators across 3 surfaces (`R`, `V`, `L`), non-destructive `oasis preview` CLI.
* **Key Demo**: `oasis preview <path>` showing live colorized unified diffs.

### Presentation 2: Execution Lifecycle, Safety & Test Runner
* **Focus**: Automated execution pipeline, Pre-flight Green Baseline Gate, Zero-Drift Git state rollback (`state.restored()`), Static NO_OP variable-shadowing detection (`noop.py`), `killed_assert` vs `killed_error` detection.
* **Key Demo**: `oasis run <path> --output results.csv` running live tests and auto-restoring Git state.

### Presentation 3: Survival Reason Classification, Benchmarks & Final Product
* **Focus**: Post-processing survival reason classifier (`no_coverage` vs `plan_only_no_assert` vs `weak_assertion`), multi-repo batch orchestrator, empirical benchmark results across 23 real-world GitHub repositories, self-updating CLI and standalone native binaries (`.pkg`, `.deb`, `.exe`).
* **Key Demo**: Full end-to-end audit of a Terraform repository, fixing a weak test to turn a surviving mutant into a killed mutant.

---

## 4. Git History & Commit Checkpoints

If evaluators ask to see gradual progress in the Git commit history:

| Phase / Milestone | Commit Hash | Date | Description & Files Included |
|---|---|---|---|
| **Milestone 1** | `7e29346` | 02/07/2026 | `parser.py`, `mutators.py`, `noop.py`, `oasis preview` CLI, unit tests |
| **Milestone 2** | `dcb147c` | 06/07/2026 | `state.py`, `runner.py`, `classifier.py`, `orchestrator.py`, `oasis run` |
| **Milestone 3 / Final** | `4707bf5` / `master` | 07/07/2026 | `install.sh`, packaging release pipeline, `benchmarks/` data & report |

### Verification Commands:
```bash
# View the commit graph
git log --oneline --graph

# Checkout Milestone 1 state:
git checkout 7e29346

# Checkout Milestone 2 state:
git checkout dcb147c

# Return to latest final product:
git checkout master
```

---

## 5. Complete 12-Slide PPT Content for Presentation 1

---

### **Slide 1: Title Slide**
* **Title**: **OASIS 🌿**
* **Subtitle**: **Open-source Assertion Scoring for Infrastructure Suites**
* **Heading**: *Evaluating Semantic Test Rigor Beyond Code Coverage in Infrastructure-as-Code*
* **Type**: Minor Project Evaluation — Milestone 1 (Foundation & Core Engine)
* **Presenter**: `[Your Name / Team]`
* **Supervisor**: `[Supervisor Name / Department]`
* **Institution**: `[College / University Name]`

> **Speaker Notes**: *"Good morning respected evaluators. Today, we present Milestone 1 of our minor project, OASIS—a domain-specific mutation testing engine designed to evaluate the true semantic quality of Infrastructure-as-Code test suites."*

---

### **Slide 2: Team & Project Overview**
* **Project Name**: OASIS (`oasis-tfmutate`)
* **Domain**: Cloud Infrastructure, Software Reliability & Mutation Testing, DevOps
* **Team Members**:
  * `[Member 1]` — Core Mutation Engine & Operator Design
  * `[Member 2]` — HCL Parsing & Compiler Validity Gate
  * `[Member 3]` — CLI Tooling, Test Fixtures & Unit Testing
* **Technology Stack**: Python 3.10+, Terraform 1.15+, OpenTofu 1.12+, HCL2, Git, Pytest

> **Speaker Notes**: *"Our team has completed the foundational phase of the project, focusing on AST-free HCL parsing, semantic fault modeling, and the initial preview CLI."*

---

### **Slide 3: Problem Statement & Motivation**
* **The IaC Testing Crisis**:
  * Cloud infrastructure is defined in code (Terraform / OpenTofu).
  * A misconfigured security group, open S3 bucket, or unencrypted storage can lead to data loss and compliance violations.
* **The False Sense of Security with Code Coverage**:
  * Standard test suites (`terraform test`) simply run `command = plan` or `apply`.
  * **Line coverage only checks execution, not verification**: Tests pass as long as infrastructure provisions without syntax errors, even if crucial security attributes are completely unverified.
* **The Mutation Testing Solution**:
  * Injects controlled, deliberate faults into code to verify if test assertions actually catch them.

> **Speaker Notes**: *"In infrastructure testing, standard coverage metrics are deceptively optimistic. Tests verify that cloud resources are created, but rarely check if specific security properties or size limits were enforced."*

---

### **Slide 4: Limitations of Existing Approaches & Research Gap**
* **General-Purpose Mutation Tools (e.g., Mutmut, Stryker, Pitest)**:
  * Built for imperative languages (Python, Java, JavaScript).
  * Cannot understand declarative HCL or cloud resource semantics (e.g., CIDR blocks, IAM policies, storage encryption flags).
* **Static Analysis Linters (e.g., TFLint, Checkov, tfsec)**:
  * Check code against static rules, but **do not test the test suite itself**.
* **The Research Gap**:
  * No dedicated framework existed to model, inject, and evaluate semantic faults for native `terraform test` / `tofu test` suites.

> **Speaker Notes**: *"Traditional mutation testing tools do not support declarative cloud configuration files. Our goal is to build an engine tailored specifically for Terraform HCL semantics."*

---

### **Slide 5: Project Objectives & Milestone 1 Scope**
* **Overall Project Goal**:
  * Build an end-to-end, zero-drift mutation testing platform that computes an empirical **Mutation Score** and classifies test survival root causes.
* **Scope of Milestone 1 (Completed Deliverables)**:
  1. **Brace-Aware Top-Level Block Scanner**: Resilient parsing of `.tf` files.
  2. **Authoritative Validity Gate**: Preventing grammar false-rejection gaps via `terraform fmt`.
  3. **12 Domain-Specific Mutation Operators**: Covering Security, Sizing, and Tag Compliance.
  4. **Multi-Surface Target Mapping**: Resources (`R`), Variable Defaults (`V`), and Locals (`L`).
  5. **Static Preview Engine**: Unified diff generation via `oasis preview`.

> **Speaker Notes**: *"For Milestone 1, our objective was to establish the mathematical fault model, build the parser and mutation engine, and create the non-destructive diff preview tool."*

---

### **Slide 6: System Architecture — Milestone 1 Overview**
* **Component Workflow**:
  ```
  Target .tf Files ──► [ parser.py ] (find_blocks + fmt validity check)
                             │
                             ▼
                      [ mutators.py ] (12-Operator Catalog & Regex Transform)
                             │
                             ▼
                      [ noop.py ] (Static Variable-Default Shadowing Check)
                             │
                             ▼
                      [ cli.py preview ] (Unified Diff Generation to Stdout)
  ```
* **Key Design Philosophy**:
  * **Read-only parsing**: Locates targets without rewriting ASTs.
  * **Precision text substitution**: Preserves developer formatting, indentation, and comments.

> **Speaker Notes**: *"Here is our core engine architecture. We separate block discovery from text transformation to ensure our tool remains fast, memory-efficient, and syntax-preserving."*

---

### **Slide 7: Robust HCL Parsing & Authoritative Validity Gate**
* **The Challenge with Traditional AST Parsers**:
  * Python HCL parsers (`python-hcl2`) often break on modern Terraform syntax (e.g. `for` expressions, splat operators).
  * Using AST parsing directly causes false rejections of valid code.
* **Our Dual-Layer Solution (`parser.py`)**:
  * **Layer 1 (Target Discovery)**: Lightweight, brace-aware lexical scanner (`find_blocks()`) to locate top-level blocks (`resource`, `variable`, `locals`) and exact 1-based line numbers.
  * **Layer 2 (Authoritative Validity Gate)**: Subprocess call to `terraform fmt -` (`is_valid_hcl()`). Uses Terraform's official compiler as the ground truth.

> **Speaker Notes**: *"Instead of relying on brittle third-party AST parsers that fail on new HCL language features, we use a brace-aware block locator paired with Terraform's own compiler format engine as the validity gate."*

---

### **Slide 8: The 12-Operator Mutation Catalog**
* Categorized across 3 critical cloud engineering domains:

| Category | Operator ID | Injected Fault / Transformation | Target Resources |
|---|---|---|---|
| **Security** | `MUT-SEC-001` | S3 ACL `"private"` $\rightarrow$ `"public"` | `aws_s3_bucket`, `aws_s3_bucket_acl` |
| **Security** | `MUT-SEC-002` | Storage Encryption `true` $\rightarrow$ `false` | `aws_ebs_volume`, `aws_db_instance`, `rds` |
| **Security** | `MUT-SEC-003` | Restrictive CIDR $\rightarrow$ `0.0.0.0/0` | `aws_security_group`, `ingress_rule` |
| **Security** | `MUT-SEC-004a-d`| Public Access Block flags `true` $\rightarrow$ `false` | `aws_s3_bucket_public_access_block` |
| **Resource** | `MUT-RES-001` | Sizing $\rightarrow$ Oversized Instance (`24xlarge`)| `aws_instance`, `compute_instance` |
| **Resource** | `MUT-RES-002/3`| Desired count $\rightarrow$ `1` / Replicas $\rightarrow$ `0` | Auto-scaling groups, containers |
| **Tags** | `MUT-TAG-001/2`| `"production"` $\rightarrow$ `"development"` / Delete tag | Compliance & Billing metadata |

> **Speaker Notes**: *"Our operators mirror real-world developer errors and cloud vulnerabilities, including leaky security groups, disabled encryption, and over-provisioned compute sizes."*

---

### **Slide 9: Multi-Surface Scoping & Static NO_OP Filtering**
* **Multi-Surface Fault Injection**:
  * Modern Terraform code rarely hardcodes values inside resource blocks.
  * Oasis scans 3 surfaces:
    * **`R` Surface**: Directly inside `resource {}` and `module {}` blocks.
    * **`V` Surface**: Inside `variable {}` default values.
    * **`L` Surface**: Inside `locals {}` constant declarations.
* **Static NO_OP Detection (`noop.py`)**:
  * Mutating a variable default is **inert** if every test run in `.tftest.hcl` explicitly overrides that variable.
  * Oasis statically detects this shadowing beforehand, eliminating false "survived" mutants.

> **Speaker Notes**: *"Most production Terraform repos parameterize configurations via variables. Oasis targets variable defaults and locals, and uses static analysis to discard shadowed variable defaults as NO-OPs."*

---

### **Slide 10: Non-Destructive Preview Engine (`oasis preview`)**
* **Purpose**: Allows developers to audit all potential mutants before executing test suites.
* **Features**:
  * Generates standard **Unified Diffs** (`diff -u`) directly to terminal stdout.
  * Shows exact operator ID, line number, surface type, and original vs mutated values.
  * **Zero disk mutation**: Read-only execution with zero chance of corrupting code.
* **Sample Output**:
  ```diff
  [MUT-SEC-002] main.tf:14  [R] aws_ebs_volume.data .encrypted
      'encrypted = true' -> 'encrypted = false'
  --- main.tf (original)
  +++ main.tf (mutant MUT-SEC-002)
  @@ -13,3 +13,3 @@
  -  encrypted = true
  +  encrypted = false
  ```

> **Speaker Notes**: *"With `oasis preview`, developers can instantly inspect all generated mutants as colorized unified diffs without modifying a single file on disk."*

---

### **Slide 11: Milestone 1 Validation & Unit Test Results**
* **Verification of Milestone 1 Deliverables**:
  * Comprehensive test suite in `tests/`:
    * `test_mutators.py`: 100% test coverage across all 12 operators and synonyms.
    * `test_parser_gate.py`: Verification of HCL syntax acceptance/rejection against `terraform fmt`.
    * `test_noop.py`: Testing shadowed vs non-shadowed variable default overrides.
* **Git Repository Checkpoint**:
  * Initial engine implementation tagged and committed at `7e29346`.
* **Next Steps for Milestone 2**:
  * Integration of the full test runner (`terraform test`), Git rollback context managers, and green-baseline test gates.

> **Speaker Notes**: *"All Milestone 1 components are backed by rigorous unit tests. We verified operator substitution correctness, syntax gating, and no-op filtering."*

---

### **Slide 12: Thank You & Q&A**
* **Project**: OASIS (`oasis-tfmutate`)
* **Milestone 1 Completed**: Mutation Modeling, HCL Parser & Preview Engine
* **Next Milestone**: Automated Execution Runner, Sandboxed Git Rollbacks & Baseline Gates
* **Repository**: `https://github.com/DegenerateUSER/Oasis`

```
           🌿 OASIS 🌿
"Open-source Assertion Scoring for Infrastructure Suites"
```

**Questions & Feedback are Welcome!**

---

## 6. Key Technical Architecture & Operators Reference

| Module | File | Core Functionality |
|---|---|---|
| **Parser** | `src/tfmutate/parser.py` | `find_blocks()`, `is_valid_hcl()`, `find_test_module_dirs()` |
| **Mutators** | `src/tfmutate/mutators.py` | `Operator`, `CATALOG` (12 operators), `generate_mutants()` |
| **No-Op** | `src/tfmutate/noop.py` | `default_is_shadowed()`, `is_noop()` |
| **State** | `src/tfmutate/state.py` | `restored()` (guaranteed `git checkout -- <file>` in `finally`) |
| **Runner** | `src/tfmutate/runner.py` | Baseline gate, `classify_test()` (`killed_assert` vs `killed_error`) |
| **Classifier** | `src/tfmutate/classifier.py` | `classify_survival()` (`no_coverage`, `plan_only_no_assert`, `weak_assertion`) |
| **Orchestrator** | `src/tfmutate/orchestrator.py` | Multi-repo unattended execution & resume logic |
| **CLI** | `src/tfmutate/cli.py` | `preview`, `run`, `update`, `uninstall` commands |

---

## 7. Benchmark Evaluation Summary

* **Scope**: Tested across **23 real-world open-source Terraform repositories** on GitHub.
* **Total Mutants Generated**: 242
* **Scored Mutants**: 177
* **Overall Mutation Score**: **24.9%** (44 killed, 133 survived).
* **Survival Root Causes**:
  * **78%** (`no_coverage`): The mutated resource was never referenced in test files.
  * **22%** (`weak_assertion`): The test executed and checked the resource, but omitted attribute-level checks.
