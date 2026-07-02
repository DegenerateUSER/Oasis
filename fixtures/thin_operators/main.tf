# Synthetic validation fixture for the two THIN operators, MUT-SEC-001 and MUT-SEC-003.
#
# These operators target patterns that authenticated GitHub code search proved are
# STRUCTURALLY ABSENT from the terraform-test population (see PHASE1_NOTES.md and
# evidence/): 46 Cohort A repos contain zero `acl = "private"` / restrictive-CIDR literals,
# and 86 repos with `acl = "private"` use zero `.tftest.hcl` files. The operators are
# therefore validated here on a hand-written fixture (FIXTURE_VALIDATED), not on a real repo
# (real-corpus validated) like the other ten. This file exists solely to exercise them.

resource "aws_s3_bucket" "legacy" {
  bucket = "legacy-private-bucket"
  acl    = "private" # MUT-SEC-001 target: -> "public"
}

resource "aws_security_group" "restricted" {
  name = "restricted-ingress"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"] # MUT-SEC-003 target: -> "0.0.0.0/0"
  }
}
