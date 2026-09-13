from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.validate_generated import ValidationResult
from tests.fixtures import _helpers as helpers


class CloneGeneratedTempTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_seeds = helpers._GENERATED_SEEDS
        self.isolated_seeds = {}
        helpers._GENERATED_SEEDS = self.isolated_seeds
        self.addCleanup(self._restore_seed_cache)

        patcher = mock.patch.object(helpers, "generate_into_temp", side_effect=self._fake_generate)
        self.generate = patcher.start()
        self.addCleanup(patcher.stop)

    def _restore_seed_cache(self) -> None:
        helpers._GENERATED_SEEDS = self.previous_seeds
        for _params, seed_dir, _result in self.isolated_seeds.values():
            shutil.rmtree(seed_dir, ignore_errors=True)

    def _fake_generate(self, **overrides):
        seed_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-clone-seed-test-"))
        (seed_dir / "fixture.txt").write_text(overrides.get("author", "Sample Author"), encoding="utf-8")
        return helpers.make_params(**overrides), seed_dir, ValidationResult(warnings=["certified"])

    def _clone(self, **overrides):
        cloned = helpers.clone_generated_temp(**overrides)
        self.addCleanup(shutil.rmtree, cloned[1], ignore_errors=True)
        return cloned

    def test_identical_overrides_generate_once_and_clone_private_trees(self) -> None:
        _params_a, clone_a, _result_a = self._clone(author="Same Author")
        _params_b, clone_b, _result_b = self._clone(author="Same Author")

        self.assertEqual(1, self.generate.call_count)
        self.assertNotEqual(clone_a, clone_b)
        (clone_a / "fixture.txt").write_text("mutated", encoding="utf-8")
        self.assertEqual("Same Author", (clone_b / "fixture.txt").read_text(encoding="utf-8"))

    def test_different_overrides_create_independent_cached_seeds(self) -> None:
        self._clone(author="First Author")
        self._clone(author="First Author")
        self._clone(author="Second Author")
        self._clone(author="Second Author")

        self.assertEqual(
            [mock.call(author="First Author"), mock.call(author="Second Author")],
            self.generate.call_args_list,
        )

    def test_returned_python_objects_do_not_expose_cached_state(self) -> None:
        params_a, _clone_a, result_a = self._clone()
        result_a.errors.append("caller mutation")
        result_a.warnings.append("caller mutation")
        try:
            setattr(params_a, "suite_name", "Contaminated")
        except AttributeError:
            pass

        params_b, _clone_b, result_b = self._clone()

        self.assertIsNot(params_a, params_b)
        self.assertIsNot(result_a, result_b)
        self.assertEqual("Sampleheim", params_b.suite_name)
        self.assertEqual([], result_b.errors)
        self.assertEqual(["certified"], result_b.warnings)


if __name__ == "__main__":
    unittest.main()
