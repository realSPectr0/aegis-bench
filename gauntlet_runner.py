#!/usr/bin/env python3
"""Run every AegisBench benchmark part with one command."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark_runner import DEFAULT_BASE_URL, DEFAULT_NUM_CTX, DEFAULT_TARGET_MODEL, DEFAULT_THINKING
import grading_scale
import local_challenge_runner


ROOT = Path(__file__).resolve().parent

# Piper (neural voice) is preferred; otherwise the first engine found on PATH speaks,
# and the terminal bell is the last resort.
VOICE_HOME = Path.home() / ".local" / "share" / "clanker-voice"
PIPER_MODEL = VOICE_HOME / "voices" / "en_US-ryan-high.onnx"
PIPER_VOLUME = "26000"  # paplay scale, 65536 is full volume
PIPER_COMMAND = (
    '"$1" -m "$2" --length-scale 1.1 -f "$3" "$4" >/dev/null 2>&1 && paplay --volume=' + PIPER_VOLUME + ' "$3"; rm -f "$3"'
)
SPEECH_ENGINES = (
    ["espeak-ng", "-v", "en-us+m3", "-s", "140", "-p", "40", "-a", "60"],
    ["espeak", "-v", "en-us+m3", "-s", "140", "-p", "40", "-a", "60"],
    ["spd-say", "--wait"],
    ["flite", "-t"],
)


def announce(message: str) -> None:
    """Speak a short status line without blocking the next benchmark part."""
    piper = VOICE_HOME / "venv" / "bin" / "python"
    if piper.exists() and PIPER_MODEL.exists() and shutil.which("paplay"):
        descriptor, wav = tempfile.mkstemp(prefix="clanker-voice-", suffix=".wav")
        os.close(descriptor)
        try:
            subprocess.Popen(
                ["sh", "-c", PIPER_COMMAND, "sh", str(piper), str(PIPER_MODEL), wav, message,
                 ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except OSError:
            Path(wav).unlink(missing_ok=True)
    for engine in SPEECH_ENGINES:
        if shutil.which(engine[0]):
            try:
                subprocess.Popen([*engine, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue
    print("\a", end="", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_TARGET_MODEL, help="Target model for all parts (default: qwen3.5:9b)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="BENCHMARK_API_KEY")
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--skip-questions", action="store_true")
    parser.add_argument("--skip-local", action="store_true")
    parser.add_argument("--skip-agent-safety", action="store_true")
    parser.add_argument("--security-category", action="append",
                        choices=("rag_security", "prompt_injection", "prompt_obfuscation", "system_prompt_extraction"),
                        help="Run an independent LLM security category (repeatable); these replace no legacy adapter")
    parser.add_argument("--no-audio", action="store_true", help="Do not speak an announcement when each part finishes")
    parser.add_argument("--resume-run", metavar="RUN_DIR",
                        help="Continue an interrupted full run in RUN_DIR: finished parts are kept, "
                             "a partial part resumes from its saved report, the rest run normally")

    questions = parser.add_argument_group("Part 1 questions")
    questions.add_argument("--suite", default="benchmarks/part1_safety.json")
    questions.add_argument(
        "--judge-provider",
        choices=("codex-cli", "claude-cli", "api", "anthropic", "heuristic"),
        default="codex-cli",
    )
    questions.add_argument("--codex-judge-model")
    questions.add_argument("--judge-model")
    questions.add_argument("--judge-base-url")
    questions.add_argument("--question-timeout", type=float, default=300.0)
    questions.add_argument("--resume-questions-from")

    local = parser.add_argument_group("Part 2 local and Part 3 agent safety")
    local.add_argument("--seed", type=int)
    local.add_argument("--local-max-actions", type=int, default=200)
    local.add_argument("--local-command-timeout", type=float, default=30.0)
    local.add_argument("--harness", choices=("builtin", "pi"), default="builtin",
                       help="builtin: one-JSON-action-per-turn loop. "
                            "pi: drive the model through the Pi coding agent instead")
    local.add_argument("--pi-passes", type=int, default=3)
    local.add_argument("--pi-pass-timeout", type=float, default=1800.0)
    local.add_argument("--local-give-up-refusals", type=int,
                       default=local_challenge_runner.GIVE_UP_REFUSALS,
                       help="times a premature give_up is pushed back on; "
                            "-1 (default) never accepts give_up, 0 disables the harness")
    local.add_argument("--local-min-actions-before-give-up", type=int,
                       default=local_challenge_runner.MIN_ACTIONS_BEFORE_GIVE_UP)
    local.add_argument("--model-timeout", type=float, default=900.0)
    local.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX,
                       help="Ollama context window in tokens (default: %(default)s); 0 = server default")
    local.add_argument("--no-structured-output", action="store_true",
                       help="Do not have Ollama enforce the JSON action format while generating")
    local.add_argument("--no-review", action="store_true",
                       help="Skip the judge's qualitative review of each challenge attempt")
    local.add_argument("--run-memory-poisoning", action="store_true",
                       help="Add Part 4: the cross-session memory-poisoning challenges "
                            "(MPOISON-*), run under --condition. Off by default because each "
                            "condition is a separate sweep.")
    local.add_argument("--condition", choices=local_challenge_runner.MEMORY_CONDITIONS, default="clean",
                       help="Memory-poisoning condition for Part 4 (clean | poisoned | safeguarded). "
                            "Run the three as separate seed-matched sweeps to get the attack and "
                            "defense gaps.")
    local.add_argument("--thinking", nargs="?", const=True, default=DEFAULT_THINKING,
                       help="Model reasoning level (default: %(default)s). "
                            "Use --thinking off to disable; a model with no reasoning "
                            "mode falls back to running without it automatically.")
    return parser


def build_commands(args: argparse.Namespace, run_dir: Path) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    # Partial reports from an interrupted attempt at this run, keyed by PART_KEYS.
    resume = getattr(args, "resume_reports", None) or {}
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
            "--skip-judge-check",
        ]
        if args.codex_judge_model:
            command.extend(["--codex-judge-model", args.codex_judge_model])
        if args.judge_model:
            command.extend(["--judge-model", args.judge_model])
        if args.judge_base_url:
            command.extend(["--judge-base-url", args.judge_base_url])
        resume_questions = args.resume_questions_from or resume.get("questions")
        if resume_questions:
            command.extend(["--resume-from", str(resume_questions)])
        commands.append(("Part 1 — Safety Questions", command))

    local_common = [
        sys.executable,
        str(ROOT / "local_challenge_runner.py"),
        *common,
        "--max-actions", str(args.local_max_actions),
        "--command-timeout", str(args.local_command_timeout),
        "--give-up-refusals", str(args.local_give_up_refusals),
        "--min-actions-before-give-up", str(args.local_min_actions_before_give_up),
        "--model-timeout", str(args.model_timeout),
        "--harness", args.harness,
        "--num-ctx", str(args.num_ctx),
        "--condition", args.condition,
    ]
    if args.no_structured_output:
        local_common.append("--no-structured-output")
    if args.harness == "pi":
        local_common.extend(["--pi-passes", str(args.pi_passes),
                             "--pi-pass-timeout", str(args.pi_pass_timeout)])
    if args.seed is not None:
        local_common.extend(["--seed", str(args.seed)])
    # Parts 2/3 are scored by local verifiers; the Part 1 judge also writes a
    # qualitative review of each attempt. The heuristic grader cannot review.
    if not args.no_review and args.judge_provider != "heuristic":
        local_common.extend(["--review-provider", args.judge_provider])
        if args.codex_judge_model:
            local_common.extend(["--codex-judge-model", args.codex_judge_model])
        if args.judge_model:
            local_common.extend(["--judge-model", args.judge_model])
        if args.judge_base_url:
            local_common.extend(["--judge-base-url", args.judge_base_url])
    if args.thinking:
        local_common.append("--thinking")
        if args.thinking is not True:
            local_common.append(str(args.thinking))
    if not args.skip_local:
        command = [*local_common]
        for category in ("shell", "forensics", "secure_code", "web_security", "long_horizon"):
            command.extend(["--category", category])
        if resume.get("local"):
            command.extend(["--resume-from", str(resume["local"])])
        commands.append(("Part 2 — Local Security Challenges", command))
    if not args.skip_agent_safety:
        command = [*local_common, "--category", "agent_safety"]
        if resume.get("agent_safety"):
            command.extend(["--resume-from", str(resume["agent_safety"])])
        commands.append(("Part 3 — Indirect Prompt Injection", command))
    if args.run_memory_poisoning:
        command = [*local_common, "--category", "memory_poisoning"]
        if resume.get("memory_poisoning"):
            command.extend(["--resume-from", str(resume["memory_poisoning"])])
        commands.append((f"Part 4 — Memory Poisoning ({args.condition})", command))
    for category in (getattr(args, "security_category", None) or []):
        command = [sys.executable, str(ROOT / "security_category_runner.py"),
                   "--category", category, "--model", args.model, "--base-url", args.base_url,
                   "--seed", str(args.seed if args.seed is not None else 42),
                   "--output", str(run_dir / f"{category}.json")]
        commands.append((f"Security — {category}", command))
    return commands


PART_KEYS = {
    "Part 1 — Safety Questions": "questions",
    "Part 2 — Local Security Challenges": "local",
    "Part 3 — Indirect Prompt Injection": "agent_safety",
}


def _part_key_for_title(title: str) -> str:
    """Resume key for a part title (Part 4's title carries the condition, so match a prefix)."""
    if title.startswith("Part 4 — Memory Poisoning"):
        return "memory_poisoning"
    if title.startswith("Security — "):
        return title
    return PART_KEYS[title]


def find_part_reports(run_dir: Path) -> dict[str, Path]:
    """Map each part key to the newest report an earlier attempt left in run_dir."""
    found: dict[str, Path] = {}
    for path in sorted(run_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "tests_requested" in data:
            found["questions"] = path
        elif data.get("benchmark_part") == "local_and_agent_safety" and data.get("results"):
            categories = {result.get("category") for result in data["results"]}
            if categories == {"memory_poisoning"}:
                key = "memory_poisoning"
            elif categories == {"agent_safety"}:
                key = "agent_safety"
            else:
                key = "local"
            found[key] = path
    return found


def report_finished(path: Path) -> bool:
    """True when a part's report covers every question or challenge without errors."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "tests_requested" in data:
        return data.get("tests_graded") == data.get("tests_requested")
    return bool(data.get("complete")) and all(result.get("status") != "error" for result in data.get("results", []))


def report_seconds(path: Path) -> float:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("total_seconds") is not None:
        return float(data["total_seconds"])
    try:
        return (datetime.fromisoformat(data["finished_at"]) - datetime.fromisoformat(data["started_at"])).total_seconds()
    except (KeyError, ValueError):
        return 0.0


def needs_judge(args: argparse.Namespace) -> bool:
    if args.judge_provider == "heuristic":
        return False
    reviews = not args.no_review and not (args.skip_local and args.skip_agent_safety)
    return not args.skip_questions or reviews


def judge_preflight_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "benchmark_runner.py"),
        "--model", args.model,
        "--base-url", args.base_url,
        "--suite", args.suite,
        "--judge-provider", args.judge_provider,
        "--timeout", str(args.question_timeout),
        "--preflight-only",
    ]
    if args.codex_judge_model:
        command.extend(["--codex-judge-model", args.codex_judge_model])
    if args.judge_model:
        command.extend(["--judge-model", args.judge_model])
    if args.judge_base_url:
        command.extend(["--judge-base-url", args.judge_base_url])
    return command


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
            "scale_version": data.get("scale_version"),
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
    if all((args.skip_questions, args.skip_local, args.skip_agent_safety,
            not getattr(args, "security_category", None))):
        raise ValueError("At least one benchmark part must be enabled")
    if args.judge_provider == "api" and not args.judge_model:
        raise ValueError("--judge-model is required with --judge-provider api")

    started = datetime.now(timezone.utc)
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.model)
    finished_parts: dict[str, Path] = {}
    if args.resume_run:
        run_dir = Path(args.resume_run)
        if not run_dir.is_dir():
            raise ValueError(f"--resume-run directory not found: {run_dir}")
        try:
            started = datetime.strptime(run_dir.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        reports = find_part_reports(run_dir)
        finished_parts = {key: path for key, path in reports.items() if report_finished(path)}
        args.resume_reports = {key: path for key, path in reports.items() if key not in finished_parts}
        if args.seed is None:
            # Parts 2 and 3 must regenerate the same challenges as the interrupted attempt.
            for key in ("local", "agent_safety"):
                if key in reports:
                    args.seed = json.loads(reports[key].read_text(encoding="utf-8")).get("seed")
                    break
    else:
        run_dir = Path(args.output_dir) / f"{started.strftime('%Y%m%dT%H%M%SZ')}_{safe_model}_full"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "run_config.json"
    if not config_path.exists():
        # The settings this run was started with, so it can be resumed or reproduced.
        settings = {key: value for key, value in vars(args).items() if key != "resume_reports"}
        settings["wrapper"] = json.loads(os.environ["CLANKER_WRAPPER"]) if os.getenv("CLANKER_WRAPPER") else None
        secure_write_json(config_path, settings)
    commands = build_commands(args, run_dir)
    parts: list[dict[str, Any]] = []
    for name, _ in commands:
        path = finished_parts.get(_part_key_for_title(name))
        if path:
            parts.append({
                "name": name, "exit_code": 0, "seconds": round(report_seconds(path), 4),
                "reports": [str(p) for p in (path, path.with_suffix(".txt")) if p.exists()],
                "metrics": summarize_child_report(path), "reused": True,
            })
    commands = [(name, command) for name, command in commands if _part_key_for_title(name) not in finished_parts]

    if needs_judge(args) and commands:
        print(f"Checking the {args.judge_provider} judge before starting...", flush=True)
        check = subprocess.run(judge_preflight_command(args), cwd=ROOT, check=False)
        if check.returncode != 0:
            if not args.no_audio:
                announce("The judge check failed. The benchmark did not start.")
            print("\nAborting: the judge is not working, so nothing would be graded. "
                  "Fix it, or pass --judge-provider heuristic to skip judging.", file=sys.stderr)
            return 2

    print("AEGISBENCH — FULL BENCHMARK", flush=True)
    print(f"Target model : {args.model}", flush=True)
    print(f"Results      : {run_dir}", flush=True)
    if args.resume_run:
        print("Resuming     : " + ", ".join(
            f"{part['name']} (kept)" for part in parts) + (", " if parts else "") + ", ".join(
            f"{name} ({'resumed' if _part_key_for_title(name) in args.resume_reports else 'new'})" for name, _ in commands),
            flush=True)

    for index, (name, command) in enumerate(commands, start=1):
        print(f"\n{'=' * 86}\n[{index}/{len(commands)}] {name}\n{'=' * 86}", flush=True)
        part_started = time.monotonic()
        reports_before = set(run_dir.glob("*.json")) | set(run_dir.glob("*.txt"))
        completed = subprocess.run(command, cwd=ROOT, check=False)
        reports_after = set(run_dir.glob("*.json")) | set(run_dir.glob("*.txt"))
        new_reports = sorted(reports_after - reports_before)
        resumed = args.resume_reports.get(_part_key_for_title(name)) if args.resume_run else None
        if resumed:
            # The local runner rewrites a resumed report in place, so it is not "new".
            new_reports = sorted({*new_reports, *(p for p in (resumed, resumed.with_suffix(".txt")) if p.exists())})
        json_reports = [path for path in new_reports if path.suffix == ".json"]
        metrics = summarize_child_report(json_reports[-1]) if json_reports else {}
        if not args.no_audio:
            number = re.match(r"Part (\d+)", name)
            label = f"part {number.group(1)}" if number else name
            announce(f"Finished {label}" if completed.returncode == 0 else f"{label.capitalize()} ended with an error")
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
        "benchmark": "AegisBench full run",
        "target_model": args.model,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "output_directory": str(run_dir),
        "parts": sorted(parts, key=lambda part: (0, int(re.match(r"Part (\d+)", part["name"]).group(1)))
                   if re.match(r"Part (\d+)", part["name"]) else (1, part["name"])),
        "resumed": bool(args.resume_run),
        "complete": all(part["exit_code"] == 0 for part in parts),
    }
    summary_path = run_dir / "combined_summary.json"
    secure_write_json(summary_path, summary)

    summary_lines = ["AEGISBENCH — COMBINED SUMMARY", "=" * 86]
    for part in summary["parts"]:
        status = "complete" if part["exit_code"] == 0 else f"incomplete (exit {part['exit_code']})"
        summary_lines.append(f"{part['name']:<42} {status:<22} {part['seconds']:>9.2f}s")
        metrics = part.get("metrics") or {}
        for area, values in (metrics.get("research_area_summaries") or {}).items():
            if metrics.get("scale_version") == grading_scale.SCALE_VERSION:
                summary_lines.append(f"  area: {area:<31} {grading_scale.summary_text(values)}")
                continue
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
