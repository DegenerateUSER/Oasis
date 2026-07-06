# Contributing to Oasis

Thank you for your interest in contributing to Oasis! This is an open-source mutation testing framework for Terraform and OpenTofu Infrastructure-as-Code (IaC). Contributions of all kinds are welcome — bug reports, operator improvements, documentation fixes, and new test coverage.

---

## Filing Issues

Before opening a new issue, please search [existing issues](https://github.com/DegenerateUSER/Oasis/issues) to avoid duplicates.

When filing a bug, please include:
- Your OS and architecture (e.g. macOS 14, Apple Silicon / Ubuntu 22.04, x86_64).
- The Oasis version (`oasis --version`).
- The Terraform / OpenTofu version (`terraform version`).
- The exact command you ran and the full output (including any stack traces).
- The `.tf` file or a minimal reproduction if the bug is operator-specific.

For feature requests or questions, open a [Discussion](https://github.com/DegenerateUSER/Oasis/discussions) rather than an issue.

---

## Running Tests Locally

### Prerequisites

- Python 3.10 or higher
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`
- `terraform` ≥ 1.5 on your `PATH`
- `git`

### Setup

```bash
git clone https://github.com/DegenerateUSER/Oasis.git
cd Oasis

# Install dependencies (uv)
uv sync

# Or with pip in a virtualenv
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Running the Test Suite

```bash
# Run all unit tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_mutators.py
```

The unit tests use lightweight hand-written `.tf` fixtures and do **not** require a live Terraform workspace or cloud credentials.

### Smoke-Testing the CLI

```bash
# Preview mutants for a local .tf file
uv run oasis preview fixtures/phase0/main.tf

# Run the full cycle against the bundled fixture
uv run oasis run fixtures/phase0/
```

---

## What Kinds of Contributions Are Welcome

- **Bug fixes** — especially around operator matching edge cases, HCL parsing, or git state restore logic.
- **New mutation operators** — follow the structure in `src/tfmutate/mutators.py`. Each operator must: produce valid HCL (checked via `terraform fmt`), be scoped to a specific resource surface, and have a corresponding unit test in `tests/`.
- **Classifier improvements** — the `survival_reason` logic in `src/tfmutate/classifier.py` currently covers three categories. Additions that are grounded in observable test output patterns are welcome.
- **Documentation** — typo fixes, clearer examples, or expanded explanations of operator behavior.
- **Corpus expansion** — if you know a public Terraform repository with `terraform test` coverage that would make a good benchmark, open an issue with the URL and we can evaluate it against the corpus rubric.

Please keep pull requests focused — one logical change per PR makes review faster and history cleaner.

---

## Code Style

- Python 3.10+ syntax; type-annotated where non-trivial.
- `ruff` for linting (run `uv run ruff check src/` before submitting).
- No new external runtime dependencies without discussion — the goal is to keep the binary small and the install surface minimal.
