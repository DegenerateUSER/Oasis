"""Scope resolution tests use tiny in-memory Terraform trees only."""
import pytest


def test_scope_excludes_unreferenced_descendants(tmp_path):
    from tfmutate.scope import resolve_scope
    (tmp_path / "main.tf").write_text('resource "terraform_data" "root" {}\n')
    other = tmp_path / "examples"
    other.mkdir()
    (other / "main.tf").write_text('resource "terraform_data" "other" {}\n')
    scope = resolve_scope(tmp_path, tmp_path)
    assert scope.files == [tmp_path / "main.tf"]


def test_scope_includes_only_referenced_local_modules(tmp_path):
    from tfmutate.scope import resolve_scope
    (tmp_path / "main.tf").write_text('module "child" {\n source = "./child"\n}\n')
    child = tmp_path / "child"
    child.mkdir()
    (child / "main.tf").write_text('resource "terraform_data" "child" {}\n')
    scope = resolve_scope(tmp_path, tmp_path)
    assert set(scope.files) == {tmp_path / "main.tf", child / "main.tf"}


def test_alternate_test_module_does_not_exercise_root(tmp_path):
    from tfmutate.scope import resolve_scope
    (tmp_path / "main.tf").write_text('resource "terraform_data" "root" {}\n')
    child = tmp_path / "fixture"
    child.mkdir()
    (child / "main.tf").write_text('resource "terraform_data" "fixture" {}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "x" {\n module {\n source = "./fixture"\n }\n}\n')
    scope = resolve_scope(tmp_path, tmp_path)
    assert scope.files == [child / "main.tf"]


def test_test_filter_and_custom_directory_are_respected(tmp_path):
    from tfmutate.scope import resolve_scope
    (tmp_path / "main.tf").write_text('resource "terraform_data" "root" {}\n')
    tests = tmp_path / "checks"
    tests.mkdir()
    (tests / "one.tftest.hcl").write_text('run "one" {}\n')
    (tests / "two.tftest.hcl").write_text('run "two" {}\n')
    scope = resolve_scope(tmp_path, tmp_path, 'terraform test -test-directory=checks -filter=checks/one.tftest.hcl')
    assert scope.test_files == [tests / "one.tftest.hcl"]
    assert scope.has_runs


def test_scope_does_not_follow_symlink_outside_repo(tmp_path):
    from tfmutate.scope import resolve_scope, ScopeError
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "main.tf").write_text('resource "terraform_data" "outside" {}\n')
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    (tmp_path / "main.tf").write_text('module "escape" {\n source = "./escape"\n}\n')
    with pytest.raises(ScopeError, match="outside"):
        resolve_scope(tmp_path, tmp_path)


def test_numeric_expansion_does_not_hide_referenced_modules(tmp_path):
    from tfmutate.scope import resolve_scope
    (tmp_path / "main.tf").write_text('module "child" { source = "./child" }\n')
    (tmp_path / "locals.tf").write_text('locals { x = cidrsubnets("10.0.0.0/8", [for i in [1, 2] : 8]...) }\n')
    child = tmp_path / "child"
    child.mkdir()
    (child / "main.tf").write_text('resource "terraform_data" "child" {}\n')
    (tmp_path / "main.tftest.hcl").write_text('run "plan" { command = plan }\n')
    scope = resolve_scope(tmp_path, tmp_path)
    assert scope.has_runs
    assert not scope.warnings
    assert set(scope.files) == {tmp_path / "main.tf", tmp_path / "locals.tf", child / "main.tf"}


def test_numeric_expansion_fallback_still_rejects_escaping_source(tmp_path):
    from tfmutate.scope import resolve_scope, ScopeError
    (tmp_path / "main.tf").write_text('locals { x = cidrsubnets("10.0.0.0/8", [for i in [1] : 8]...) }\nmodule "bad" { source = "../outside" }\n')
    with pytest.raises(ScopeError, match="outside repository"):
        resolve_scope(tmp_path, tmp_path)
