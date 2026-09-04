import unittest

from bootstrap import render


class TemplateStructureTests(unittest.TestCase):
    def test_template_validates_cleanly(self):
        self.assertEqual([], render.validate_template())


if __name__ == "__main__":
    unittest.main()
