"""Run the full Phase 5 batch across every repo under corpus/.

Usage:
    uv run python scripts/run_batch.py

Resumable: safe to Ctrl-C and re-run -- any repo that already has a CSV in batch_results/
is skipped, not re-processed. A failing repo is logged to batch_results/<repo>.log and does
not stop the batch (see orchestrator.py / PHASE5_NOTES.md).
"""

import logging
from pathlib import Path

from tfmutate import orchestrator

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus"
OUTPUT_DIR = REPO_ROOT / "batch_results"
PLUGIN_CACHE = Path.home() / ".cache" / "tfmutate" / "plugins"

# Repos whose test suite is written for OpenTofu, not Terraform (they use `tofu test`, and
# running `terraform test` against them fails outright with "unknown provider" -- Terraform
# and OpenTofu maintain separate provider/lock state, so this is a genuine engine mismatch,
# not a flaky error. See PHASE5_NOTES.md.
TOFU_REPOS = {"tofu-modules"}


def main() -> None:
    repos = sorted(p for p in CORPUS_DIR.iterdir() if p.is_dir())
    print(f"batch of {len(repos)} repos:")
    for r in repos:
        print(f"  {r.name}{'  [tofu]' if r.name in TOFU_REPOS else ''}")

    PLUGIN_CACHE.mkdir(parents=True, exist_ok=True)

    tofu_repos = [r for r in repos if r.name in TOFU_REPOS]
    tf_repos = [r for r in repos if r.name not in TOFU_REPOS]

    results = orchestrator.run_batch(
        tf_repos, OUTPUT_DIR,
        test_cmd="terraform test", timeout=90, plugin_cache_dir=PLUGIN_CACHE,
    )
    if tofu_repos:
        results += orchestrator.run_batch(
            tofu_repos, OUTPUT_DIR,
            test_cmd="tofu test", timeout=90, plugin_cache_dir=PLUGIN_CACHE,
        )

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  [{r.status:9}] {r.repo:55} n={r.n_mutants:4} {r.reason[:60]}")

    n = orchestrator.aggregate_master_csv(OUTPUT_DIR, OUTPUT_DIR / "master.csv")
    print(f"\nmaster.csv: {n} rows")

    print("\n=== FINAL CLEAN CHECK (every repo) ===")
    clean = orchestrator.verify_all_clean(repos)
    dirty = [name for name, ok in clean.items() if not ok]
    for name, ok in sorted(clean.items()):
        print(f"  {name}: {'CLEAN' if ok else 'DIRTY'}")
    if dirty:
        print(f"\n!!! {len(dirty)} repo(s) NOT clean: {dirty}")
    else:
        print(f"\nAll {len(clean)} repos clean.")


if __name__ == "__main__":
    main()
