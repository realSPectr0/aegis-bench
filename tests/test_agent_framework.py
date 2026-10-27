import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_framework as af


class KnowledgeBaseTests(unittest.TestCase):
    def test_retrieves_relevant_notes_by_topic(self):
        kb = af.KnowledgeBase()
        got = {doc.doc_id for doc in kb.retrieve("fix the SQL injection in user search", 3)}
        self.assertIn("sqli-fix", got)
        ssrf = {doc.doc_id for doc in kb.retrieve("validate outbound URL to block SSRF to localhost", 3)}
        self.assertIn("ssrf-fix", ssrf)
        enc = {doc.doc_id for doc in kb.retrieve("reverse gzip base32 hex layers in payload.bin", 3)}
        self.assertIn("enc-layers", enc)

    def test_empty_query_returns_nothing_and_k_is_respected(self):
        kb = af.KnowledgeBase()
        self.assertEqual(kb.retrieve("", 3), [])
        self.assertLessEqual(len(kb.retrieve("incident timeline dns exfiltration beacon", 2)), 2)


class SummarizeTests(unittest.TestCase):
    def test_keeps_goal_and_recent_summarizes_older(self):
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "THE GOAL"}]
        for i in range(10):
            messages.append({"role": "assistant", "content": f"act {i}"})
            messages.append({"role": "user", "content": f"OBS {i} " + "x" * 2000})
        packed = af.summarize_transcript(messages, keep_recent=4, max_obs_chars=200)
        self.assertEqual(packed[0]["role"], "system")
        self.assertIn("THE GOAL", packed[1]["content"])
        self.assertTrue(any("summarized" in str(m["content"]) for m in packed))
        self.assertEqual(packed[-4:], messages[-4:])        # recent kept verbatim
        self.assertLess(len(packed), len(messages))          # older collapsed

    def test_short_transcript_is_unchanged(self):
        messages = [{"role": "user", "content": "goal"}, {"role": "assistant", "content": "a"}]
        self.assertEqual(af.summarize_transcript(messages, keep_recent=6), messages)


class FrameworkTests(unittest.TestCase):
    def make(self, **cfg):
        self.calls = []

        def backend(messages, *, think=False, max_tokens=1200):
            self.calls.append({"messages": messages, "think": think})
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            if "TASK-TRACKER" in messages[0]["content"]:
                return "1. inspect files\n2. decode layer"
            self.last_system = system
            return '{"action":"command","command":"ls","reason":"look"}'

        return af.AgentFramework(backend, af.AgentConfig(**cfg))

    def test_executor_gets_persona_rag_and_contract(self):
        agent = self.make()
        out = agent.complete([{"role": "user", "content": "fix the SQL injection vulnerability"}])
        self.assertIn('"action"', out)
        self.assertIn("AegisAgent", self.last_system)
        self.assertIn("REFERENCE NOTES", self.last_system)
        self.assertIn("sql", self.last_system.lower())
        self.assertIn("TASK CHECKLIST", self.last_system)   # planner ran on first step

    def test_planner_is_cached_and_refreshed(self):
        agent = self.make(plan_every=3)
        goal = [{"role": "user", "content": "investigate the incident timeline"}]
        for _ in range(4):
            agent.complete(goal)
        planner_calls = sum("TASK-TRACKER" in c["messages"][0]["content"] for c in self.calls)
        self.assertEqual(planner_calls, 2)   # step 1 and step 4 (after plan_every)

    def test_rag_and_planner_can_be_disabled(self):
        agent = self.make(use_rag=False, use_planner=False)
        agent.complete([{"role": "user", "content": "fix the SQL injection vulnerability"}])
        self.assertNotIn("REFERENCE NOTES", self.last_system)
        self.assertNotIn("TASK CHECKLIST", self.last_system)
        self.assertTrue(all("TASK-TRACKER" not in c["messages"][0]["content"] for c in self.calls))

    def test_executor_thinking_is_passed_through(self):
        agent = self.make(thinking="high")
        agent.complete([{"role": "user", "content": "decode the payload"}])
        exec_calls = [c for c in self.calls if "TASK-TRACKER" not in c["messages"][0]["content"]]
        self.assertEqual(exec_calls[-1]["think"], "high")

    def test_planner_failure_does_not_break_the_step(self):
        def backend(messages, *, think=False, max_tokens=1200):
            if "TASK-TRACKER" in messages[0]["content"]:
                raise RuntimeError("planner down")
            return '{"action":"give_up","reason":"x"}'
        agent = af.AgentFramework(backend, af.AgentConfig())
        out = agent.complete([{"role": "user", "content": "do the task"}])
        self.assertIn("give_up", out)


class StuckDetectionTests(unittest.TestCase):
    def transcript(self, n_repeats):
        msgs = [{"role": "user", "content": "decode the payload"}]
        for _ in range(n_repeats):
            msgs.append({"role": "assistant",
                         "content": '{"action":"command","command":"python3 x.py","reason":"r"}'})
            msgs.append({"role": "user", "content": "COMMAND RESULT: exit=1 error"})
        return msgs

    def test_stuck_count_counts_consecutive_repeats(self):
        self.assertEqual(af.stuck_count(self.transcript(4)), 4)
        self.assertEqual(af.stuck_count([{"role": "user", "content": "goal"}]), 0)

    def test_change_tactic_nudge_injected_when_stuck(self):
        calls = []
        def backend(messages, *, think=False, max_tokens=1200):
            if "TASK-TRACKER" in messages[0]["content"]:
                return "1. decode [failed]\nNEXT: try base32"
            calls.append(next(m["content"] for m in messages if m["role"] == "system"))
            return '{"action":"command","command":"python3 x.py","reason":"r"}'
        agent = af.AgentFramework(backend, af.AgentConfig(stuck_threshold=3))
        agent.complete(self.transcript(3))
        self.assertIn("STUCK CHECK", calls[-1])
        self.assertIn("Change approach", calls[-1])

    def test_no_nudge_below_threshold(self):
        calls = []
        def backend(messages, *, think=False, max_tokens=1200):
            if "TASK-TRACKER" in messages[0]["content"]:
                return "1. decode [todo]\nNEXT: inspect"
            calls.append(next(m["content"] for m in messages if m["role"] == "system"))
            return '{"action":"command","command":"python3 x.py","reason":"r"}'
        agent = af.AgentFramework(backend, af.AgentConfig(stuck_threshold=3))
        agent.complete(self.transcript(2))
        self.assertNotIn("STUCK CHECK", calls[-1])

    def test_planner_reflects_on_previous_checklist(self):
        seen = {}
        def backend(messages, *, think=False, max_tokens=1200):
            if "TASK-TRACKER" in messages[0]["content"]:
                seen["prompt"] = messages[0]["content"]
                return "1. inspect [done]\nNEXT: decode"
            return '{"action":"command","command":"ls","reason":"r"}'
        agent = af.AgentFramework(backend, af.AgentConfig(plan_every=1))
        goal = [{"role": "user", "content": "decode the payload"}]
        agent.complete(goal)
        agent.complete(goal)
        self.assertIn("PREVIOUS CHECKLIST", seen["prompt"])
        self.assertIn("inspect [done]", seen["prompt"])   # prior checklist fed back in


if __name__ == "__main__":
    unittest.main()
