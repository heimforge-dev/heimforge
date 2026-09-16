import unittest

from tests.fixtures._helpers import generate_into_temp


class GenerateDefaultTests(unittest.TestCase):
    def test_default_generation_validates_cleanly(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((output_dir / f"{params.root_namespace}.sln").is_file())
        diagnostics = (
            output_dir
            / "src"
            / f"{params.root_namespace}.Common"
            / "Diagnostics"
            / "RuntimeDiagnostics.cs"
        )
        self.assertTrue(diagnostics.is_file())
        self.assertIn(
            f"namespace {params.root_namespace}.Common.Diagnostics;",
            diagnostics.read_text(encoding="utf-8"),
        )

    def test_bootstrapper_attribution_survives_validation(self):
        _params, output_dir, result = generate_into_temp()
        readme = (output_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("HeimForge", readme)
        self.assertTrue(result.ok, result.errors)


    def test_generated_shared_diagnostics_contains_bounded_rpc_handshake(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        server_plugin = (output_dir / "src" / f"{params.root_namespace}.ServerCore" / "Plugin.cs").read_text()
        plugin = (output_dir / "src" / f"{params.root_namespace}.Shared.Diagnostics" / "Plugin.cs").read_text()
        rpc = (output_dir / "src" / f"{params.root_namespace}.Shared.Diagnostics" / "DiagnosticRpc.cs").read_text()
        bootstrap_prompt = (output_dir / "BOOTSTRAP_PROMPT.md").read_text()
        self.assertIn("new DiagnosticRpc(Logger)", plugin)
        self.assertEqual(1, rpc.count("AddRPC("))
        self.assertIn("AddRPC(RpcName, OnServerReceive, OnClientReceive)", rpc)
        self.assertIn("args.InitialSynchronization", rpc)
        self.assertIn("IsClientInstance()", rpc)
        compatibility_check = rpc.index("ModCompatibility.IsModuleOnServer")
        pending_clear = rpc.index("pendingAcknowledgementConnection = null;")
        pending_set = rpc.index("pendingAcknowledgementConnection = znet;")
        server_duplicate_guard = rpc.index("acknowledgedPeers.Add(peer)")
        server_log = rpc.index("diagnostic ping received from peer")
        client_duplicate_guard = rpc.index("ReferenceEquals(pendingAcknowledgementConnection, znet)")
        client_log = rpc.index("RPC acknowledgement received")
        self.assertLess(pending_clear, compatibility_check)
        self.assertLess(compatibility_check, pending_set)
        self.assertLess(server_duplicate_guard, server_log)
        self.assertLess(client_duplicate_guard, client_log)
        self.assertIn("HashSet<ZNetPeer>", rpc)
        self.assertIn("var connectedPeers = znet.GetConnectedPeers();", rpc)
        self.assertIn("acknowledgedPeers.RemoveWhere(peer => !connectedPeers.Contains(peer))", rpc)
        self.assertNotIn("znet.m_peers", rpc)
        self.assertIn("var serverPeer = znet ? znet.GetServerPeer() : null;", rpc)
        self.assertIn("serverPeer == null", rpc)
        self.assertIn("sender != serverPeer.m_uid", rpc)
        self.assertIn("SendPackageRoutine(sender", rpc)
        self.assertIn("OnConfigurationSynchronized -=", rpc)
        self.assertNotIn("pingSent", rpc)
        self.assertIn('"graphical"', plugin)
        self.assertIn('"graphical"', server_plugin)
        self.assertNotIn("graphical client", plugin)
        self.assertNotIn("graphical listen server", server_plugin)
        self.assertIn("one remote client-to-server diagnostic ping", bootstrap_prompt)
        self.assertNotIn("Vibeheim", rpc)
        self.assertNotIn("intentionally left", plugin)


if __name__ == "__main__":
    unittest.main()
