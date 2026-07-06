# Mutation operator specification (synonyms, scoping, surface)

This is the **methodology reference** for the operator catalog — the authoritative mapping
from each fault operator to the concrete HCL it matches. It is maintained as a standalone,
citable document (droppable into a paper's *Methods* section); `PHASE1_NOTES.md` records
*why* the catalog deviates from the original spec, this document records *what* it matches.

## Matching model

A mutation operator fires on a **site** = one attribute assignment in a `.tf` file. Three
rules govern whether a site matches:

1. **Attribute synonyms.** Each operator matches a curated set of attribute names, not one
   literal name, because real modules use synonyms (`instance_type` vs `instance_class`).
2. **Resource-type scoping.** In a resource body, a synonym only matches when its
   **enclosing resource type** is in the operator's allowed set. This prevents an attribute
   named, say, `encrypted` on an unrelated resource from being mutated as if it were storage
   encryption. Scoping is `(resource_type, attribute)`, never attribute-in-isolation.
3. **Surface.** Modern Cohort A modules parameterise values, so operators may target three
   surfaces: **R** = resource body, **V** = `variable {} default`, **L** = `locals {}`
   (incl. tag maps). On the **V** and **L** surfaces there is no enclosing resource type, so
   scoping falls back to the **name** (variable name / local key / tag key) matching the
   synonym set. Every mutant records the exact attribute, line, resource (or var/local), and
   surface in the CSV, so analysis granularity lives in the data regardless of operator ID.

A site is skipped (not mutated) when its value is a `var.*`/`local.*`/expression reference
rather than a literal, or when the mutated value would equal the original (equivalent).

## Value-transform note (RES-001 sizing)

"Scale up" cannot be one literal across families, so the operator maps to a representative
**much-larger** size per attribute family. Under `mock_provider` the size is not validated
against a cloud, so an over-large-but-well-formed token faithfully represents the
"over-provisioning / cost" fault. Exact targets are listed below and are illustrative of
the fault, not a claim that the specific SKU is optimal-plus-one.

## Catalog

Legend — Surface: R=resource body, V=variable default, L=locals/tags. **Validation** is the
status that matters for methodological honesty and must be carried through to the report table
verbatim — never collapsed into an undifferentiated "all working" claim:
- **CORPUS** = produces a syntactically-valid mutant on a live site in the real corpus
  (`psoxy`, `cloud-native-deployment-platform`, `platform-design`), verified via `terraform fmt`.
- **FIXTURE** = operator works (unit-tested + `terraform fmt`-valid) but has **no real target**
  in the terraform-test population; validated only on `fixtures/thin_operators/`. This is not a
  weakness of the operator — it is the disjointness finding (see PHASE1_NOTES.md + `evidence/`).

| ID | Category | Attribute synonyms | Resource-type scope | Surface | Original → Mutated | Validation |
|---|---|---|---|---|---|---|
| MUT-SEC-001 | security | `acl` | `aws_s3_bucket`, `aws_s3_bucket_acl` | R | `"private"` → `"public"` | **FIXTURE** |
| MUT-SEC-004a | security | `block_public_acls` | `aws_s3_bucket_public_access_block` | R | `true` → `false` | CORPUS |
| MUT-SEC-004b | security | `block_public_policy` | `aws_s3_bucket_public_access_block` | R | `true` → `false` | CORPUS |
| MUT-SEC-004c | security | `ignore_public_acls` | `aws_s3_bucket_public_access_block` | R | `true` → `false` | CORPUS |
| MUT-SEC-004d | security | `restrict_public_buckets` | `aws_s3_bucket_public_access_block` | R | `true` → `false` | CORPUS |
| MUT-SEC-002 | security | `encrypted`, `storage_encrypted` | `aws_ebs_volume`, `aws_ebs_snapshot`, `aws_db_instance`, `aws_rds_cluster`, `aws_dax_cluster`, `aws_elasticache_replication_group`, `aws_docdb_cluster`, `aws_neptune_cluster` | R | `true` → `false` | CORPUS |
| MUT-SEC-003 | security | `cidr_block`, `cidr_blocks` | `aws_security_group`, `aws_security_group_rule`, `aws_vpc_security_group_ingress_rule` | R | restrictive CIDR → `"0.0.0.0/0"` | **FIXTURE** |
| MUT-RES-001 | resource | `instance_type`, `instance_class`, `node_type`, `machine_type` | `aws_instance`, `aws_launch_template`, `aws_db_instance`, `aws_elasticache_cluster`, `google_compute_instance` | R, V | small size → representative XL (see below) | CORPUS |
| MUT-RES-002 | resource | `count`, `desired_count`, `desired_capacity`, `min_size` | any (meta-arg) / autoscaling & service resources | R, V | int ≥ 2 → `1` | CORPUS |
| MUT-RES-003 | resource | `replicas`, `replica_count`, `min_replicas` | k8s/helm & scaling resources | R, V | int ≥ 1 → `0` | CORPUS |
| MUT-TAG-001 | compliance | `env`, `environment`, `Environment` | tags maps / any | R, V, L | `"production"`/`"prod"` → `"development"`/`"dev"` | CORPUS |
| MUT-TAG-002 | compliance | `team`, `owner`, `cost_center` | tags maps (scoped) | R, L | *(entry deleted)* | **FIXTURE** |

**Validation summary: 9/12 CORPUS-validated, 3/12 FIXTURE-validated** (MUT-SEC-001, MUT-SEC-003, MUT-TAG-002).

> **`encrypt` (Terraform S3 backend state-encryption) is intentionally excluded** from
> MUT-SEC-002: it is a `terraform { backend "s3" {} }` setting, not a resource attribute, so
> it cannot be resource-type-scoped per Q2. It is a different fault surface (state, not
> infrastructure) and is out of scope for the resource-oriented catalog.

### RES-001 representative XL targets (by attribute family)

| Attribute | Family | Mutated-to (representative over-provisioned size) |
|---|---|---|
| `instance_type` | AWS EC2 | `m5.24xlarge` |
| `instance_class` | AWS RDS | `db.r5.24xlarge` |
| `node_type` | AWS ElastiCache | `cache.r6g.16xlarge` |
| `machine_type` | GCP Compute | `n2-standard-128` |

## Operator numbering

IDs follow PROJECT_SPEC.md §7 exactly (no renumbering mid-project — deferred to Phase 3). The
`MUT-SEC-004a–d` set is the only addition, documented in `PHASE1_NOTES.md`. Where an
operator spans several synonym attributes (e.g. SEC-002), it keeps a single §7 ID and
disambiguates per-mutant in the CSV rather than fragmenting into per-attribute IDs (Q4).

## Open items feeding later phases

- **Corpus:** adding `platform-design` (Cohort A, 119 mock_provider test files) supplied real
  targets for RES-003 (`replicas = 2`) and TAG-001 (`Environment = "production"`), taking
  the catalog to **9/12 operators validated on real files**.
- **SEC-001 and SEC-003 — resolved as FIXTURE-validated.** Authenticated GitHub code search
  proved these targets are structurally absent from the terraform-test population (46 Cohort A
  repos: 0 ACL/CIDR literals; 86 `acl = "private"` repos: 0 `.tftest.hcl`). Rather than widen
  the Cohort A definition to chase them (rejected) or reformulate the fault (rejected), they
  are validated on `fixtures/thin_operators/` and both remain in the v1 catalog. The
  disjointness is a headline finding — see PHASE1_NOTES.md and `evidence/`.
- **NO_OP validity check**: a mutant on a **V**-surface default is inert if a `.tftest.hcl`
  run block overrides that variable. Such mutants must be classified `NO_OP` (a category
  distinct from `INVALID` and from `SURVIVED`/`KILLED`) so they never inflate the
  "tests missed this" numbers. Mechanism under discussion (see PHASE1_NOTES / spec §6).
