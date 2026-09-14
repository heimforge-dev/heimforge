"""Regression coverage for the optional-module rendering/empty-runtime
issue: generated operational documents must never name a module or
package family that this specific generation omits, across every
supported optional-module combination.

Every scenario renders through the real `generate()` pipeline into a
disposable temp directory -- never the live `template/` tree.
"""

import itertools
import unittest

from tests.fixtures._helpers import generate_into_temp

VALID_COMBINATIONS = [c for c in itertools.product((True, False), repeat=3) if any(c)]


def _lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines()}


def _expected_side_note(side_label: str, standard_module: str | None, shared_diagnostics: bool) -> str:
    """Independently reconstructs the exact side-membership sentence from
    the combo's own ground-truth flags -- not by calling
    `bootstrap.model.deploy_side_notes_lines()` -- so a regression in that
    function's logic actually fails this test instead of only asserting
    against itself."""
    parts = ["Common"]
    if standard_module:
        parts.append(standard_module)
    if shared_diagnostics:
        parts.append("Shared.Diagnostics")
    return f"{side_label} receives {' + '.join(parts)}."


class NoStaleModuleReferencesTests(unittest.TestCase):
    def test_operational_documents_never_name_an_omitted_module(self):
        for server_core, client, shared_diagnostics in VALID_COMBINATIONS:
            with self.subTest(server_core=server_core, client=client, shared_diagnostics=shared_diagnostics):
                params, output_dir, result = generate_into_temp(
                    include_server_core=server_core,
                    include_client=client,
                    include_shared_diagnostics=shared_diagnostics,
                )
                self.assertTrue(result.ok, result.errors)
                ns = params.root_namespace
                has_server_package = server_core or shared_diagnostics
                has_client_package = client or shared_diagnostics

                prompt = (output_dir / "BOOTSTRAP_PROMPT.md").read_text(encoding="utf-8")
                current_state = (output_dir / ".context" / "CURRENT_STATE.md").read_text(encoding="utf-8")
                release = (output_dir / "docs" / "release.md").read_text(encoding="utf-8")
                readme = (output_dir / "README.md").read_text(encoding="utf-8")
                project_spec = (output_dir / "docs" / "PROJECT_SPEC.md").read_text(encoding="utf-8")
                release_lines = _lines(release)
                readme_lines = _lines(readme)

                if not server_core:
                    self.assertNotIn(f"{ns}.ServerCore", prompt)
                    self.assertNotIn("ServerCore must not require clients to install it.", prompt)
                    self.assertNotIn(f"`{ns}.ServerCore`", current_state)
                    self.assertNotIn("- ServerCore", release_lines)
                if not client:
                    self.assertNotIn(f"{ns}.Client", prompt)
                    self.assertNotIn("Client must not require servers to install it.", prompt)
                    self.assertNotIn(f"`{ns}.Client`", current_state)
                    self.assertNotIn("- Client", release_lines)
                if not shared_diagnostics:
                    self.assertNotIn(f"{ns}.Shared.Diagnostics", prompt)
                    self.assertNotIn("Shared Diagnostics must be safe on both sides", prompt)
                    self.assertNotIn("Milestone 2 diagnostics", prompt)
                    self.assertNotIn("Shared Diagnostics proves the CustomRPC", prompt)
                    self.assertNotIn(f"`{ns}.Shared.Diagnostics`", current_state)
                    self.assertNotIn("- one ZIP per Shared Module", release_lines)
                    self.assertNotIn("Shared Diagnostics RPC runtime proof", readme)
                    self.assertIn("Not applicable: Shared.Diagnostics was not generated for this suite.", project_spec)
                else:
                    self.assertIn("- Shared Diagnostics RPC runtime proof", readme)
                    self.assertNotIn("Shared Diagnostics RPC implementation/runtime proof", readme)
                    self.assertIn(
                        "Shared Diagnostics proves CustomRPC request/response, module/version reporting, and "
                        "multiplayer plumbing without changing gameplay state.",
                        project_spec,
                    )
                self.assertNotIn("{{PROJECT_SPEC_MILESTONE2_BODY}}", project_spec)
                self.assertNotIn("{{", project_spec)

                server_note_lines = {line for line in readme_lines if line.startswith("Server receives")}
                client_note_lines = {line for line in readme_lines if line.startswith("Client receives")}

                if not has_server_package:
                    self.assertNotIn("Server build:", current_state)
                    self.assertNotIn("- ServerPack", release_lines)
                    self.assertFalse((output_dir / "packaging" / "server" / "README.md").exists())
                    self.assertNotIn("./scripts/deploy-server.sh Debug", readme_lines)
                    self.assertEqual(set(), server_note_lines)
                    self.assertNotIn(
                        "+-- deploy server DLLs to the Linux/Docker dedicated server", readme_lines
                    )
                else:
                    self.assertIn("- ServerPack", release_lines)
                    self.assertTrue((output_dir / "packaging" / "server" / "README.md").exists())
                    self.assertIn("./scripts/deploy-server.sh Debug", readme_lines)
                    expected_server_note = _expected_side_note(
                        "Server", "ServerCore" if server_core else None, shared_diagnostics
                    )
                    self.assertEqual({expected_server_note}, server_note_lines)

                if not has_client_package:
                    self.assertNotIn("Client build:", current_state)
                    self.assertNotIn("- ClientPack", release_lines)
                    self.assertFalse((output_dir / "packaging" / "client" / "README.md").exists())
                    self.assertNotIn("./scripts/deploy-client.sh Debug", readme_lines)
                    self.assertEqual(set(), client_note_lines)
                    self.assertNotIn(
                        "+-- deploy client DLLs to Windows Valheim through /mnt/c/...", readme_lines
                    )
                else:
                    self.assertIn("- ClientPack", release_lines)
                    self.assertTrue((output_dir / "packaging" / "client" / "README.md").exists())
                    self.assertIn("./scripts/deploy-client.sh Debug", readme_lines)
                    expected_client_note = _expected_side_note(
                        "Client", "Client" if client else None, shared_diagnostics
                    )
                    self.assertEqual({expected_client_note}, client_note_lines)

                # Section 13: the empty-runtime product invariant is always stated,
                # regardless of which specific combination was generated.
                self.assertIn(
                    "at least one of the three must be enabled -- a generation request disabling all three is "
                    "rejected before this repository is created.",
                    readme,
                )


if __name__ == "__main__":
    unittest.main()
