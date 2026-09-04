import json
import unittest

from tests.fixtures._helpers import generate_into_temp


class SideIsolationTests(unittest.TestCase):
    def test_client_and_server_package_sets_never_cross_scopes(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        cfg = json.loads((output_dir / "suite.config.json").read_text(encoding="utf-8"))
        scopes = {name: item["scope"] for name, item in cfg["projects"].items()}
        packages = cfg["packages"]

        server = {packages["commonModule"], *packages["serverModules"]}
        client = {
            packages["commonModule"],
            *packages["requiredClientModules"],
            *packages["optionalClientModules"],
            *packages["clientOnlyModules"],
        }
        self.assertFalse(any(scopes[m] == "clientOnly" for m in server))
        self.assertFalse(any(scopes[m] == "serverOnly" for m in client))


if __name__ == "__main__":
    unittest.main()
