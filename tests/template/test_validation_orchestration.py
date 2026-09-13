from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.model import build_model, solution_text, suite_config_dict
from bootstrap.validate_generated import validate_generated
from tests.fixtures._helpers import make_params


BOOTSTRAP_VALIDATION_VARIABLE = "SUITE_BOOTSTRAP_VALIDATION"
TEMPLATE_SCRIPTS = Path(__file__).resolve().parents[2] / "template" / "scripts"


class BootstrapValidationOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params = make_params()
        self.output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-validation-orchestration-"))
        self.addCleanup(shutil.rmtree, self.output_dir, ignore_errors=True)
        model = build_model(self.params)
        (self.output_dir / "suite.config.json").write_text(
            json.dumps(suite_config_dict(model), indent=2) + "\n", encoding="utf-8"
        )
        (self.output_dir / f"{self.params.root_namespace}.sln").write_text(
            solution_text(model), encoding="utf-8"
        )
        for module in model.modules:
            project_dir = self.output_dir / "src" / module.project_name
            project_dir.mkdir(parents=True)
            (project_dir / f"{module.project_name}.csproj").write_text(
                "<Project />", encoding="utf-8"
            )

    def _validate(
        self,
        run_result,
        dotnet_results=("/usr/bin/dotnet", "/usr/bin/dotnet"),
    ) -> tuple[object, list]:
        with (
            mock.patch("bootstrap.validate_generated.subprocess.run", side_effect=run_result) as run,
            mock.patch("bootstrap.validate_generated.shutil.which", side_effect=dotnet_results),
        ):
            result = validate_generated(self.output_dir, self.params)
        return result, run.call_args_list

    def test_nested_scripts_receive_only_explicitly_satisfied_prerequisites(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        result, calls = self._validate(lambda *_args, **_kwargs: completed)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(
            [
                ["python3", "scripts/suite_metadata.py", "check"],
                ["python3", "-m", "unittest", "discover", "-s", "tests/scaffold", "-p", "test_*.py"],
                ["bash", "scripts/preflight.sh", "--portable", "--json"],
                ["bash", "scripts/test.sh"],
            ],
            [call.args[0] for call in calls],
        )
        environments = [call.kwargs["env"] for call in calls]
        self.assertNotIn(BOOTSTRAP_VALIDATION_VARIABLE, environments[0])
        self.assertNotIn(BOOTSTRAP_VALIDATION_VARIABLE, environments[1])
        self.assertEqual("1", environments[2][BOOTSTRAP_VALIDATION_VARIABLE])
        self.assertEqual("1", environments[3][BOOTSTRAP_VALIDATION_VARIABLE])

    def test_failed_metadata_or_scaffold_does_not_enable_bootstrap_mode(self) -> None:
        metadata_command = ["python3", "scripts/suite_metadata.py", "check"]
        scaffold_command = [
            "python3", "-m", "unittest", "discover", "-s", "tests/scaffold", "-p", "test_*.py"
        ]
        for failed_command, message in (
            (metadata_command, "invalid metadata"),
            (scaffold_command, "invalid scaffold"),
        ):
            with self.subTest(command=failed_command):
                def fail_prerequisite(command, **_kwargs):
                    failed = command == failed_command
                    return subprocess.CompletedProcess(
                        command, 2 if failed else 0, stdout="", stderr=message if failed else ""
                    )

                result, calls = self._validate(fail_prerequisite)

                self.assertFalse(result.ok)
                self.assertTrue(any(message in error for error in result.errors), result.errors)
                for call in calls[2:]:
                    self.assertNotIn(BOOTSTRAP_VALIDATION_VARIABLE, call.kwargs["env"])

    def test_late_dotnet_availability_does_not_upgrade_structural_metadata(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        result, calls = self._validate(
            lambda *_args, **_kwargs: completed,
            dotnet_results=(None, "/usr/bin/dotnet"),
        )

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(
            ["python3", "scripts/suite_metadata.py", "check", "--structural-only"],
            calls[0].args[0],
        )
        for call in calls[2:]:
            self.assertNotIn(BOOTSTRAP_VALIDATION_VARIABLE, call.kwargs["env"])


class GeneratedScriptOrchestrationTests(unittest.TestCase):
    def test_preflight_skips_metadata_only_for_bootstrap_validation(self) -> None:
        fake_bin = Path(tempfile.mkdtemp(prefix="valheimsuite-preflight-orchestration-"))
        self.addCleanup(shutil.rmtree, fake_bin, ignore_errors=True)
        dotnet = fake_bin / "dotnet"
        dotnet.write_text(
            "#!/usr/bin/bash\n"
            "printf '8.0.0 marker=%s\\n' \"${SUITE_BOOTSTRAP_VALIDATION-unset}\"\n",
            encoding="utf-8",
        )
        child_env_log = fake_bin / "child-env.log"
        (fake_bin / "sitecustomize.py").write_text(
            "import os, sys\n"
            "if any(arg.endswith('suite_metadata.py') for arg in sys.argv):\n"
            "    with open(os.environ['CHILD_ENV_LOG'], 'a') as log:\n"
            "        log.write(os.environ.get('SUITE_BOOTSTRAP_VALIDATION', 'unset') + '\\n')\n",
            encoding="utf-8",
        )
        dotnet.chmod(0o755)
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = f"{fake_bin}:{environment.get('PYTHONPATH', '')}"
        environment["CHILD_ENV_LOG"] = str(child_env_log)
        environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
        environment.pop(BOOTSTRAP_VALIDATION_VARIABLE, None)
        command = [sys.executable, str(TEMPLATE_SCRIPTS / "preflight.py"), "--portable", "--json"]

        standalone = subprocess.run(command, env=environment, text=True, capture_output=True)
        self.assertNotEqual(0, standalone.returncode)
        self.assertIn("suite.config.json", json.loads(standalone.stdout)["error"])

        environment[BOOTSTRAP_VALIDATION_VARIABLE] = "true"
        non_exact = subprocess.run(command, env=environment, text=True, capture_output=True)
        self.assertNotEqual(0, non_exact.returncode)
        self.assertIn("suite.config.json", json.loads(non_exact.stdout)["error"])
        self.assertEqual(["unset", "unset"], child_env_log.read_text(encoding="utf-8").splitlines())

        environment[BOOTSTRAP_VALIDATION_VARIABLE] = "1"
        orchestrated = subprocess.run(command, env=environment, text=True, capture_output=True)
        report = json.loads(orchestrated.stdout)
        self.assertEqual(0, orchestrated.returncode, report)
        self.assertEqual(
            "already certified by bootstrap validation", report["checks"]["metadata"]
        )
        self.assertEqual("8.0.0 marker=unset", report["checks"]["dotnet"])

    def test_test_script_skips_only_prevalidated_metadata_and_scaffold(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="valheimsuite-test-script-orchestration-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copy2(TEMPLATE_SCRIPTS / "test.sh", scripts / "test.sh")
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log = root / "commands.log"
        (fake_bin / "python3").write_text(
            "#!/usr/bin/bash\n"
            "printf 'python3 marker=%s %s\\n' \"${SUITE_BOOTSTRAP_VALIDATION-unset}\" \"$*\" "
            ">>\"$COMMAND_LOG\"\n"
            "if [[ \"${1:-}\" == \"-c\" ]]; then "
            "echo tests/Sampleheim.Common.Tests/Sampleheim.Common.Tests.csproj; fi\n",
            encoding="utf-8",
        )
        (fake_bin / "dotnet").write_text(
            "#!/usr/bin/bash\n"
            "printf 'dotnet marker=%s %s\\n' \"${SUITE_BOOTSTRAP_VALIDATION-unset}\" \"$*\" "
            ">>\"$COMMAND_LOG\"\n",
            encoding="utf-8",
        )
        (fake_bin / "python3").chmod(0o755)
        (fake_bin / "dotnet").chmod(0o755)

        environment = os.environ.copy()
        environment.update(PATH=f"{fake_bin}:{environment['PATH']}", COMMAND_LOG=str(log))
        environment[BOOTSTRAP_VALIDATION_VARIABLE] = "true"
        non_exact = subprocess.run(
            ["bash", "scripts/test.sh"], cwd=root, env=environment, text=True, capture_output=True
        )
        self.assertEqual(0, non_exact.returncode, non_exact.stdout + non_exact.stderr)
        non_exact_commands = log.read_text(encoding="utf-8").splitlines()

        log.unlink()
        environment[BOOTSTRAP_VALIDATION_VARIABLE] = "1"
        orchestrated = subprocess.run(
            ["bash", "scripts/test.sh"], cwd=root, env=environment, text=True, capture_output=True
        )
        self.assertEqual(0, orchestrated.returncode, orchestrated.stdout + orchestrated.stderr)
        orchestrated_commands = log.read_text(encoding="utf-8").splitlines()

        self.assertTrue(any("suite_metadata.py check" in command for command in non_exact_commands))
        self.assertTrue(any("unittest discover" in command for command in non_exact_commands))
        self.assertFalse(any("suite_metadata.py check" in command for command in orchestrated_commands))
        self.assertFalse(any("unittest discover" in command for command in orchestrated_commands))
        self.assertTrue(all("marker=unset" in command for command in non_exact_commands))
        self.assertTrue(all("marker=unset" in command for command in orchestrated_commands))
        self.assertTrue(
            any(command.startswith("dotnet marker=unset test ") for command in orchestrated_commands)
        )


if __name__ == "__main__":
    unittest.main()
