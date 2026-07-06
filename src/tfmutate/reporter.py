"""CSV output (PROJECT_SPEC.md §9). Markdown reporting arrives with the classifier (Phase 4).

The CSV is the source of truth. Rows are written in a deterministic order (as produced by the
runner, which iterates files and operators deterministically) so that running the tool twice on
the same repo yields a byte-identical file -- part of the Phase 2 done-condition.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import astuple, fields
from pathlib import Path

from .runner import MutantOutcome

CSV_COLUMNS = [f.name for f in fields(MutantOutcome)]


def write_csv(outcomes: Iterable[MutantOutcome], path: Path | str) -> int:
    """Write outcomes to ``path``; return the row count."""
    rows = list(outcomes)
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for o in rows:
            writer.writerow(astuple(o))
    return len(rows)
