import re
import unittest

from bootstrap.create_project import parse_args, resolve_params
from tests.fixtures._helpers import generate_into_temp


AGENT_TOOLING_FILES = {
    "AGENTS.md",
    "BOOTSTRAP_PROMPT.md",
    ".agents/skills/harmony-reverse-engineering/SKILL.md",
    ".agents/skills/valheim-modding/SKILL.md",
    ".agents/skills/valheim-networking/SKILL.md",
    ".agents/skills/valheim-release/SKILL.md",
    ".context/CONTEXT.md",
    ".context/_meta/schema.md",
    ".context/_templates/finding.md",
    ".context/findings/CONTEXT.md",
    ".context/findings/valheim-runtime.md",
    ".context/references/CONTEXT.md",
    ".context/references/architecture.md",
    ".context/references/networking.md",
    ".context/references/patching.md",
    ".context/references/project.md",
    ".context/references/testing.md",
    ".context/state/CONTEXT.md",
    ".context/state/current.md",
}

OMP_ADAPTER_FILES = {
    ".omp/extensions/valheim-dev/README.md",
    ".omp/extensions/valheim-dev/index.ts",
    ".omp/prompts/bootstrap-valheim.md",
}


def _files(root):
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    }


def _cli_params(*extra):
    args = parse_args(
        [
            "--name", "Sampleheim",
            "--guid", "org.example-tests.sampleheim",
            "--author", "Sample Author",
            "--thunderstore-namespace", "SampleNS",
            "--output", "/tmp/sampleheim-agent-cli-test",
            *extra,
        ]
    )
    return resolve_params(args)[0]


class AgentIntegrationTests(unittest.TestCase):
    def test_default_generation_includes_portable_agent_tooling_without_harness_adapter(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(params.include_agent_tooling)
        self.assertEqual((), params.agent_adapters)

        files = _files(output_dir)
        self.assertTrue(AGENT_TOOLING_FILES <= files)
        self.assertTrue((output_dir / ".agents" / "skills").is_dir())
        self.assertFalse((output_dir / ".omp").exists())

    def test_no_agent_tooling_removes_only_the_portable_agent_layer(self):
        _default_params, default_dir, default_result = generate_into_temp()
        self.assertTrue(default_result.ok, default_result.errors)

        params, output_dir, result = generate_into_temp(
            include_agent_tooling=False,
        )
        self.assertTrue(result.ok, result.errors)
        self.assertFalse(params.include_agent_tooling)
        self.assertEqual((), params.agent_adapters)

        default_files = _files(default_dir)
        bare_files = _files(output_dir)

        self.assertEqual(AGENT_TOOLING_FILES, default_files - bare_files)
        self.assertEqual(bare_files, default_files - AGENT_TOOLING_FILES)
        for rel in sorted(bare_files):
            self.assertEqual(
                (default_dir / rel).read_bytes(),
                (output_dir / rel).read_bytes(),
                rel,
            )
        self.assertFalse((output_dir / ".agents").exists())
        self.assertFalse((output_dir / ".context").exists())
        self.assertFalse((output_dir / "AGENTS.md").exists())
        self.assertFalse((output_dir / "BOOTSTRAP_PROMPT.md").exists())
        self.assertFalse((output_dir / ".omp").exists())

    def test_omp_adapter_is_strictly_additive_to_portable_agent_tooling(self):
        _default_params, default_dir, default_result = generate_into_temp()
        self.assertTrue(default_result.ok, default_result.errors)

        params, output_dir, result = generate_into_temp(
            agent_adapters=("omp",),
        )
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(params.include_agent_tooling)
        self.assertEqual(("omp",), params.agent_adapters)

        default_files = _files(default_dir)
        omp_files = _files(output_dir)

        self.assertEqual(OMP_ADAPTER_FILES, omp_files - default_files)
        self.assertEqual(default_files, omp_files - OMP_ADAPTER_FILES)
        for rel in sorted(default_files):
            self.assertEqual(
                (default_dir / rel).read_bytes(),
                (output_dir / rel).read_bytes(),
                rel,
            )

    def test_default_generated_tree_has_no_provider_specific_agent_references(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        forbidden_literals = (
            ".omp/",
            "@oh-my-pi",
            "oh-my-pi",
            "Context7",
            "Context Mode",
        )
        for path in output_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = str(path.relative_to(output_dir))

            with self.subTest(path=rel, marker="OMP"):
                self.assertIsNone(re.search(r"\\bOMP\\b", text))

            for marker in forbidden_literals:
                with self.subTest(path=rel, marker=marker):
                    self.assertNotIn(marker, text)

    def test_cli_defaults_to_portable_agent_tooling(self):
        params = _cli_params()
        self.assertTrue(params.include_agent_tooling)
        self.assertEqual((), params.agent_adapters)

    def test_cli_can_disable_agent_tooling(self):
        params = _cli_params("--no-agent-tooling")
        self.assertFalse(params.include_agent_tooling)
        self.assertEqual((), params.agent_adapters)

    def test_cli_can_add_omp_adapter(self):
        params = _cli_params("--agent-adapter", "omp")
        self.assertTrue(params.include_agent_tooling)
        self.assertEqual(("omp",), params.agent_adapters)


if __name__ == "__main__":
    unittest.main()
