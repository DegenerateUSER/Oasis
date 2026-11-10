# Oasis paper

## Author-designated final revision

The authors supplied these files on 10 November 2026. They are preserved unchanged:

- [`final/Oasis-humanised-final.pdf`](final/Oasis-humanised-final.pdf): final author PDF, manuscript plus reviewer response.
- [`final/Oasis-humanised-final.zip`](final/Oasis-humanised-final.zip): original editable-source archive.
- [`final/source/main.tex`](final/source/main.tex): extracted source entrypoint. This includes `references.tex` and `reviewer-response.tex`; the response fragment is not a standalone document.

SHA-256 identities:

```text
ab2a43b57b4084228172cb89c5e6af1dda6d0e38554dedd0af19b1a8a09dc5d3  Oasis-humanised-final.pdf
749cb6e73ccae789626e6b2c95840e1f5592e49d1b62c7191019632f7f620792  Oasis-humanised-final.zip
```

The supplied ZIP contains nine local source/template/logo assets. A TeX installation and the additional packages named in `main.tex` are required. The exact extracted source compiled successfully with Tectonic in untrusted mode during publication preparation, after downloading missing standard `fleqn.sty`/`fleqn.clo` dependencies. The build reports overfull/underfull box warnings and produces **15 pages**, versus **14 pages** in the supplied author PDF; it is therefore not a layout-identical reconstruction. The supplied PDF remains authoritative and has not been replaced by the locally generated PDF.

**Supplement boundary:** the final manuscript refers to Tables S1–S10, but no matching supplement was supplied in this ZIP. Older supplements in `archive/` must not be described as the matching final supplement without checking their table numbering and content.

## Historical drafts

`archive/` contains dated earlier revision artifacts. These are superseded, not the current paper. Their document-check receipts describe their own versions, not this author-supplied final revision. This is a curated subset: the earlier coauthor full-evidence ZIP is withheld because it contains a third-party full-text paper whose redistribution rights were not established. Its author-source-only ZIP and the allowlisted processed evidence are preserved separately. Historical checksum/package manifests describe their original complete deliveries; the publication manifest describes the actual public subset.

## Code and evidence boundary

The root product is the recovery/GUI implementation based on commit `d535bee1ef9bb1f62c9c258dd67ead715ba826b3`. The frozen catalog-3 research implementation is separately preserved in `../research/catalog3/`; installing the root product does not install that research snapshot. The paper's primary catalog-3 study, the historical catalog-2 study and the matched strengthening study are separate datasets and must not be pooled.

Processed evidence is under `../research/evidence/`. Complete native execution archives, private session exports, credential files, provider caches and the paused research-extension prototype are not part of this publication candidate. No new corpus experiments were performed for this packaging work.

## Rights and publication status

The software MIT license does not automatically relicense author manuscripts, third-party templates or publisher artwork. Preserve the notices supplied with those assets. Local preparation is not a claim of publisher acceptance, redistribution clearance, external publication or push approval.
