"""Atomic CSV artifacts and JSON reports using the shared score contract."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

from .metrics import grouped_summary, row_dict, summarize, validate_dataset
from .mutators import CATALOG, CATEGORIES
from .provenance import MANIFEST_SCHEMA_VERSION
from .runner import MutantOutcome

CSV_COLUMNS = [f.name for f in fields(MutantOutcome)]


@contextmanager
def _atomic_stream(path: Path | str, *, newline=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_csv(outcomes: Iterable[MutantOutcome | dict], path: Path | str) -> int:
    """Publish a complete CSV without ever exposing a partially written artifact."""
    count = 0
    with _atomic_stream(path, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(row_dict(outcome))
            count += 1
    return count


def read_csv(path: Path | str) -> list[dict]:
    """Read current or legacy datasets; record-type inference lives in metrics."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def summary_data(outcomes: Iterable, *, known_operators=None) -> dict:
    rows = [row_dict(row) for row in outcomes]
    known = CATALOG if known_operators is None else known_operators
    return {"schema_version": MANIFEST_SCHEMA_VERSION,
            "overall": summarize(rows),
            "by_repo": grouped_summary(rows, "repo_name", known={r.get("repo_name", "") for r in rows}),
            "by_category": grouped_summary(rows, "operator_category", known=CATEGORIES),
            "by_operator": grouped_summary(rows, "operator_id", known=known),
            "validation_problems": validate_dataset(rows)}


def write_summary(outcomes: Iterable, path: Path | str, *, known_operators=None) -> dict:
    data = summary_data(outcomes, known_operators=known_operators)
    with _atomic_stream(path) as stream:
        json.dump(data, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return data
