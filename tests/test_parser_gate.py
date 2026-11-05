"""Tests for the `terraform fmt`-based validity gate.

These shell out to `terraform`, so they are skipped if it is not on PATH. They exist to lock
in the fix for the hcl2 false-rejection bug: a `for` expression that hcl2 rejects but
Terraform accepts must pass the gate (PHASE1_NOTES.md).
"""

from __future__ import annotations

import shutil
import textwrap

import pytest

from tfmutate.mutators import MUT_SEC_001
from tfmutate.parser import is_valid_hcl

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None, reason="terraform not on PATH"
)


@pytest.mark.parametrize("resource_type", ["aws_s3_bucket", "aws_s3_bucket_acl"])
def test_acl_mutant_is_hcl_syntax_valid_not_schema_validated(resource_type):
    text = f'resource "{resource_type}" "b" {{\n  acl = "private"\n}}\n'
    [mutant] = MUT_SEC_001.generate("main.tf", text)
    assert mutant.mutated_value == "public-read"
    assert is_valid_hcl(mutant.mutated_text) is True


def test_fmt_gate_does_not_validate_provider_attribute_values():
    # Even an unsupported canned ACL is syntactically valid. Do not conflate fmt
    # acceptance with provider/schema validation or successful planning/applying.
    text = 'resource "aws_s3_bucket_acl" "b" {\n  acl = "not-a-canned-acl"\n}\n'
    assert is_valid_hcl(text) is True


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
