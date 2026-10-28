"""AegisBench persistent memory-poisoning evaluation layer.

A modular, independently-runnable component that measures whether information introduced in
one interaction can persist in external memory (memory_store.MemoryStore) and influence a
model's behavior in a later, otherwise-independent task -- and how well defenses counter it.

Paper-inspired, not reproductions: the designs adapt MINJA (query-only formation), PMPA
(injection/trigger across sessions, ISR/C-ASR), and MemSecBench (Write-Execute-Forget,
selective repair) to this repo's local-Ollama harness. All tasks use synthetic facts and
fictional labels with simulated consequences; nothing executes harmful actions or touches
model weights.
"""

from .trial_log import TrialLogger, TrialRecord

__all__ = ["TrialLogger", "TrialRecord"]
