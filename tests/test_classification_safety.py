"""Synthetic static-evidence regressions; never invoke Terraform or a corpus."""

from types import SimpleNamespace

import pytest

from tfmutate.classifier import classify_outcomes, classify_survival

RESOURCE = "aws_s3_bucket.main"
ATTRIBUTE = "acl"


def test_condition_not_error_message_is_the_evidence():
    text = f'''run "x" {{ command = plan
      assert {{ condition = true
        error_message = "{RESOURCE}.{ATTRIBUTE} is wrong" }}
    }}'''
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "no_coverage"


@pytest.mark.parametrize("condition", [
    '"aws_s3_bucket.main.acl" == "literal"',
    'true /* aws_s3_bucket.main.acl */',
    'aws_s3_bucket.main_extra.acl == "private"',
    'other_aws_s3_bucket.main.acl == "private"',
])
def test_non_reference_mentions_do_not_count(condition):
    text = f'run "x" {{ command = plan\n assert {{ condition = {condition}\n error_message = "bad" }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "no_coverage"


@pytest.mark.parametrize("reference", [
    "aws_s3_bucket.main[0].acl",
    'aws_s3_bucket.main["instance"].acl',
    "aws_s3_bucket.main[*].acl",
    "aws_s3_bucket.main.*.acl",
    "aws_s3_bucket.main[var.selected].acl",
    "(aws_s3_bucket.main).acl",
])
def test_indexed_resource_attribute_is_direct_evidence(reference):
    text = f'run "x" {{ assert {{ condition = {reference} != null }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "attribute_asserted_survived"


@pytest.mark.parametrize("address", ["variable.enable_encryption", "var.enable_encryption"])
def test_variable_default_metadata_matches_var_condition(address):
    text = 'run "x" { assert { condition = var.enable_encryption == true } }'
    assert classify_survival(address, "default", [text]) == "attribute_asserted_survived"


def test_variable_name_prefix_collision_is_not_a_reference():
    text = 'run "x" { assert { condition = var.enable_encryption_extra == true } }'
    assert classify_survival("variable.enable_encryption", "default", [text]) == "no_coverage"


def test_attribute_name_prefix_collision_is_weak_not_direct():
    text = f'run "x" {{ assert {{ condition = {RESOURCE}.acl_extra == "private" }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "weak_assertion"


@pytest.mark.parametrize("condition", [
    'output.bucket_acl == "private"',
    'module.child.bucket_acl == "private"',
    'run.setup.bucket_acl == "private"',
    'local.expected_acl == "private"',
    f'{RESOURCE}.bucket != "" && output.bucket_acl == "private"',
    f'alltrue([for bucket in [{RESOURCE}] : bucket.acl == "private"])',
])
def test_unresolved_indirect_assertions_are_unknown(condition):
    text = f'run "x" {{ assert {{ condition = {condition} }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "unknown"


@pytest.mark.parametrize("texts", [
    ['run "broken" {'],
    [f'run "x" {{ assert {{ condition = {RESOURCE}.acl == "private" }} }}', 'run "broken" {'],
    [],
])
def test_incomplete_or_unparseable_evidence_is_unknown(texts):
    assert classify_survival(RESOURCE, ATTRIBUTE, texts) == "unknown"


@pytest.mark.parametrize("command", ["apply", None])
def test_resource_override_without_plan_is_unknown_not_plan_only(command):
    command_text = f"command = {command}" if command else ""
    text = f'''run "x" {{ {command_text}
      override_resource {{ target = {RESOURCE}\n values = {{ acl = "private" }} }}
    }}'''
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "unknown"


def test_plan_in_different_run_does_not_explain_apply_reference():
    text = f'''run "planned" {{ command = plan }}
    run "applied" {{ command = apply
      override_resource {{ target = {RESOURCE}\n values = {{ acl = "private" }} }}
    }}'''
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "unknown"


@pytest.mark.parametrize("condition", [
    f'{RESOURCE}[var.attribute] == "private"',
    f'lookup({RESOURCE}, var.attribute, "") == "private"',
    f'{RESOURCE} == {{ acl = "private" }}',
])
def test_unresolved_attribute_selection_cannot_prove_weak_assertions(condition):
    text = f'run "x" {{ assert {{ condition = {condition} }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "unknown"


def test_direct_mutated_attribute_in_nested_map_condition_is_distinct():
    text = f'''run "x" {{ command = plan
      assert {{
        condition = lookup({{ actual = {RESOURCE}.acl }}, "actual", "") == "private"
        error_message = "bad"
      }}
    }}'''
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "attribute_asserted_survived"


@pytest.mark.parametrize("condition, expected", [
    ('"$${aws_s3_bucket.main.acl}" == "x"', "no_coverage"),
    ('"${jsonencode({ note = "aws_s3_bucket.main.acl" })}" != "x"', "no_coverage"),
    ('"${jsonencode({ actual = aws_s3_bucket.main.acl })}" != "x"', "attribute_asserted_survived"),
    ('"%{ if aws_s3_bucket.main.acl != null }x%{ endif }" == "x"', "attribute_asserted_survived"),
    ('trimspace(<<EOF\naws_s3_bucket.main.acl\nEOF\n) == "x"', "no_coverage"),
    ('trimspace(<<EOF\n$${aws_s3_bucket.main.acl}\nEOF\n) == "x"', "no_coverage"),
    ('trimspace(<<EOF\n${aws_s3_bucket.main.acl}\nEOF\n) == "x"', "unknown"),
    ('"%{ for bucket in [aws_s3_bucket.main] }${bucket.acl}%{ endfor }" == "x"', "unknown"),
])
def test_nested_templates_do_not_manufacture_or_hide_reference_evidence(condition, expected):
    text = f'run "x" {{ assert {{ condition = {condition} }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == expected


def test_template_reference_in_error_message_is_not_condition_evidence():
    text = f'''run "x" {{ assert {{ condition = true
      error_message = "${{{RESOURCE}.acl}}" }} }}'''
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "no_coverage"


@pytest.mark.parametrize("condition", [
    'alltrue([for aws_s3_bucket in [{ main = { acl = "private" } }] : aws_s3_bucket.main.acl == "private"])',
    '"%{ for aws_s3_bucket in [{ main = { acl = "private" } }] }${aws_s3_bucket.main.acl}%{ endfor }" == "private"',
])
def test_loop_alias_cannot_masquerade_as_resource_namespace(condition):
    text = f'run "x" {{ assert {{ condition = {condition} }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "unknown"


def test_resource_used_as_instance_selector_is_also_reference_evidence():
    text = f'run "x" {{ assert {{ condition = aws_s3_bucket.other[{RESOURCE}.acl].bucket != "" }} }}'
    assert classify_survival(RESOURCE, ATTRIBUTE, [text]) == "attribute_asserted_survived"


@pytest.mark.parametrize("module_dir, file_mutated, expected", [
    (".", "main.tf", "attribute_asserted_survived"),
    ("modules/root", "modules/root/main.tf", "attribute_asserted_survived"),
    (".", "modules/child/main.tf", "unknown"),
    ("modules/root", "modules/root/child/main.tf", "unknown"),
    ("modules/root", "modules/alternate/main.tf", "unknown"),
    (".", "", "unknown"),
    ("", "modules/child/main.tf", "attribute_asserted_survived"),
])
def test_outcome_classification_requires_resolved_execution_module(module_dir, file_mutated, expected):
    text = f'run "x" {{ assert {{ condition = {RESOURCE}.acl == "private" }} }}'
    outcome = SimpleNamespace(test_status="survived", resource_or_var=RESOURCE,
                              attribute=ATTRIBUTE, survival_reason="n/a",
                              module_dir=module_dir, file_mutated=file_mutated)
    outcomes = [outcome]
    assert classify_outcomes(outcomes, [text]) is outcomes
    assert outcome.survival_reason == expected


def test_legacy_outcome_without_module_metadata_is_still_classified():
    text = f'run "x" {{ assert {{ condition = {RESOURCE}.acl == "private" }} }}'
    outcome = SimpleNamespace(test_status="survived", resource_or_var=RESOURCE,
                              attribute=ATTRIBUTE, survival_reason="n/a")
    classify_outcomes([outcome], [text])
    assert outcome.survival_reason == "attribute_asserted_survived"


def test_non_survivor_outcome_is_not_reclassified_for_child_module():
    outcome = SimpleNamespace(test_status="killed_assert", survival_reason="n/a",
                              module_dir=".", file_mutated="modules/child/main.tf")
    classify_outcomes([outcome], [])
    assert outcome.survival_reason == "n/a"
