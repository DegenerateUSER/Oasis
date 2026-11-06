"""Preview must not execute repository hooks or construct unbounded mutant copies."""
import os
import shlex
import subprocess

import pytest

from tfmutate.gui import validation


def git(root, *args):
    return subprocess.run(
        ['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
         '-c', 'commit.gpgSign=false', '-C', str(root), *args],
        check=True, capture_output=True, text=True, timeout=10,
    )


@pytest.fixture
def preview_repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'main.tf').write_text('resource "terraform_data" "example" {\n  count = 2\n}\n')
    (root / 'main.tftest.hcl').write_text('run "preview" {\n  command = plan\n}\n')
    git(root, 'init')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Preview Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'provider-free preview fixture')
    return root


@pytest.mark.parametrize('has_tests', [True, False])
def test_preview_never_executes_configured_fsmonitor(tmp_path, preview_repo, has_tests):
    root = preview_repo
    if not has_tests:
        (root / 'main.tftest.hcl').unlink()
        git(root, 'add', '-A')
        git(root, '-c', 'user.name=Preview Test', '-c', 'user.email=test@example.invalid',
            'commit', '-m', 'no selected tests')
    marker = tmp_path / 'fsmonitor-ran'
    hook = root / '.git' / 'preview-fsmonitor'
    hook.write_text('#!/bin/sh\n: > ' + shlex.quote(str(marker)) + "\nprintf 'preview-token\\0/\\0'\n")
    hook.chmod(0o700)
    git(root, 'config', 'core.fsmonitor', shlex.quote(str(hook)))
    # Positive control: this real Git version honors the harmless configured hook.
    subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'],
                   check=True, capture_output=True, text=True, timeout=10)
    assert marker.exists(), 'positive control did not execute the configured fsmonitor'
    marker.unlink()

    body = {'target_path': str(root), 'engine': 'terraform', 'operators': ['MUT-RES-002']}
    if has_tests:
        assert len(validation.preview(body, tmp_path / 'state')['mutants']) == 1
    else:
        with pytest.raises(ValueError, match='no selected'):
            validation.preview(body, tmp_path / 'state')
    assert not marker.exists(), 'read-only preview executed repository core.fsmonitor'


def test_preview_bounds_full_mutant_construction(tmp_path, preview_repo, monkeypatch):
    from tfmutate.mutators import Operator

    text = ''.join(f'resource "terraform_data" "site_{i}" {{\n  count = 2\n}}\n' for i in range(300))
    (preview_repo / 'main.tf').write_text(text)
    git(preview_repo, 'add', 'main.tf')
    git(preview_repo, '-c', 'user.name=Preview Test', '-c', 'user.email=test@example.invalid',
        'commit', '-m', 'many lexical sites')
    monkeypatch.setattr(validation, 'MAX_PREVIEW', 1)
    original = Operator._substitution
    constructed = []

    def bounded_substitution(self, *args, **kwargs):
        assert len(constructed) < 2, 'preview constructed beyond its one result plus one sentinel'
        mutant = original(self, *args, **kwargs)
        constructed.append(mutant)
        return mutant

    monkeypatch.setattr(Operator, '_substitution', bounded_substitution)
    result = validation.preview(
        {'target_path': str(preview_repo), 'engine': 'terraform', 'operators': ['MUT-RES-002']},
        tmp_path / 'state',
    )
    assert len(result['mutants']) == 1
    assert result['truncated'] is True
    assert len(constructed) == 2


def test_preview_shares_remaining_budget_and_stops_later_files_and_scopes(tmp_path, monkeypatch):
    from tfmutate.scope import MutationScope

    first, second, later = [tmp_path / name for name in ('a.tf', 'b.tf', 'unread.tf')]
    first.write_text('resource "terraform_data" "first" {\n count = 2\n}\n')
    second.write_text('resource "terraform_data" "second" {\n' + ' count = 2\n' * 300 + '}\n')
    scopes = [(tmp_path, MutationScope([first, first, second, later], [], [])),
              (tmp_path / 'later-module', MutationScope([later], [], []))]
    config = {'operators': ['MUT-RES-002']}
    monkeypatch.setattr(validation, '_validate', lambda *_args, **_kwargs: (config, tmp_path, scopes))
    monkeypatch.setattr(validation, 'MAX_PREVIEW', 2)
    original = validation.generate_mutants
    calls = []

    def bounded_generate(path, text, operators, *, limit):
        assert path != later, 'preview continued reading after the truncation sentinel'
        calls.append((path, limit))
        return original(path, text, operators, limit=limit)

    monkeypatch.setattr(validation, 'generate_mutants', bounded_generate)
    result = validation.preview({}, tmp_path / 'state')
    assert len(result['mutants']) == 2
    assert result['truncated'] is True
    assert calls == [(first, 3), (second, 2)]


@pytest.mark.parametrize('sites', [0, 1, 2, 3])
def test_preview_distinguishes_exact_cap_from_truncation(tmp_path, monkeypatch, sites):
    from tfmutate.scope import MutationScope

    path = tmp_path / 'main.tf'
    path.write_text('resource "terraform_data" "example" {\n' + ' count = 2\n' * sites + '}\n')
    scopes = [(tmp_path, MutationScope([path], [], []))]
    config = {'operators': ['MUT-RES-002']}
    monkeypatch.setattr(validation, '_validate', lambda *_args, **_kwargs: (config, tmp_path, scopes))
    monkeypatch.setattr(validation, 'MAX_PREVIEW', 2)
    result = validation.preview({}, tmp_path / 'state')
    assert len(result['mutants']) == min(sites, 2)
    assert result['truncated'] is (sites > 2)
