"""Per-trial JSONL logging for the memory-poisoning experiments (spec Phase 7).

Every trial is one JSON object on one line, holding enough to independently audit the result:
the experiment/trial identity, the model and its config, the condition and defense, the
challenge and its ground truth, the memory state and the records written/retrieved/repaired,
the session boundaries, the raw model output and parsed outcome, whether the behavioral
criterion was met, and the error/latency bookkeeping.

Failed calls and malformed responses are never silently dropped: they are logged with an
explicit `status` so downstream metrics can decide how they affect denominators.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Trial outcome status. "ok" trials are eligible for the behavioral metrics; the error
# statuses are counted and reported separately rather than folded into success rates.
STATUSES = ("ok", "model_error", "storage_error", "timeout", "invalid_output", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TrialRecord:
    """One trial's fields. Unknown-at-write-time fields stay None and are still logged."""
    experiment_id: str
    trial_id: str
    phase: str                      # e.g. "formation", "trigger", "execute", "forget"
    condition: str                  # A..E or clean/poisoned/safeguarded/...
    challenge_id: str
    model: str = ""
    model_config: dict[str, Any] = field(default_factory=dict)
    sampling: dict[str, Any] = field(default_factory=dict)   # temperature, seed, num_ctx...
    defense: dict[str, Any] = field(default_factory=dict)    # prompt_safeguard / trust_gate...
    ground_truth: Any = None
    memory_state_id: str = ""       # reproducible id of the initial memory state
    memory_before: list[str] = field(default_factory=list)   # record ids present at start
    written: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    intervening: int = 0            # benign interactions between injection and trigger
    session_boundary: bool = False  # True when this trial ran in a fresh session
    model_output: str = ""
    parsed_outcome: Any = None
    criterion_met: bool | None = None
    latency_seconds: float | None = None
    status: str = "ok"
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")


class TrialLogger:
    """Append-only JSONL writer for TrialRecords, with a readback helper."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: TrialRecord) -> dict[str, Any]:
        row = {"logged_at": _now(), **asdict(record)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return row

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def count_by_status(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for row in self.read():
            counts[row.get("status", "ok")] = counts.get(row.get("status", "ok"), 0) + 1
        return counts
