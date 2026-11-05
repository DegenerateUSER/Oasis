"""Unit tests for static NO_OP (override) detection."""

from __future__ import annotations

import textwrap

from types import SimpleNamespace

import pytest

from tfmutate.noop import default_is_shadowed, is_noop, read_tftest_files


@pytest.mark.parametrize("metadata", [{"variable_name": "instance_class"}, {"resource_address": "variable.instance_class"}])
def test_is_noop_uses_actual_variable_name_not_default(tmp_path, metadata):
    (tmp_path / "main.tftest.hcl").write_text(RUN_OVERRIDES)
    mutant = SimpleNamespace(surface="V", attribute="default", **metadata)
    assert is_noop(mutant, tmp_path) is True


def test_is_noop_without_variable_identity_cannot_be_proven(tmp_path):
    (tmp_path / "main.tftest.hcl").write_text('run "x" { variables { default = 1 } }')
    assert is_noop(SimpleNamespace(surface="V", attribute="default"), tmp_path) is False

RUN_OVERRIDES = textwrap.dedent(
    """\
    mock_provider "aws" {}

    run "sized" {
      command = plan
      variables {
        instance_class = "db.t3.large"
      }
    }
    """
)

RUN_USES_DEFAULT = textwrap.dedent(
    """\
    mock_provider "aws" {}

    run "plain" {
      command = plan
    }
    """
)

FILE_LEVEL_OVERRIDE = textwrap.dedent(
    """\
    variables {
      instance_class = "db.t3.large"
    }

    run "a" {
      command = plan
    }
    run "b" {
      command = plan
    }
    """
)


@pytest.mark.parametrize("text", [
    'run "broken" {',
    'run = "not a run block"',
    'run = [{ x = { variables = [{ instance_class = "large" }] } }]',
    'run "x" { variables = [{ instance_class = "large" }] }',
    'variables = [{ instance_class = "large" }]\nrun "x" {}',
    'run "dynamic" { variables { instance_class = run.setup.size } }',
    'run "dynamic" { variables { instance_class = "${var.instance_class}" } }',
    'run "nullable" { variables { instance_class = null } }',
    'run "alternate" { module { source = "./child" }\n variables { instance_class = "large" } }',
])
def test_uncertain_input_cannot_prove_shadowing(text):
    assert default_is_shadowed("instance_class", [RUN_OVERRIDES, text]) is False


def test_run_override_must_not_reintroduce_uncertainty_after_file_literal():
    text = FILE_LEVEL_OVERRIDE + '\nrun "dynamic" { variables { instance_class = run.setup.size } }'
    assert default_is_shadowed("instance_class", [text]) is False


@pytest.mark.parametrize("assignment", [
    'other = var.instance_class',
    'instance_class = { (var.key) = "large" }',
])
def test_unresolved_input_cannot_be_ignored_for_noop(assignment):
    initial = '' if assignment.startswith('instance_class') else 'instance_class = "large"\n'
    text = f'run "x" {{ variables {{ {initial} {assignment} }} }}'
    # Dynamic inputs may depend on the original default; this is not evaluated here.
    assert default_is_shadowed("instance_class", [text]) is False


def test_unreadable_test_file_prevents_noop(tmp_path, monkeypatch):
    path = tmp_path / "main.tftest.hcl"
    path.write_text(RUN_OVERRIDES)
    def fail_read(*args, **kwargs):
        raise OSError("unreadable test")
    monkeypatch.setattr(type(path), "read_text", fail_read)
    mutant = SimpleNamespace(surface="V", attribute="default", resource_address="variable.instance_class")
    assert is_noop(mutant, tmp_path) is False


def test_override_in_run_shadows_default():
    assert default_is_shadowed("instance_class", [RUN_OVERRIDES]) is True


def test_run_without_override_uses_default():
    assert default_is_shadowed("instance_class", [RUN_USES_DEFAULT]) is False


def test_file_level_variables_shadow_every_run():
    assert default_is_shadowed("instance_class", [FILE_LEVEL_OVERRIDE]) is True


def test_mixed_files_not_shadowed_if_any_run_uses_default():
    # One file overrides, another leaves it to the default -> the default is still live.
    assert default_is_shadowed("instance_class", [RUN_OVERRIDES, RUN_USES_DEFAULT]) is False


def test_no_runs_is_not_a_noop():
    assert default_is_shadowed("instance_class", ['mock_provider "aws" {}\n']) is False


def test_read_tftest_files_is_module_scoped_and_nonrecursive(tmp_path):
    (tmp_path / "main.tftest.hcl").write_text("root")
    for directory, content in [("tests", "selected"), ("examples/demo/tests", "unrelated"), ("tests/fixtures/child", "nested")]:
        folder = tmp_path / directory
        folder.mkdir(parents=True)
        (folder / "main.tftest.hcl").write_text(content)
    assert read_tftest_files(tmp_path) == ["root", "selected"]


def test_read_tftest_files_accepts_custom_test_directory(tmp_path):
    for directory in ["checks", "tests"]:
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "main.tftest.hcl").write_text(directory)
    assert read_tftest_files(tmp_path, test_directory="checks") == ["checks"]


@pytest.mark.parametrize("directory", ["../unrelated", "/unrelated"])
def test_test_directory_must_stay_within_the_module(tmp_path, directory):
    with pytest.raises(ValueError, match="within the module"):
        read_tftest_files(tmp_path, test_directory=directory)


def test_is_noop_accepts_explicit_module_directory(tmp_path):
    module = tmp_path / "modules" / "selected"
    module.mkdir(parents=True)
    (module / "main.tftest.hcl").write_text(RUN_OVERRIDES)
    (tmp_path / "unrelated.tftest.hcl").write_text(RUN_USES_DEFAULT)
    mutant = SimpleNamespace(surface="V", attribute="default", resource_address="variable.instance_class")
    assert is_noop(mutant, tmp_path, module_dir=module) is True


def test_read_tftest_files_excludes_dot_terraform(tmp_path):
    (tmp_path / "main.tftest.hcl").write_text('mock_provider "aws" {}\n')
    vendored = tmp_path / ".terraform" / "modules" / "some_dep"
    vendored.mkdir(parents=True)
    (vendored / "main.tftest.hcl").write_text('mock_provider "aws" {}\nrun "x" { command = plan }\n')

    texts = read_tftest_files(tmp_path)
    assert texts == ['mock_provider "aws" {}\n']
