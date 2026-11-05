
import pytest
from tfmutate import provenance


def test_configuration_signature_changes_with_sources_and_options(tmp_path):
    source = tmp_path / "main.tf"
    source.write_text("# original\n")
    first = provenance.configuration_signature(tmp_path, {"timeout": 10, "operators": ["MUT-RES-002"]})
    assert first == provenance.configuration_signature(tmp_path, {"operators": ["MUT-RES-002"], "timeout": 10})
    assert first != provenance.configuration_signature(tmp_path, {"timeout": 20, "operators": ["MUT-RES-002"]})
    source.write_text("# changed\n")
    assert first != provenance.configuration_signature(tmp_path, {"timeout": 10, "operators": ["MUT-RES-002"]})


def test_completed_artifact_verification_rejects_tampering(tmp_path):
    csv = tmp_path / "tiny.csv"
    csv.write_text("header\n")
    manifest = tmp_path / "tiny.manifest.json"
    provenance.write_manifest(manifest, "signature", csv, {"state": "completed"})
    assert provenance.can_resume(manifest, csv, "signature")
    assert not provenance.can_resume(manifest, csv, "different")
    csv.write_text("tampered\n")
    assert not provenance.can_resume(manifest, csv, "signature")


def test_missing_or_partial_manifest_cannot_resume(tmp_path):
    assert not provenance.can_resume(tmp_path / "missing", tmp_path / "missing.csv", "x")


@pytest.mark.parametrize("name", ["main.tf", "tests/a.tftest.hcl", "main.tf.json", ".terraform.lock.hcl"])
def test_eligible_configuration_hashes_are_recorded(tmp_path, name):
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("first")
    options = {"test_cmd": "tofu test -filter=tests/a.tftest.hcl", "engine_versions": {"tofu": "1.2"}}
    inputs = provenance.configuration_inputs(tmp_path, options)
    assert set(inputs["files"]) == {name}
    assert len(inputs["files"][name]) == 64
    assert inputs["tool_version"]
    assert inputs["catalog_version"]
    assert inputs["schema_version"]
    assert inputs["tool_code_sha256"]
    assert inputs["options"] == options
    first = provenance.configuration_signature(tmp_path, options)
    target.write_text("second")
    assert first != provenance.configuration_signature(tmp_path, options)


def test_signature_excludes_secrets_caches_and_external_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.tf").write_text("# safe")
    options = {"engine_versions": {"terraform": "1"}}
    first = provenance.configuration_signature(root, options)
    for name in [".env", "terraform.tfstate", "secret.tfvars", "credentials.json", ".terraform/cache.tf", ".git/ignored.tf"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("secret")
    outside = tmp_path / "private.tf"
    outside.write_text("external secret")
    (root / "linked.tf").symlink_to(outside)
    assert first == provenance.configuration_signature(root, options)
    changed = {"engine_versions": {"terraform": "2"}}
    assert first != provenance.configuration_signature(root, changed)


def test_signature_changes_with_tool_code_and_catalog(tmp_path, monkeypatch):
    first = provenance.configuration_signature(tmp_path, {})
    monkeypatch.setattr(provenance, "tool_code_hashes", lambda: {"runner.py": "changed"})
    assert first != provenance.configuration_signature(tmp_path, {})
    second = provenance.configuration_signature(tmp_path, {})
    monkeypatch.setattr(provenance, "CATALOG_VERSION", "future")
    assert second != provenance.configuration_signature(tmp_path, {})


def test_manifest_is_atomic_and_partial_or_malformed_records_are_not_resumable(tmp_path, monkeypatch):
    csv = tmp_path / "data.csv"
    csv.write_text("header\n")
    manifest = tmp_path / "data.manifest.json"
    provenance.write_manifest(manifest, "s", csv, {"state": "running"})
    assert not provenance.can_resume(manifest, csv, "s")
    original = manifest.read_bytes()
    def fail_replace(*args):
        raise OSError("interrupted publish")
    monkeypatch.setattr(provenance.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        provenance.write_manifest(manifest, "s", csv, {"state": "completed"})
    assert manifest.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == [csv.name, manifest.name]
    manifest.write_text("[]")
    assert not provenance.can_resume(manifest, csv, "s")
    manifest.write_text("{broken")
    assert not provenance.can_resume(manifest, csv, "s")
