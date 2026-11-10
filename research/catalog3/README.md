# Catalog-3 research source snapshot

**Tool `0.3.0-research.1` · catalog `3` · 16 operators.** This is the frozen implementation associated with the [final author paper](../../paper/final/Oasis-humanised-final.pdf), not the maintained product in [`../../src/tfmutate/`](../../src/tfmutate/) (`0.1.0`, catalog `2`, 12 operators).

## Exact snapshot boundary

[`catalog3-freeze.json`](catalog3-freeze.json) lists **22 Python files** and their SHA-256 identities. Each `code_sha256` key is relative to [`src/tfmutate/`](src/tfmutate/), including six `gui/` Python modules. Those listed source bytes define the frozen snapshot; this README and metadata are outside that hashed source set. Do not modify the implementation to make it resemble the root product or silently regenerate evidence with a different catalog.

The four additions to the retained twelve operators are:

| Operator | Frozen transformation |
|---|---|
| `MUT-CFG-001` | Configuration boolean literal inversion, including eligible module inputs and scalar defaults; not an inferred security classification |
| `MUT-RES-004` | Positive curated provisioning capacity/count literals to zero |
| `MUT-SEC-005` | Eligible EC2/launch-template IMDS `http_tokens`: `required` to `optional` |
| `MUT-SEC-006` | EFS/Redshift encryption `true` to `false`, separate from legacy `MUT-SEC-002` |

See the [actual catalog](src/tfmutate/mutators.py) and freeze metadata for exact scopes, exclusions and deduplication. Catalog 3 also changes selected-run caller/default binding analysis. Potential default reachability is not runtime coverage. Identical edits are deduplicated with earlier specialized operators retaining attribution. The retained-twelve results inside catalog 3 are a within-version split, not a historical catalog-2 rerun.

## Avoid importing the product by accident

Both implementations are named **`tfmutate`**. Root `uv sync`, root `oasis` entrypoints, an editable product install or a combined `PYTHONPATH` can select the wrong code. Use a separate interpreter environment with compatible dependencies already prepared, no installed product package, and only the frozen source path on `PYTHONPATH`. Run from a neutral directory, not either source tree. Do not use Python `-I` with this approach: it ignores `PYTHONPATH`.

The following is a **documentation example, not a command run during publication preparation**. It only checks module resolution/version/catalog metadata; it does not execute Terraform, tests, mutations or a GUI. Replace both absolute paths with your own locations:

```sh
REPO="/absolute/path/to/Oasis"
RESEARCH_PYTHON="/absolute/path/to/research-venv/bin/python"
(
  cd "$HOME" || exit 1
  env -u PYTHONHOME PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$REPO/research/catalog3/src" \
    "$RESEARCH_PYTHON" -s -c '
import os
from pathlib import Path
import tfmutate
from tfmutate import mutators
expected = Path(os.environ["PYTHONPATH"]).resolve() / "tfmutate"
assert Path(tfmutate.__file__).resolve() == expected / "__init__.py"
assert Path(mutators.__file__).resolve() == expected / "mutators.py"
assert tfmutate.__version__ == "0.3.0-research.1"
assert mutators.CATALOG_VERSION == "3"
assert len(mutators.CATALOG) == 16
print(Path(tfmutate.__file__).resolve())
print(tfmutate.__version__, mutators.CATALOG_VERSION, len(mutators.CATALOG))
'
)
```

Resolving the expected modules is necessary but **not** a source-hash verification or a reproduction of the study. Independently compare all 22 listed source hashes against the freeze before any research execution. Any actual rerun additionally needs the original inputs, test selection, engine/provider locks and source policy; import success does not supply them.

## What is not bundled

This directory has no standalone `pyproject.toml`, lockfile or compiled GUI static assets. The frozen GUI Python files are included because they belong to the recorded hash set, not because a standalone research GUI is packaged. Do not run `pip install research/catalog3` or assume the root install supplies its research version. The root product GUI assets are not a substitute for missing research assets.

The [research evidence guide](../README.md) distinguishes the primary catalog-3 campaign, historical catalog-2 data, matched 123-case strengthening and the earlier pilot. Results are preserved processed data, not new runs. Raw execution archives and caches are excluded; historical reproduction recipes retain nonportable absolute paths and original external-layout dependencies. Historical test counts in the freeze are historical receipts, not validation of this publication worktree.

The unchanged [final paper/source provenance](../../paper/README.md) also records a publication blocker: **no matching final Tables S1–S10 supplement was supplied**. Older supplements must not be substituted. Preserve author and third-party notices; the root MIT license does not automatically relicense manuscripts, templates, logos or corpus material.
