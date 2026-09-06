import unittest

from bootstrap import naming
from bootstrap.model import ProjectParams, build_model, solution_text, suite_config_dict, token_map, validate_params


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


class ModelTests(unittest.TestCase):
    def test_build_model_includes_all_modules_by_default(self):
        model = build_model(make_params())
        names = {m.project_name for m in model.modules}
        self.assertEqual(
            names,
            {"Sampleheim.Common", "Sampleheim.ServerCore", "Sampleheim.Client", "Sampleheim.Shared.Diagnostics"},
        )

    def test_build_model_omits_excluded_modules(self):
        model = build_model(make_params(include_client=False))
        self.assertIsNone(model.client)
        names = {m.project_name for m in model.modules}
        self.assertNotIn("Sampleheim.Client", names)

    def test_suite_config_dict_isolates_client_and_server_packages(self):
        cfg = suite_config_dict(build_model(make_params()))
        packages = cfg["packages"]
        self.assertIn("Sampleheim.ServerCore", packages["serverModules"])
        self.assertIn("Sampleheim.Client", packages["clientOnlyModules"])
        self.assertNotIn("Sampleheim.Client", packages["serverModules"])
        self.assertNotIn("Sampleheim.ServerCore", packages["clientOnlyModules"])

    def test_solution_text_references_every_project_and_test_project(self):
        model = build_model(make_params())
        sln = solution_text(model)
        for module in model.modules:
            self.assertIn(f"src\\{module.project_name}\\{module.project_name}.csproj", sln)
        self.assertIn("tests\\Sampleheim.Common.Tests\\Sampleheim.Common.Tests.csproj", sln)

    def test_module_catalog_rows_omit_excluded_and_never_name_a_feature(self):
        model = build_model(make_params(include_server_core=False))
        tokens = token_map(model)
        self.assertNotIn("ServerCore", tokens["MODULE_CATALOG_ROWS"])
        self.assertNotIn("AutoFeed", tokens["MODULE_CATALOG_ROWS"])

    def test_included_modules_list_reflects_omitted_module(self):
        model = build_model(make_params(include_shared_diagnostics=False))
        tokens = token_map(model)
        self.assertNotIn("Shared.Diagnostics", tokens["INCLUDED_MODULES_LIST"])
        self.assertIn("Sampleheim.ServerCore", tokens["INCLUDED_MODULES_LIST"])

    def test_compatibility_boundaries_list_reflects_omitted_module(self):
        model = build_model(make_params(include_client=False))
        tokens = token_map(model)
        self.assertNotIn("Client:", tokens["COMPATIBILITY_BOUNDARIES_LIST"])
        self.assertIn("ServerCore:", tokens["COMPATIBILITY_BOUNDARIES_LIST"])



    def test_derived_project_names_reject_reserved_device_roots(self):
        for namespace in ("CON", "COM1", "LPT9", "NUL"):
            with self.subTest(namespace=namespace):
                with self.assertRaises(naming.NamingError):
                    validate_params(make_params(root_namespace=namespace))
                with self.assertRaises(naming.NamingError):
                    build_model(make_params(root_namespace=namespace))

    def test_derived_project_names_preserve_portable_namespaces(self):
        for namespace in ("_Private", "Example.Company", "Example.CON"):
            with self.subTest(namespace=namespace):
                params = make_params(root_namespace=namespace)
                validate_params(params)
                self.assertEqual(f"{namespace}.Common", build_model(params).common.project_name)
if __name__ == "__main__":
    unittest.main()
