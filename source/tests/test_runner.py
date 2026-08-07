import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "runner"))

from chakrikoi_installed_runner.runner import PROFILES, Service, normalized


class RunnerTests(unittest.TestCase):
    def test_supported_profiles_have_a_command(self):
        self.assertTrue(all(profile[2] for profile in PROFILES.values()))

    def test_output_normalization_ignores_trailing_whitespace(self):
        self.assertEqual(normalized("answer  \r\n"), normalized("answer\n"))

    def test_missing_runtime_image_is_retried_then_available(self):
        service = object.__new__(Service)
        calls = [
            CompletedProcess([], 1),
            CompletedProcess([], 1, stderr="temporary registry failure"),
            CompletedProcess([], 0),
        ]
        progress = []
        with patch("chakrikoi_installed_runner.runner.subprocess.run", side_effect=calls), patch("chakrikoi_installed_runner.runner.time.sleep"):
            service.ensure_image("node:22-alpine", progress.append)
        self.assertEqual(progress, [
            "Downloading runtime node:22-alpine (attempt 1/2)",
            "Downloading runtime node:22-alpine (attempt 2/2)",
        ])

    def test_local_result_keeps_test_diagnostics(self):
        result = Service.result(
            {"id": 7, "input": "1 2\n", "expected_output": "3\n"},
            "failed", 12, "", "",
        )
        self.assertEqual(result["input"], "1 2\n")
        self.assertEqual(result["expected_output"], "3\n")
        self.assertIsNone(result["exit_code"])


if __name__ == "__main__":
    unittest.main()
