"""Unit tests for the survival-reason classifier (PROJECT_SPEC.md §8)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tfmutate.classifier import classify_survival

RESOURCE = "aws_s3_bucket_public_access_block.config"
ATTR = "block_public_acls"


def test_no_coverage_when_resource_never_mentioned():
    tftest = textwrap.dedent(
        """\
        mock_provider "aws" {}
        run "s3_bucket_created" {
          command = plan
          assert {
            condition     = aws_s3_bucket.config.bucket == "test-config-bucket"
            error_message = "bucket name should match"
          }
        }
        """
    )
    assert classify_survival(RESOURCE, ATTR, [tftest]) == "no_coverage"


def test_plan_only_no_assert_when_resource_mentioned_but_never_asserted():
    # override_resource is a real .tftest.hcl construct that names a resource address
    # outside of any assert -- e.g. to supply a computed value the plan needs -- without
    # asserting on it. Modeled on the real pattern found in platform-design/secret-rotation.
    tftest = textwrap.dedent(
        f"""\
        mock_provider "aws" {{}}
        run "creates_pab" {{
          command = plan
          override_resource {{
            target = {RESOURCE}
            values = {{ id = "example" }}
          }}
          assert {{
            condition     = aws_s3_bucket.config.bucket == "test-config-bucket"
            error_message = "bucket name should match"
          }}
        }}
        """
    )
    assert classify_survival(RESOURCE, ATTR, [tftest]) == "plan_only_no_assert"


def test_weak_assertion_when_resource_asserted_on_different_attribute():
    tftest = textwrap.dedent(
        """\
        mock_provider "aws" {}
        run "pab_exists" {
          command = plan
          assert {
            condition     = aws_s3_bucket_public_access_block.config.bucket == "test-config-bucket"
            error_message = "PAB should target the right bucket"
          }
        }
        """
    )
    assert classify_survival(RESOURCE, ATTR, [tftest]) == "weak_assertion"


def test_multiple_test_files_are_combined():
    a = 'run "x" { command = plan\n assert { condition = true } }'
    b = f'run "y" {{ command = plan\n assert {{ condition = {RESOURCE}.bucket == "x" }} }}'
    assert classify_survival(RESOURCE, ATTR, [a, b]) == "weak_assertion"


# --- Ground-truth regression: real Cohort A modules, real terraform test signal ---------
# These pin down the classifier against actual survived mutants confirmed by a live
# `tfmutate run` (not just synthetic fixtures) so a future change can't silently drift.

def test_ground_truth_aws_config_no_coverage():
    """platform-design/aws-config: none of the 4 public-access-block flags -- or the
    resource itself -- are referenced anywhere in the test file (confirmed by grep and by
    a live run: all 4 MUT-SEC-004* mutants come back SURVIVED)."""
    tftest = Path(
        "corpus/platform-design/terraform/modules/aws-config/aws-config.tftest.hcl"
    )
    if not tftest.exists():
        pytest.skip("corpus not present in this environment")
    texts = [tftest.read_text()]
    for attr in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        assert classify_survival(
            "aws_s3_bucket_public_access_block.config", attr, texts
        ) == "no_coverage"


def test_ground_truth_mlflow_weak_assertion():
    """platform-design/aws-ml-artifact-store: block_public_acls/policy/restrict_public_buckets
    are explicitly asserted true, but ignore_public_acls never appears -- confirmed by a live
    run: MUT-SEC-004c is the lone SURVIVED mutant among the four SEC-004 flags."""
    tftest = Path(
        "corpus/platform-design/terraform/modules/aws-ml-artifact-store/"
        "aws-ml-artifact-store.tftest.hcl"
    )
    if not tftest.exists():
        pytest.skip("corpus not present in this environment")
    texts = [tftest.read_text()]
    assert classify_survival(
        "aws_s3_bucket_public_access_block.mlflow_artifacts", "ignore_public_acls", texts
    ) == "weak_assertion"


def test_ground_truth_plan_only_no_assert_boundary():
    """fixtures/classifier_boundary: a constructed fixture (modeled on the real
    override_resource pattern -- see PHASE5_NOTES.md) that has NEVER occurred naturally in
    the 3-repo corpus. A live `tfmutate run` confirms MUT-SEC-004a-d genuinely SURVIVE (the
    resource is override_resource-targeted but never asserted on) while MUT-SEC-002/RES-001
    on the untouched sibling resource genuinely SURVIVE as no_coverage -- both in the same
    run, proving the boundary is reachable and distinguishable in practice, not just theory."""
    tftest = Path("fixtures/classifier_boundary/main.tftest.hcl")
    if not tftest.exists():
        pytest.skip("fixture not present in this environment")
    texts = [tftest.read_text()]
    for attr in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        assert classify_survival(
            "aws_s3_bucket_public_access_block.data", attr, texts
        ) == "plan_only_no_assert"
    assert classify_survival("aws_db_instance.reporting", "storage_encrypted", texts) == "no_coverage"
