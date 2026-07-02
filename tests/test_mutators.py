"""Unit tests for the parser + full operator catalog."""

from __future__ import annotations

import textwrap

from tfmutate.mutators import (
    MUT_RES_001,
    MUT_RES_002,
    MUT_RES_003,
    MUT_SEC_001,
    MUT_SEC_002,
    MUT_SEC_003,
    MUT_SEC_004A,
    MUT_SEC_004B,
    MUT_SEC_004C,
    MUT_SEC_004D,
    MUT_TAG_001,
    MUT_TAG_002,
    generate_mutants,
)
from tfmutate.parser import enclosing_block, find_blocks


def _one(text, op):
    m = generate_mutants("main.tf", text, [op])
    assert len(m) == 1, f"expected 1 mutant, got {len(m)}"
    return m[0]


# --- parser: block detection ----------------------------------------------------------

def test_find_blocks_kinds_and_ranges():
    text = textwrap.dedent(
        """\
        terraform {
          required_providers {}
        }

        variable "size" {
          default = "small"
        }

        resource "aws_s3_bucket" "b" {
          bucket = "x"
        }
        """
    )
    blocks = find_blocks(text)
    assert [(b.kind, b.address) for b in blocks] == [
        ("terraform", "terraform"),
        ("variable", "variable.size"),
        ("resource", "aws_s3_bucket.b"),
    ]
    # Nested `required_providers {}` must NOT close the terraform block early.
    tf = blocks[0]
    assert tf.start_line == 1 and tf.end_line == 3
    assert enclosing_block(blocks, 6).kind == "variable"
    assert enclosing_block(blocks, 10).address == "aws_s3_bucket.b"


# --- MUT-SEC-001: ACL, resource-scoped -------------------------------------------------

def test_sec001_scoped_to_s3_and_flips_private():
    text = textwrap.dedent(
        """\
        resource "aws_s3_bucket" "b" {
          acl = "private"
        }
        resource "aws_instance" "web" {
          acl = "private"
        }
        """
    )
    # Only the S3 bucket is in scope; the aws_instance acl is ignored.
    m = _one(text, MUT_SEC_001)
    assert m.resource_address == "aws_s3_bucket.b"
    assert (m.original_value, m.mutated_value) == ("private", "public")
    assert m.surface == "R"


# --- MUT-SEC-004a-d: atomic public-access-block flags ----------------------------------

PUBLIC_ACCESS_BLOCK = textwrap.dedent(
    """\
    resource "aws_s3_bucket_public_access_block" "this" {
      bucket                  = aws_s3_bucket.this.id
      block_public_acls       = true
      block_public_policy     = true
      ignore_public_acls      = true
      restrict_public_buckets = true
    }
    """
)


def test_sec004_four_atomic_operators_one_flag_each():
    ops = {
        MUT_SEC_004A: "block_public_acls",
        MUT_SEC_004B: "block_public_policy",
        MUT_SEC_004C: "ignore_public_acls",
        MUT_SEC_004D: "restrict_public_buckets",
    }
    for op, flag in ops.items():
        m = _one(PUBLIC_ACCESS_BLOCK, op)
        assert flag in m.original_snippet
        assert (m.original_value, m.mutated_value) == ("true", "false")
        assert m.resource_address == "aws_s3_bucket_public_access_block.this"
        assert m.mutated_text.count("= true") == 3 and m.mutated_text.count("= false") == 1


def test_sec004_ignores_flags_outside_the_pab_resource():
    text = 'resource "aws_instance" "x" {\n  block_public_acls = true\n}\n'
    assert generate_mutants("m.tf", text, [MUT_SEC_004A]) == []


# --- MUT-SEC-002: encryption, resource-scoped ------------------------------------------

def test_sec002_scopes_encryption_to_storage_resources():
    text = textwrap.dedent(
        """\
        resource "aws_db_instance" "db" {
          storage_encrypted = true
        }
        resource "aws_fancy_thing" "x" {
          encrypted = true
        }
        """
    )
    m = _one(text, MUT_SEC_002)  # aws_fancy_thing is not in scope
    assert m.resource_address == "aws_db_instance.db"
    assert m.mutated_value == "false"


# --- MUT-SEC-003: CIDR widening --------------------------------------------------------

def test_sec001_fixture_validated_operator_produces_valid_mutant():
    # SEC-001 is FIXTURE-validated (no real Cohort A target exists; see PHASE1_NOTES.md).
    # This locks in that the operator itself is correct.
    text = 'resource "aws_s3_bucket" "b" {\n  acl = "private"\n}\n'
    m = _one(text, MUT_SEC_001)
    assert (m.original_value, m.mutated_value) == ("private", "public")


def test_sec003_widens_restrictive_cidr_only():
    text = textwrap.dedent(
        """\
        resource "aws_security_group" "sg" {
          cidr_block  = "10.0.0.0/8"
          cidr_blocks = ["0.0.0.0/0"]
        }
        """
    )
    mutants = generate_mutants("m.tf", text, [MUT_SEC_003])
    assert len(mutants) == 1  # already-open 0.0.0.0/0 is skipped (equivalent)
    assert mutants[0].original_value == "10.0.0.0/8"
    assert mutants[0].mutated_value == "0.0.0.0/0"


# --- MUT-RES-001: sizing, R and V surfaces ---------------------------------------------

def test_res001_scales_up_by_family_in_resource_and_variable():
    resource = 'resource "aws_db_instance" "db" {\n  instance_class = "db.t4g.micro"\n}\n'
    m = _one(resource, MUT_RES_001)
    assert m.surface == "R" and m.mutated_value == "db.r5.24xlarge"

    variable = 'variable "instance_class" {\n  default = "db.t4g.micro"\n}\n'
    mv = _one(variable, MUT_RES_001)
    assert mv.surface == "V" and mv.mutated_value == "db.r5.24xlarge"
    assert mv.resource_address == "variable.instance_class"


def test_res001_ignores_unrelated_variable_defaults():
    variable = 'variable "region" {\n  default = "us-east-1"\n}\n'
    assert generate_mutants("m.tf", variable, [MUT_RES_001]) == []


# --- MUT-RES-002 / 003: counts, with equivalence guard ---------------------------------

def test_res002_reduces_counts_but_skips_ones():
    text = textwrap.dedent(
        """\
        resource "aws_autoscaling_group" "g" {
          desired_capacity = 3
          min_size         = 1
        }
        """
    )
    mutants = generate_mutants("m.tf", text, [MUT_RES_002])
    assert len(mutants) == 1  # min_size = 1 -> 1 is equivalent, skipped
    assert mutants[0].attribute == "desired_capacity"
    assert (mutants[0].original_value, mutants[0].mutated_value) == ("3", "1")


def test_res003_zeroes_replicas():
    m = _one('resource "k" "x" {\n  replicas = 2\n}\n', MUT_RES_003)
    assert m.mutated_value == "0"


# --- MUT-TAG-001 / 002: compliance -----------------------------------------------------

def test_tag001_demotes_environment_in_tags_and_locals():
    text = textwrap.dedent(
        """\
        locals {
          common_tags = {
            Environment = "production"
          }
        }
        """
    )
    m = _one(text, MUT_TAG_001)
    assert m.surface == "L"
    assert (m.original_value, m.mutated_value) == ("production", "development")


def test_tag002_deletes_required_tag_line():
    text = textwrap.dedent(
        """\
        resource "aws_s3_bucket" "b" {
          tags = {
            team = "platform"
            env  = "prod"
          }
        }
        """
    )
    m = _one(text, MUT_TAG_002)
    assert m.is_deletion is True
    assert 'team = "platform"' not in m.mutated_text
    assert 'env  = "prod"' in m.mutated_text  # only the team line is removed
    assert len(m.mutated_text.splitlines()) == len(text.splitlines()) - 1


def test_tag002_ignores_synonym_named_functional_attributes():
    # `owner` here is a functional attribute of a Config rule's source block, NOT a tag.
    # tags_only scoping must leave it untouched (guards the false positive found in corpus).
    text = textwrap.dedent(
        """\
        resource "aws_config_config_rule" "r" {
          source {
            owner             = "AWS"
            source_identifier = "ROOT_ACCOUNT_MFA_ENABLED"
          }
        }
        """
    )
    assert generate_mutants("m.tf", text, [MUT_TAG_002]) == []


def test_tag002_matches_labels_map_too():
    text = textwrap.dedent(
        """\
        resource "x" "y" {
          labels = {
            team = "gpu-infra"
          }
        }
        """
    )
    assert len(generate_mutants("m.tf", text, [MUT_TAG_002])) == 1
