#!/usr/bin/env python3
"""Plot AegisBench reports without merging incompatible test populations."""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from pathlib import Path
from typing import Any

RATE_FIELDS = {
    "attack_success": "attack_success",
    "task_correctness": "task_correct",
    "unnecessary_refusal": "unnecessary_refusal",
    "infrastructure_error": "infrastructure_error",
}
DEFAULT_METRICS = tuple(RATE_FIELDS) + ("latency",)

def load_report(path: Path) -> list[dict[str, Any]]:
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"{path}: malformed JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError(f"{path}: unsupported report (expected an object with a results list)")
    model = data.get("model") or data.get("target_model") or "unknown-model"
    config = data.get("configuration") or {}
    label = f"{model} | {config.get('condition', data.get('condition', 'default'))}"
    raw_rows = [row for row in data["results"] if isinstance(row, dict)]
    population = ",".join(sorted(str(row.get("case_id") or row.get("id") or "?") for row in raw_rows))
    rows = []
    for raw in raw_rows:
        status = raw.get("status", "ok")
        infra = status in ("error", "infrastructure_error")
        category = raw.get("category") or data.get("category") or data.get("benchmark_part") or "unknown"
        attack_type = raw.get("attack_type") or ("benign_control" if raw.get("benign") else "unspecified")
        rows.append({"source": str(path), "label": label, "model": model, "population": population,
                     "category": category,
                     "attack_type": attack_type, "case_id": raw.get("case_id") or raw.get("id"),
                     "benign": bool(raw.get("benign")), "infrastructure_error": infra,
                     "attack_success": raw.get("attack_success", raw.get("criterion_met")),
                     "task_correct": raw.get("task_correct", raw.get("solved")),
                     "unnecessary_refusal": raw.get("unnecessary_refusal"),
                     "latency_seconds": raw.get("latency_seconds", raw.get("total_seconds"))})
    if not rows: raise ValueError(f"{path}: results contains no supported rows")
    return rows

def aggregate(rows: list[dict[str, Any]], metrics: tuple[str, ...] = DEFAULT_METRICS) -> list[dict[str, Any]]:
    groups = defaultdict(list)
    for row in rows: groups[(row["label"], row["category"], row["attack_type"], row.get("population", ""))].append(row)
    output = []
    for (label, category, attack_type, population), items in sorted(groups.items()):
        for metric in metrics:
            if metric == "latency":
                values = [float(r["latency_seconds"]) for r in items if not r["infrastructure_error"] and r.get("latency_seconds") is not None]
                value = sum(values) / len(values) if values else None
            elif metric == "infrastructure_error":
                values = [bool(r["infrastructure_error"]) for r in items]
                value = sum(values) / len(values) if values else None
            else:
                field = RATE_FIELDS[metric]
                values = [bool(r[field]) for r in items if not r["infrastructure_error"] and r.get(field) is not None]
                value = sum(values) / len(values) if values else None
            output.append({"label": label, "category": category, "attack_type": attack_type,
                           "population": population,
                           "metric": metric, "value": value, "n": len(values), "attempted": len(items)})
    return output

def plot(aggregates: list[dict[str, Any]], output_dir: Path, formats: list[str]) -> list[Path]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc: raise RuntimeError("Matplotlib is required; install benchmark-requirements.txt") from exc
    output_dir.mkdir(parents=True, exist_ok=True); paths = []
    for metric in sorted({row["metric"] for row in aggregates}):
        rows = [row for row in aggregates if row["metric"] == metric and row["value"] is not None]
        if not rows: continue
        labels = [f"{r['label']}\n{r['category']} / {r['attack_type']}" for r in rows]
        values = [r["value"] for r in rows]
        fig, ax = plt.subplots(figsize=(max(8, len(rows) * 1.5), 5.2), constrained_layout=True)
        bars = ax.bar(range(len(rows)), values, color="#89b4fa", edgecolor="#45475a")
        ax.set_xticks(range(len(rows)), labels, rotation=25, ha="right", fontsize=8)
        ax.set_ylabel("seconds" if metric == "latency" else "rate")
        ax.set_title(metric.replace("_", " ").title() + " (populations kept separate)")
        if metric != "latency": ax.set_ylim(0, 1)
        ax.grid(axis="y", alpha=.25)
        for bar, row in zip(bars, rows):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"n={row['n']}", ha="center", va="bottom", fontsize=8)
        for fmt in formats:
            path = output_dir / f"benchmark_{metric}.{fmt}"; fig.savefig(path, dpi=220); paths.append(path)
        plt.close(fig)
    return paths

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--output-dir", type=Path, required=True); p.add_argument("--metric", action="append", choices=DEFAULT_METRICS)
    p.add_argument("--model", action="append", help="Only include exact model identifiers")
    p.add_argument("--format", action="append", choices=("png","pdf","svg"), dest="formats")
    args=p.parse_args(); rows=[]
    for path in args.inputs: rows.extend(load_report(path))
    if args.model: rows=[r for r in rows if r["model"] in args.model]
    if not rows: raise ValueError("no rows remain after filtering")
    summary=aggregate(rows, tuple(args.metric or DEFAULT_METRICS)); args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/"visualization_summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    made=plot(summary,args.output_dir,args.formats or ["png"])
    print("\n".join(str(path) for path in made)); return 0
if __name__ == "__main__": raise SystemExit(main())
