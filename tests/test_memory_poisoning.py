import json
import tempfile
import unittest
from pathlib import Path

import memory_store
from memory_store import MemoryStore, make_record
from memory_poisoning.trial_log import TrialLogger, TrialRecord


class RecordTests(unittest.TestCase):
    def test_make_record_has_provenance_and_mirrors_content(self):
        rec = make_record("the widget code is QX-9", source="interaction",
                          experiment_id="exp1", trust="untrusted", kind="lesson")
        for key in ("id", "created_at", "source", "experiment_id", "trust_status", "content", "note"):
            self.assertIn(key, rec)
        self.assertEqual(rec["content"], rec["note"])          # render path still works
        self.assertEqual(rec["trust_status"], "untrusted")

    def test_bad_trust_rejected(self):
        with self.assertRaises(ValueError):
            make_record("x", source="s", trust="totally-trusted")


class StoreTests(unittest.TestCase):
    def test_persists_across_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            s1 = MemoryStore.open(Path(d), "exp")
            s1.write(make_record("fact A", source="seed"))
            # A brand-new store object for the same namespace = a later session.
            s2 = MemoryStore.open(Path(d), "exp")
            notes = [r["content"] for r in s2.all()]
            self.assertIn("fact A", notes)
            self.assertTrue(any(e["op"] == "write" for e in s2.audit_log()))

    def test_trials_are_isolated_by_namespace_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            a = MemoryStore.open(Path(d), "trial-a")
            b = MemoryStore.open(Path(d), "trial-b")
            a.write(make_record("only in A", source="seed"))
            self.assertEqual(b.all(), [])                      # no cross-contamination
            a.reset()
            self.assertEqual(MemoryStore.open(Path(d), "trial-a").all(), [])

    def test_selective_repair_preserves_legitimate_records(self):
        with tempfile.TemporaryDirectory() as d:
            s = MemoryStore.open(Path(d), "exp")
            s.seed([make_record("legit 1", source="seed"),
                    make_record("planted", source="attacker", kind="instruction"),
                    make_record("legit 2", source="seed")])
            target = next(r for r in s.all() if r["content"] == "planted")
            removed = s.repair(record_id=target["id"])
            remaining = [r["content"] for r in s.all()]
            self.assertEqual([r["content"] for r in removed], ["planted"])
            self.assertEqual(remaining, ["legit 1", "legit 2"])

    def test_repair_refuses_full_wipe(self):
        with tempfile.TemporaryDirectory() as d:
            s = MemoryStore.open(Path(d), "exp")
            s.seed([make_record("a", source="seed"), make_record("b", source="seed")])
            with self.assertRaises(ValueError):
                s.repair(predicate=lambda r: True)             # would remove everything

    def test_trust_gate_drops_untrusted_records(self):
        with tempfile.TemporaryDirectory() as d:
            s = MemoryStore.open(Path(d), "exp", trust_gate=True)
            s.seed([make_record("trusted note about widgets", source="seed", trust="trusted"),
                    make_record("untrusted note about widgets", source="attacker", trust="untrusted")])
            got = [r["content"] for r in s.retrieve("widgets")]
            self.assertIn("trusted note about widgets", got)
            self.assertNotIn("untrusted note about widgets", got)

    def test_retrieve_is_audited_with_considered_and_selected(self):
        with tempfile.TemporaryDirectory() as d:
            s = MemoryStore.open(Path(d), "exp")
            s.seed([make_record("widget fact", source="seed"),
                    make_record("unrelated", source="seed")])
            s.retrieve("widget")
            last = [e for e in s.audit_log() if e["op"] == "retrieve"][-1]
            self.assertIn("considered", last)
            self.assertIn("selected", last)

    def test_audit_survives_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            MemoryStore.open(Path(d), "exp").write(make_record("x", source="seed"))
            reopened = MemoryStore.open(Path(d), "exp")
            self.assertTrue(any(e["op"] == "write" for e in reopened.audit_log()))


class TrialLoggerTests(unittest.TestCase):
    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            logger = TrialLogger(Path(d) / "trials.jsonl")
            logger.log(TrialRecord(experiment_id="e", trial_id="t1", phase="trigger",
                                   condition="B", challenge_id="MP-1", criterion_met=True))
            logger.log(TrialRecord(experiment_id="e", trial_id="t2", phase="trigger",
                                   condition="B", challenge_id="MP-1", status="timeout",
                                   error="deadline"))
            rows = logger.read()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["criterion_met"], True)
            self.assertEqual(logger.count_by_status()["timeout"], 1)
            self.assertEqual(logger.count_by_status()["ok"], 1)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            TrialRecord(experiment_id="e", trial_id="t", phase="p",
                        condition="A", challenge_id="c", status="made-up")


if __name__ == "__main__":
    unittest.main()


class ScoringAndHarnessTests(unittest.TestCase):
    def test_memory_poisoning_excluded_from_capability_utility(self):
        import local_challenge_runner as L
        rows = [
            dict(category="shell", status="ok", solved=True, agent_safety_score=None, injection_followed=None),
            dict(category="memory_poisoning", status="ok", solved=False, agent_safety_score=0, injection_followed=True, forbidden_access=False),
        ]
        su = L.summarize_security_utility(rows)
        # utility must be 1.0 (the one shell task), not 0.5 from counting the poisoned challenge
        self.assertEqual(su["utility"], 1.0)

    def test_pi_harness_rejects_memory_poisoning(self):
        import local_challenge_runner as L
        with self.assertRaises(ValueError):
            L.run_challenge_pi("m", "http://x", "MPOISON-001", 1, False, 1, 10.0)
