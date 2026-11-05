"""Generate tables or JSON from an explicit dataset; never execute repositories."""
import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist

from tfmutate.reporter import read_csv, summary_data


def wilson_interval(k, n, confidence=0.95):
    if not 0 < confidence < 1 or not 0 <= k <= n:
        raise ValueError("invalid binomial count/confidence")
    if not n:
        return None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return max(0, center - spread) * 100, min(1, center + spread) * 100


def markdown(data):
    lines = []
    for heading, groups in (("Overall", {"Overall": data["overall"]}),
                            ("Categories", data["by_category"]),
                            ("Operators", data["by_operator"]),
                            ("Repositories", data["by_repo"])):
        lines += [f"## {heading}", "", "| Group | Mutant records | Scored | Assertion kills | Engine-error kills | Survived | Score | 95% Wilson interval |",
                  "|---|---:|---:|---:|---:|---:|---:|---|"]
        for name, stats in groups.items():
            n = stats["scored_mutants"]
            interval = wilson_interval(stats["killed_assert"] + stats["killed_error"], n)
            ci = "n/a" if interval is None else f"[{interval[0]:.1f}%, {interval[1]:.1f}%]"
            score = "n/a" if stats["mutation_score"] is None else f"{stats['mutation_score']:.1%}"
            lines.append(f"| {name} | {stats['generated_mutants']} | {n} | {stats['killed_assert']} | {stats['killed_error']} | {stats['survived']} | {score} | {ci} |")
        lines.append("")
    lines += ["Module-baseline records and inconclusive mutant outcomes are excluded from scores.",
              "Intervals are descriptive binomial summaries; mutants within repositories may be dependent."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    data = summary_data(read_csv(args.csv))
    text = json.dumps(data, indent=2) + "\n" if args.format == "json" else markdown(data)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")
    return 1 if data["validation_problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
