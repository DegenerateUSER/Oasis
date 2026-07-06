"""Real (non-mocked) verification that OpenTofu's CLI output is compatible with
classify_test's string matching, and that its version pin is in place (PHASE5_NOTES.md).

`nullplatform/tofu-modules` is a corpus candidate that uses `tofu test`, not
`terraform test`. classify_test's killed_assert/killed_error split depends on matching a
literal "Error: Test assertion failed" string -- this must be verified against the real
`tofu` binary, not assumed, before trusting any tofu-based repo's results.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from tfmutate.runner import PINNED_VERSIONS, check_pinned_version, classify_test

pytestmark = pytest.mark.skipif(shutil.which("tofu") is None, reason="tofu not on PATH")


def test_tofu_has_a_recorded_version_pin():
    assert "tofu" in PINNED_VERSIONS


def test_tofu_binary_matches_its_pin():
    check = check_pinned_version("tofu")
    assert check.ok, check.message


def test_tofu_assertion_failure_wording_matches_classify_test(tmp_path):
    (tmp_path / "main.tf").write_text(
        textwrap.dedent(
            """\
            terraform {
              required_providers {
                aws = { source = "hashicorp/aws", version = "~> 5.0" }
              }
            }
            resource "aws_s3_bucket" "this" {
              bucket = "example-bucket"
            }
            """
        )
    )
    (tmp_path / "main.tftest.hcl").write_text(
        textwrap.dedent(
            """\
            mock_provider "aws" {}
            run "wrong_assertion" {
              command = plan
              assert {
                condition     = aws_s3_bucket.this.bucket == "not-the-real-value"
                error_message = "deliberate mismatch"
              }
            }
            """
        )
    )
    subprocess.run(["tofu", "init", "-no-color"], cwd=tmp_path, capture_output=True, check=True)
    r = subprocess.run(["tofu", "test", "-no-color"], cwd=tmp_path, capture_output=True, text=True)
    output = r.stdout + r.stderr
    assert classify_test(r.returncode, output) == "killed_assert"


def test_tofu_engine_error_wording_matches_classify_test(tmp_path):
    (tmp_path / "main.tf").write_text(
        textwrap.dedent(
            """\
            terraform {
              required_providers {
                aws = { source = "hashicorp/aws", version = "~> 5.0" }
              }
            }
            resource "aws_db_instance" "this" {
              engine = "postgres"
              # missing required instance_class -> a genuine engine error, not an assertion
            }
            """
        )
    )
    (tmp_path / "main.tftest.hcl").write_text(
        textwrap.dedent(
            """\
            mock_provider "aws" {}
            run "plans_cleanly" {
              command = plan
              assert {
                condition     = aws_db_instance.this.engine == "postgres"
                error_message = "engine mismatch"
              }
            }
            """
        )
    )
    subprocess.run(["tofu", "init", "-no-color"], cwd=tmp_path, capture_output=True, check=True)
    r = subprocess.run(["tofu", "test", "-no-color"], cwd=tmp_path, capture_output=True, text=True)
    output = r.stdout + r.stderr
    assert classify_test(r.returncode, output) == "killed_error"
