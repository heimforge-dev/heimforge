import importlib
import sys
import unittest
from pathlib import Path

from bootstrap import naming
from bootstrap.model import ProjectParams, build_model, suite_config_dict

TEMPLATE_SCRIPTS = Path(__file__).resolve().parents[2] / "template" / "scripts"


def _load_package_module():
    # Importing directly from template/scripts (rather than a rendered
    # output copy) must never write __pycache__ into the live template —
    # that's exactly the kind of untracked template contamination
    # validate_template() now rejects.
    sys.path.insert(0, str(TEMPLATE_SCRIPTS))
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        import package as pkg

        importlib.reload(pkg)
        return pkg
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        sys.path.remove(str(TEMPLATE_SCRIPTS))


def _definitions_for(**overrides):
    params = ProjectParams(
        suite_name="Vibeheim",
        root_namespace="Vibeheim",
        plugin_guid_root="com.example.vibeheim",
        author="A",
        thunderstore_namespace="NS",
        **overrides,
    )
    cfg = suite_config_dict(build_model(params))
    pkg = _load_package_module()
    return {name: kind for name, _modules, kind in pkg.package_definitions(cfg)}


class PackageDefinitionsTests(unittest.TestCase):
    def test_all_modules_included_produces_five_packages(self):
        names = _definitions_for()
        self.assertEqual(
            set(names),
            {
                "Vibeheim-ServerCore",
                "Vibeheim-Client",
                "Vibeheim-Shared-Diagnostics",
                "Vibeheim-ServerPack",
                "Vibeheim-ClientPack",
            },
        )

    def test_omitted_client_produces_no_empty_client_package(self):
        names = _definitions_for(include_client=False)
        self.assertNotIn("Vibeheim-Client", names)
        self.assertIn("Vibeheim-ServerPack", names)
        self.assertIn("Vibeheim-ClientPack", names)

    def test_omitted_server_core_produces_no_empty_server_core_package(self):
        names = _definitions_for(include_server_core=False)
        self.assertNotIn("Vibeheim-ServerCore", names)
        self.assertIn("Vibeheim-Client", names)

    def test_omitted_shared_diagnostics_drops_shared_module_package(self):
        names = _definitions_for(include_shared_diagnostics=False)
        self.assertNotIn("Vibeheim-Shared-Diagnostics", names)
        self.assertIn("Vibeheim-ServerCore", names)
        self.assertIn("Vibeheim-Client", names)

    def test_everything_omitted_is_rejected_before_a_package_could_be_computed(self):
        with self.assertRaises(naming.NamingError):
            _definitions_for(include_server_core=False, include_client=False, include_shared_diagnostics=False)


if __name__ == "__main__":
    unittest.main()
