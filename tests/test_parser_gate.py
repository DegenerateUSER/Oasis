"""Tests for the `terraform fmt`-based validity gate.

These shell out to `terraform`, so they are skipped if it is not on PATH. They exist to lock
in the fix for the hcl2 false-rejection bug: a `for` expression that hcl2 rejects but
Terraform accepts must pass the gate (PHASE1_NOTES.md).
"""

from __future__ import annotations

import shutil
import textwrap

import pytest

from tfmutate.parser import is_valid_hcl

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None, reason="terraform not on PATH"
)


def test_accepts_plain_valid_hcl():
    assert is_valid_hcl('resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}\n') is True


def test_rejects_genuine_syntax_error():
    assert is_valid_hcl('resource "x" "y" {') is False  # unterminated block


def test_accepts_for_expression_that_hcl2_rejects():
    # This is the exact class of file the old hcl2 gate wrongly dropped.
    text = textwrap.dedent(
        """\
        locals {
          names = { for k, v in var.items : k => v.name }
        }
        """
    )
    assert is_valid_hcl(text) is True
