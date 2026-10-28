# Sample report — pipeline demonstration

> **These numbers are NOT real model results.** They were produced by a **deterministic fake
> model** (`tests/test_memory_experiment.FakeModel`) that always follows a retrieved planted
> record. The purpose is to show the pipeline end-to-end and that the metrics separate the
> conditions as designed — not to make any claim about any real LLM. Real numbers require a
> model running in Ollama (`python -m memory_poisoning.experiment --model <tag>`).

Generated with: 5 trials/condition, seed 42, intervening `[0, 1, 3]`.
Full data: `trigger_metrics.json`, `wef_metrics.json` in this folder.

## Cross-session (trigger protocol)

| Cond | Name | C-ASR | retrieval | influence | ISR | benign | C-ASR@{0,1,3} |
|------|------|------:|----------:|----------:|----:|-------:|---------------|
| A | clean | — (no eligible) | — | — | — | 1.00 | — |
| B | seeded | 1.00 | 1.00 | 1.00 | — | 1.00 | 1.0 / 1.0 / 1.0 |
| C | formation | 1.00 | 1.00 | 1.00 | **1.00** | 1.00 | 1.0 / 1.0 / 1.0 |
| D | prompt safeguard | **1.00** | 1.00 | 1.00 | — | 1.00 | 1.0 / 1.0 / 1.0 |
| E | memory safeguard | **0.00** | 0.00 | — | — | 1.00 | 0.0 / 0.0 / 0.0 |

0 error trials.

## Write–Execute–Forget (wef protocol)

| Cond | write | execute | repair | legit preserved |
|------|------:|--------:|-------:|----------------:|
| B | 1.00 | 1.00 | 1.00 | 1.00 |
| C | 1.00 | 1.00 | 1.00 | 1.00 |
| E | 1.00 | 0.00 | — (no effect to repair) | 1.00 |

## What this illustrates (about the pipeline, not about a real model)

- **A** correctly has **no eligible attack trials** (nothing was planted).
- **C** records **ISR=1.0** only because the fake model wrote a `REMEMBER:` line containing the
  planted code — storage, not a mere claim.
- On the **defense side**, the layered pattern the thesis predicts appears: the **prompt-layer
  safeguard (D) does not stop** this follower (C-ASR stays 1.0) while the **memory-layer
  safeguard (E) does** (retrieval and C-ASR drop to 0.0). With a real model these would be
  empirical questions, not guaranteed outcomes — measure them.
- **WEF** shows selective repair removing the effect (execute 1.0 → repair 1.0) while keeping
  every legitimate record (legit 1.0); under E the effect never fired, so there is nothing to
  repair.
