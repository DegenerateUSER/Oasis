"""Validate and summarize an existing CSV without executing any repositories."""
import argparse
import csv
import json
from pathlib import Path

from tfmutate.metrics import grouped_summary, summarize, validate_dataset
from tfmutate.mutators import CATALOG


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.csv.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    report = {"overall": summarize(rows), "by_operator": grouped_summary(rows, "operator_id", known=CATALOG),
              "by_repository": grouped_summary(rows, "repo_name"), "issues": validate_dataset(rows)}
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
