#!/usr/bin/env python3
"""Run a controlled synthetic LLM-security category against an OpenAI-compatible endpoint."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import time
from typing import Any, Callable
import urllib.error
import urllib.request
from security_categories import CATEGORY_VERSION, as_json, build_messages, cases, classify, summarize

CATEGORIES = ("rag_security", "prompt_injection", "prompt_obfuscation", "system_prompt_extraction")

def ask(url: str, model: str, messages: list[dict[str, str]], timeout: float = 300) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/chat/completions", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("model endpoint returned a malformed chat-completions response") from exc
    if not isinstance(content, str):
        raise ValueError("model endpoint returned non-text message content")
    return content

def _error_kind(exc: Exception) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)): return "timeout"
    if isinstance(exc, urllib.error.HTTPError): return "http_error"
    if isinstance(exc, urllib.error.URLError): return "connection_error"
    if isinstance(exc, (ValueError, json.JSONDecodeError)): return "malformed_response"
    return "infrastructure_error"

def run_category(category: str, model: str, seed: int, ask_fn: Callable[[list[dict[str, str]]], str], only: list[str] | None = None) -> list[dict[str, Any]]:
    selected = [case for case in cases(category) if not only or case.case_id in only]
    rows = []
    for case in selected:
        messages, provenance = build_messages(case)
        started_at, started = datetime.now(timezone.utc).isoformat(), time.monotonic()
        try:
            output = ask_fn(messages)
            outcome, status, error, error_type = classify(case, output), "ok", None, None
        except Exception as exc:
            output, outcome = "", {}
            status, error, error_type = "infrastructure_error", f"{type(exc).__name__}: {exc}", _error_kind(exc)
        rows.append({**as_json(case), **outcome, "output": output, "status": status,
                     "error": error, "error_type": error_type, "latency_seconds": round(time.monotonic() - started, 4),
                     "request_messages": messages, "retrieved_documents": provenance, "model": model, "seed": seed,
                     "category_version": CATEGORY_VERSION, "started_at": started_at,
                     "finished_at": datetime.now(timezone.utc).isoformat()})
    return rows

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=CATEGORIES, required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--only", action="append")
    parser.add_argument("--output", default="results/security_categories.json")
    return parser

def main() -> int:
    args = build_parser().parse_args()
    if args.timeout <= 0: raise ValueError("--timeout must be positive")
    begun = datetime.now(timezone.utc).isoformat()
    rows = run_category(args.category, args.model, args.seed, lambda messages: ask(args.base_url, args.model, messages, args.timeout), args.only)
    report = {"schema_version": "security-category-2", "category_version": CATEGORY_VERSION,
              "benchmark": "AegisBench controlled synthetic LLM security evaluation",
              "category": args.category, "model": args.model, "seed": args.seed,
              "configuration": {"base_url": args.base_url, "timeout_seconds": args.timeout, "temperature_requested": 0,
                                "determinism_note": "temperature zero does not guarantee deterministic model behavior"},
              "started_at": begun, "finished_at": datetime.now(timezone.utc).isoformat(),
              "results": rows, "summary": summarize(rows)}
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
