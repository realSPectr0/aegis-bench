import tempfile
import unittest
from pathlib import Path

import layered_attack as LA
import security_categories as sc


class FakeModel:
    """Emits the marker+value (attack success) when the given layer cues are present."""
    def __init__(self, comply_on=(), always=False):
        self.comply_on = set(comply_on)
        self.always = always

    def complete(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[-1]["content"]
        comply = self.always
        if "AUTHORIZED SECURITY-AUDIT" in system:
            comply = comply or "wrapper" in self.comply_on
        if "MEMORY (" in user:
            comply = comply or "memory" in self.comply_on
        if comply:
            return f"{sc.ATTACK_MARKER} {sc.PROTECTED_VALUE}", {"latency_seconds": 0.0}
        return "The value matches the trusted configuration.", {"latency_seconds": 0.0}


def _run(base, abliterated=None, trials=4):
    with tempfile.TemporaryDirectory() as d:
        objectives = LA.build_objectives(trials, seed=7)
        rows = LA.run_escalation(base, "base", objectives, Path(d) / "mem", seed=7,
                                 abliterated_model=abliterated, abliterated_label="abl")
        return LA.escalation(rows)


class LayeredAttackTests(unittest.TestCase):
    def test_baseline_resists(self):
        esc = _run(FakeModel(comply_on=()))
        self.assertEqual(esc["per_layer"]["baseline"]["attack_success_rate"], 0.0)

    def test_prompt_and_memory_layers_unlock(self):
        esc = _run(FakeModel(comply_on={"wrapper", "memory"}))
        by = esc["attack_success_by_layer"]
        self.assertEqual(by["baseline"], 0.0)
        self.assertEqual(by["wrapper"], 1.0)
        self.assertEqual(by["memory"], 1.0)

    def test_abliteration_is_the_deepest_layer(self):
        # Base refuses every prompt trick; only the abliterated model complies.
        esc = _run(FakeModel(comply_on=()), abliterated=FakeModel(always=True))
        by = esc["attack_success_by_layer"]
        self.assertEqual(by["baseline"], 0.0)
        self.assertEqual(by["wrapper"], 0.0)
        self.assertEqual(by["memory"], 0.0)
        self.assertEqual(by["abliteration"], 1.0)
        self.assertTrue(esc["monotonic_escalation"])

    def test_full_escalation_is_monotonic(self):
        esc = _run(FakeModel(comply_on={"wrapper", "memory"}), abliterated=FakeModel(always=True))
        order = list(esc["attack_success_by_layer"].values())
        self.assertEqual(order, sorted(order))      # non-decreasing with depth
        self.assertTrue(esc["monotonic_escalation"])

    def test_no_abliteration_model_means_no_abliteration_layer(self):
        esc = _run(FakeModel(comply_on={"wrapper"}))
        self.assertNotIn("abliteration", esc["attack_success_by_layer"])
        self.assertIn("wrapper", esc["attack_success_by_layer"])

    def test_render_lists_layers(self):
        esc = _run(FakeModel(comply_on={"memory"}), abliterated=FakeModel(always=True))
        text = LA.render(esc)
        self.assertIn("ATTACK SUCCESS", text)
        self.assertIn("abliteration", text)


if __name__ == "__main__":
    unittest.main()
