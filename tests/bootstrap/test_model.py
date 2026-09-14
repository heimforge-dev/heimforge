import json
import unittest
from pathlib import Path

from bootstrap import naming
from bootstrap.model import DEPENDENCY_BASELINE, ProjectParams, build_model, identity_lock_dict, solution_text, suite_config_dict, token_map, validate_params


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

    def test_build_model_rejects_all_optional_modules_omitted(self):
        with self.assertRaises(naming.NamingError) as ctx:
            build_model(
                make_params(include_server_core=False, include_client=False, include_shared_diagnostics=False)
            )
        self.assertIn("at least one runtime module", str(ctx.exception))

    def test_validate_params_rejects_all_optional_modules_omitted(self):
        with self.assertRaises(naming.NamingError):
            validate_params(
                make_params(include_server_core=False, include_client=False, include_shared_diagnostics=False)
            )

    def test_has_server_package_true_only_when_server_core_or_shared_diagnostics_present(self):
        self.assertTrue(build_model(make_params(include_client=False, include_shared_diagnostics=False)).has_server_package)
        self.assertTrue(build_model(make_params(include_server_core=False, include_client=False)).has_server_package)
        self.assertFalse(build_model(make_params(include_server_core=False, include_shared_diagnostics=False)).has_server_package)

    def test_has_client_package_true_only_when_client_or_shared_diagnostics_present(self):
        self.assertTrue(build_model(make_params(include_server_core=False, include_shared_diagnostics=False)).has_client_package)
        self.assertTrue(build_model(make_params(include_server_core=False, include_client=False)).has_client_package)
        self.assertFalse(build_model(make_params(include_client=False, include_shared_diagnostics=False)).has_client_package)

    def test_runtime_module_constraints_list_omits_excluded_module(self):
        tokens = token_map(build_model(make_params(include_client=False)))
        self.assertNotIn("Client must not require", tokens["RUNTIME_MODULE_CONSTRAINTS_LIST"])
        self.assertIn("ServerCore must not require", tokens["RUNTIME_MODULE_CONSTRAINTS_LIST"])

    def test_bootstrap_diagnostics_milestone_present_only_with_shared_diagnostics(self):
        with_diag = token_map(build_model(make_params()))["BOOTSTRAP_DIAGNOSTICS_MILESTONE"]
        without_diag = token_map(build_model(make_params(include_shared_diagnostics=False)))["BOOTSTRAP_DIAGNOSTICS_MILESTONE"]
        self.assertIn("Milestone 2 diagnostics", with_diag)
        self.assertEqual("", without_diag)

    def test_bootstrap_milestones_proven_clause_reflects_diagnostics_presence(self):
        self.assertIn("Milestones 0-2", token_map(build_model(make_params()))["BOOTSTRAP_MILESTONES_PROVEN_CLAUSE"])
        without_diag = token_map(build_model(make_params(include_shared_diagnostics=False)))["BOOTSTRAP_MILESTONES_PROVEN_CLAUSE"]
        self.assertIn("Milestones 0-1", without_diag)

    def test_release_and_side_package_family_lists_match_package_definitions_gating(self):
        model = build_model(make_params(include_server_core=False))
        tokens = token_map(model)
        self.assertNotIn("ServerCore", tokens["RELEASE_PACKAGE_FAMILIES_LIST"])
        self.assertIn("ServerPack", tokens["RELEASE_PACKAGE_FAMILIES_LIST"])  # Shared.Diagnostics still reaches the server side
        self.assertNotIn("ServerCore", tokens["SERVER_PACKAGE_FAMILY_LIST"])
        self.assertIn("ServerPack", tokens["SERVER_PACKAGE_FAMILY_LIST"])

    def test_side_package_family_list_empty_when_that_side_has_no_package(self):
        client_only = build_model(make_params(include_server_core=False, include_shared_diagnostics=False))
        server_only = build_model(make_params(include_client=False, include_shared_diagnostics=False))
        self.assertEqual("", token_map(client_only)["SERVER_PACKAGE_FAMILY_LIST"])
        self.assertEqual("", token_map(server_only)["CLIENT_PACKAGE_FAMILY_LIST"])

    def test_initial_milestones_list_renumbers_when_diagnostics_omitted(self):
        with_diag = token_map(build_model(make_params()))["INITIAL_MILESTONES_LIST"]
        without_diag = token_map(build_model(make_params(include_shared_diagnostics=False)))["INITIAL_MILESTONES_LIST"]
        self.assertIn("2. Shared Diagnostics CustomRPC proof.", with_diag)
        self.assertNotIn("Shared Diagnostics", without_diag)
        self.assertIn("2. First real feature", without_diag)

    def test_current_state_build_status_lines_omit_absent_package_side(self):
        both_sides = token_map(build_model(make_params()))["CURRENT_STATE_BUILD_STATUS_LINES"]
        self.assertEqual(
            "- Server build: NOT RUN IN USER ENVIRONMENT\n- Client build: NOT RUN IN USER ENVIRONMENT",
            both_sides,
        )

        client_only = build_model(make_params(include_server_core=False, include_shared_diagnostics=False))
        lines = token_map(client_only)["CURRENT_STATE_BUILD_STATUS_LINES"]
        self.assertEqual("- Client build: NOT RUN IN USER ENVIRONMENT", lines)

    def test_project_spec_milestone2_body_reflects_diagnostics_presence(self):
        self.assertIn("CustomRPC", token_map(build_model(make_params()))["PROJECT_SPEC_MILESTONE2_BODY"])
        without_diag = token_map(build_model(make_params(include_shared_diagnostics=False)))["PROJECT_SPEC_MILESTONE2_BODY"]
        self.assertIn("Not applicable", without_diag)

    def test_pending_proof_lists_omit_diagnostics_line_when_absent(self):
        without_diag = build_model(make_params(include_shared_diagnostics=False))
        tokens = token_map(without_diag)
        self.assertNotIn("Shared Diagnostics", tokens["PENDING_RUNTIME_PROOF_LIST"])
        self.assertNotIn("Shared Diagnostics", tokens["HARDENING_PENDING_PROOF_LIST"])
        self.assertIn("- Shared Diagnostics RPC runtime proof", token_map(build_model(make_params()))["PENDING_RUNTIME_PROOF_LIST"])

    def test_deploy_side_notes_name_exactly_the_modules_that_side_receives(self):
        server_core_and_diagnostics = token_map(
            build_model(make_params(include_client=False))
        )["DEPLOY_SIDE_NOTES_LIST"]
        self.assertIn("Server receives Common + ServerCore + Shared.Diagnostics.", server_core_and_diagnostics)
        self.assertIn("Client receives Common + Shared.Diagnostics.", server_core_and_diagnostics)
        self.assertNotIn("Client receives Common + Shared.Diagnostics + Client", server_core_and_diagnostics)

        client_and_diagnostics = token_map(
            build_model(make_params(include_server_core=False))
        )["DEPLOY_SIDE_NOTES_LIST"]
        self.assertIn("Server receives Common + Shared.Diagnostics.", client_and_diagnostics)
        self.assertIn("Client receives Common + Client + Shared.Diagnostics.", client_and_diagnostics)
        self.assertNotIn("ServerCore", client_and_diagnostics)

        server_core_only = token_map(
            build_model(make_params(include_client=False, include_shared_diagnostics=False))
        )["DEPLOY_SIDE_NOTES_LIST"]
        self.assertEqual("Server receives Common + ServerCore.", server_core_only)

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

    def test_validate_params_rejects_malformed_thunderstore_namespace(self):
        """Original bug: `ProjectParams(thunderstore_namespace="Bad Name!")`
        passed generator-time validation via the generic `validate_label`."""
        with self.assertRaises(naming.NamingError):
            validate_params(make_params(thunderstore_namespace="Bad Name!"))

    def test_validate_params_rejects_malformed_semver(self):
        """Original bug: `01.2.3` and `1.2.3-alpha..1` passed
        generator-time SemVer validation."""
        for bad in ("01.2.3", "1.2.3-alpha..1", "1.2.3-..."):
            with self.subTest(bad=bad):
                with self.assertRaises(naming.NamingError):
                    validate_params(make_params(suite_version=bad))

    def test_validate_params_accepts_valid_build_metadata_semver(self):
        validate_params(make_params(suite_version="1.2.3-alpha+build.1"))

    def test_validate_params_accepts_suite_name_at_max_length(self):
        """template/scripts/deploy.py's deployment manifest filename is
        f".{suiteName}.deploy-manifest.json"; naming.MAX_SUITE_NAME_LENGTH
        is exactly the longest suiteName that keeps that filename within
        the common 255-byte filesystem component limit."""
        validate_params(make_params(suite_name="S" * naming.MAX_SUITE_NAME_LENGTH))

    def test_validate_params_rejects_suite_name_over_max_length(self):
        with self.assertRaises(naming.NamingError):
            validate_params(make_params(suite_name="S" * (naming.MAX_SUITE_NAME_LENGTH + 1)))

    def test_identity_lock_dict_contains_only_suite_name_root_namespace_and_schema_version(self):
        """The baseline must stay a minimal companion to suite.config.json:
        just the field(s) that already determined physical repository
        structure/external identity at render time, not a second copy of
        the whole config."""
        lock = identity_lock_dict(build_model(make_params()))
        self.assertEqual({"schemaVersion", "suiteName", "rootNamespace"}, set(lock))
        self.assertEqual(1, lock["schemaVersion"])
        self.assertEqual("Sampleheim", lock["suiteName"])
        self.assertEqual("Sampleheim", lock["rootNamespace"])

    def test_identity_lock_dict_matches_suite_config_dict_identity_fields(self):
        model = build_model(make_params(suite_name="Auditheim", root_namespace="ExampleCompany.Skogtind"))
        cfg = suite_config_dict(model)
        lock = identity_lock_dict(model)
        self.assertEqual(cfg["suiteName"], lock["suiteName"])
        self.assertEqual(cfg["rootNamespace"], lock["rootNamespace"])

    def test_bootstrap_manifest_dependency_baseline_matches_model(self):
        manifest = json.loads(Path("BOOTSTRAP_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "Jotunn": DEPENDENCY_BASELINE["jotunn_version"],
                "BepInExPack_Valheim": DEPENDENCY_BASELINE["bepinex_version"],
                "Microsoft.NETFramework.ReferenceAssemblies": DEPENDENCY_BASELINE["netfx_reference_version"],
            },
            manifest["dependencyBaseline"],
        )


if __name__ == "__main__":
    unittest.main()
