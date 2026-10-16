import sys
import unittest
from pathlib import Path

from gauntlet_runner import build_commands, build_parser


class GauntletRunnerTests(unittest.TestCase):
    def test_default_llama_target_is_forwarded_to_every_part(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.model, "hf.co/peculiar-ragdoll/Cyber-Tiel-Coder-35B-A3B-GGUF-MTP:UD-Q4_K_M")
        self.assertEqual(args.base_url, "http://127.0.0.1:11434/v1")
        for _, command in build_commands(args, Path("results/run")):
            self.assertEqual(command[command.index("--model") + 1], args.model)
            self.assertEqual(command[command.index("--base-url") + 1], args.base_url)

    def test_defaults_run_questions_expanded_local_and_agent_safety(self):
        args = build_parser().parse_args(["--model", "example"])
        commands = build_commands(args, Path("results/run"))
        self.assertEqual([name for name, _ in commands], [
            "Part 1 — Safety Questions",
            "Part 2 — Local Security Challenges",
            "Part 3 — Indirect Prompt Injection",
        ])
        question_command = commands[0][1]
        local_command = commands[1][1]
        self.assertEqual(question_command[0], sys.executable)
        self.assertIn("--judge-provider", question_command)
        self.assertEqual(local_command.count("--category"), 5)
        self.assertIn("long_horizon", local_command)

    def test_skip_flags_select_one_part(self):
        args = build_parser().parse_args(["--model", "example"])
        commands = build_commands(args, Path("results/run"))
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0][0], "Part 1 — Safety Questions")

    def test_all_skip_flags_disable_every_part(self):
        args = build_parser().parse_args([
            "--model", "example", "--skip-questions", "--skip-local",
            "--skip-agent-safety",
        ])
        self.assertEqual(build_commands(args, Path("results/run")), [])

    def test_local_seed_and_categories_are_forwarded(self):
        args = build_parser().parse_args([
            "--model", "example", "--skip-questions", "--seed", "42",
        ])
        commands = build_commands(args, Path("results/run"))
        local = commands[0][1]
        agent = commands[1][1]
        self.assertEqual(local[local.index("--seed") + 1], "42")
        self.assertEqual(local.count("--category"), 5)
        self.assertIn("long_horizon", local)
        self.assertEqual(agent[agent.index("--category") + 1], "agent_safety")


if __name__ == "__main__":
    unittest.main()
