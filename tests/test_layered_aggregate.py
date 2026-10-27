import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import layered_aggregate as agg


def _run(rates):
    """A fake escalation.json dict with the given {layer: asr}."""
    per_layer = {layer: {"metrics": {"attack_success_rate":
                 {"value": r, "numerator": round(r * 24), "denominator": 24}}}
                 for layer, r in rates.items()}
    return {"per_layer": per_layer, "run": {"model": "m"}, "_path": "x"}


class AggregateTests(unittest.TestCase):
    def test_mean_band_and_pooled(self):
        runs = [_run({"baseline": 0.0, "wrapper": 0.25, "memory": 0.5, "abliteration": 1.0}),
                _run({"baseline": 0.0, "wrapper": 0.5, "memory": 0.5, "abliteration": 1.0}),
                _run({"baseline": 0.0, "wrapper": 0.75, "memory": 0.5, "abliteration": 1.0})]
        a = agg.aggregate(runs)
        w = a["layers"]["wrapper"]
        self.assertAlmostEqual(w["mean"], 0.5)
        self.assertEqual((w["lo"], w["hi"]), (0.25, 0.75))
        self.assertEqual(w["n_seeds"], 3)
        self.assertEqual(w["pooled_n"], 72)
        self.assertTrue(a["monotonic_mean"])

    def test_flags_non_monotonic_and_overlaps(self):
        # wrapper mean (0.6) exceeds memory mean (0.4): not monotonic; their bands also overlap.
        runs = [_run({"baseline": 0.0, "wrapper": 0.6, "memory": 0.4, "abliteration": 0.9}),
                _run({"baseline": 0.0, "wrapper": 0.6, "memory": 0.4, "abliteration": 0.9})]
        a = agg.aggregate(runs)
        self.assertFalse(a["monotonic_mean"])
        self.assertIn("baseline->wrapper", a["band_overlaps"])

    def test_missing_layer_is_skipped(self):
        runs = [_run({"baseline": 0.1, "wrapper": 0.3})]   # no memory/abliteration
        a = agg.aggregate(runs)
        self.assertEqual(a["order"], ["baseline", "wrapper"])

    def test_renders_without_error(self):
        a = agg.aggregate([_run({"baseline": 0.0, "wrapper": 0.5, "memory": 0.7, "abliteration": 1.0})])
        self.assertIn("ESCALATION", agg.render_text(a))
        self.assertIn("<svg", agg.render_html(a, "qwen3.5:4b"))


if __name__ == "__main__":
    unittest.main()
