"""Tiny, offline regression fixtures for source-offset-safe HCL mutation."""

from __future__ import annotations

import pytest

from tfmutate import parser
from tfmutate.mutators import (
    MUT_RES_001, MUT_RES_002, MUT_SEC_001, MUT_SEC_002, MUT_SEC_003,
    MUT_TAG_001, MUT_TAG_002, Operator, generate_mutants,
)


def test_inline_tag_deletions_preserve_neighbor_attributes_and_braces():
    text = 'locals {\n  tags = { team = "platform", owner = "ops", env = "prod" }\n}\n'
    mutants = MUT_TAG_002.generate('main.tf', text)
    assert len(mutants) == 2
    assert mutants[0].mutated_text == text.replace('team = "platform",', '')
    assert mutants[1].mutated_text == text.replace('owner = "ops",', '')


def test_inline_last_tag_deletion_removes_preceding_comma_only():
    text = 'locals { tags = { env = "prod", team = "platform" } }\n'
    [mutant] = MUT_TAG_002.generate('main.tf', text)
    assert mutant.mutated_text == 'locals { tags = { env = "prod" } }\n'


@pytest.mark.parametrize(
    'text, expected',
    [
        ('locals {\n  tags = {\n    team =\n      "platform"\n    env = "prod"\n  }\n}\n',
         'locals {\n  tags = {\n    env = "prod"\n  }\n}\n'),
        ('locals {\n  tags = {\n    /* comment\n    */ team = "platform"\n    env = "prod"\n  }\n}\n',
         'locals {\n  tags = {\n    /* comment\n    */ \n    env = "prod"\n  }\n}\n'),
        ('locals {\n  tags = {\n    team = "platform" /* comment\n    */\n    env = "prod"\n  }\n}\n',
         'locals {\n  tags = {\n     /* comment\n    */\n    env = "prod"\n  }\n}\n'),
    ],
)
def test_tag_deletion_keeps_multiline_assignment_and_comment_boundaries(text, expected):
    [mutant] = MUT_TAG_002.generate('main.tf', text)
    assert mutant.mutated_text == expected


def test_attribute_next_to_inline_tag_map_is_not_a_tag_deletion_site():
    text = 'locals {\n  policy = { tags = { env = "prod" }, owner = "AWS" }\n}\n'
    assert MUT_TAG_002.generate('main.tf', text) == []


def test_tag_deletion_ignores_commented_fake_assignments_inside_map():
    text = 'locals {\n  tags = {\n    # team = "fake"\n    /* owner = "fake" */\n    team = "real"\n  }\n}\n'
    [mutant] = MUT_TAG_002.generate('main.tf', text)
    assert mutant.mutated_text == text.replace('    team = "real"\n', '')


@pytest.mark.parametrize('transform', [lambda key, value: value, lambda key, value: None])
def test_unchanged_or_ineligible_transform_emits_no_mutants(transform):
    op = Operator('TEST', 'test', 'unchanged', ('count',), r'(?P<target>\d+)', transform=transform)
    text = 'resource "aws_instance" "x" { count = 3 }\n'
    assert op.generate('main.tf', text) == []


@pytest.mark.parametrize(
    'header, assignment, op',
    [
        ('resource "aws_instance" "x"', f'count = {expr}', MUT_RES_002)
        for expr in ('2+var.x', '2 + var.x', '2.5', '2e3', '2 ? 3 : 4', '2 /* gap */ + var.x')
    ] + [
        ('variable "instance_count"', 'default = 2+var.x', MUT_RES_002),
        ('resource "aws_ebs_volume" "x"', 'encrypted = true && var.enabled', MUT_SEC_002),
        ('resource "aws_ebs_volume" "x"', 'encrypted = true ? false : true', MUT_SEC_002),
        ('resource "aws_s3_bucket" "x"', 'acl = "private" == var.acl ? "private" : "public-read"', MUT_SEC_001),
        ('resource "aws_instance" "x"', 'instance_type = "${var.instance_type}"', MUT_RES_001),
        ('resource "aws_instance" "x"', 'instance_type = "t3.micro" == var.size ? "t3.micro" : "m5.large"', MUT_RES_001),
        ('resource "aws_security_group" "x"', 'cidr_blocks = ["10.0.0.0/8"][0]', MUT_SEC_003),
        ('resource "aws_security_group" "x"', 'cidr_blocks = ["10.0.0.0/8" == var.cidr ? var.cidr : "10.1.0.0/16"]', MUT_SEC_003),
    ],
)
def test_expression_prefixes_are_not_literal_mutation_sites(header, assignment, op):
    text = f'{header} {{\n  {assignment}\n}}\n'
    assert op.generate('main.tf', text) == []


@pytest.mark.parametrize('suffix', [' # count = 4', ' // count = 4', ' /* trailing */', ' /* multi\nline */'])
def test_actual_literals_with_trailing_comments_still_mutate(suffix):
    text = f'resource "aws_instance" "x" {{\n  count = 3{suffix}\n}}\n'
    [mutant] = MUT_RES_002.generate('main.tf', text)
    assert mutant.mutated_text == text.replace('  count = 3', '  count = 1')


@pytest.mark.parametrize(
    'header, assignment, actual, op',
    [
        ('resource "aws_instance" "x"', 'count = 4', 'count = 3', MUT_RES_002),
        ('variable "max_instance_count"', 'default = 4', 'default = 3', MUT_RES_002),
        ('resource "aws_ebs_volume" "x"', 'encrypted = true', 'encrypted = true', MUT_SEC_002),
        ('locals', 'env = "production"', 'env = "prod"', MUT_TAG_001),
    ],
)
@pytest.mark.parametrize('wrapper', ['# {}', '// {}', '/*\n{}\n*/', 'description = <<EOF\n{}\nEOF'])
def test_only_real_assignments_generate_single_faults(header, assignment, actual, op, wrapper):
    hidden = wrapper.format(assignment)
    text = f'{header} {{\n  {hidden}\n  {actual}\n}}\n'
    mutants = generate_mutants('main.tf', text, [op])
    assert len(mutants) == 1
    [mutant] = mutants
    start = text.rindex(actual)
    assert mutant.mutated_text[:start] == text[:start]
    assert mutant.mutated_text.endswith('}\n')
    assert mutant.original_snippet == actual


@pytest.mark.parametrize(
    'description',
    [
        '"embedded count = 4"',
        r'"escaped \" count = 4"',
        '"${jsonencode({ count = 4 })}"',
    ],
)
def test_embedded_assignments_in_strings_are_not_mutation_sites(description):
    text = f'resource "aws_instance" "x" {{\n  description = {description}\n  count = 3\n}}\n'
    [mutant] = MUT_RES_002.generate('main.tf', text)
    assert mutant.original_value == '3'
    assert mutant.mutated_text == text.replace('  count = 3', '  count = 1')


def test_attribute_synonyms_are_not_suffixes_of_hyphenated_identifiers():
    text = 'resource "aws_instance" "x" {\n  not-count = 4\n  count = 3\n}\n'
    [mutant] = MUT_RES_002.generate('main.tf', text)
    assert mutant.original_value == '3'



@pytest.mark.parametrize(
    "hidden",
    [
        '# count = 4 { "fake" }',
        '// count = 4 { "fake" }',
        '/* count = 4 {\n  encrypted = true\n} */',
        '"count = 4 { encrypted = true }"',
        r'"escaped \" count = 4 { }"',
        '"${jsonencode({ count = 4, description = "}" })}"',
        '"%{ if true } count = 4 %{ endif }"',
        '"$${ literal } count = 4"',
        '<<EOT\ncount = 4 {\n/* not a real comment */\nEOT\n',
        '<<-EOT\n  count = 4 {\n  EOT\n',
    ],
)
def test_code_mask_hides_non_code_and_preserves_character_offsets(hidden):
    prefix = 'locals {\n  note = '
    suffix = '\n  count = 3\n}\n'
    text = prefix + hidden + suffix
    masked = parser.code_mask(text)

    assert len(masked) == len(text)
    assert [i for i, c in enumerate(masked) if c in '\r\n'] == [
        i for i, c in enumerate(text) if c in '\r\n'
    ]
    assert 'count = 4' not in masked
    assert 'encrypted = true' not in masked
    assert masked[text.index('  count = 3'):] == suffix[1:]
    assert masked[:len(prefix)] == prefix


def test_code_mask_preserves_quote_delimiters_and_crlf():
    text = 'name = "é☃ { fake }" /* comment */\r\ncount = 3 // trailing\r\n'
    masked = parser.code_mask(text)
    expected = 'name = "           "              \r\ncount = 3            \r\n'
    # Quote delimiters remain visible; only their contents are blanked.
    assert masked == expected


def test_find_blocks_ignores_commented_headers_and_non_code_braces():
    text = '''/*
resource "aws_instance" "commented" { count = 4 }
*/
// resource "aws_instance" "line_comment" {}
locals {
  note = <<-DOC
    }
    resource "aws_instance" "heredoc" {}
    DOC
  text = "${jsonencode({ note = "}" })}"
  /* } */
}
/* leading comment */ resource "aws_instance" "real" {
  count = 3
}
'''
    blocks = parser.find_blocks(text)
    assert [(b.address, b.start_line, b.end_line) for b in blocks] == [
        ('locals', 5, 12), ('aws_instance.real', 13, 15)
    ]


def test_find_tag_maps_ignores_fake_maps_and_masked_braces():
    text = '''/*
tags = { owner = "fake" }
*/
locals {
  note = <<EOF
tags = { owner = "fake" }
EOF
  common_tags = {
    note = "}"
    /* } */
    team = "real"
  }
}
'''
    assert parser.find_tag_maps(text) == [(8, 12)]


def test_find_tag_maps_supports_inline_maps_without_confusing_string_text():
    text = 'locals { tags = { team = "real" } }\n'
    assert parser.find_tag_maps(text) == [(1, 1)]


@pytest.mark.parametrize('text', ['# trailing', '/* unterminated', '"unterminated', '<<EOF\nunterminated'])
def test_code_mask_handles_unterminated_non_code_conservatively(text):
    masked = parser.code_mask(text)
    assert len(masked) == len(text)
    assert 'unterminated' not in masked
    assert 'trailing' not in masked
