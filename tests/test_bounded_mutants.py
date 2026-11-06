"""Optional generation limits bound construction, not just the returned list."""
import pytest

import tfmutate.mutators as mutators
from tfmutate.mutators import MUT_RES_002, MUT_RES_003, MUT_TAG_001, MUT_TAG_002, Operator, generate_mutants


@pytest.mark.parametrize('operator,text,constructor', [
    (MUT_RES_002, ''.join(f'resource "terraform_data" "r{i}" {{\n count = 2\n}}\n' for i in range(300)), '_substitution'),
    (MUT_RES_002, ''.join(f'variable "desired_count_{i}" {{\n default = 2\n}}\n' for i in range(300)), '_substitution'),
    (MUT_TAG_001, 'locals {\n' + ' environment = "production"\n' * 300 + '}\n', '_substitution'),
    (MUT_TAG_002, 'locals {\n tags = {\n' + ' owner = "team"\n' * 300 + ' }\n}\n', '_deletion'),
    (MUT_RES_002, 'resource "terraform_data" "r" {\n count = 2\n}\n' +
     ''.join(f'variable "desired_count_{i}" {{\n default = 2\n}}\n' for i in range(300)), '_substitution'),
], ids=['resource', 'variable', 'locals', 'deletion', 'resource-then-variable'])
def test_operator_limit_stops_before_extra_full_text(monkeypatch, operator, text, constructor):
    expected = operator.generate('main.tf', text)
    original = getattr(Operator, constructor)
    constructed = []

    def bounded_constructor(self, *args, **kwargs):
        assert len(constructed) < 2, 'attempted a full mutant allocation beyond the limit'
        mutant = original(self, *args, **kwargs)
        constructed.append(mutant)
        return mutant

    monkeypatch.setattr(Operator, constructor, bounded_constructor)
    result = operator.generate('main.tf', text, limit=2)
    assert result == expected[:2]
    assert len(constructed) == 2


def test_generate_mutants_spends_one_shared_construction_budget(monkeypatch):
    text = ('resource "terraform_data" "r" {\n count = 2\n desired_count = 3\n' +
            ' replicas = 2\n' * 300 + ' environment = "production"\n}\n')
    operators = [MUT_RES_002, MUT_RES_003, MUT_TAG_001]
    expected = generate_mutants('main.tf', text, operators)
    original = Operator._substitution
    constructed = []

    def bounded_substitution(self, *args, **kwargs):
        assert len(constructed) < 3, 'each operator must share the remaining construction budget'
        mutant = original(self, *args, **kwargs)
        constructed.append(mutant)
        return mutant

    monkeypatch.setattr(Operator, '_substitution', bounded_substitution)
    monkeypatch.setattr(MUT_TAG_001, 'generate', lambda *_args, **_kwargs: pytest.fail('later operators must not scan'))
    result = generate_mutants('main.tf', text, operators, limit=3)
    assert result == expected[:3]
    assert [mutant.operator_id for mutant in result] == ['MUT-RES-002', 'MUT-RES-002', 'MUT-RES-003']
    assert len(constructed) == 3


@pytest.mark.parametrize('direct_operator', [False, True])
def test_zero_limit_does_not_scan_source(monkeypatch, direct_operator):
    monkeypatch.setattr(mutators, 'code_mask', lambda *_: pytest.fail('zero limit must not scan source'))
    if direct_operator:
        result = MUT_RES_002.generate('main.tf', 'not inspected', limit=0)
    else:
        result = generate_mutants('main.tf', 'not inspected', limit=0)
    assert result == []


@pytest.mark.parametrize('direct_operator', [False, True])
def test_negative_limit_is_rejected(direct_operator):
    with pytest.raises(ValueError, match='limit'):
        if direct_operator:
            MUT_RES_002.generate('main.tf', '', limit=-1)
        else:
            generate_mutants('main.tf', '', limit=-1)


@pytest.mark.parametrize('limit', [0, 1, 2, 3, 4, 10, None])
def test_limit_preserves_existing_order_and_skips_equivalent_sites(limit):
    text = ('resource "terraform_data" "r" {\n count = 1\n desired_count = 3\n replicas = 2\n}\n'
            'variable "desired_count" {\n default = 2\n}\n')
    expected = generate_mutants('main.tf', text)
    assert len(expected) == 3
    assert generate_mutants('main.tf', text, limit=limit) == expected[:limit]
