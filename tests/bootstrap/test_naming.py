import unittest

from bootstrap import naming


class NamingTests(unittest.TestCase):
    def test_namespace_accepts_dot_separated_segments(self):
        naming.validate_namespace("ExampleCompany.Vibeheim", "rootNamespace")
        naming.validate_namespace("Vibeheim", "rootNamespace")

    def test_namespace_rejects_malformed_input(self):
        for bad in ("", "1Bad", "Bad-Name", "Trailing.", ".Leading", "Has Space", "a..b", "path/sep"):
            with self.assertRaises(naming.NamingError):
                naming.validate_namespace(bad, "rootNamespace")

    def test_guid_root_accepts_dot_and_hyphen_segments(self):
        naming.validate_guid_root("com.example.vibeheim")
        naming.validate_guid_root("net.example-mods.skogtind")

    def test_guid_root_rejects_malformed_input(self):
        for bad in ("", "NotAValidGuid!!", "onlyoneword", "trailing.", ".leading"):
            with self.assertRaises(naming.NamingError):
                naming.validate_guid_root(bad)

    def test_semver_accepts_and_rejects(self):
        naming.validate_semver("0.1.0", "suiteVersion")
        naming.validate_semver("1.2.3-beta.1", "suiteVersion")
        with self.assertRaises(naming.NamingError):
            naming.validate_semver("v1.0", "suiteVersion")

    def test_label_rejects_empty_untrimmed_and_path_separators(self):
        naming.validate_label("Tai Benvenuti", "author")
        for bad in ("", "  padded  ", "has/slash", "has\\backslash"):
            with self.assertRaises(naming.NamingError):
                naming.validate_label(bad, "author")


if __name__ == "__main__":
    unittest.main()
