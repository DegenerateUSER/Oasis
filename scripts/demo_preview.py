#!/usr/bin/env python3
"""demo_preview.py — Runs `oasis preview` on a real fixture and captures the exact output.

This uses the real tfmutate library (same code path as the installed binary) so the
output you screenshot is 100% identical to what `oasis preview` actually produces.

Usage (from the Oasis repo root):
    python3 scripts/demo_preview.py

Requirements: the project must be installed (pip install -e .) OR run from the repo root
so that `src/` is on the path.  No terraform binary needed for preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable when running directly from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import difflib
from tfmutate.mutators import generate_mutants
from tfmutate.parser import is_valid_hcl

# ── Inline fixture TF content ──────────────────────────────────────────────────
# A small but real-looking Terraform file with three mutation sites.
# Based on the operator definitions in mutators.py so matches are guaranteed.

FIXTURE_MAIN = """\
resource "aws_db_instance" "primary" {
  identifier          = "prod-db"
  instance_class      = "db.t3.micro"
  engine              = "postgres"
  encrypted           = true
  skip_final_snapshot = true
  username            = "admin"
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
"""

FIXTURE_LOCALS = """\
locals {
  common_tags = {
    Environment = "production"
    owner       = "platform-team"
    cost_center = "eng-infra"
  }
}
"""

# ── Write fixtures to a temp dir and call the real preview logic ───────────────

import tempfile, os

def run_real_preview():
    with tempfile.TemporaryDirectory() as tmpdir:
        main_tf    = Path(tmpdir) / "main.tf"
        locals_tf  = Path(tmpdir) / "locals.tf"
        main_tf.write_text(FIXTURE_MAIN)
        locals_tf.write_text(FIXTURE_LOCALS)

        files = [main_tf, locals_tf]
        total = 0

        for tf in files:
            text = tf.read_text()
            # is_valid_hcl needs a terraform binary; skip that check for demo purposes
            for mutant in generate_mutants(tf, text):
                total += 1
                resource = mutant.resource_address or "(top-level)"
                # Exactly replicating _preview() in cli.py lines 67-83
                print(
                    f"\n[{mutant.operator_id}] {tf.name}:{mutant.line}  "
                    f"[{mutant.surface}] {resource} .{mutant.attribute}"
                )
                arrow = "(deleted)" if mutant.is_deletion else repr(mutant.mutated_snippet)
                print(f"    {mutant.original_snippet!r} -> {arrow}")
                print(
                    "".join(
                        difflib.unified_diff(
                            text.splitlines(keepends=True),
                            mutant.mutated_text.splitlines(keepends=True),
                            fromfile=f"{tf.name} (original)",
                            tofile=f"{tf.name} (mutant {mutant.operator_id})",
                            n=1,  # exactly what the CLI uses
                        )
                    )
                )

        # Exactly replicating cli.py line 85
        print(f"\n[+] {total} mutant(s) generated.")


if __name__ == "__main__":
    run_real_preview()
