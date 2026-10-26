import sys
import unittest
from pathlib import Path

import json
import tempfile

import gauntlet_runner
from gauntlet_runner import build_commands, build_parser, find_part_reports, needs_judge, report_finished
from unittest import mock


class GauntletRunnerTests(unittest.TestCase):
    def test_resume_run_keeps_finished_parts_and_resumes_partial_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "a_model.json").write_text(json.dumps({"tests_requested": 2, "tests_graded": 2}))
            (run / "b_model_local.json").write_text(json.dumps({
                "benchmark_part": "local_and_agent_safety", "complete": False, "seed": 7,
                "results": [{"id": "SHELL-001", "category": "shell", "status": "solved"}]}))
            (run / "combined_summary.json").write_text(json.dumps({"parts": []}))
            reports = find_part_reports(run)
            self.assertEqual(set(reports), {"questions", "local"})
            self.assertTrue(report_finished(reports["questions"]))
            self.assertFalse(report_finished(reports["local"]))
            args = build_parser().parse_args(["--model", "example"])
            args.resume_reports = {"local": reports["local"]}
            commands = dict(build_commands(args, run))
            local = commands["Part 2 — Local Security Challenges"]
            self.assertEqual(local[local.index("--resume-from") + 1], str(reports["local"]))
            self.assertNotIn("--resume-from", commands["Part 3 — Indirect Prompt Injection"])

    def test_memory_poisoning_alone_is_a_valid_run(self):
        flags = ["--model", "example", "--skip-questions", "--skip-local", "--skip-agent-safety",
                 "--run-memory-poisoning", "--condition", "poisoned", "--no-audio"]
        args = build_parser().parse_args(flags)
        self.assertEqual([name for name, _ in build_commands(args, Path("results/run"))],
                         ["Part 4 — Memory Poisoning (poisoned)"])
        self.assertTrue(needs_judge(args))  # its challenges are judge-reviewed, so preflight the judge
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(sys, "argv", ["gauntlet_runner.py", *flags, "--output-dir", folder,
                                                "--judge-provider", "heuristic"]), \
                mock.patch.object(gauntlet_runner, "build_commands", return_value=[]):
            gauntlet_runner.main()  # must not reject the run as having no parts

    def test_default_llama_target_is_forwarded_to_every_part(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.model, "qwen3.5:9b")
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

    def test_judge_reviews_local_parts_unless_disabled(self):
        args = build_parser().parse_args(["--model", "example", "--codex-judge-model", "gpt-x"])
        for _, command in build_commands(args, Path("results/run"))[1:]:
            self.assertEqual(command[command.index("--review-provider") + 1], "codex-cli")
            self.assertEqual(command[command.index("--codex-judge-model") + 1], "gpt-x")
        for flags in (["--no-review"], ["--judge-provider", "heuristic"]):
            args = build_parser().parse_args(["--model", "example", *flags])
            for _, command in build_commands(args, Path("results/run"))[1:]:
                self.assertNotIn("--review-provider", command)

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
