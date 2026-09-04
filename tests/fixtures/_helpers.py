"""Shared fixture-generation helper for tests/fixtures/*.

Every fixture renders into a system temp directory (tempfile.mkdtemp), never
under this repository, so no bootstrapper .gitignore handling is needed and
independence from the bootstrapper is proven by construction.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from bootstrap.create_project import generate
from bootstrap.model import ProjectParams
from bootstrap.validate_generated import ValidationResult


def make_params(**overrides) -> ProjectParams:
    defaults = dict(
        suite_name="Sampleheim",
        root_namespace="Sampleheim",
        plugin_guid_root="org.example-tests.sampleheim",
        author="Sample Author",
        thunderstore_namespace="SampleNS",
        suite_version="0.1.0",
    )
    defaults.update(overrides)
    return ProjectParams(**defaults)


def generate_into_temp(**overrides) -> tuple[ProjectParams, Path, ValidationResult]:
    params = make_params(**overrides)
    output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
    result = generate(params, output_dir)
    return params, output_dir, result
