# Oasis — scientifically polished revision

Paper ID: 1352. Completed-archive reporting snapshot: **9 November 2026**.

## Files and entry points
- `manuscript.tex` / `manuscript.pdf`: revised research article.
- `reviewer-response.tex`: shared cover-letter and 14-comment response content.
- `reviewer-letter.tex` / `reviewer-letter.pdf`: standalone letter, with manuscript page references.
- `1352_revised_version.tex` / `1352_revised_version.pdf`: manuscript followed by the identical response text, as requested by the committee.
- `repository-supplement.tex` / `.pdf`: all 62 completed repository attempts, bounded historical adaptation accounting and native worked-example provenance.

Keep the supplied files together. Main files load shared formatting, table and bibliography inputs.

## Portable build
With Tectonic installed, run from the extracted source directory:

```
tectonic --keep-logs --keep-intermediates manuscript.tex
tectonic --keep-logs --keep-intermediates reviewer-letter.tex
tectonic --keep-logs --keep-intermediates 1352_revised_version.tex
tectonic --keep-logs --keep-intermediates repository-supplement.tex
```

Build the manuscript first: the standalone letter imports `manuscript.aux` for section/table/page references. All figure, branding, class/style, table and bibliography inputs are local. A first build may download free TeX packages; no API key or paid service is required. Do not use old `integrate_and_build.py`, `generate_tables.py` or `package_deliverables.py` helpers to regenerate this polish: they belong to the superseded preparation stage and can overwrite later edits. They are not part of the portable submission source.

## What this polish changes
1. States a bounded native-suite integration/evidence contribution rather than claiming mutation testing or operator count as novelty.
2. Documents the actual frozen root/nested caller-binding rules, conservative exceptions, and active-first/all-shadowed aggregation. It does not claim general semantic equivalence or dynamic coverage.
3. Explains a genuine Equinor default → planned resource → existing assertion → native diagnostic chain, with hash-verified source/log evidence.
4. Adds an explicit fault-model/contract mapping without claiming representative real-fault validation.
5. Discloses historical assertion repairs and constant-assertion removal. A 23-repository adaptation ledger distinguishes manifest-verified final files, recipe-only information and unavailable applied ledgers; unknown is not zero.
6. Reports both assertion-only and combined per-operator rates, names actual case fields, improves retrospective prose and corrects technical spacing.
7. Fixes the old title-header box allocation without changing fonts, margins or artwork scaling; regression checks confirm preserved global header text positions.
8. Aligns the reviewer letter with implemented changes and explicitly retains partial fulfillment of the OpenTofu-specific-operator request.

## Results are unchanged
Primary catalog 3: **95 planned identities; 62 completed archives; 47 scored repositories; 1,288 scored cases = 115 assertion kills + 76 runtime-error kills + 1,097 survivors**. There are 245 generated exclusions. Among scored repositories, 39 pass every selected baseline and eight retain blocked scopes. Fifteen completed attempts yield no scored cases; three failed preparations, one in-progress identity and 29 unstarted identities contribute no primary results at the frozen snapshot. n8n remains excluded in this reporting snapshot, regardless of any later live campaign state.

The 1,288 cases contain 1,049 distinct repository-qualified edit identities; repeated selected scopes are not independent real defects. Generic Boolean inversion supplies 89.1% of scored cases. Historical catalog 2, the 123-case matched study and the historical tfsec comparison remain separate, not a pooled 69-repository mutation score. Matched strengthening includes assertions AND input/positive-control expansion, with concentrated gains—not an assertion-only causal result.

No native Terraform/OpenTofu/scanner experiments were run during this manuscript polish. Builds and CSV/receipt/hash checks do not independently reproduce the research.

## Evidence and package scope
`polish-evidence/worked-example-evidence.json` retains verified Equinor native diagnostic/summary/binding records and member hashes. Selected original source/test files, five hash-matched frozen implementation files, seven manifest-matched historical source samples and named historical recipes accompany the processed evidence. Recipe availability alone is not proof every conditional adaptation ran. Complete per-category historical change totals remain unknown.

The source-only ZIP contains editable LaTeX, required assets and this focused proof material. The larger source/evidence ZIP additionally contains the frozen current/historical CSV/JSON exports and historical scanner supplement. Neither is a full native-experiment environment: complete raw archives remain on local/external storage. Reviewer access must be arranged; no public deposit, new DOI or newly published research commit is claimed. No credential files or provider binaries are included.

## Format
The original PDF uses a **192 × 262 mm**, single-column Times/Procedia layout. Original publisher logo objects and the retained `elsarticle`/`ecrc` assets are used. Geometry was reconstructed because the original editable source was unavailable; this is not a pixel-identical line/page-break guarantee or certification of current venue rules. Header year/volume, copyright/licensing text and final author details remain publisher/author confirmation items.

## Human submission checks — still required
- Obtain the committee-required authenticated similarity report (at most 10%); none is supplied or certified.
- Confirm the permitted final length, publisher-controlled frontmatter and template rules.
- Obtain coauthor review of the research interpretation, contact/affiliation details and AI-assistance declaration. No completed review is falsely asserted.
- Confirm funding declarations if the venue requires them; an unsupported blanket no-grant statement has been removed rather than guessed.
- Arrange reviewer access to full native evidence, confirm repository/research revisions and approve the exact final file version.

No acknowledgment email, upload or submission has been performed. Acceptance and complete fulfillment of the unperformed real-fault/OpenTofu extensions cannot be guaranteed by editing.
