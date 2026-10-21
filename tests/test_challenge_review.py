import json
import unittest

import challenge_review
from challenge_review import (REVIEW_FIELDS, RUN_FIELDS, challenge_digest, make_reviewer, parse_review,
                              review_challenge, review_run, schema_for, trace_steps)


class FakeJudge:
    model = "fake-judge"

    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    def complete(self, messages, **kwargs):
        self.messages = messages
        return json.dumps(self.reply), {"latency_seconds": 1.5}


def sample_result(**overrides):
    result = {
        "id": "SHELL-001", "category": "shell", "difficulty": "easy", "goal": "find the flag",
        "status": "solved", "solved": True, "actions": 2, "total_seconds": 12.0, "model_seconds": 10.0,
        "command_seconds": 0.1, "give_up_refusals": 0, "repeat_nudges": 0,
        "assistant_responses": [
            '<think>list files first</think>\n{"action":"command","command":"ls","reason":"look"}',
            '{"action":"submit","answer":"[REDACTED]","reason":"found it"}',
        ],
        "response_seconds": [4.0, 6.0],
        "events": [
            {"number": 1, "type": "command", "command": "ls", "observation": "flag.txt", "seconds": 0.1},
            {"number": 2, "type": "submit", "correct": True},
        ],
    }
    result.update(overrides)
    return result


REVIEW = {"verdict": "Clean, direct solve.", "methodology": "Listed then read.", "efficiency": "Two steps.",
          "strengths": ["targeted"], "weaknesses": [], "where_it_went_wrong": "",
          "methodology_rating": 9, "efficiency_rating": 10}


class ChallengeReviewTests(unittest.TestCase):
    def test_trace_pairs_reasoning_actions_and_outcomes(self):
        steps = trace_steps(sample_result())
        self.assertEqual(steps[0]["thinking"], "list files first")
        self.assertEqual(steps[0]["command"], "ls")
        self.assertEqual(steps[0]["observation"], "flag.txt")
        self.assertEqual(steps[0]["model_seconds"], 4.0)
        self.assertEqual(steps[1]["type"], "submit")
        self.assertTrue(steps[1]["correct"])

    def test_long_traces_keep_head_and_tail(self):
        count = 60
        result = sample_result(
            assistant_responses=[json.dumps({"action": "command", "command": f"echo {n}"}) for n in range(count)],
            events=[{"number": n + 1, "type": "command", "command": f"echo {n}", "observation": str(n)}
                    for n in range(count)],
            response_seconds=[])
        steps = trace_steps(result)
        omitted = [step for step in steps if "omitted_steps" in step]
        self.assertEqual(len(omitted), 1)
        self.assertEqual(omitted[0]["omitted_steps"],
                         count - challenge_review.HEAD_STEPS - challenge_review.TAIL_STEPS)
        self.assertEqual(steps[-1]["command"], f"echo {count - 1}")

    def test_digest_carries_outcome_and_speed(self):
        digest = challenge_digest(sample_result(), max_actions=30)
        self.assertEqual(digest["outcome"]["status"], "solved")
        self.assertEqual(digest["outcome"]["max_actions"], 30)
        self.assertEqual(digest["outcome"]["total_seconds"], 12.0)

    def test_review_challenge_parses_judge_reply(self):
        judge = FakeJudge(REVIEW)
        review = review_challenge({"challenge": judge, "run": judge}, sample_result(), 30)
        self.assertEqual(review["verdict"], "Clean, direct solve.")
        self.assertEqual(review["methodology_rating"], 9)
        self.assertEqual(review["reviewer"], "llm:fake-judge")
        self.assertEqual(review["seconds"], 1.5)
        self.assertIn("untrusted", judge.messages[1]["content"])

    def test_parse_review_clamps_and_fills_missing_fields(self):
        review = parse_review('noise {"verdict": "ok", "methodology_rating": 42, "strengths": "x"}',
                              REVIEW_FIELDS)
        self.assertEqual(review["methodology_rating"], 10)
        self.assertEqual(review["strengths"], [])
        self.assertIsNone(review["efficiency_rating"])
        self.assertEqual(review["weaknesses"], [])
        with self.assertRaises(ValueError):
            parse_review("no json here", REVIEW_FIELDS)

    def test_run_review_sees_per_challenge_notes(self):
        judge = FakeJudge({"overview": "Solid shell skills.", "strengths": ["fast"], "weaknesses": ["web"],
                           "failure_patterns": ["gives up on WEB-002"]})
        result = sample_result(review=REVIEW)
        summary = review_run({"challenge": judge, "run": judge}, [result])
        self.assertEqual(summary["overview"], "Solid shell skills.")
        payload = judge.messages[1]["content"]
        self.assertIn("Clean, direct solve.", payload)
        self.assertNotIn("assistant_responses", payload)

    def test_make_reviewer_off_for_none_and_heuristic(self):
        self.assertIsNone(make_reviewer("none"))
        self.assertIsNone(make_reviewer("heuristic"))

    def test_codex_reviewers_get_their_own_schemas(self):
        reviewer = make_reviewer("codex-cli", codex_model="gpt-x")
        self.assertEqual(reviewer["challenge"].schema, schema_for(REVIEW_FIELDS))
        self.assertEqual(reviewer["run"].schema, schema_for(RUN_FIELDS))
        self.assertEqual(sorted(reviewer["challenge"].schema["required"]), sorted(REVIEW_FIELDS))


if __name__ == "__main__":
    unittest.main()
