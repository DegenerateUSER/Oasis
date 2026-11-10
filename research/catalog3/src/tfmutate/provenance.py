"""Configuration-aware, content-verified run completion records.

Only Terraform source/test/JSON configuration and provider lock files are read
from target repositories. State, variable values, credentials and environments
are never collected. Engine versions are supplied by the caller in options.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import __version__
from .mutators import CATALOG_VERSION

MANIFEST_SCHEMA_VERSION = 3


def resume_context_is_known(root: Path) -> bool:
    """Refuse reuse with unrecorded variable/workspace inputs; never read secrets."""
    if any(key.startswith(("TF_VAR_", "TF_CLI_ARGS")) or key == "TF_WORKSPACE" for key in os.environ):
        return False
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if d not in {".git", ".terraform"} and not (base / d).is_symlink()]
        if any(name in {"terraform.tfvars", "terraform.tfvars.json"}
               or name.endswith((".auto.tfvars", ".auto.tfvars.json")) for name in files):
            return False
    return True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_code_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parent
    return {str(p.relative_to(package)): _sha256(p) for p in sorted(package.rglob("*.py")) if not p.name.startswith("._")}


def configuration_inputs(root: Path, options: dict) -> dict:
    """Return auditable signature inputs, without collecting source contents."""
    root = Path(root).resolve()
    hashes = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in {".git", ".terraform"}
                         and not (base / d).is_symlink())
        for name in sorted(files):
            p = base / name
            if (not name.startswith("._") and not p.is_symlink() and p.is_file() and p.resolve().is_relative_to(root)
                    and (name.endswith((".tf", ".tf.json", ".tftest.hcl", ".tofu", ".tofu.json", ".tofutest.hcl"))
                         or name == ".terraform.lock.hcl")):
                hashes[str(p.relative_to(root))] = _sha256(p)
    try:
        hcl_version = version("python-hcl2")
    except PackageNotFoundError:
        hcl_version = "unavailable"
    return {"schema_version": MANIFEST_SCHEMA_VERSION, "catalog_version": CATALOG_VERSION,
            "tool_version": __version__, "tool_code_sha256": tool_code_hashes(),
            "runtime_versions": {"python": sys.version.split()[0], "python-hcl2": hcl_version},
            "files": hashes, "options": options}


def configuration_signature(root: Path, options: dict) -> str:
    payload = configuration_inputs(root, options)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def write_manifest(path: Path, signature: str, csv: Path, metadata: dict) -> None:
    """Publish the completion marker last, using an atomic same-directory rename."""
    path, csv = Path(path), Path(csv)
    payload = dict(metadata)
    artifacts = [csv, *(Path(p) for p in payload.pop("artifact_paths", []))]
    artifact_hashes = {}
    base = path.parent.resolve()
    for artifact in artifacts:
        if artifact.is_symlink() or not artifact.resolve().is_relative_to(base):
            raise ValueError(f"unsafe artifact path: {artifact}")
        artifact_hashes[str(artifact.resolve().relative_to(base))] = _sha256(artifact)
    payload.update(schema_version=MANIFEST_SCHEMA_VERSION, signature=signature,
                   csv_sha256=_sha256(csv), artifacts_sha256=artifact_hashes,
                   completed=metadata.get("state") == "completed")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def can_resume(path: Path, csv: Path, signature: str, *, require_resumable: bool = True) -> bool:
    try:
        path, csv = Path(path), Path(csv)
        if path.is_symlink() or csv.is_symlink():
            return False
        payload = json.loads(path.read_text())
        if not (isinstance(payload, dict)
                and payload.get("schema_version") == MANIFEST_SCHEMA_VERSION
                and payload.get("completed") is True
                and payload.get("state") == "completed"
                and payload.get("signature") == signature
                and payload.get("csv_sha256") == _sha256(csv)):
            return False
        if require_resumable and payload.get("resume_allowed", True) is not True:
            return False
        hashes = payload.get("artifacts_sha256")
        if not isinstance(hashes, dict) or not hashes:
            return False
        base = path.parent.resolve()
        for relative, expected in hashes.items():
            artifact = base / relative
            if (Path(relative).is_absolute() or artifact.is_symlink()
                    or not artifact.resolve().is_relative_to(base)
                    or _sha256(artifact) != expected):
                return False
        return True
    except (OSError, ValueError, TypeError):
        return False
