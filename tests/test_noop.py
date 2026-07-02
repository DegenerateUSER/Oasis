"""Unit tests for static NO_OP (override) detection."""

from __future__ import annotations

import textwrap

from tfmutate.noop import default_is_shadowed

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
