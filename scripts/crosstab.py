"""Cross-tabulate survivor reasons from an explicitly supplied CSV."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from tfmutate.metrics import record_type
from tfmutate.reporter import read_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args(argv)
    table = defaultdict(Counter)
    for row in read_csv(args.csv):
        if record_type(row) == "mutant" and row.get("test_status") == "survived":
            table[row["operator_id"]][row.get("survival_reason", "unknown")] += 1
    if args.format == "json":
        print(json.dumps({op: dict(counts) for op, counts in sorted(table.items())}, indent=2))
    else:
        reasons = sorted({reason for counts in table.values() for reason in counts})
        print("| Operator | " + " | ".join(reasons) + " |")
        print("|---|" + "---:|" * len(reasons))
        for op, counts in sorted(table.items()):
            print(f"| {op} | " + " | ".join(str(counts[r]) for r in reasons) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
