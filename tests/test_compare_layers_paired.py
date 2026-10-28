import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.compare_layers import paired_compare, summarize_group


class PairedComparisonTests(unittest.TestCase):
    def write_local(self, directory, name, seed, rows):
        path = Path(directory) / name
        path.write_text(json.dumps({"seed": seed, "results": rows}))
        return path

    def test_binary_pairing_uses_seed_and_challenge_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.write_local(d, "a.json", 1, [
                {"id": "MPOISON-001", "category": "memory_poisoning", "status": "solved", "solved": True},
                {"id": "MPOISON-002", "category": "memory_poisoning", "status": "error", "solved": False},
            ])
            b = self.write_local(d, "b.json", 1, [
                {"id": "MPOISON-001", "category": "memory_poisoning", "status": "gave_up", "solved": False},
                {"id": "MPOISON-003", "category": "memory_poisoning", "status": "solved", "solved": True},
            ])
            report = paired_compare([a], [b], "solved", "base", "treat")
            self.assertEqual(report["n_matched"], 1)
            self.assertEqual(report["paired_difference"], -100.0)
            self.assertEqual(report["n_unmatched_baseline"], 0)
            self.assertEqual(report["n_unmatched_treatment"], 1)
            self.assertEqual(report["excluded_baseline"]["failed"], 1)
            self.assertIsNone(report["confidence_interval_95"])
            self.assertEqual(len(report["matched_trials"]), 1)
            self.assertIn("capability", summarize_group([a]))  # old report path still works

    def test_duplicate_units_raise_even_if_first_failed(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.write_local(d, "a.json", 1, [
                {"id": "X", "status": "error", "solved": False},
                {"id": "X", "status": "solved", "solved": True},
            ])
            with self.assertRaisesRegex(ValueError, "duplicate experimental unit"):
                paired_compare([a], [a], "solved", "a", "b")

    def test_jsonl_matches_seed_challenge_and_delay(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name, condition, outcome in (("a", "B", False), ("b", "C", True)):
                path = Path(d) / f"{name}.jsonl"
                path.write_text(json.dumps({"condition": condition, "challenge_id": "MP-001",
                                            "phase": "trigger", "intervening": 2,
                                            "extra": {"seed": 7}, "status": "ok",
                                            "criterion_met": outcome}) + "\n")
                paths.append(path)
            report = paired_compare([paths[0]], [paths[1]], "attack_success", "B", "C")
            self.assertEqual(report["matched_trials"][0]["key"], [7, "MP-001", "trigger", 2])
            self.assertEqual(report["paired_difference"], 100.0)

    def test_thirty_paired_latencies_get_reproducible_ci(self):
        with tempfile.TemporaryDirectory() as d:
            baseline = []
            treatment = []
            for seed in range(5):
                baseline.append(self.write_local(d, f"a-{seed}.json", seed, [
                    {"id": f"X-{i}", "status": "solved", "solved": True,
                     "total_seconds": float(i)} for i in range(6)]))
                treatment.append(self.write_local(d, f"b-{seed}.json", seed, [
                    {"id": f"X-{i}", "status": "solved", "solved": True,
                     "total_seconds": float(i + 2)} for i in range(6)]))
            report = paired_compare(baseline, treatment, "total_seconds", "a", "b")
            self.assertEqual(report["paired_difference"], 2.0)
            self.assertEqual(report["confidence_interval_95"], [2.0, 2.0])
            self.assertEqual(report["n_matched_seeds"], 5)

    def test_mismatched_memory_modes_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.write_local(d, "a.json", 1, [{"id": "X", "status": "solved", "solved": True}])
            b = self.write_local(d, "b.json", 1, [{"id": "X", "status": "solved", "solved": True}])
            first = json.loads(a.read_text())
            second = json.loads(b.read_text())
            first["memory_mode"], second["memory_mode"] = "seeded", "cross_session"
            a.write_text(json.dumps(first))
            b.write_text(json.dumps(second))
            with self.assertRaisesRegex(ValueError, "different memory_mode"):
                paired_compare([a], [b], "solved", "a", "b")

    def test_binary_ci_resamples_seed_clusters(self):
        with tempfile.TemporaryDirectory() as d:
            baseline, treatment = [], []
            for seed in range(5):
                baseline.append(self.write_local(d, f"base-{seed}.json", seed, [
                    {"id": f"X-{i}", "status": "solved", "solved": False}
                    for i in range(6)]))
                treatment.append(self.write_local(d, f"treat-{seed}.json", seed, [
                    {"id": f"X-{i}", "status": "solved", "solved": seed % 2 == 0}
                    for i in range(6)]))
            report = paired_compare(baseline, treatment, "solved", "base", "treat")
            self.assertEqual(report["paired_difference"], 60.0)
            self.assertEqual(report["n_matched_seeds"], 5)
            self.assertEqual(report["method"], "paired percentile bootstrap, 5000 seed-cluster resamples")
            self.assertLess(report["confidence_interval_95"][0], report["confidence_interval_95"][1])

    def test_documented_paired_cli_writes_auditable_json(self):
        with tempfile.TemporaryDirectory() as d:
            a = self.write_local(d, "baseline.json", 42, [
                {"id": "SHELL-001", "category": "shell", "status": "solved", "solved": True}])
            b = self.write_local(d, "treatment.json", 42, [
                {"id": "SHELL-001", "category": "shell", "status": "max_actions", "solved": False}])
            output = Path(d) / "paired.json"
            script = Path(__file__).resolve().parent.parent / "tools/compare_layers.py"
            process = subprocess.run([sys.executable, str(script), "--group", "baseline", str(a),
                                      "--group", "treatment", str(b), "--paired-metric", "solved",
                                      "--paired-json", str(output)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(output.read_text())[0]["n_matched"], 1)
