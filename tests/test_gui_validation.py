"""Read-only preview and strict, bounded executable/configuration validation."""
import subprocess

import pytest

SOURCE = '''variable "desired_count" {
  type = number
  default = 2
}
resource "terraform_data" "example" {
  count = 2
  input = var.desired_count
}
'''
TEST = '''run "small_plan" {
  command = plan
  assert {
    condition = length(terraform_data.example) == 2
    error_message = "instance count requirement"
  }
}
'''


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True, timeout=10)


@pytest.fixture
def tiny_repo(tmp_path):
    root = tmp_path / 'tiny'
    root.mkdir()
    (root / 'main.tf').write_text(SOURCE)
    (root / 'main.tftest.hcl').write_text(TEST)
    git(root, 'init')
    git(root, 'add', 'main.tf', 'main.tftest.hcl')
    git(root, '-c', 'user.name=Oasis Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'tiny provider-free fixture')
    return root


def test_preview_is_read_only_and_uses_shared_mutators(tmp_path, tiny_repo, monkeypatch):
    from tfmutate.gui.validation import preview
    from tfmutate.runner import Runner
    monkeypatch.setattr(Runner, 'run_module', lambda *_: pytest.fail('preview cannot execute'))
    result = preview({'target_path': str(tiny_repo), 'engine': 'terraform',
                      'operators': ['MUT-RES-002']}, tmp_path / 'state')
    assert result['modules'] == ['.']
    assert len(result['mutants']) == 2
    assert result['mutants'][0]['operator_id'] == 'MUT-RES-002'
    assert any('-  default = 2' in mutant['diff'] for mutant in result['mutants'])
    assert result['warnings']  # syntax/validation/baseline are not execution evidence
    assert result['truncated'] is False
    assert (tiny_repo / 'main.tf').read_text() == SOURCE
    assert not (tiny_repo / '.terraform').exists()
    assert git(tiny_repo, 'status', '--porcelain').stdout == ''


@pytest.mark.parametrize('changes', [
    {'engine': '/bin/sh'}, {'engine': 'terraform;id'}, {'operators': ['not-an-operator']},
    {'operators': []}, {'operators': 'MUT-RES-002'}, {'test_directory': '../outside'},
    {'test_directory': '/absolute'}, {'test_directory': '-flag'}, {'unknown': True},
])
def test_preview_rejects_untrusted_command_inputs(tmp_path, tiny_repo, changes):
    from tfmutate.gui.validation import preview
    with pytest.raises(ValueError):
        preview({'target_path': str(tiny_repo), 'engine': 'terraform', **changes}, tmp_path / 'state')


def test_preview_refuses_dirty_missing_test_and_symlink_escape(tmp_path, tiny_repo):
    from tfmutate.gui.validation import preview
    body = {'target_path': str(tiny_repo), 'engine': 'terraform'}
    (tiny_repo / 'main.tf').write_text(SOURCE + '#dirty\n')
    with pytest.raises(ValueError, match='dirty'):
        preview(body, tmp_path / 'state')
    (tiny_repo / 'main.tf').write_text(SOURCE)
    (tiny_repo / 'escape.tf').symlink_to(tmp_path / 'outside.tf')
    with pytest.raises(ValueError, match='symlink|unsafe'):
        preview(body, tmp_path / 'state')
    (tiny_repo / 'escape.tf').unlink()
    with pytest.raises(ValueError, match='outside|state|overlap'):
        preview(body, tiny_repo / 'state')
    (tiny_repo / 'main.tftest.hcl').rename(tiny_repo / 'no-test.txt')
    git(tiny_repo, 'add', '-A')
    git(tiny_repo, '-c', 'user.name=Oasis Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'no tests')
    with pytest.raises(ValueError, match='test'):
        preview(body, tmp_path / 'state')


@pytest.mark.parametrize('changes', [
    {'acknowledge_execution': False}, {'acknowledge_execution': 1},
    {'max_mutants': 0}, {'max_mutants': 5001}, {'max_mutants': True},
    {'budget_seconds': 7201}, {'timeout': 301}, {'timeout': 1.2},
    {'init_timeout': 0}, {'init_attempts': 4}, {'command': 'echo bad'},
])
def test_job_limits_are_validated_before_execution(tmp_path, tiny_repo, changes):
    from tfmutate.gui.validation import validate_job
    with pytest.raises(ValueError):
        validate_job({'target_path': str(tiny_repo), 'engine': 'terraform',
                      'operators': ['MUT-RES-002'], 'acknowledge_execution': True, **changes}, tmp_path / 'state')


def test_preview_honestly_reports_empty_sites_and_truncates(tmp_path, tiny_repo, monkeypatch):
    import tfmutate.gui.validation as module
    monkeypatch.setattr(module, 'MAX_PREVIEW', 1)
    result = module.preview({'target_path': str(tiny_repo), 'engine': 'terraform',
                             'operators': ['MUT-RES-002']}, tmp_path / 'state')
    assert len(result['mutants']) == 1 and result['truncated']
    result = module.preview({'target_path': str(tiny_repo), 'engine': 'terraform',
                             'operators': ['MUT-SEC-001']}, tmp_path / 'state')
    assert result['mutants'] == []
    assert any('no eligible' in warning.lower() for warning in result['warnings'])
