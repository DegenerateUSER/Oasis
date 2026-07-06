"""Unit tests for the parser + full operator catalog."""

from __future__ import annotations

import textwrap

import pytest

from tfmutate.mutators import (
    CATALOG,
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
    select_operators,
)
from tfmutate.parser import enclosing_block, find_blocks, find_test_module_dirs, read_tf_files


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


# --- select_operators: --operator / --category CLI filtering (PROJECT_SPEC.md §7) ------

def test_select_operators_defaults_to_whole_catalog():
    assert select_operators() == list(CATALOG.values())


def test_select_operators_by_exact_id():
    assert select_operators(operator_id="MUT-SEC-002") == [CATALOG["MUT-SEC-002"]]


def test_select_operators_by_single_category():
    ops = select_operators(categories=["compliance"])
    assert {op.id for op in ops} == {"MUT-TAG-001", "MUT-TAG-002"}


def test_select_operators_by_multiple_categories():
    ops = select_operators(categories=["resource", "compliance"])
    assert {op.category for op in ops} == {"resource", "compliance"}


def test_select_operators_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown operator"):
        select_operators(operator_id="MUT-NOPE-999")


def test_select_operators_unknown_category_raises():
    with pytest.raises(ValueError, match="unknown categor"):
        select_operators(categories=["bogus"])


# --- .terraform/ exclusion (Phase 5 batch bug: vendored module code must never be scanned) --
# `terraform init` vendors remote module sources under `.terraform/modules/`. That tree is
# gitignored/untracked, so mutating a file there and then trying `git checkout --` to restore
# it fails outright -- this crashed two real batch repos before the fix (PHASE5_NOTES.md).

def test_read_tf_files_excludes_dot_terraform(tmp_path):
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    vendored = tmp_path / ".terraform" / "modules" / "some_dep" / "examples" / "basic"
    vendored.mkdir(parents=True)
    (vendored / "main.tf").write_text('resource "a" "b" {}\n')

    found = read_tf_files(tmp_path)
    assert found == [tmp_path / "main.tf"]


def test_find_test_module_dirs_excludes_dot_terraform(tmp_path):
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    (tmp_path / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')
    vendored = tmp_path / ".terraform" / "modules" / "some_dep" / "examples" / "basic"
    vendored.mkdir(parents=True)
    (vendored / "main.tf").write_text('resource "a" "b" {}\n')
    (vendored / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')

    found = find_test_module_dirs(tmp_path)
    assert found == [tmp_path]


# --- tests/ subdirectory convention (Phase 5 batch bug: "initialized in an empty directory") -
# Terraform's own convention lets a `.tftest.hcl` live in a nested `tests/`/`test/` dir
# instead of alongside the module's .tf files -- `terraform test` is still run from the
# MODULE ROOT. Treating the tests/ dir itself as the root means running init/test with zero
# .tf files present, which silently produced degenerate "empty directory" results across
# roughly half the real Phase 5 corpus (PHASE5_NOTES.md) before this fix.

def test_climbs_out_of_a_bare_tests_subdir_to_the_real_module_root(tmp_path):
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')

    assert find_test_module_dirs(tmp_path) == [tmp_path]


def test_stays_in_tests_subdir_when_it_has_its_own_tf_files(tmp_path):
    # A tests/ dir that is itself a genuine, self-contained fixture module (has its own .tf
    # files) must NOT be climbed out of.
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "fixture.tf").write_text('resource "a" "b" {}\n')
    (tests_dir / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')

    assert find_test_module_dirs(tmp_path) == [tests_dir]


def test_multiple_test_files_in_same_tests_subdir_dedupe_to_one_module_root(tmp_path):
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "a.tftest.hcl").write_text('mock_provider "aws" {}\n')
    (tests_dir / "b.tftest.hcl").write_text('mock_provider "aws" {}\n')

    assert find_test_module_dirs(tmp_path) == [tmp_path]


def test_climb_is_name_agnostic_not_just_tests_or_test(tmp_path):
    # Real repos use other names too (e.g. `e2e-tests/`) -- the rule is "no .tf files here",
    # not "named tests/test", which is exactly what the Phase 5 batch caught missing.
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n')
    e2e_dir = tmp_path / "e2e-tests"
    e2e_dir.mkdir()
    (e2e_dir / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')

    assert find_test_module_dirs(tmp_path) == [tmp_path]


def test_excludes_test_file_with_no_real_module_at_either_level(tmp_path):
    # Neither the containing directory nor its parent has any .tf files -- this is not a
    # real, runnable module (e.g. a Bazel test-harness template found in the real corpus:
    # BUILD/.bzl files plus a `.tftest.hcl` template, not an actual module under test). It
    # must be EXCLUDED, not misresolved to some arbitrary further-up ancestor.
    tests_dir = tmp_path / "tftesting"
    tests_dir.mkdir()
    (tests_dir / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')

    assert find_test_module_dirs(tmp_path) == []
