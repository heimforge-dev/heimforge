import importlib
import sys
import unittest
from pathlib import Path

from bootstrap.model import ProjectParams, build_model, suite_config_dict

TEMPLATE_SCRIPTS = Path(__file__).resolve().parents[2] / "template" / "scripts"


def _load_package_module():
    sys.path.insert(0, str(TEMPLATE_SCRIPTS))
    try:
        import package as pkg

        importlib.reload(pkg)
        return pkg
    finally:
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

    def test_everything_omitted_produces_no_packages_at_all(self):
        names = _definitions_for(include_server_core=False, include_client=False, include_shared_diagnostics=False)
        self.assertEqual({}, names)


if __name__ == "__main__":
    unittest.main()
