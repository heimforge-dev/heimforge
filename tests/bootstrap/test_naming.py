import unittest

from bootstrap import naming


class NamingTests(unittest.TestCase):
    def test_namespace_accepts_dot_separated_segments(self):
        naming.validate_namespace("ExampleCompany.Vibeheim", "rootNamespace")
        naming.validate_namespace("Vibeheim", "rootNamespace")
        naming.validate_namespace("_Private", "rootNamespace")

    def test_namespace_rejects_malformed_input(self):
        for bad in ("", "1Bad", "Bad-Name", "Trailing.", ".Leading", "Has Space", "a..b", "path/sep"):
            with self.assertRaises(naming.NamingError):
                naming.validate_namespace(bad, "rootNamespace")

    def test_namespace_rejects_reserved_keyword_segments(self):
        """Original bug: `class` and `namespace.Tools` passed namespace
        validation and would have generated an unparseable `namespace
        class;`/`using namespace.Tools;` declaration."""
        for bad in ("class", "namespace.Tools", "Example.class"):
            with self.assertRaises(naming.NamingError):
                naming.validate_namespace(bad, "rootNamespace")
        naming.validate_namespace("Example.Tools", "rootNamespace")

    def test_guid_root_accepts_dot_and_hyphen_segments(self):
        naming.validate_guid_root("com.example.vibeheim")
        naming.validate_guid_root("net.example-mods.skogtind")

    def test_guid_root_rejects_malformed_input(self):
        for bad in ("", "NotAValidGuid!!", "onlyoneword", "trailing.", ".leading", "com.example.suite\n"):
            with self.assertRaises(naming.NamingError):
                naming.validate_guid_root(bad)

    def test_semver_accepts_valid_semver_2_0_0(self):
        for good in (
            "0.1.0",
            "1.2.3-beta.1",
            "1.2.3-alpha",
            "1.2.3-alpha.1",
            "1.2.3-0.3.7",
            "1.2.3-x.7.z.92",
            "1.2.3+build.1",
            "1.2.3+001",
            "1.2.3-alpha+build.1",
        ):
            with self.subTest(good=good):
                naming.validate_semver(good, "suiteVersion")

    def test_semver_rejects_invalid_semver_2_0_0(self):
        """Original bug: `01.2.3` (leading-zero core), `1.2.3-alpha..1`
        and `1.2.3-...` (empty prerelease identifiers) were accepted by
        the old regex, while valid build-metadata syntax was rejected."""
        for bad in (
            "v1.0",
            "1.0.0\n",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-alpha..1",
            "1.2.3-...",
            "1.2.3-alpha.01",
            "1.2.3-",
            "1.2.3+",
            "",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(naming.NamingError):
                    naming.validate_semver(bad, "suiteVersion")

    def test_label_rejects_empty_untrimmed_and_path_separators(self):
        naming.validate_label("Tai Benvenuti", "author")
        for bad in ("", "  padded  ", "has/slash", "has\\backslash", "has\tcontrol"):
            with self.assertRaises(naming.NamingError):
                naming.validate_label(bad, "author")

    def test_label_rejects_unicode_control_line_and_paragraph_separators(self):
        """Reviewer follow-up: the ASCII-only control-character check
        (`ord(ch) < 0x20 or ord(ch) == 0x7F`) let C1 controls (e.g.
        U+0085 NEXT LINE, U+009F) and Unicode line/paragraph separators
        (U+2028, U+2029) through untouched."""
        naming.validate_label("Ünïcödé Authör", "author")
        naming.validate_label("O'Brien & Sons \"Team\" <legit>", "author")
        for bad in (
            "Tai\u0085Benvenuti",
            "Tai\u009fBenvenuti",
            "Tai\u2028Benvenuti",
            "Tai\u2029Benvenuti",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(naming.NamingError):
                    naming.validate_label(bad, "author")

    def test_label_rejects_characters_invalid_in_xml_1_0(self):
        """Reviewer follow-up: `author` is emitted into
        `build/Suite.Generated.props` (XML). Cc/Zl/Zp does not exclude
        the surrogate range (category `Cs`) or the U+FFFE/U+FFFF
        noncharacters (category `Cn`), both of which are invalid XML 1.0
        character data and previously broke `Suite.Generated.props`."""
        naming.validate_label("Renée O'Neil", "author")
        naming.validate_label("Tai" + chr(0xFFFD) + "Benvenuti", "author")
        naming.validate_label("Tai" + chr(0x1F600) + "Benvenuti", "author")
        for bad in (
            "Tai\ud800Benvenuti",
            "Tai\udfffBenvenuti",
            "Tai\ufffeBenvenuti",
            "Tai\uffffBenvenuti",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(naming.NamingError):
                    naming.validate_label(bad, "author")

    def test_path_component_rejects_generated_metadata_incompatible_suite_names(self):
        naming.validate_path_component("Sampleheim", "suiteName")
        for bad in ("My Suite", "../escaped", "CON", "component\n"):
            with self.assertRaises(naming.NamingError):
                naming.validate_path_component(bad, "suiteName")

    def test_thunderstore_namespace_uses_the_platform_identifier_charset(self):
        """Original bug: `validate_label()` accepted `Bad Name!` for
        thunderstoreNamespace because it only rejected control characters
        and path separators, not the Thunderstore identifier charset."""
        naming.validate_thunderstore_namespace("SampleNS", "thunderstoreNamespace")
        naming.validate_thunderstore_namespace("Sample_NS1", "thunderstoreNamespace")
        for bad in ("Bad Name!", "Bad Name", "bad-name", "bad.name", "bad/name", "bad\nname", ""):
            with self.assertRaises(naming.NamingError):
                naming.validate_thunderstore_namespace(bad, "thunderstoreNamespace")

    def test_thunderstore_namespace_enforces_edge_characters_and_max_length(self):
        """Reviewer follow-up: the namespace contract requires alphanumeric
        first/last characters (underscore only internally) and a 64-char
        maximum -- the previous `^[A-Za-z0-9_]+$` grammar accepted both a
        leading/trailing underscore and unbounded length."""
        naming.validate_thunderstore_namespace("Team", "thunderstoreNamespace")
        naming.validate_thunderstore_namespace("Team_One", "thunderstoreNamespace")
        naming.validate_thunderstore_namespace("Northern_Guild1", "thunderstoreNamespace")
        naming.validate_thunderstore_namespace("a" * 64, "thunderstoreNamespace")
        for bad in ("_Team", "Team_", "_", "a" * 65):
            with self.subTest(bad=bad if len(bad) <= 8 else f"<len {len(bad)}>"):
                with self.assertRaises(naming.NamingError):
                    naming.validate_thunderstore_namespace(bad, "thunderstoreNamespace")


if __name__ == "__main__":
    unittest.main()
