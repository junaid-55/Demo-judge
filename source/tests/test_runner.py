import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runner"))

from chakrikoi_installed_runner.runner import PROFILES, normalized


class RunnerTests(unittest.TestCase):
    def test_supported_profiles_have_a_command(self):
        self.assertTrue(all(profile[2] for profile in PROFILES.values()))

    def test_output_normalization_ignores_trailing_whitespace(self):
        self.assertEqual(normalized("answer  \r\n"), normalized("answer\n"))


if __name__ == "__main__":
    unittest.main()
