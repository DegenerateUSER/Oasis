"""Bounded offline policy comparison; never runs Terraform/cloud tests."""
import argparse
import json
from pathlib import Path

from tfmutate.mutators import select_operators
from tfmutate.scanner import compare_repo


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tfsec", default="tfsec", help="path to an installed tfsec binary")
    parser.add_argument("--operator")
    parser.add_argument("--max-mutants", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--budget-seconds", type=float, default=120)
    parser.add_argument("--outcomes-csv", type=Path)
    args = parser.parse_args(argv)
    try:
        report = compare_repo(args.target, args.output_dir, binary=args.tfsec,
                              operators=select_operators(args.operator),
                              timeout=args.timeout, budget_seconds=args.budget_seconds,
                              max_mutants=args.max_mutants, outcomes_csv=args.outcomes_csv)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"baseline_status": report["baseline"]["status"],
                      "mutants_compared": len(report["mutants"]),
                      "duration_seconds": report["duration_seconds"],
                      "output": str(args.output_dir / "comparison.json")}, indent=2))
    return 0 if report["baseline"]["status"] == "completed" and all(r["scan"]["status"] == "completed" for r in report["mutants"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
