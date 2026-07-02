# Demo module for MUT-SEC-001. Uses the (now-deprecated) inline `acl` argument that the
# operator targets, so the mutation can be shown end-to-end. Real Cohort A repos increasingly
# express the same fault via `aws_s3_bucket_public_access_block` instead -- see PHASE1_NOTES.md.

resource "aws_s3_bucket" "logs" {
  bucket = "example-logs"
  acl    = "private"
}

resource "aws_s3_bucket" "data" {
  bucket = "example-data"
  acl    = "private"
}
