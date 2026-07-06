# Oasis Benchmarks

This directory contains the complete raw outputs from the empirical pilot study run against a curated corpus of 23 real-world public Terraform repositories.

## What is in This Directory

| File/Directory | Description |
|---|---|
| `batch_results/master.csv` | Combined evaluation dataset — 242 rows, 177 scored mutants |
| `batch_results/<repo>.csv` | Per-repository raw mutation results |
| `batch_results.log` | Batch orchestrator run log (skips, errors, timestamps) |
| `report_draft.md` | Full empirical evaluation report with analysis, findings, and discussion |

## Corpus — Repositories Tested

23 repositories were selected from GitHub's public Terraform ecosystem using a rubric requiring: ≥1 `.tftest.hcl` test file, real resource definitions (not stubs), no cloud credentials required at validate time, and a passing green baseline on at least one test module.

| Repository | Source |
|---|---|
| `aws-platform-starter` | github.com |
| `aws-terraform-infrastructure` | github.com |
| `cloud-native-deployment-platform` | github.com |
| `conf-data-processing-architecture-reference` | github.com |
| `eks-vulnerable-infra` | github.com |
| `genai-idp-terraform` | github.com |
| `platform-design` | github.com |
| `platform-tools` | github.com |
| `psoxy` | github.com |
| `server-terraform` | github.com |
| `serverless-architecture-patterns` | github.com |
| `terraform-aws-compliance` | github.com |
| `terraform-aws-lb` | github.com |
| `terraform-aws-oidc-github` | github.com |
| `terraform-aws-security-group` | github.com |
| `terraform-aws-sonarqube` | github.com |
| `terraform-aws-static-site` | github.com |
| `terraform-aws-vpc` | github.com |
| `terraform-datadog-users` | github.com |
| `terraform-duplocloud-components` | github.com |
| `terraform-mongodbatlas-project` | github.com |
| `terraform-postgres-config-dbs-users-roles` | github.com |
| `tofu-modules` | github.com |

## How to Reproduce This Run

> **Prerequisites**: `terraform >= 1.5`, `git`, and Oasis installed (`oasis --help`).

```bash
# 1. Clone this repository
git clone https://github.com/DegenerateUSER/Oasis.git
cd Oasis

# 2. Clone the target corpus repos into /corpus
#    (example for one repo — repeat for each)
git clone https://github.com/<org>/<repo-name> corpus/<repo-name>

# 3. Run Oasis against a single repo
oasis run corpus/<repo-name>/ --output benchmarks/batch_results/<repo-name>.csv

# 4. Or run the batch orchestrator across all cloned repos
python scripts/batch_run.py --corpus-dir corpus/ --out-dir benchmarks/batch_results/
```

The `batch_results.log` file in this directory captures the exact run that produced the current dataset, including timestamps and any skipped/already-completed repos.

## Notes on Reproducibility

- **Terraform version**: Results were generated with Terraform `1.15.7`. Mutation scores may differ on other versions because `terraform test` output parsing is version-sensitive. Use `--allow-version-drift` to bypass the version gate if needed.
- **Cloud credentials**: Some repositories that required live cloud credentials to init produced `baseline_fail` rows (61 of the 242 total rows). These are documented in `report_draft.md §5` (Threats to Validity).
- **Architecture baseline failures**: 20 of the 61 baseline failures in `conf-data-processing-architecture-reference` were traced to a subprocess binary compiled for a different CPU architecture on the test machine. These are noted in the report.
