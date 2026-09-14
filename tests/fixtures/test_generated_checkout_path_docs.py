"""Regression coverage: generated operational docs must point at the
generated project's own likely checkout directory, never at the
bootstrapper repository's own checkout path.
"""

import unittest

from tests.fixtures._helpers import generate_into_temp


class GeneratedCheckoutPathDocsTests(unittest.TestCase):
    def test_project_and_development_docs_use_generated_checkout_path(self):
        params, output_dir, result = generate_into_temp(
            suite_name="Vibeheim",
            root_namespace="Vibeheim",
            plugin_guid_root="com.taibenvenuti.vibeheim",
            author="Tai Benvenuti",
            thunderstore_namespace="TaiBenvenuti",
        )
        self.assertTrue(result.ok, result.errors)

        project_md = (output_dir / ".context" / "references" / "project.md").read_text(encoding="utf-8")
        development_md = (output_dir / "docs" / "development.md").read_text(encoding="utf-8")

        self.assertIn("~/src/vibeheim", project_md)
        self.assertIn("~/src/vibeheim", development_md)
        self.assertNotIn("heimforge", project_md)
        self.assertNotIn("heimforge", development_md)

    def test_dotted_namespace_lowers_the_full_dotted_form_for_the_checkout_path(self):
        """`ROOT_NAMESPACE_LOWER` is a plain `.lower()` of the full dotted
        namespace -- confirms that stays the right convention for a
        filesystem checkout example rather than redesigning it here."""
        params, output_dir, result = generate_into_temp(
            suite_name="Skogtind",
            root_namespace="ExampleCompany.Skogtind",
            plugin_guid_root="net.example-mods.skogtind",
            author="Test Author",
            thunderstore_namespace="TestNS",
            include_client=False,
        )
        self.assertTrue(result.ok, result.errors)

        development_md = (output_dir / "docs" / "development.md").read_text(encoding="utf-8")
        self.assertIn("~/src/examplecompany.skogtind", development_md)
        self.assertNotIn("heimforge", development_md)


if __name__ == "__main__":
    unittest.main()
