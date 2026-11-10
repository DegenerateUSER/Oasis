# Oasis

Mutation testing for Terraform and OpenTofu native test suites. Oasis makes small configuration edits, runs selected tests against each mutant, and separates assertion failures, runtime-error kills, survivors and excluded work. A mutation score measures sensitivity to these injected faults—not runtime coverage, security assurance or general test correctness.

## Paper and research artifacts

- **Final author paper:** [Oasis-humanised-final.pdf](paper/final/Oasis-humanised-final.pdf), including the reviewer response.
- **Unchanged supplied source:** [original ZIP](paper/final/Oasis-humanised-final.zip) and [extracted LaTeX entrypoint](paper/final/source/main.tex). See [paper provenance and build status](paper/README.md) for SHA-256 identities and artifact roles.
- **Missing supplement:** the final manuscript cites Tables S1–S10, but its matching supplement was not supplied. Older supplements are historical, not substitutes.

Two implementations are deliberately separate:

| Tree | Version / catalog | Purpose |
|---|---|---|
| [`src/tfmutate/`](src/tfmutate/) | `0.1.0` / catalog `2`, 12 operators | Maintained product CLI, recovery and local GUI |
| [`research/catalog3/`](research/catalog3/README.md) | `0.3.0-research.1` / catalog `3`, 16 operators | Frozen, hash-identified research source |

Installing the root project installs the product, **not** the paper's catalog-3 snapshot. Both use the Python name `tfmutate`; do not mix their import paths. [Research documentation](research/README.md) explains isolation, processed evidence and reproduction limits.

### Reported results, not a new rerun

The final paper's catalog-3 snapshot reports **1,533 generated mutants**, **1,288 scored** across **47 repositories**: 115 assertion kills, 76 runtime-error kills and 1,097 survivors. Its assertion-detection rate is **8.9%**; the combined mutation score is **14.8%**. The other 245 generated cases are excluded. These figures come from [frozen processed evidence](research/evidence/catalog3-study/summary.json), whose original interim/submission-readiness flags remain unchanged; they do not establish completion of the full 95-repository plan.

Keep primary catalog-3, historical catalog-2 and matched-strengthening results separate. The convenience sample, historically adapted sources and operator mix limit generalization. The [old pilot report](benchmarks/report_draft.md) is historical, not the main result. No corpus experiments were rerun for this publication preparation.

## Install the product from source

Requires Python 3.10+ and `uv`. From the repository root:

```sh
uv sync --locked
uv run oasis --version
```

Terraform or OpenTofu must be separately available to execute native commands; provider dependencies and engine version pins belong to the target repository. This documentation does not assert that release binaries or native installers were rebuilt or verified for this source revision.

## Local browser workspace

```sh
uv run oasis gui
# Optional: keep the browser closed and choose the local port
uv run oasis gui --no-open --port 8765
```

The GUI provides CSV exploration/import/export and bounded local jobs. It is **loopback-only, for one trusted local user**, not public hosting. Compiled frontend assets are present in the product source tree; normal use does not require Node. Source asset builds, provenance labels, platform limits and cancellation details are in the [GUI guide](Docs/GUI.md). Historical/imported CSVs are not verified reruns merely because they appear in the GUI.

## Preview and run

```sh
# Read-only source preview; the CLI may invoke the engine's fmt check
uv run oasis preview /path/to/trusted-module

# Use a clean, committed target and keep output outside it
uv run oasis run /path/to/trusted-repo \
  --output /path/outside-target/results.csv \
  --max-mutants 3 --budget-seconds 60 \
  --timeout 30 --init-timeout 30 --init-attempts 1
```

For OpenTofu, use `--fmt-cmd tofu` with `preview`, and `--test-cmd "tofu test"` with `run`. Select one exact operator using `--operator`, or categories using `--category security resource compliance`; the two filters are mutually exclusive. See `uv run oasis run --help` for the actual options. The CLI defaults to a 120-second repository budget but has no default mutant-count cap; set an explicit cap for small runs.

**Trusted repositories only:** tests and providers can execute local code, read environment credentials, contact networks and create cloud resources. Oasis is not a sandbox. Prefer mocked or plan-only fixtures, review the target first, and do not edit it or run competing tools during a job. Budget/cancellation handling allows source cleanup; it is not a guarantee of instantaneous termination.

Execution uses baseline and validation gates, then test classification and owned-source restoration. Restoration is not guaranteed after SIGKILL, power loss or machine failure: inspect an interrupted target before reuse. Native GUI execution currently targets POSIX/macOS, not Windows. See [safety and development checks](Docs/DEVELOPMENT_CHECKS.md).

## Operators and scores

The product's authoritative catalog is [`src/tfmutate/mutators.py`](src/tfmutate/mutators.py). Catalog 2 covers scoped ACL/encryption/public-access/CIDR edits, instance sizing and provisioning counts, environment values and required-tag deletion. Categories are `security`, `resource` and `compliance`. Operators target eligible literals on specific surfaces; this is not an arbitrary-expression or dependency-deletion engine. Research catalog 3 adds four families and changes binding/deduplication behavior; old CSVs are not interchangeable with new catalogs.

Only mutant records with `killed_assert`, `killed_error` or `survived` enter the scored denominator:

```text
N = assertion kills + runtime-error kills + survivors
assertion score = assertion kills / N
mutation score = (assertion kills + runtime-error kills) / N
```

A zero denominator means no score. Baseline records, invalid mutants, no-ops, timeouts, unresolved/unexecuted cases and unknown errors are not scored. Runtime-error kills are not evidence of a successful test assertion. Static survivor explanations are not runtime coverage, and specific no-op checks do not solve general semantic equivalence. See [shared score accounting](src/tfmutate/metrics.py).

## Bounded development checks

```sh
uv run python scripts/quick_check.py
# Narrower loop
uv run python scripts/quick_check.py tests/test_runner_safety.py tests/test_scope.py
```

The helper enforces a maximum 120-second test budget and does not launch the benchmark corpus. Provider-download tests are opt-in. Commands here are instructions, not claims that these checks ran during documentation preparation. See [development checks](Docs/DEVELOPMENT_CHECKS.md) for tiny real-engine fixtures and offline dataset auditing, and [CONTRIBUTING.md](CONTRIBUTING.md) for contributions.

## License and notices

Oasis software is under the [MIT License](LICENSE), copyright © 2026 Tushar Teotia. This does **not** relicense author manuscripts, third-party templates, publisher logos/artwork or upstream corpus material. Preserve their supplied notices and applicable licenses; public availability is not redistribution clearance. Local preparation is not a claim of publisher acceptance or external publication.
