# Frozen research artifacts

This tree preserves the implementation and processed evidence associated with the [final author paper](../paper/final/Oasis-humanised-final.pdf). It is not a replacement for the maintained root product, a newly executed experiment or a complete standalone reproduction package.

## Implementation boundary

| Location | Tool version | Catalog | Role |
|---|---|---|---|
| [`../src/tfmutate/`](../src/tfmutate/) | `0.1.0` | `2`: 12 operators | Product CLI, recovery and GUI; installed by root `pyproject.toml` |
| [`catalog3/src/tfmutate/`](catalog3/src/tfmutate/) | `0.3.0-research.1` | `3`: 16 operators | Frozen research implementation |

[`catalog3/catalog3-freeze.json`](catalog3/catalog3-freeze.json) identifies **exactly 22 Python source files** by relative path and SHA-256, including six GUI Python modules. The paths are relative to `catalog3/src/tfmutate/`. That file set, not every file in this publication tree, defines the code snapshot. The README and freeze metadata are not additional hashed Python sources. Preserve the listed bytes; product fixes must not be silently applied to the research snapshot.

The freeze records four added operators, caller/default binding rules, deduplication and campaign policy. Catalog-3 results from its retained twelve operators are a **within-version subset**, not a fresh catalog-2 rerun. See [snapshot use and import isolation](catalog3/README.md) before loading it: both implementations have the same `tfmutate` module name.

## Evidence map and study distinctions

All results below are frozen data, not rerun results from publication preparation.

| Artifact | Meaning / boundary |
|---|---|
| [`evidence/catalog3-study/`](evidence/catalog3-study/) | Primary catalog-3 campaign: processed mutant rows, scopes, command events, repository dispositions and archived integrity summaries |
| [`evidence/historical-expanded-study/`](evidence/historical-expanded-study/) | Historical catalog-2 expansion data, separate from the primary campaign and from the original pilot |
| [`evidence/historical-paired-study/`](evidence/historical-paired-study/) | Matched strengthening: the same 123 cases scored in both original and strengthened arms; not an independent primary sample |
| [`../benchmarks/`](../benchmarks/) | Earlier pilot artifacts; not the final paper's main result |
| [`evidence/polish-evidence/`](evidence/polish-evidence/) | Source-policy/adaptation records, selected source examples, historical recipes and a partial frozen-code cross-check; not the complete catalog-3 implementation |
| [`evidence/repository-provenance.csv`](evidence/repository-provenance.csv) | Upstream identity and provenance records |
| [`evidence/table-verification.json`](evidence/table-verification.json), [`evidence/selected-cases.json`](evidence/selected-cases.json) | Preserved processed-table checks and selected examples, not new native executions |

The [catalog-3 summary](evidence/catalog3-study/summary.json) reports 1,533 generated cases: 1,288 scored (115 assertion kills, 76 runtime-error kills, 1,097 survivors) and 245 excluded (193 no-ops, 39 unresolved contexts, 13 timeouts). Its reported rates are 8.9% assertion detection and 14.8% combined kills. There are 62 archived repository attempts and 47 scored repositories from a 95-repository plan; blocked scopes do not imply known numbers of ungenerated mutants.

**Status caveat:** the preserved summary still says `interim_pending_final_authorized_repositories` and `submission_ready: false`. The final author manuscript uses the completed archived subset at the 9 November 2026 cutoff. Neither the manuscript designation nor these documentation changes turn unrun, in-flight, cancelled or blocked work into completed experiments. Consult [`all95-dispositions.csv`](evidence/catalog3-study/all95-dispositions.csv) and the original status fields rather than assuming the entire plan finished.

The final manuscript separately describes the historical original catalog-2 study (299 generated / 276 scored) and the matched-strengthening comparison. The matched [summary](evidence/historical-paired-study/summary.json) records assertion kills increasing from 39 to 73 among 123 pairs; additional runs change input exposure, so the gain is not attributable to assertions alone. Do not pool these denominators with catalog 3, concatenate original and strengthened arms as independent cases, or confuse the older pilot with the final historical comparison.

The [version-separated identity audit](evidence/catalog3-study/analysis/version-separated-identities.json) reports a deduplicated cross-version union of 69 scored repository identities. That is an identity count, **not** a pooled mutation-score denominator. Historically adapted original-study sources remain a distinct cohort; absence of new assertion changes in catalog 3 does not mean all sources were untouched upstream originals. Known adaptations are documented, but complete historical adaptation records are not available for every repository.

## Preservation and reproduction limits

- [`evidence/evidence-freeze.json`](evidence/evidence-freeze.json) is the original submission-source inventory with a snapshot timestamp, source path, sizes and hashes. Its paths describe that original package: it is not an inventory asserting that every listed file is present under this directory. Paper/archive placement and excluded assets must be considered separately.
- CSV exports and summaries are processed evidence. Publication exports may replace campaign-local paths with `[campaign-root]`; remaining absolute paths in metadata/recipes are provenance, not portable locations or instructions to access this machine.
- Full native execution archives, original raw-log/source archives, provider caches, credentials and private session exports are **excluded**. Archived integrity claims are preserved reports, not proof that a fresh reader can re-audit omitted archive bytes from this checkout.
- [`reproduction/`](reproduction/) contains historical analysis/packaging recipes. They retain absolute workstation/volume paths, original `framework-v3`/control layouts and external-archive requirements. They are not drop-in commands for this tree; some write derived files. Inspect and adapt them in a separate workspace before use, and do not overwrite frozen evidence.
- The catalog-3 snapshot has no standalone packaging metadata or compiled GUI assets here. Root installation does not package it; do not claim a standalone research install or a working research GUI. See its [README](catalog3/README.md) for an import-check example that does not run native experiments.
- Reported exclusions, static binding reachability and survivor explanations are not runtime coverage or general mutant-equivalence proofs. The sample and dominant boolean-operator share limit generalization.

## Paper and rights

The [paper README](../paper/README.md) identifies the unchanged supplied final PDF, original editable-source ZIP, extracted LaTeX and historical drafts. **The matching final S1–S10 supplement is missing.** Older archived supplements have not been substituted or relabeled as final; claims referring to those final supplementary tables remain limited by that missing artifact.

The root [MIT license](../LICENSE) covers Oasis software; it does not automatically relicense manuscripts, third-party templates/logos or upstream corpus extracts. Preserve supplied notices and upstream terms. This local artifact preparation is not publisher acceptance, redistribution clearance or external publication.
