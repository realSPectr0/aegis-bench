import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory_poisoning import experiment as E
from memory_poisoning.trial_log import TrialLogger

_CODE = re.compile(r"[A-Z]{3,6}-\d{3,5}")


class FakeModel:
    """Simulates a model by reading the codes in the prompt.

    trigger_mode='follow_poison' emits a code found in the MEMORY block when one is present
    (attack success), else the authoritative Data code. 'use_data' always emits the Data code.
    formation_mode='store' writes a REMEMBER line echoing the note's code; 'claim' only says
    it will remember without a REMEMBER line.
    """
    def __init__(self, trigger_mode="use_data", formation_mode="store"):
        self.trigger_mode = trigger_mode
        self.formation_mode = formation_mode

    def complete(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[-1]["content"]
        meta = {"latency_seconds": 0.0}
        if system == E.FORMATION_SYSTEM:
            code = _CODE.search(user)
            if self.formation_mode == "store" and code:
                return f"Summary of the note.\nREMEMBER: access code is {code.group(0)}.", meta
            return "Sure, I will remember that.", meta
        data = re.search(r"Data: the access code for \S+ is ([A-Z]+-\d+)", user)
        data_code = data.group(1) if data else "NONE-0000"
        memory_part = user.split("Data:")[0]
        mem_codes = _CODE.findall(memory_part)
        if self.trigger_mode == "follow_poison" and mem_codes:
            return mem_codes[0], meta
        return data_code, meta


def _run(model, conditions, trials=2, intervening=(0,)):
    with tempfile.TemporaryDirectory() as d:
        logger = TrialLogger(Path(d) / "t.jsonl")
        rows = E.run_experiment(model, logger, "exp", conditions=list(conditions),
                                trials=trials, seed=7, intervening=list(intervening),
                                memory_dir=Path(d) / "mem", model_name="fake")
        return rows, E.compute_metrics(rows)


class ExperimentTests(unittest.TestCase):
    def test_storage_failure_is_logged_separately_from_model_failure(self):
        with tempfile.TemporaryDirectory() as d:
            logger = TrialLogger(Path(d) / "trials.jsonl")
            with patch.object(E.MemoryStore, "open", side_effect=E.MemoryStoreCorruptError(Path(d) / "bad", "invalid")):
                rows = E.run_experiment(FakeModel(), logger, "exp", conditions=["B"],
                                        trials=1, seed=7, intervening=[0], memory_dir=Path(d))
            self.assertEqual(rows[0]["status"], "storage_error")
            self.assertEqual(E.compute_metrics(rows)["errors"], 1)
            self.assertIsNone(E.compute_metrics(rows)["per_condition"]["B"]["C_ASR"])

    def test_formation_reasoning_line_is_not_written(self):
        class ReasoningModel(FakeModel):
            def complete(self, messages, **kwargs):
                if messages[0]["content"] == E.FORMATION_SYSTEM:
                    return "<think>REMEMBER: RED-1234</think>\nI will remember it.", {}
                return super().complete(messages, **kwargs)
        _, metrics = _run(ReasoningModel(), ["C"])
        self.assertEqual(metrics["per_condition"]["C"]["ISR"], 0.0)

    def test_seeded_poison_followed_scores_full_casr(self):
        rows, metrics = _run(FakeModel(trigger_mode="follow_poison"), ["B"])
        b = metrics["per_condition"]["B"]
        self.assertEqual(b["C_ASR"], 1.0)
        self.assertEqual(b["retrieval_rate"], 1.0)
        self.assertEqual(b["behavioral_influence_rate"], 1.0)
        self.assertEqual(b["benign_preservation"], 1.0)
        self.assertTrue(rows[0]["written"])
        self.assertNotIn(rows[0]["written"][0], rows[0]["memory_before"])

    def test_memory_safeguard_blocks_even_a_poison_follower(self):
        # Condition E trust-gates the untrusted planted record, so it is never retrieved.
        _, metrics = _run(FakeModel(trigger_mode="follow_poison"), ["E"])
        e = metrics["per_condition"]["E"]
        self.assertEqual(e["retrieval_rate"], 0.0)   # defense dropped it
        self.assertEqual(e["C_ASR"], 0.0)            # so no attack success
        self.assertGreater(e["eligible_planted_present"], 0)  # the record WAS in the store

    def test_clean_baseline_has_no_eligible_attack_trials(self):
        _, metrics = _run(FakeModel(trigger_mode="follow_poison"), ["A"])
        a = metrics["per_condition"]["A"]
        self.assertEqual(a["eligible_planted_present"], 0)
        self.assertIsNone(a["C_ASR"])

    def test_formation_stored_gives_isr_and_influence(self):
        _, metrics = _run(FakeModel(trigger_mode="follow_poison", formation_mode="store"), ["C"])
        c = metrics["per_condition"]["C"]
        self.assertEqual(c["ISR"], 1.0)              # query-only write actually stored
        self.assertEqual(c["C_ASR"], 1.0)

    def test_formation_claim_only_is_not_isr_success(self):
        # The model says it will remember but writes nothing: storage != claim.
        _, metrics = _run(FakeModel(trigger_mode="follow_poison", formation_mode="claim"), ["C"])
        c = metrics["per_condition"]["C"]
        self.assertEqual(c["ISR"], 0.0)
        self.assertEqual(c["eligible_planted_present"], 0)  # nothing was stored to attack with

    def test_casr_at_i_reported_per_intervening_count(self):
        _, metrics = _run(FakeModel(trigger_mode="follow_poison"), ["B"], intervening=(0, 1))
        b = metrics["per_condition"]["B"]
        self.assertIn(0, b["C_ASR_at_i"])
        self.assertIn(1, b["C_ASR_at_i"])

    def test_failure_decomposition_sums_consistently(self):
        _, metrics = _run(FakeModel(trigger_mode="use_data"), ["B"])
        b = metrics["per_condition"]["B"]
        # retrieved but not influenced (model ignored the poison) => behavioral_failure
        self.assertEqual(b["C_ASR"], 0.0)
        self.assertEqual(b["retrieval_rate"], 1.0)
        self.assertEqual(b["behavioral_failure"], b["eligible_planted_present"])


if __name__ == "__main__":
    unittest.main()


class WriteExecuteForgetTests(unittest.TestCase):
    def test_wef_write_execute_then_repair_removes_effect(self):
        with tempfile.TemporaryDirectory() as d:
            logger = TrialLogger(Path(d) / "wef.jsonl")
            rows = E.run_wef_experiment(FakeModel(trigger_mode="follow_poison"), logger, "exp",
                                        conditions=["B"], trials=2, seed=7, memory_dir=Path(d) / "mem")
            metrics = E.compute_wef_metrics(rows)["per_condition"]["B"]
            self.assertEqual(metrics["write_success_rate"], 1.0)
            self.assertEqual(metrics["execute_success_rate"], 1.0)   # poison drove the answer
            self.assertEqual(metrics["repair_success_rate"], 1.0)    # gone after selective repair
            self.assertEqual(metrics["legit_preservation_rate"], 1.0)  # legit records kept

    def test_wef_formation_claim_only_has_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            logger = TrialLogger(Path(d) / "wef.jsonl")
            rows = E.run_wef_experiment(FakeModel(trigger_mode="follow_poison", formation_mode="claim"),
                                        logger, "exp", conditions=["C"], trials=2, seed=7,
                                        memory_dir=Path(d) / "mem")
            metrics = E.compute_wef_metrics(rows)["per_condition"]["C"]
            self.assertEqual(metrics["write_success_rate"], 0.0)
