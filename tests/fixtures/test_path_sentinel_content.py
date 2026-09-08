import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.model import build_model, solution_text, suite_config_dict
from bootstrap.validate_generated import validate_generated
from tests.fixtures._helpers import make_params


def _write_minimal_valid_project(output_dir: Path, params) -> None:
    model = build_model(params)
    (output_dir / "suite.config.json").write_text(
        json.dumps(suite_config_dict(model), indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / f"{params.root_namespace}.sln").write_text(solution_text(model), encoding="utf-8")
    for m in model.modules:
        project_dir = output_dir / "src" / m.project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / f"{m.project_name}.csproj").write_text("<Project />", encoding="utf-8")


class PathSentinelContentTests(unittest.TestCase):
    def test_root_namespace_sentinel_in_content_fails_validation(self):
        """`__ROOT_NAMESPACE__` left over in a text file's *body* (as
        opposed to its path) must fail -- the path-only check that
        predates this fix never looked at content."""
        params = make_params()
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        _write_minimal_valid_project(output_dir, params)
        (output_dir / "NOTES.md").write_text(
            "leftover __ROOT_NAMESPACE__ literal in content", encoding="utf-8"
        )

        result = validate_generated(output_dir, params)

        self.assertFalse(result.ok)
        self.assertTrue(any("NOTES.md" in e and "unresolved path token" in e for e in result.errors), result.errors)

    def test_root_namespace_sentinel_in_path_fails_validation(self):
        params = make_params()
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        _write_minimal_valid_project(output_dir, params)
        sentinel_dir = output_dir / "some" / "__ROOT_NAMESPACE__"
        sentinel_dir.mkdir(parents=True)
        (sentinel_dir / "file.txt").write_text("x", encoding="utf-8")

        result = validate_generated(output_dir, params)

        self.assertFalse(result.ok)
        self.assertTrue(
            any("some/__ROOT_NAMESPACE__/file.txt" in e and "unresolved path token" in e for e in result.errors),
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
