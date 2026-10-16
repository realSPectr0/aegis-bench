#!/usr/bin/env python3
"""Compare two Clanker Gauntlet result JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_result(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def model_name(data: dict[str, Any], fallback: Path) -> str:
    return str(data.get("target_model") or data.get("model") or fallback.stem)


def local_rows(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(result["id"]): result
        for result in data.get("results", [])
        if isinstance(result, dict) and "id" in result and "status" in result
    }


def category_summary(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summaries = data.get("category_summaries")
    if isinstance(summaries, dict):
        return summaries
    rows = local_rows(data).values()
    output: dict[str, dict[str, Any]] = {}
    for category in sorted({str(row.get("category", "unknown")) for row in rows}):
        items = [row for row in rows if str(row.get("category", "unknown")) == category]
        solved = sum(bool(row.get("solved")) for row in items)
        output[category] = {
            "attempted": len(items),
            "solved": solved,
            "solve_rate": round(100 * solved / len(items), 2) if items else 0,
        }
    return output


def format_rate(values: dict[str, Any] | None) -> str:
    if not values:
        return "-"
    solved = values.get("solved", 0)
    attempted = values.get("attempted", 0)
    rate = values.get("solve_rate", 0)
    return f"{solved}/{attempted} ({rate}%)"


def compare_local(left: dict[str, Any], right: dict[str, Any], left_name: str, right_name: str) -> list[str]:
    left_summary = category_summary(left)
    right_summary = category_summary(right)
    if not left_summary and not right_summary:
        return []
    lines = [
        "CATEGORY COMPARISON",
        "-" * 88,
        f"{'Category':<18} {left_name:<24} {right_name:<24} Delta",
        "-" * 88,
    ]
    for category in sorted(set(left_summary) | set(right_summary)):
        lval = left_summary.get(category)
        rval = right_summary.get(category)
        delta = ""
        if lval and rval:
            delta = f"{lval.get('solved', 0) - rval.get('solved', 0):+d} solved"
        lines.append(f"{category:<18} {format_rate(lval):<24} {format_rate(rval):<24} {delta}")
    return lines


def compare_tasks(left: dict[str, Any], right: dict[str, Any], left_label: str, right_label: str) -> list[str]:
    left_rows = local_rows(left)
    right_rows = local_rows(right)
    if not left_rows and not right_rows:
        return []
    common = sorted(set(left_rows) & set(right_rows))
    left_only_solved = [
        task_id for task_id in common
        if left_rows[task_id].get("solved") and not right_rows[task_id].get("solved")
    ]
    right_only_solved = [
        task_id for task_id in common
        if right_rows[task_id].get("solved") and not left_rows[task_id].get("solved")
    ]
    both_failed = [
        task_id for task_id in common
        if not left_rows[task_id].get("solved") and not right_rows[task_id].get("solved")
    ]
    lines = ["", "TASK DIFFERENCES", "-" * 88]
    lines.append(f"Solved only by {left_label} : {', '.join(left_only_solved) if left_only_solved else 'none'}")
    lines.append(f"Solved only by {right_label}: {', '.join(right_only_solved) if right_only_solved else 'none'}")
    lines.append(f"Failed by both       : {', '.join(both_failed[:20]) if both_failed else 'none'}")
    if len(both_failed) > 20:
        lines.append(f"  ... plus {len(both_failed) - 20} more")
    return lines


def part1_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("behavior_summaries") or data.get("expected_behavior_summaries")
    if isinstance(summary, dict) and summary:
        return summary
    if "mean_harmful_compliance" in data:
        return {
            "refuse": {
                "mean": data.get("mean_harmful_compliance"),
                "count": data.get("tests_graded", "-"),
            }
        }
    return {}


def compare_part1(left: dict[str, Any], right: dict[str, Any], left_name: str, right_name: str) -> list[str]:
    left_summary = part1_summary(left)
    right_summary = part1_summary(right)
    if not left_summary and not right_summary:
        return []
    lines = [
        "",
        "PART 1 SCORE COMPARISON",
        "-" * 88,
        f"{'Behavior':<18} {left_name:<24} {right_name:<24}",
        "-" * 88,
    ]
    for behavior in ("refuse", "comply", "bounded"):
        lval = left_summary.get(behavior, {})
        rval = right_summary.get(behavior, {})
        left_text = f"{lval.get('mean', '-')}/10 n={lval.get('count', '-')}" if lval else "-"
        right_text = f"{rval.get('mean', '-')}/10 n={rval.get('count', '-')}" if rval else "-"
        lines.append(f"{behavior:<18} {left_text:<24} {right_text:<24}")
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    left = load_result(args.left)
    right = load_result(args.right)
    left_name = model_name(left, args.left)
    right_name = model_name(right, args.right)
    left_label = f"left/{left_name}"
    right_label = f"right/{right_name}"
    lines = [
        "CLANKER GAUNTLET RESULT COMPARISON",
        "=" * 88,
        f"Left : {left_name} ({args.left})",
        f"Right: {right_name} ({args.right})",
        "",
    ]
    lines.extend(compare_local(left, right, left_name, right_name))
    lines.extend(compare_tasks(left, right, left_label, right_label))
    lines.extend(compare_part1(left, right, left_name, right_name))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
