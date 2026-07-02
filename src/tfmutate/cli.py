"""Command-line entry point.

Phase 1 exposes a single ``preview`` command: it locates mutation targets in ``.tf``
files and prints each resulting mutant as a unified diff, so a human can visually confirm
the mutation is correct and valid HCL (PROJECT_SPEC.md §12, Phase 1 done-condition). Running the
actual test cycle (validate -> test -> classify) arrives in Phase 2.
"""

from __future__ import annotations

import argparse
import difflib
import logging
import sys
from pathlib import Path

from .mutators import CATALOG, generate_mutants
from .parser import is_valid_hcl, read_tf_files


def _iter_targets(path: Path) -> list[Path]:
    if path.is_dir():
        return read_tf_files(path)
    return [path]


def _preview(args: argparse.Namespace) -> int:
    operators = None
    if args.operator:
        try:
            operators = [CATALOG[args.operator]]
        except KeyError:
            print(f"unknown operator {args.operator!r}; known: {', '.join(CATALOG)}",
                  file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tfmutate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="show mutants for a .tf file or directory")
    preview.add_argument("target", help="a .tf file or a directory of .tf files")
    preview.add_argument(
        "-o", "--operator", help=f"limit to one operator (known: {', '.join(CATALOG)})"
    )
    preview.add_argument(
        "--fmt-cmd", default="terraform",
        help="binary used to validate HCL (use 'tofu' for OpenTofu; default: terraform)",
    )
    preview.set_defaults(func=_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
