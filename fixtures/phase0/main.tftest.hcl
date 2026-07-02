# Phase 0 smoke test: proves `terraform test` + `mock_provider` work on this machine
# with no cloud credentials and no real API calls.

mock_provider "aws" {}

run "bucket_name_is_set" {
  command = plan

  assert {
    condition     = aws_s3_bucket.this.bucket == "oasis-phase0-bucket"
    error_message = "bucket name did not match the expected value"
  }
}
