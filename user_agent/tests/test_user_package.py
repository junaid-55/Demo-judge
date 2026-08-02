import subprocess
import unittest
from pathlib import Path


PACKAGE = Path(__file__).parents[1]


class UserPackageTests(unittest.TestCase):
    def test_runner_binary_and_runtime_links_exist(self):
        self.assertTrue((PACKAGE / "chakrikoi-runner").is_file())
        self.assertTrue((PACKAGE / "chakrikoi-runner").stat().st_mode & 0o111)
        self.assertTrue((PACKAGE / "bootstrap.json").is_symlink())
        self.assertTrue((PACKAGE / "submit.py").is_symlink())

    def test_runner_displays_help(self):
        result = subprocess.run([PACKAGE / "chakrikoi-runner", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--bootstrap", result.stdout)


if __name__ == "__main__":
    unittest.main()
