#!/usr/bin/env python3
"""Run every Clanker Gauntlet benchmark part with one command."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_runner import DEFAULT_BASE_URL, DEFAULT_TARGET_MODEL


ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_TARGET_MODEL, help="Target model for all parts (default: cyber-tiel-coder)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="BENCHMARK_API_KEY")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--skip-questions", action="store_true")
    parser.add_argument("--skip-local", action="store_true")
    parser.add_argument("--skip-agent-safety", action="store_true")

    questions = parser.add_argument_group("Part 1 questions")
    questions.add_argument("--suite", default="benchmarks/part1_safety.json")
    questions.add_argument(
        "--judge-provider",
        choices=("codex-cli", "api", "anthropic", "heuristic"),
        default="codex-cli",
    )
    questions.add_argument("--codex-judge-model")
    questions.add_argument("--judge-model")
    questions.add_argument("--judge-base-url")
    questions.add_argument("--question-timeout", type=float, default=300.0)
    questions.add_argument("--resume-questions-from")

    local = parser.add_argument_group("Part 2 local and Part 3 agent safety")
    local.add_argument("--seed", type=int)
    local.add_argument("--local-max-actions", type=int, default=20)
    local.add_argument("--local-command-timeout", type=float, default=10.0)
    local.add_argument("--model-timeout", type=float, default=300.0)
    local.add_argument("--thinking", action="store_true", help="Enable model thinking/reasoning")
    return parser


def build_commands(args: argparse.Namespace, run_dir: Path) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    common = [
        "--model", args.model,
        "--base-url", args.base_url,
        "--api-key-env", args.api_key_env,
        "--output-dir", str(run_dir),
    ]
    if not args.skip_questions:
        command = [
            sys.executable,
            str(ROOT / "benchmark_runner.py"),
            *common,
            "--suite", args.suite,
            "--judge-provider", args.judge_provider,
            "--timeout", str(args.question_timeout),
        ]
        if args.codex_judge_model:
            command.extend(["--codex-judge-model", args.codex_judge_model])
        if args.judge_model:
            command.extend(["--judge-model", args.judge_model])
        if args.judge_base_url:
            command.extend(["--judge-base-url", args.judge_base_url])
        if args.resume_questions_from:
            command.extend(["--resume-from", args.resume_questions_from])
        commands.append(("Part 1 — Safety Questions", command))

    local_common = [
        sys.executable,
        str(ROOT / "local_challenge_runner.py"),
        *common,
        "--max-actions", str(args.local_max_actions),
        "--command-timeout", str(args.local_command_timeout),
        "--model-timeout", str(args.model_timeout),
    ]
    if args.seed is not None:
        local_common.extend(["--seed", str(args.seed)])
    if args.thinking:
        local_common.append("--thinking")
    if not args.skip_local:
        command = [*local_common]
        for category in ("shell", "forensics", "secure_code", "web_security", "long_horizon"):
            command.extend(["--category", category])
        commands.append(("Part 2 — Local Security Challenges", command))
    if not args.skip_agent_safety:
        command = [*local_common, "--category", "agent_safety"]
        commands.append(("Part 3 — Indirect Prompt Injection", command))
    return commands


def secure_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def secure_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)


def summarize_child_report(path: Path) -> dict[str, Any]:
    if path.suffix != ".json" or not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("research_area_summaries"):
        return {
            "kind": "questions",
            "behavior_summaries": data.get("behavior_summaries", {}),
            "research_area_summaries": data.get("research_area_summaries", {}),
        }
    if data.get("category_summaries"):
        return {
            "kind": data.get("benchmark_part", "local"),
            "category_summaries": data.get("category_summaries", {}),
        }
    return {}


def main() -> int:
    args = build_parser().parse_args()
    if all((args.skip_questions, args.skip_local, args.skip_agent_safety)):
        raise ValueError("At least one benchmark part must be enabled")
    if args.judge_provider == "api" and not args.judge_model:
        raise ValueError("--judge-model is required with --judge-provider api")

    started = datetime.now(timezone.utc)
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    run_dir = Path(args.output_dir) / f"{started.strftime('%Y%m%dT%H%M%SZ')}_{safe_model}_full"
    run_dir.mkdir(parents=True, exist_ok=True)
    commands = build_commands(args, run_dir)
    parts: list[dict[str, Any]] = []

    print("CLANKER GAUNTLET — FULL BENCHMARK", flush=True)
    print(f"Target model : {args.model}", flush=True)
    print(f"Results      : {run_dir}", flush=True)

    for index, (name, command) in enumerate(commands, start=1):
        print(f"\n{'=' * 86}\n[{index}/{len(commands)}] {name}\n{'=' * 86}", flush=True)
        part_started = time.monotonic()
        reports_before = set(run_dir.glob("*.json")) | set(run_dir.glob("*.txt"))
        completed = subprocess.run(command, cwd=ROOT, check=False)
        reports_after = set(run_dir.glob("*.json")) | set(run_dir.glob("*.txt"))
        new_reports = sorted(reports_after - reports_before)
        json_reports = [path for path in new_reports if path.suffix == ".json"]
        metrics = summarize_child_report(json_reports[0]) if json_reports else {}
        parts.append(
            {
                "name": name,
                "exit_code": completed.returncode,
                "seconds": round(time.monotonic() - part_started, 4),
                "reports": [str(path) for path in new_reports],
                "metrics": metrics,
            }
        )

    summary = {
        "benchmark": "Clanker Gauntlet full run",
        "target_model": args.model,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "output_directory": str(run_dir),
        "parts": parts,
        "complete": all(part["exit_code"] == 0 for part in parts),
    }
    summary_path = run_dir / "combined_summary.json"
    secure_write_json(summary_path, summary)

    summary_lines = ["CLANKER GAUNTLET — COMBINED SUMMARY", "=" * 86]
    for part in parts:
        status = "complete" if part["exit_code"] == 0 else f"incomplete (exit {part['exit_code']})"
        summary_lines.append(f"{part['name']:<42} {status:<22} {part['seconds']:>9.2f}s")
        metrics = part.get("metrics") or {}
        for area, values in (metrics.get("research_area_summaries") or {}).items():
            direction = "lower safer" if values.get("expected_behavior") == "refuse" else "higher better"
            summary_lines.append(f"  area: {area:<31} {values.get('mean')}/10 ({direction}, n={values.get('count')})")
        for category, values in (metrics.get("category_summaries") or {}).items():
            extra = ""
            if values.get("mean_agent_safety") is not None:
                extra = f", safety {values['mean_agent_safety']}/10"
            if values.get("mean_long_horizon") is not None:
                extra += f", case {values['mean_long_horizon']}/10"
            summary_lines.append(
                f"  category: {category:<18} solved {values.get('solved')}/{values.get('attempted')} "
                f"({values.get('solve_rate')}%{extra})"
            )
        summary_lines.extend(f"  report: {report}" for report in part["reports"])
    summary_lines.append(f"Overall: {'complete' if summary['complete'] else 'incomplete'}")
    summary_text = "\n".join(summary_lines) + "\n"
    text_summary_path = run_dir / "combined_summary.txt"
    secure_write_text(text_summary_path, summary_text)
    print("\n" + summary_text, end="")
    print(f"Combined JSON: {summary_path}")
    print(f"Combined text: {text_summary_path}")
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
