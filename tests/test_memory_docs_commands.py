import subprocess
import sys
import unittest
from pathlib import Path

import local_challenge_runner as L

ROOT = Path(__file__).resolve().parent.parent


class DocumentationCommandTests(unittest.TestCase):
    def test_local_memory_examples_use_supported_flags(self):
        for mode in ("seeded", "cross_session"):
            args = L.build_parser().parse_args([
                "--model", "qwen3.5:9b", "--category", "memory_poisoning",
                "--memory-mode", mode, "--condition", "poisoned",
                "--seed", "42", "--max-actions", "20"])
            self.assertEqual(args.memory_mode, mode)

    def test_documented_module_help_commands_exit_successfully(self):
        for command in ([sys.executable, "-m", "memory_poisoning.experiment", "--help"],
                        [sys.executable, "tools/compare_layers.py", "--help"]):
            with self.subTest(command=command):
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_docs_name_both_modes_and_corrupt_policy(self):
        for name in ("README.md", "BENCHMARK.md"):
            text = (ROOT / name).read_text()
            self.assertIn("--memory-mode seeded", text)
            self.assertIn("--memory-mode cross_session", text)
        benchmark = (ROOT / "BENCHMARK.md").read_text()
        self.assertIn("MemoryStoreCorruptError", benchmark)
        self.assertIn("--paired-metric solved", benchmark)
