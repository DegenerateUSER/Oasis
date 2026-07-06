# Phase 1 notes

## Corpus finding that shaped the operator catalog

The spec's first operator, **MUT-SEC-001**, targets the literal `acl = "private"` on
`aws_s3_bucket`. When implementing Phase 1 we confirmed via grep that **neither vetted
Cohort A repo** (`Worklytics/psoxy`, `MPeets/cloud-native-deployment-platform`) contains
that literal — **0 sites**.

This is not bad luck. The inline `acl` argument on `aws_s3_bucket` was **deprecated in AWS
provider v4+ (2022)**. Repositories that adopted the native `terraform test` framework are
by definition recent (Terraform v1.7+, 2024), so they overwhelmingly express the same
"accidental public exposure" fault through the newer `aws_s3_bucket_public_access_block`
resource instead. psoxy, for example, has it in real modules:

```hcl
resource "aws_s3_bucket_public_access_block" "sanitized" {
  block_public_acls       = true   # flip any of these to false -> public exposure
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

## Decision

- **MUT-SEC-001** is kept exactly as specified (verified via unit tests + `fixtures/phase1_demo/`).
  *Update (Phase 5/6)*: Targeted corpus expansion and deeper scans revealed that the literal `acl = "private"` is structurally present in 2 out of 23 repos (`platform-tools` and `terraform-aws-static-site`). However, mutating `"private"` to `"public"` generates an invalid mutant that fails `terraform validate` because `"public"` is not a valid canned ACL value in the AWS provider S3 bucket schema (which accepts `"public-read"` or `"public-read-write"`). These mutants are correctly classified as `invalid` and are excluded from the scored set.
- The **modern equivalent** of MUT-SEC-001 was added as **four atomic operators**,
  `MUT-SEC-004a`–`MUT-SEC-004d`, one per `aws_s3_bucket_public_access_block` guard flag:
  - `004a` → `block_public_acls = true → false`
  - `004b` → `block_public_policy = true → false`
  - `004c` → `ignore_public_acls = true → false`
  - `004d` → `restrict_public_buckets = true → false`

  These target the same fault class ("accidental public exposure") and, unlike
  MUT-SEC-001, have real scored targets in the Cohort A corpus, so Phase 1's done-condition
  ("mutate a real `.tf` file from a Cohort A repo") is satisfied on genuine files.

### Why four atomic operators, not one compound operator

They are deliberately **not** a single "flip any public-access-block flag" operator. Each
flag is its own operator so that (a) mutation score is attributable per flag, (b) operators
stay individually toggleable per PROJECT_SPEC.md §7, and (c) the Phase 3+ dataset never records a
conflated `MUT-SEC-004` row that would be expensive to disaggregate after data exists.
Splitting is cheap now and costly to unwind later — do not merge them back.

## Validity gate: `terraform fmt`, not `python-hcl2`

**Bug found.** The initial parser used `python-hcl2` to decide whether a `.tf` file was valid
HCL before mutating it. hcl2's grammar (a third-party lark parser) is **stricter than
Terraform's**: it raises on some `for` expressions that Terraform parses without complaint.
Because a parse failure skipped the *whole file*, real mutation targets were being silently
dropped.

**Quantified impact (3-repo corpus).** hcl2 rejected **3 files** (`gpu-inference-cilium-advanced`,
`gpu-inference-cilium-encryption`, `gpu-inference-dcgm` in `platform-design`) carrying **9
mutants that `terraform fmt` accepts as valid**. Most visibly, `MUT-TAG-002` collapsed to 0
because its real `team = "..."` targets (inside `labels = {}` maps) all lived in those files.

**Fix.** The validity gate is now `terraform fmt -` (via `is_valid_hcl`) — the *same engine
that runs the tests*, so it cannot have a false-rejection gap the way a third-party parser
can. hcl2 is no longer a gate; it remains only in `noop.py` for parsing `.tftest.hcl` files.
Target location was already done by the brace-aware raw-text scanner (`find_blocks`), which
handled these files correctly all along. After the fix: 9 mutants recovered, **0 genuine
`fmt` failures across the corpus** (confirming every hcl2 rejection was a false negative). A
`SKIPPED_FILE` category logs any *real* `fmt` syntax failure rather than dropping it silently.

## Tag-map scoping for deletion operators (MUT-TAG-002)

A "missing required tag" fault only makes sense inside an actual `tags`/`labels` map. Without
scoping, `MUT-TAG-002` matched any `owner`/`team`/`cost_center` synonym in a resource body —
e.g. `owner = "AWS"`, a *functional* attribute of `aws_config_config_rule`'s `source {}`
block — and deleting it produced a nonsensical (and invalid) mutant. `MUT-TAG-002` is now
`tags_only`: R/L matches must sit inside a `tags`/`labels`/`*_tags`/`*_labels` map literal
(detected by `find_tag_maps`). `MUT-TAG-001` stays unscoped because it is tightly
value-constrained (`prod`/`production` only), so it cannot misfire the same way.

## Finding: the "textbook" security operators are structurally absent (SEC-001, SEC-003)

MUT-SEC-001 (`acl = "private" → "public"`) and MUT-SEC-003 (restrictive CIDR → `0.0.0.0/0`)
are the canonical S3-public-exposure and open-firewall mutation operators. We set out to
validate them on a real Cohort A repo per the corpus-first rule, and could not — because no
such repo appears to exist.

**Evidence (authenticated GitHub code search, saved in `evidence/`):**

- `evidence/cohortA_repos.txt` — 46 repos containing `mock_provider` in a `.tftest.hcl` file
  (the Cohort A definition). **Zero** contain `acl = "private"`, zero contain any `acl =`
  assignment, and zero contain a `10.0.0.0/16`-style restrictive CIDR literal.
- `evidence/acl_private_repos.txt` — 86 repos containing the literal `acl = "private"`.
  **Zero** of them contain any `.tftest.hcl` file.

The two populations are **disjoint** in the sampled data. The cause is chronological, not
coincidental: Terraform's native `test` framework with `mock_provider` is a 1.6/1.7 feature
(late 2023 / early 2024), so every repo that adopts it is recent; meanwhile the inline `acl`
argument on `aws_s3_bucket` was **deprecated in AWS provider v4 (2022)** in favour of the
`aws_s3_bucket_acl` / `aws_s3_bucket_public_access_block` resources, and hardcoded restrictive
CIDRs in security groups are an anti-pattern that recent modules avoid by parameterising with
variables. A repo modern enough to use `terraform test` is modern enough to have abandoned
both patterns. **The textbook IaC-misconfiguration operators barely apply to the population of
code that is actually unit-tested** — arguably the more interesting result than any single
mutation score.

**Decision.** Per the corpus-first rule we did **not** reformulate the faults or widen the
Cohort A definition to manufacture targets. SEC-001 and SEC-003 stay in the v1 catalog and are
`FIXTURE`-validated on `fixtures/thin_operators/main.tf` (both produce `terraform fmt`-valid
mutants; unit-tested). Every catalog presentation — `OPERATOR_SYNONYMS.md` and the eventual
report table — carries a **CORPUS vs FIXTURE** validation column so this distinction is never
collapsed into an undifferentiated "all operators working" claim. Final Phase 1 status:
**10/12 CORPUS-validated, 2/12 FIXTURE-validated.**

### Renumbering / catalog consolidation (deferred to Phase 3)

`MUT-SEC-004a`–`d` are **outside** the PROJECT_SPEC.md §7 catalog table. We are intentionally
**not** editing that spec table mid-phase. When the full catalog is consolidated in
Phase 3, revisit the ID scheme then. The part that is genuinely hard to reconstruct later
— and is therefore captured here — is the *reasoning*: the inline-`acl` deprecation and
the **measured target count of 0** for `acl = "private"` across both vetted Cohort A repos
(`Worklytics/psoxy`, `MPeets/cloud-native-deployment-platform`), which is itself an early
empirical finding (the textbook S3 operator barely applies to the modern IaC test
population).
