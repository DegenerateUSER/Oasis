"""Optional OFFLINE schema validation using an explicitly supplied cached AWS provider."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tfmutate.mutators import MUT_SEC_001, generate_mutants


@pytest.mark.provider_integration
def test_public_read_acl_mutant_passes_cached_aws_provider_schema(tmp_path):
    mirror = os.environ.get("OASIS_AWS_PLUGIN_DIR")
    version = os.environ.get("OASIS_AWS_VERSION")
    if not mirror or not version or not shutil.which("terraform"):
        pytest.skip("set OASIS_AWS_PLUGIN_DIR and OASIS_AWS_VERSION to an existing provider mirror")
    assert Path(mirror).is_dir()
    source = tmp_path / "main.tf"
    source.write_text('terraform {\n required_providers {\n aws = {\n source = "hashicorp/aws"\n version = "=%s"\n }\n }\n}\nresource "aws_s3_bucket_acl" "example" {\n bucket = "oasis-offline-schema-check"\n acl = "private"\n}\n' % version)
    mutants = generate_mutants(source, source.read_text(), [MUT_SEC_001])
    assert len(mutants) == 1 and mutants[0].mutated_value == "public-read"
    source.write_text(mutants[0].mutated_text)
    config = tmp_path / "offline.tfrc"
    config.write_text("disable_checkpoint = true\n")
    env = dict(os.environ, TF_CLI_CONFIG_FILE=str(config))
    init = subprocess.run(["terraform", "init", "-backend=false", "-no-color", f"-plugin-dir={mirror}"],
                          cwd=tmp_path, capture_output=True, text=True, env=env, timeout=20)
    assert init.returncode == 0, init.stdout + init.stderr
    result = subprocess.run(["terraform", "validate", "-no-color"], cwd=tmp_path,
                            capture_output=True, text=True, env=env, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
