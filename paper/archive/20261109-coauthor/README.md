# Oasis — coauthor-review and similarity-screening version

Paper ID **1352**. Research snapshot: **9 November 2026**. This version integrates the supplied Ribeiro & Neves primary paper and aligns the reviewer responses. It supersedes the earlier polished paper for this review cycle; earlier files remain preserved separately.

## Which file to use

- **`manuscript.pdf`**: standalone research article. Use this for coauthor reading and manuscript-only similarity screening, subject to your institution/venue's required settings.
- **`reviewer-letter.pdf`**: cover letter plus all 14 original reviewer comments and point-by-point responses. Page references point to the manuscript.
- **`1352_revised_version.pdf`**: manuscript followed by the same response text, for the committee's combined-file requirement after author approval.
- **`repository-supplement.pdf`**: all 62 completed repository attempts and bounded historical adaptation/source-to-oracle evidence.

The reviewer letter quotes the reviewers by design. Keep it separate when requesting a manuscript-only similarity report unless the venue explicitly requires screening the combined file. The separately supplied published reference PDF is supporting literature, NOT part of the manuscript to screen. No similarity service has been contacted, no similarity percentage is promised, and no content has been omitted or disguised to manipulate a score.

## Editable sources and build

`manuscript.tex`, `reviewer-letter.tex`, `1352_revised_version.tex` and `repository-supplement.tex` are the entry points. `reviewer-response.tex` is shared by the standalone/combined responses. Keep all supplied `.tex`, `.cls`, `.sty` and logo assets together.

With Tectonic installed, run in the extracted `oasis-paper/` folder:

```
tectonic --keep-logs --keep-intermediates manuscript.tex
tectonic --keep-logs --keep-intermediates reviewer-letter.tex
tectonic --keep-logs --keep-intermediates 1352_revised_version.tex
tectonic --keep-logs --keep-intermediates repository-supplement.tex
```

Build the article first: the standalone letter imports its section/table/page labels from `manuscript.aux`. A first build may fetch free TeX packages. No paid API or research/cloud credentials are needed. No superseded manuscript/table regeneration scripts are included.

## What changed for this version

1. Adds Ribeiro & Neves (2026), DOI `10.5753/reic.2026.8471`, from the complete supplied primary PDF. Accurately acknowledges Terramutate's reference-project test execution instead of claiming that no earlier Terraform mutation tool existed.
2. Adds a **16-identifier source-level mapping**, distinguishing direct transformations, partial correspondence and generic motivation. Numeric-to-zero/one is not mislabeled as the same operator as general ±1. Default changes and module arguments have distinct prior variants. Uncovered families are explicit.
3. Connects recorded survivors and scanner findings to prior misconfiguration research without conflating policy findings, deployed vulnerabilities, unavailable scanner runs or equivalence.
4. Updates the novelty, fault-model and survivor responses, with automatic manuscript locations; retains all original reviewer comments.
5. Includes Claude's literature assistance in the AI declaration. No claim of completed coauthor review is made.

## Evidence and unchanged results

Catalog 3 remains **1,533 generated / 1,288 scored / 245 excluded cases** from 62 completed attempts, with 47 scored repositories. The 1,288 scored outcomes are 115 assertion kills, 76 runtime-error kills and 1,097 survivors. All current/historical CSV/JSON records and focused native evidence remain unchanged from the prior revision. The 123-case strengthening study and historical scanner study have separate denominators. No new Terraform/OpenTofu/scanner experiments were run for this revision.

The new mapping is analytical literature evidence, not a measured real-bug coupling study. An OpenTofu-specific semantic operator was NOT evaluated; R3.2 remains explicitly partially addressed. Historical applied adaptation counts remain unknown where records are missing. These are disclosed study boundaries, not experiments that the prose claims to have completed.

The source ZIP contains build inputs, mapping/provenance metadata and documentation. The larger evidence ZIP adds the frozen processed studies, focused source/log evidence and the supplied CC BY 4.0 Ribeiro & Neves PDF, unchanged with attribution. It does not include complete native archives, provider binaries, credentials, personal chat exports or the paused research prototype. Original native archives remain separately retained; no new public deposit or DOI is claimed.

## Format and author handoff

The 192 × 262 mm single-column Times/Procedia reconstruction, original logo objects and shared formatting are preserved. Original editable source was unavailable, so this is not a pixel-identical guarantee. The authors handle similarity screening, venue length/frontmatter, author/affiliation/contact/funding details, AI declaration approval and evidence access, as agreed. No upload, email or submission has been made.
