import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_challenge_runner as local
import pi_harness as pi


class ConfigTests(unittest.TestCase):
    def test_models_json_describes_the_ollama_endpoint(self):
        config = pi.models_config("qwen3.5:9b", "http://localhost:11434")
        provider = config["providers"]["ollama"]
        self.assertEqual(provider["baseUrl"], "http://localhost:11434/v1")
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual(provider["models"], [{"id": "qwen3.5:9b"}])
        # Ollama ignores the key, but Pi needs one to register the endpoint.
        self.assertTrue(provider["apiKey"])

    def test_a_base_url_that_already_has_v1_is_not_doubled(self):
        config = pi.models_config("m", "http://localhost:11434/v1/")
        self.assertEqual(config["providers"]["ollama"]["baseUrl"], "http://localhost:11434/v1")

    def test_agent_dir_is_written_without_touching_the_users_config(self):
        with tempfile.TemporaryDirectory() as directory:
            agent_dir = Path(directory) / "agent"
            written = pi.write_agent_dir(agent_dir, "m", "http://localhost:11434")
            self.assertEqual(json.loads(written.read_text())["providers"]["ollama"]["models"],
                             [{"id": "m"}])


class CommandTests(unittest.TestCase):
    def test_json_mode_and_hermetic_flags_are_requested(self):
        command = pi.pi_command("m", "high", "do it", continue_session=False)
        self.assertEqual(command[:4], ["pi", "--mode", "json", "--provider"])
        for flag in ("--no-extensions", "--no-skills", "--no-mcp", "--offline"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--thinking") + 1], "high")
        self.assertNotIn("--continue", command)
        self.assertEqual(command[-1], "do it")

    def test_thinking_true_becomes_the_highest_level(self):
        self.assertEqual(
            pi.pi_command("m", True, "x", continue_session=False)[-3:-1], ["--thinking", "high"])

    def test_thinking_off_omits_the_flag(self):
        self.assertNotIn("--thinking", pi.pi_command("m", False, "x", continue_session=False))

    def test_later_passes_resume_the_session(self):
        self.assertIn("--continue", pi.pi_command("m", False, "x", continue_session=True))

    def test_sandbox_confines_the_filesystem_but_shares_the_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = pi.sandbox_argv(root / "w", root / "a", root / "h", ["pi", "x"])
        self.assertIn("--unshare-all", argv)
        # Pi has to reach Ollama on the host, so only the network is shared.
        self.assertIn("--share-net", argv)
        self.assertIn("--die-with-parent", argv)
        joined = " ".join(argv)
        self.assertIn("--ro-bind /usr /usr", joined)
        self.assertIn("--chdir /workspace", joined)
        # The user's real Pi configuration and credentials must stay invisible.
        self.assertIn(pi.AGENT_DIR_ENV, argv)
        self.assertIn("/pi-agent", argv)
        self.assertNotIn(str(Path.home() / ".pi"), joined)


class ParsingTests(unittest.TestCase):
    def test_last_message_end_wins_and_tools_are_traced(self):
        stream = "\n".join(json.dumps(event) for event in [
            {"type": "session", "id": "s1", "cwd": "/workspace"},
            {"type": "message_end", "message": {"content": [{"type": "text", "text": "thinking"}]}},
            {"type": "tool_execution_end", "toolName": "bash", "args": {"cmd": "ls"},
             "result": "notes.txt", "isError": False, "durationMs": 12},
            {"type": "message_end", "message": {"content": [{"type": "text", "text": "ANSWER: CG{x}"}]}},
            {"type": "agent_settled", "aborted": False},
        ])
        parsed = pi.parse_events(stream)
        self.assertEqual(parsed["final_text"], "ANSWER: CG{x}")
        self.assertEqual(parsed["tools"][0]["tool"], "bash")
        self.assertEqual(parsed["tools"][0]["result"], "notes.txt")
        self.assertFalse(parsed["aborted"])
        self.assertEqual(parsed["malformed_lines"], 0)

    def test_a_string_content_message_is_handled(self):
        stream = json.dumps({"type": "message_end", "message": {"content": "ANSWER: 7"}})
        self.assertEqual(pi.parse_events(stream)["final_text"], "ANSWER: 7")

    def test_garbage_lines_are_counted_not_raised(self):
        stream = 'not json\n["a list"]\n' + json.dumps({"type": "agent_settled", "aborted": True})
        parsed = pi.parse_events(stream)
        self.assertEqual(parsed["malformed_lines"], 2)
        self.assertTrue(parsed["aborted"])
        self.assertEqual(parsed["final_text"], "")

    def test_answer_is_taken_from_the_sentinel(self):
        self.assertEqual(pi.extract_answer("blah\nANSWER: CG{abc}"), "CG{abc}")
        self.assertEqual(pi.extract_answer("ANSWER: `CG{abc}`"), "CG{abc}")
        # The last sentinel wins, so a worked example earlier cannot hijack grading.
        self.assertEqual(pi.extract_answer("ANSWER: wrong\nmore\nANSWER: right"), "right")

    def test_a_reply_without_the_sentinel_falls_back_to_the_whole_text(self):
        self.assertEqual(pi.extract_answer("  CG{abc}  "), "CG{abc}")


def stub_pi(directory: Path, stdout: str, exit_code: int = 0) -> Path:
    """A fake `pi` that prints a fixed JSONL stream, so the driver can be tested."""
    binary = directory / "pi"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


class DriverTests(unittest.TestCase):
    """Exercise run_challenge_pi end to end with a stub agent."""

    def setUp(self):
        if not shutil.which("bwrap"):
            self.skipTest("bubblewrap is required")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_with(self, stdout, exit_code=0, passes=1, challenge="SHELL-001"):
        directory = Path(self.tmp.name)
        stub_pi(directory, stdout, exit_code)
        path = f"{directory}{os.pathsep}{os.environ['PATH']}"
        with patch.dict(os.environ, {"PATH": path}):
            return local.run_challenge_pi(
                "m", "http://localhost:11434", challenge, 42, False, passes, 60.0)

    def test_a_correct_answer_is_graded_as_solved(self):
        # Recover the real flag the way a solver would, then feed it back.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            flag = local.generate_challenge("SHELL-001", workspace, 42).expected
        stream = json.dumps({"type": "message_end",
                             "message": {"content": [{"type": "text", "text": f"ANSWER: {flag}"}]}})
        result = self.run_with(stream)
        self.assertTrue(result["solved"])
        self.assertEqual(result["status"], "solved")
        self.assertEqual(result["harness"], "pi")
        self.assertEqual(result["difficulty"], "easy")
        # The flag must never survive into the saved report.
        self.assertNotIn(flag, json.dumps(result))

    def test_a_wrong_answer_is_retried_with_a_push_back(self):
        stream = json.dumps({"type": "message_end",
                             "message": {"content": [{"type": "text", "text": "ANSWER: CG{nope}"}]}})
        result = self.run_with(stream, passes=3)
        self.assertFalse(result["solved"])
        self.assertEqual(result["status"], "max_actions")
        # Two push-backs between three passes.
        self.assertEqual(result["give_up_refusals"], 2)
        self.assertEqual(sum(1 for e in result["events"] if e["type"] == "pi_pass"), 3)

    def test_a_crashed_agent_is_reported_as_a_harness_error(self):
        result = self.run_with("", exit_code=1)
        self.assertEqual(result["status"], "harness_error")
        self.assertFalse(result["solved"])

    def test_a_missing_pi_binary_is_an_explicit_error(self):
        with patch.object(pi.shutil, "which", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                local.run_challenge_pi("m", "http://x", "SHELL-001", 42, False, 1, 5.0)
        self.assertIn("npm install -g", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class PiReasoningTests(unittest.TestCase):
    def test_thinking_blocks_are_kept_as_think_tags(self):
        message = {"content": [{"type": "thinking", "thinking": "work it out"},
                               {"type": "text", "text": "ANSWER: CG{x}"}]}
        self.assertEqual(pi.message_text(message), "<think>work it out</think>\nANSWER: CG{x}")

    def test_answers_drafted_while_thinking_do_not_count(self):
        text = "<think>maybe ANSWER: CG{wrong}</think>\nANSWER: CG{right}"
        self.assertEqual(pi.extract_answer(text), "CG{right}")
