"""Explicitly scoped, bounded batch execution. Never runs the full corpus by default."""
import argparse
import logging
from pathlib import Path

from tfmutate import orchestrator

REPO_ROOT = Path(__file__).resolve().parent.parent
TOFU_REPOS = {"tofu-modules"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", help="one explicit repository name; repeat to select more")
    parser.add_argument("--confirm-full-corpus", action="store_true", help="explicitly authorize every repository under --corpus-dir")
    parser.add_argument("--corpus-dir", type=Path, default=REPO_ROOT / "corpus")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "batch_results")
    parser.add_argument("--plugin-cache-dir", type=Path, default=Path.home() / ".cache" / "tfmutate" / "plugins")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--budget-seconds", type=float, default=120)
    parser.add_argument("--max-mutants", type=int, default=3)
    args = parser.parse_args(argv)
    if not args.repo and not args.confirm_full_corpus:
        parser.error("choose --repo NAME or explicitly pass --confirm-full-corpus; implicit full-corpus runs are disabled")
    if args.repo and args.confirm_full_corpus:
        parser.error("choose explicit repositories OR the full corpus, not both")
    if min(args.timeout, args.budget_seconds, args.max_mutants) <= 0:
        parser.error("timeouts, budget and mutant limit must be positive")
    if not args.corpus_dir.is_dir():
        parser.error(f"no corpus directory: {args.corpus_dir}")
    if args.repo:
        if any(Path(name).name != name or name in (".", "..") for name in args.repo):
            parser.error("--repo must be a directory name, not a path")
        repos = [args.corpus_dir / name for name in sorted(set(args.repo))]
        if any(not repo.is_dir() for repo in repos):
            parser.error("a selected repository is missing")
    else:
        repos = sorted(p for p in args.corpus_dir.iterdir() if p.is_dir())
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    args.plugin_cache_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for engine, selected in (("terraform", [r for r in repos if r.name not in TOFU_REPOS]),
                             ("tofu", [r for r in repos if r.name in TOFU_REPOS])):
        if selected:
            results.extend(orchestrator.run_batch(selected, args.output_dir,
                test_cmd=f"{engine} test", timeout=args.timeout,
                plugin_cache_dir=args.plugin_cache_dir, budget_seconds=args.budget_seconds,
                max_mutants=args.max_mutants, init_timeout=min(30, args.timeout), init_attempts=1))
    for result in results:
        print(f"[{result.status}] {result.repo}: {result.n_mutants} mutant records {result.reason}")
    count = orchestrator.aggregate_master_csv(args.output_dir, args.output_dir / "master.csv")
    print(f"master.csv: {count} records")
    clean = orchestrator.verify_all_clean(repos)
    return 1 if any(r.status == "failed" for r in results) or not all(clean.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
