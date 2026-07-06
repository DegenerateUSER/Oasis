# Oasis 🌿

[![Release](https://img.shields.io/github/v/release/DegenerateUSER/Oasis?logo=github)](https://github.com/DegenerateUSER/Oasis/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python)](https://www.python.org/)

**Oasis** is an open-source mutation testing framework designed specifically for Terraform and OpenTofu Infrastructure-as-Code (IaC) test suites. 

Rather than relying on basic code coverage metrics, Oasis evaluates the **semantic quality** of your `terraform test` assertions. It injects small, logical faults ("mutants") directly into your `.tf` resource configurations, runs your test suites against each mutant, and validates whether your assertions successfully detect (kill) the injected failure.

---

## 🚀 Key Features

*   **12 Specialized Mutation Operators**: Targets variables, logical resource dependencies (`depends_on`), conditional tags, lifecycle rules, security enums, and tag casing.
*   **Zero-Drift State Management**: Uses a robust `restored` context manager that guarantees your git repository state is cleanly reverted (`git checkout`) after every test execution, even on crash or manual abort.
*   **Survival Reason Classifier**: Automatically categorizes *why* a mutant survived into three actionable categories:
    *   `no_coverage`: The mutated file or resource was never targeted by tests.
    *   `plan_only_no_assert`: The test block has run-gates (`command = plan`) but lacks explicit check assertions.
    *   `weak_assertion`: The test block executes and verifies the state, but fails to check the mutated parameter.
*   **Zero-Dependency Installer Packages**: Distributed as compiled, standalone native binaries (via Nuitka) for macOS, Linux, and Windows—no Python runtime required.

---

## 📦 Installation

### 1. One-Command Installer (macOS & Linux)
To download the correct binary, package it, and install it to `/usr/local/bin/oasis` automatically:

```bash
curl -sSfL https://raw.githubusercontent.com/DegenerateUSER/Oasis/master/bin/install.sh | sh
```

### 2. Native Package Installers
Go to the [GitHub Releases](https://github.com/DegenerateUSER/Oasis/releases) page and download:
*   **macOS**: `oasis-macos-arm64.pkg` (Double-click to install using the macOS wizard)
*   **Linux (Ubuntu/Debian)**: `oasis-linux-amd64.deb` (`sudo dpkg -i oasis-linux-amd64.deb`)
*   **Windows**: `oasis-windows-amd64.zip` (Extract `oasis-windows-amd64.exe` to a directory in your `PATH`)

### 3. Install from Source
Ensure you have [uv](https://github.com/astral-sh/uv) or `pip` installed:

```bash
git clone https://github.com/DegenerateUSER/Oasis.git
cd Oasis
pip install .
```

---

## 🛠️ Usage

Oasis operates via four subcommands: `preview`, `run`, `update`, and `uninstall`.

### Previewing Mutants
To see where Oasis will inject mutations and preview them as unified diffs without modifying files:
```bash
oasis preview /path/to/module/
```

### Running Mutation Tests
To run the full mutation testing cycle on a repository, execute its `terraform test` suite against all mutants, and generate a `results.csv` evaluation report:
```bash
oasis run /path/to/repo/
```

### CLI Options

```bash
usage: oasis [-h] [-V] {preview,run,update,uninstall} ...

positional arguments:
  {preview,run,update,uninstall}
    preview             show mutants for a .tf file or directory
    run                 run the full mutation cycle over a repo and write a CSV
    update              download and install the latest Oasis release
    uninstall           remove the Oasis binary from this system

options:
  -h, --help            show this help message and exit
  -V, --version         show program's version number and exit
```

#### `oasis run` Customizations
*   `--test-cmd "tofu test"`: Run tests using OpenTofu instead of Terraform.
*   `--timeout 120`: Set a custom per-test execution timeout in seconds.
*   `--plugin-cache-dir <dir>`: Use a shared provider plugin cache to speed up test initialization across modules.
*   `--allow-version-drift`: Proceed even if the Terraform binary version doesn't match the pinned target.
*   `-c <category>`: Only run specific categories of mutation operators (e.g. `security`, `logic`, `variables`, `tags`).

---

## 📊 Mutation Operators

Oasis runs 12 mutations divided into four categories:

| Operator ID | Category | Description | Target Surface |
|---|---|---|---|
| **MUT-VAR-001** | Variables | Deletes default values from variables | `variable.default` |
| **MUT-VAR-002** | Variables | Replaces variable default values with empty values | `variable.default` |
| **MUT-LGC-001** | Logic | Swaps boolean logic values (`true` $\leftrightarrow$ `false`) | Logical values |
| **MUT-LGC-002** | Logic | Deletes explicit resource dependencies | `depends_on` |
| **MUT-LGC-003** | Logic | Swaps count conditions (`count = 0` $\leftrightarrow$ `count = 1`) | Resource `count` |
| **MUT-LGC-004** | Logic | Inverts conditional ternary expressions | Ternary operators |
| **MUT-SEC-001** | Security | Swaps private ACL values to public-read | S3 / resource ACLs |
| **MUT-SEC-002** | Security | Disables encryption-at-rest keys/parameters | Encryption settings |
| **MUT-SEC-003** | Security | Deletes security group ingress rules | Security ingress blocks |
| **MUT-SEC-004** | Security | Alters lifecycle/prevent_destroy rules | Lifecycle configurations |
| **MUT-TAG-001** | Tags | Swaps string values inside tags/labels | Tag value pairs |
| **MUT-TAG-002** | Tags | Changes casing of tag names (e.g., key casing) | Tag keys |

---

## 📈 Understanding Results

The output of `oasis run` is a structured CSV file (`results.csv`) containing the evaluation of every mutant. The key metric is the **Mutation Score**:

$$\text{Mutation Score} = \frac{\text{Killed Mutants}}{\text{Scored Mutants}} \times 100\%$$

Each row in the report contains:
*   `module_path`: Target test module path.
*   `file_path`: Mutated source configuration file.
*   `operator_id`: Applied mutation operator.
*   `outcome`: Classification outcome of the test run:
    *   `killed_assert`: Test suite caught the change via an assertion failure.
    *   `killed_error`: Test suite crashed during execution (e.g., invalid state, cloud error).
    *   `survived`: Test suite completed successfully (the mutation went unnoticed).
    *   `baseline_fail`: The base module failed to run before mutations were applied.
*   `survival_reason`: Explains the structural failure of the assertions if the outcome is `survived`.

---

## 🔄 Self-Update & Uninstall

Oasis makes maintenance easy with built-in commands:

*   **Check and Install Updates**:
    ```bash
    oasis update
    ```
    This fetches release assets directly from GitHub, checks for new versions, and runs the matching native package installer for your operating system.

*   **Clean Uninstall**:
    ```bash
    oasis uninstall
    ```
    This removes the binary globally from `/usr/local/bin` and cleans up associated package manager registry details (like `dpkg` configurations on Linux).

---

## 📄 License

Oasis is released under the permissive [MIT License](./LICENSE). Copyright (c) 2026 Tushar Teotia.
