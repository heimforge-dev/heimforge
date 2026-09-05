"""Shared fixture-generation helper for tests/fixtures/*.

Every fixture renders into a system temp directory (tempfile.mkdtemp), never
under this repository, so no bootstrapper .gitignore handling is needed and
independence from the bootstrapper is proven by construction.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from bootstrap.create_project import generate
from bootstrap.model import ProjectParams
from bootstrap.render import TEMPLATE_DIR
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


def copy_template_to_temp() -> Path:
    """A private, disposable copy of the real `template/` tree that a test
    can freely mutate (inject/delete files) without touching the
    bootstrapper's own template or leaking state to other tests.
    """
    dest = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-template-copy-"))
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True)
    return dest


def generate_into_temp(*, template_dir: Path | None = None, **overrides) -> tuple[ProjectParams, Path, ValidationResult]:
    params = make_params(**overrides)
    output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
    result = generate(params, output_dir, template_dir=template_dir)
    return params, output_dir, result


def expected_relpaths(
    root_namespace: str, *, server_core: bool = True, client: bool = True, shared_diagnostics: bool = True
) -> set[str]:
    """The exact set of files a successful `generate()` must produce:
    every manifest-approved path (post `__ROOT_NAMESPACE__` substitution,
    filtered to the included optional modules) plus the handful of paths
    `generate()`/`suite_metadata.py sync` write programmatically. Shared
    by every test asserting an exact output surface so there is one
    definition of "the expected output" instead of several that could
    silently drift apart.
    """
    from bootstrap.template_manifest import OPTIONAL_TEMPLATE_FILES, REQUIRED_TEMPLATE_FILES

    expected = {rel.replace("__ROOT_NAMESPACE__", root_namespace) for rel in REQUIRED_TEMPLATE_FILES}
    for included, module in (
        (server_core, "server_core"),
        (client, "client"),
        (shared_diagnostics, "shared_diagnostics"),
    ):
        if included:
            expected |= {rel.replace("__ROOT_NAMESPACE__", root_namespace) for rel in OPTIONAL_TEMPLATE_FILES[module]}
    expected |= {
        "suite.config.json",
        f"{root_namespace}.sln",
        "build/Suite.Generated.props",
        f"src/{root_namespace}.Common/SuiteConstants.Generated.cs",
        "packaging/profile-lock.json",
    }
    return expected
