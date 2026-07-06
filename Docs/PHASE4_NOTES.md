# Phase 4 Notes: Classifier Ground-Truth Validation

This document records the design decisions, implementation details, and ground-truth validation for the survival-reason classifier (§8 of [PROJECT_SPEC.md](file:///Users/tusharteotia/Documents/GitHub/Oasis/PROJECT_SPEC.md)).

## 1. Classification Categories & Logic

The classifier inspects the `.tftest.hcl` files of a module to determine *why* a mutant survived. For a given mutated resource address (e.g. `aws_s3_bucket_public_access_block.config`) and attribute name (e.g. `block_public_acls`), the classification logic is as follows:

1. **`no_coverage`**: The mutated resource address does not appear *anywhere* in the content of the `.tftest.hcl` files.
2. **`plan_only_no_assert`**: The resource address is referenced somewhere in the test file (typically via `override_resource { target = <address> }`), but no `assert` block's `condition` references the resource at all.
3. **`weak_assertion`**: The resource address is referenced in one or more `assert` conditions, but the specific mutated attribute is never referenced in any assertion condition.
4. **`n/a`**: The mutant did not survive (it was killed, invalid, timeout, or a no-op).

## 2. Ground-Truth Validation on Real Cohort A Modules

Rather than relying entirely on synthetic tests, the classifier's rules were verified and pinned against real-world test outcomes from the Cohort A corpus. These are implemented as regression tests in [test_classifier.py](file:///Users/tusharteotia/Documents/GitHub/Oasis/tests/test_classifier.py):

### Case A: `no_coverage` validation
*   **Target Module:** `platform-design/aws-config`
*   **Observed Signal:** All four `MUT-SEC-004a–d` public-access-block mutants survived the real `terraform test` execution.
*   **Validation:** Grep-inspection confirmed that the resource `aws_s3_bucket_public_access_block.config` is completely absent from [aws-config.tftest.hcl](file:///Users/tusharteotia/Documents/GitHub/Oasis/corpus/platform-design/terraform/modules/aws-config/aws-config.tftest.hcl). The classifier correctly derived `no_coverage` for all 4 mutants. This is verified by `test_ground_truth_aws_config_no_coverage`.

### Case B: `weak_assertion` validation
*   **Target Module:** `platform-design/aws-ml-artifact-store`
*   **Observed Signal:** Under a live run, three of the `MUT-SEC-004` flags were successfully caught (`killed_assert`), but `MUT-SEC-004c` (`ignore_public_acls`) survived.
*   **Validation:** Inspection of [aws-ml-artifact-store.tftest.hcl](file:///Users/tusharteotia/Documents/GitHub/Oasis/corpus/platform-design/terraform/modules/aws-ml-artifact-store/aws-ml-artifact-store.tftest.hcl) confirmed that while the test suite explicitly asserts `block_public_acls`, `block_public_policy`, and `restrict_public_buckets` to be true, it never asserts on `ignore_public_acls`. The classifier correctly identifies this as `weak_assertion` (the test suite covers the resource but fails to assert on this specific attribute). This is verified by `test_ground_truth_mlflow_weak_assertion`.

### Case C: `plan_only_no_assert` boundary validation
*   **Observed Signal:** This category never fired naturally in the real corpus (see [PHASE5_NOTES.md](file:///Users/tusharteotia/Documents/GitHub/Oasis/PHASE5_NOTES.md)). To prove the classification boundary was genuine, we constructed a fixture under [fixtures/classifier_boundary/main.tftest.hcl](file:///Users/tusharteotia/Documents/GitHub/Oasis/fixtures/classifier_boundary/main.tftest.hcl).
*   **Validation:** The fixture references the target resource within an `override_resource` block to satisfy planning dependencies but contains no assertions against it. A live run confirms that:
    1. The four `MUT-SEC-004a-d` mutants survive `terraform test`.
    2. The classifier correctly maps them to `plan_only_no_assert`.
    3. An untouched sibling resource is correctly classified as `no_coverage` in the same run.
    This boundary is verified by `test_ground_truth_plan_only_no_assert_boundary`.

## 3. Findings & Implications for Phase 6

*   **No Coverage Dominates:** Ground-truth classification of the corpus shows that the vast majority of surviving mutants are due to a complete lack of test coverage (`no_coverage` was derived for 60 of the 71 survived mutants).
*   **Clean Separation:** The validation proves that the three survival reasons represent distinct, clean boundaries in HCL test logic that can be extracted statically without a heavy AST analyzer.
