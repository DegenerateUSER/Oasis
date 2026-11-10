# Oasis — manuscript and reviewer-response revision

Frozen completed-archive snapshot: 9 November 2026. Paper ID1352.

## Deliverables
- manuscript.pdf / manuscript.tex: revised article.
- reviewer-letter.pdf / reviewer-letter.tex: cover letter and all14 verbatim reviewer comments with responses and manuscript section/table/page references.
- 1352_revised_version.pdf / .tex: manuscript followed by identical response content.
- repository-supplement.pdf / .tex: all62 completed repository attempts.

## Original format
The supplied original PDF is192x262mm, single-column Times. Its original three publisher logo Form XObjects have been extracted directly without copying article text. The original elsarticle/ecrc class, Procedia header, title, five author identities, corresponding-author details, numbered headings, abstract/keywords and bibliography conventions are retained. Geometry is reconstructed from the PDF because original editable source was unavailable. This is the original visual template, not an assertion of pixel-identical line/page breaks after substantial content changes. Header year2026 and page span are compilation metadata; publisher-controlled year/volume/frontmatter require confirmation. Legal/template language is not a claim of publisher acceptance.

## Build
Install Tectonic (free) or use an existing installation. From this directory:

```
tectonic --keep-logs --keep-intermediates manuscript.tex
tectonic --keep-logs --keep-intermediates reviewer-letter.tex
tectonic --keep-logs --keep-intermediates 1352_revised_version.tex
tectonic --keep-logs --keep-intermediates repository-supplement.tex
```

Build manuscript first: the standalone letter imports manuscript.aux via xr, so its references point to manuscript pages. All required article figures/branding/table/reference inputs are local. Tectonic may fetch free TeX packages on first build. No API key or paid service is required. Do not use integrate_and_build.py to rebuild a portable package; that local provenance helper depends on original source paths. The commands above are the portable path.

## Evidence boundaries
Current primary catalog3:95 planned identities,62 completed archives,47 scored repositories,1,288 scored cases;115 assertion kills,76 runtime kills,1,097 survivors.245 generated exclusions remain explicit.39 scored repositories pass every selected baseline;8 are partial. Fifteen archived attempts yield no scored cases;3 preparation failures,1 in-progress identity and29 unstarted identities do not contribute primary outcomes. n8n remains excluded at the frozen snapshot. Historical catalog2, the123-case matched comparison and historical tfsec results are separate studies, not a pooled69-repository mutation score. The matched intervention is assertions PLUS input/positive-control strengthening, not an assertion-only effect. Generic Boolean edits dominate89.1% of scored primary cases.

CSV/JSON arithmetic and timing quantiles were checked against frozen exports. Saved scanner receipts and scholarly DOI metadata were inspected. This manuscript preparation did not rerun native Terraform/OpenTofu or scanner experiments. Full raw archives remain on local/external storage; the source/evidence ZIP is not a self-contained native-experiment reproduction environment and creates no public DOI/deposit. Historical pathnames in evidence may reference cold-storage originals.

## Before submission
1. Obtain the committee-required authenticated similarity report (threshold at most10%); none is supplied or claimed.
2. Confirm final page limit. The expanded manuscript/letter are not claimed to satisfy an unspecified venue length limit.
3. All coauthors must verify source/evidence interpretation, affiliations/contact details, AI-assistance declaration, ethical/submission statements and publisher-controlled frontmatter.
4. Arrange permitted reviewer access to raw archives and research revisions; do not imply that a locally retained archive is a public release.
5. Explicitly approve the final version before any upload/email/submission. No external submission has occurred.

## Provenance
Existing Codex manuscript was used as the scientific base, with additional integration, sample/equivalence clarification, capability comparison, real recorded cases, binding illustration, historical scanner examples, concentration limitations and AI disclosure. Inputs and original research/code repositories were not modified. original-format-provenance.json records direct logo extraction; evidence-freeze.json records copied source hashes. reference-check.json records16 resolved scholarly DOI registrations (not an assertion that registration metadata alone validates every cited claim).
