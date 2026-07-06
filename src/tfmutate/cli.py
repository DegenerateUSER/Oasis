"""Command-line entry point.

Two commands:
  * ``preview`` -- locate mutation targets and print each mutant as a unified diff (Phase 1).
  * ``run`` -- execute the full mutation cycle over a repo's test modules and write the CSV
    dataset (Phase 2): per module, init -> green-baseline gate -> per-mutant validate/test/
    classify, restoring git state after every cycle. Every SURVIVED mutant is additionally
    given a ``survival_reason`` by the Phase 4 classifier (PROJECT_SPEC.md §8).
"""

from __future__ import annotations

import argparse
import difflib
import logging
import shlex
import sys
from collections import Counter
from pathlib import Path

from . import state
from .classifier import classify_outcomes
from .mutators import CATALOG, CATEGORIES, generate_mutants, select_operators
from .noop import read_tftest_files
from .parser import find_test_module_dirs, is_valid_hcl, read_tf_files
from .reporter import write_csv
from .runner import Runner, check_pinned_version


def _iter_targets(path: Path) -> list[Path]:
    if path.is_dir():
        return read_tf_files(path)
    return [path]


def _preview(args: argparse.Namespace) -> int:
    try:
        operators = select_operators(args.operator, args.category)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2

    total = 0
    skipped = 0
    for tf in _iter_targets(root):
        text = tf.read_text()
        if not is_valid_hcl(text, args.fmt_cmd):
            skipped += 1  # genuine syntax error; logged by is_valid_hcl (SKIPPED_FILE)
            continue
        for mutant in generate_mutants(tf, text, operators):
            total += 1
            resource = mutant.resource_address or "(top-level)"
            print(
                f"\n[{mutant.operator_id}] {tf}:{mutant.line}  "
                f"[{mutant.surface}] {resource} .{mutant.attribute}"
            )
            arrow = "(deleted)" if mutant.is_deletion else repr(mutant.mutated_snippet)
            print(f"    {mutant.original_snippet!r} -> {arrow}")
            print(
                "".join(
                    difflib.unified_diff(
                        text.splitlines(keepends=True),
                        mutant.mutated_text.splitlines(keepends=True),
                        fromfile=f"{tf} (original)",
                        tofile=f"{tf} (mutant {mutant.operator_id})",
                        n=1,
                    )
                )
            )

    print(f"\n[+] {total} mutant(s) generated.")
    if skipped:
        print(f"[!] {skipped} file(s) skipped (failed `{args.fmt_cmd} fmt`; see warnings).")
    return 0


def _run(args: argparse.Namespace) -> int:
    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 2
    root = root.resolve()  # absolute, so paths align with the git repo root

    binary = shlex.split(args.test_cmd)[0]
    try:
        repo_root = state.repo_root_of(root)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    version = check_pinned_version(binary)
    print(f"[{'+' if version.ok else '!'}] {version.message}")
    if not version.ok and not args.allow_version_drift:
        print("Refusing to run on a version drift (pass --allow-version-drift to override).",
              file=sys.stderr)
        return 2

    try:
        operators = select_operators(args.operator, args.category)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    module_dirs = find_test_module_dirs(root)
    if not module_dirs:
        print(f"no .tftest.hcl test modules found under {root}", file=sys.stderr)
        return 1
    print(f"[+] {len(module_dirs)} test module(s) under {root}")

    cache = Path(args.plugin_cache_dir).expanduser()
    cache.mkdir(parents=True, exist_ok=True)  # shared provider cache: offline, deterministic init

    all_outcomes = []
    for md in module_dirs:
        print(f"[+] {md.relative_to(repo_root)} ...", flush=True)
        runner = Runner(
            module_dir=md, repo_root=repo_root, test_cmd=args.test_cmd,
            timeout=args.timeout, operators=operators, plugin_cache_dir=cache,
        )
        outcomes = runner.run_module()
        classify_outcomes(outcomes, read_tftest_files(md))  # fills survival_reason (§8)
        all_outcomes.extend(outcomes)
        tally = Counter(o.test_status for o in outcomes)
        print("    " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))

    n = write_csv(all_outcomes, args.output)
    scored = [o for o in all_outcomes if o.test_status in ("survived", "killed_assert", "killed_error")]
    killed = sum(o.test_status.startswith("killed") for o in scored)
    score = (killed / len(scored) * 100) if scored else 0.0
    print(f"\n[+] {n} row(s) -> {args.output}")
    print(f"[+] Mutation score: {score:.0f}% ({killed}/{len(scored)} killed; "
          f"no_op/invalid/baseline excluded).")

    survived = [o for o in all_outcomes if o.test_status == "survived"]
    if survived:
        reasons = Counter(o.survival_reason for o in survived)
        print(f"[+] Survived-mutant breakdown ({len(survived)} total): "
              + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))

    if not state.is_clean(repo_root):
        print("[!] WARNING: git working tree is not clean after run.", file=sys.stderr)
        return 1
    return 0


def _add_operator_filters(subparser: argparse.ArgumentParser) -> None:
    """--operator (exact ID) and --category (one or more) are mutually exclusive filters,
    per PROJECT_SPEC.md §7: "each operator must be independently toggleable ... per category,
    not just overall"."""
    group = subparser.add_mutually_exclusive_group()
    group.add_argument(
        "-o", "--operator", help=f"limit to one operator (known: {', '.join(CATALOG)})"
    )
    group.add_argument(
        "-c", "--category", nargs="+", choices=CATEGORIES,
        help=f"limit to one or more categories (known: {', '.join(CATEGORIES)})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tfmutate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="show mutants for a .tf file or directory")
    preview.add_argument("target", help="a .tf file or a directory of .tf files")
    _add_operator_filters(preview)
    preview.add_argument(
        "--fmt-cmd", default="terraform",
        help="binary used to validate HCL (use 'tofu' for OpenTofu; default: terraform)",
    )
    preview.set_defaults(func=_preview)

    run = sub.add_parser("run", help="run the full mutation cycle over a repo and write a CSV")
    run.add_argument("target", help="a repo or directory containing .tftest.hcl test modules")
    run.add_argument("-O", "--output", default="results.csv", help="CSV output path")
    run.add_argument(
        "--test-cmd", default="terraform test",
        help="test command (use 'tofu test' for OpenTofu; default: 'terraform test')",
    )
    run.add_argument("--timeout", type=int, default=60, help="per-test timeout in seconds")
    _add_operator_filters(run)
    run.add_argument(
        "--plugin-cache-dir", default="~/.cache/tfmutate/plugins",
        help="shared provider plugin cache (offline, deterministic init across modules/runs)",
    )
    run.add_argument(
        "--allow-version-drift", action="store_true",
        help="proceed even if the test-cmd binary doesn't match its pinned version",
    )
    run.set_defaults(func=_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
