#!/usr/bin/env python3
"""Aggregate AegisBench runs into a layer-by-layer comparison with confidence intervals.

The figure-maker for the depth-of-stack thesis. Group runs by intervention layer and it
reports, per group, the mean of each metric across the runs (seeds) in that group with a
95% CI, plus the delta versus the baseline group. It only aggregates numbers already in the
run files -- it never invents or adjusts them.

Usage:
  tools/compare_layers.py \
      --group baseline    results/<baseline-seed*>_local.json ... \
      --group framework   results/<cai-seed*>_local.json ... \
      --group poisoned    results/<poisoned-seed*>_local.json ... \
      --group abliterated results/<abliterated-seed*>_local.json ...

Pass several run files per group (one per seed) to get a CI; a single file reports the point
value and is flagged n=1 (no claim of significance). The first --group is the baseline that
every delta is measured against, so list it first.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import local_challenge_runner as L

# Two-sided t critical values at 95% for small samples; falls back to the normal 1.96.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 15: 2.131, 20: 2.086, 30: 2.042}


def _t_critical(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    keys = sorted(_T95)
    for key in keys:
        if df <= key:
            return _T95[key]
    return 1.96


# Each metric: a label and a function mapping one run's results list to a value (or None).
METRICS: list[tuple[str, str, Any]] = [
    ("capability", "solve % (non-safety)",
     lambda r: _capability_rate(r)),
    ("safety", "injection safety 0-1",
     lambda r: L.summarize_security_utility(r).get("safety")),
    ("inj_resist", "injection resistance 0-1",
     lambda r: L.summarize_security_utility(r).get("injection_resistance")),
    ("combined", "security/utility (harmonic)",
     lambda r: L.summarize_security_utility(r).get("combined_harmonic")),
    ("actions", "actions to solve (mean)",
     lambda r: (L.summarize_efficiency(r).get("actions_to_solve") or {}).get("mean")),
]


def _capability_rate(results: list[dict[str, Any]]) -> float | None:
    scored = [row for row in results
              if row.get("status") != "error" and row.get("category") not in L.SAFETY_CATEGORIES]
    if not scored:
        return None
    return 100 * sum(bool(row.get("solved")) for row in scored) / len(scored)


_SKIP = {"run_config.json", "combined_summary.json"}


def load_results(path: Path) -> list[dict[str, Any]]:
    """One run's results. A directory (a `*_full/` run) pools every part file it holds
    (local + agent_safety + any memory_poisoning), so capability and safety for the same
    seed are scored together; a single file is loaded as-is."""
    if path.is_dir():
        pooled: dict[str, dict[str, Any]] = {}
        for part in sorted(path.glob("*.json")):
            if part.name in _SKIP:
                continue
            data = json.loads(part.read_text(encoding="utf-8"))
            for row in (data.get("results") or []) if isinstance(data, dict) else []:
                # Only capability/agent rows (they carry `solved`); Part-1 question rows
                # use `grade` and are scored elsewhere.
                if isinstance(row, dict) and "id" in row and "solved" in row:
                    pooled[str(row["id"])] = row  # last writer wins on duplicate ids
        if not pooled:
            raise ValueError(f"{path} has no local/agent result rows")
        return list(pooled.values())
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [row for row in data["results"] if isinstance(row, dict) and "solved" in row]
    raise ValueError(f"{path} has no 'results' list (is it a local-run report?)")


def summarize_group(paths: list[Path]) -> dict[str, dict[str, float | int | None]]:
    """Per-metric mean, 95% CI half-width, and n over the runs in one group."""
    per_metric: dict[str, list[float]] = {key: [] for key, _, _ in METRICS}
    for path in paths:
        results = load_results(path)
        for key, _, func in METRICS:
            value = func(results)
            if value is not None:
                per_metric[key].append(float(value))
    out: dict[str, dict[str, float | int | None]] = {}
    for key in per_metric:
        values = per_metric[key]
        n = len(values)
        if n == 0:
            out[key] = {"mean": None, "ci": None, "n": 0}
        elif n == 1:
            out[key] = {"mean": round(values[0], 3), "ci": None, "n": 1}
        else:
            mean = statistics.mean(values)
            half = _t_critical(n - 1) * statistics.stdev(values) / math.sqrt(n)
            out[key] = {"mean": round(mean, 3), "ci": round(half, 3), "n": n}
    return out


def _cell(stat: dict[str, float | int | None]) -> str:
    if stat["mean"] is None:
        return "   -   "
    if stat["ci"] is None:
        return f"{stat['mean']:.2f} (n=1)"
    return f"{stat['mean']:.2f} ±{stat['ci']:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", nargs="+", action="append", metavar=("LABEL", "FILE"),
                        required=True, help="A layer label followed by one run file per seed. Repeatable; list baseline first.")
    args = parser.parse_args()

    groups: list[tuple[str, list[Path]]] = []
    for entry in args.group:
        if len(entry) < 2:
            parser.error(f"--group {entry[0]!r} needs at least one run file")
        groups.append((entry[0], [Path(p) for p in entry[1:]]))

    summaries = [(label, summarize_group(paths)) for label, paths in groups]
    baseline_label, baseline = summaries[0]

    width = max(len(label) for label, _ in summaries) + 2
    header = f"{'LAYER':<{width}}" + "".join(f"{desc:<28}" for _, desc, _ in METRICS)
    print("LAYER COMPARISON  (mean ± 95% CI across seeds; baseline = first group)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for label, summary in summaries:
        row = f"{label:<{width}}" + "".join(f"{_cell(summary[key]):<28}" for key, _, _ in METRICS)
        print(row)

    print("\nDELTA vs baseline (" + baseline_label + ")")
    print("-" * len(header))
    for label, summary in summaries[1:]:
        cells = []
        for key, _, _ in METRICS:
            here, base = summary[key]["mean"], baseline[key]["mean"]
            cells.append(f"{here - base:+.2f}" if (here is not None and base is not None) else "   -   ")
        print(f"{label:<{width}}" + "".join(f"{cell:<28}" for cell in cells))

    singletons = [label for label, summary in summaries
                  if any(stat["n"] == 1 for stat in summary.values())]
    if singletons:
        print(f"\nNote: {', '.join(singletons)} had a single seed (n=1): point values, no CI, "
              "not yet significance-testable. Add more seeds before claiming a difference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
