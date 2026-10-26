# AegisBench GUI

The default target is Cyber-Tiel through Ollama at
`http://127.0.0.1:11434/v1`, model
`hf.co/peculiar-ragdoll/Cyber-Tiel-Coder-35B-A3B-GGUF-MTP:UD-Q4_K_M`, in both
interfaces and all three standalone runners. Start Ollama before launching a benchmark.
Run the full benchmark with `python gauntlet_runner.py --seed 42` or open the
terminal control panel with `python results/gui/cli.py`.
Override the defaults with `--model` and `--base-url`, or the environment
variables `BENCHMARK_MODEL` and `BENCHMARK_BASE_URL` in the Python runners.
Override the model if you want to benchmark another model installed in Ollama.

For the interactive terminal version (no web server needed):

```bash
python results/gui/cli.py
```

The main screen has Run setup, Benchmark output, and Target / judge exchange
panes, plus Machine activity. Use Tab to move between panes, arrow keys to select, and Enter to edit or
toggle a field. Model and wrapper fields open selection menus. Mouse clicks
also select setup controls. Enter toggles each of the three benchmark parts.
Select Start benchmark to launch. Wrapper servers must already be running;
their actual backend models are configured in those servers.

F1 opens Benchmark, F2 opens Results, and F3 opens Models. Results groups saved
reports by run directory and displays all three parts, individual case outcomes,
and judge rationale. Missing reports are labeled. Interrupted runs split across
folders remain separate. Escape returns to the result list.
F4 opens the full-size Machine activity page. It shows the system/challenge
prompts, model responses, sandbox commands and output, validation failures,
test verification, and final challenge status for Parts 2 and 3. Verifier-run
commands are distinguished from model-requested commands. Events appear after
each model response or command completes, with timestamps; this is not token
streaming. Only benchmark-controlled sandbox activity is observed. Flags,
injected markers, and private canaries are redacted before observer logs are
written. Existing runs launched before this update do not have live traces.
The report opens with an overview of all three parts. Press 1/2/3 to jump to
each part's case details, or 0 to return to the overview.

The Judge model field opens a picker populated by Codex's `model/list` catalog
on startup and refresh. If discovery is unavailable, the local Codex model cache
is used and labeled. Configured default and custom model IDs are also supported.
The chosen ID is passed to the existing Codex CLI grader. A catalog entry does
not guarantee account access; inference verifies access when grading runs.
Reference: https://developers.openai.com/codex/app-server

In an output pane, PageUp/PageDown or arrow keys scroll, and End resumes
following the latest output. Part 1 exchanges appear when each response completes:
question, target answer, judge handoff, and score/rationale. The judge does not
participate in Parts 2 or 3, which use local verifiers. Observer logs are saved
in `gui/logs/*.events.jsonl` with private file permissions.

Press `s` to stop and `r` to refresh. In Models, press `l` to load the selected
model into Ollama memory and `u` to unload it. Loading runs in the background and
the status line reports when it finishes or fails.
Press `q` to close a report or quit; quitting an active run asks before stopping.
Only runs launched in that CLI process are controlled by it. The terminal needs
at least 80 columns and 27 rows; 120 columns gives the panes more room.

Optional defaults: `--model NAME --base-url URL --judge MODEL --seed 42`.

## Cyber-Tiel through Ollama

Start Ollama, then open the benchmark control panel:

```bash
ollama serve
python results/gui/cli.py
```

The CLI connects directly to Ollama. Select Wrapper > Off (direct Ollama) in the
control panel if you previously selected a wrapper.

From the repository root:

```bash
python results/gui/server.py --port 8765
```

Open http://127.0.0.1:8765. The GUI reads existing JSON reports under `results/`
and launches the existing `gauntlet_runner.py`. Python and the benchmark's
dependencies must be installed; Ollama and Codex authentication use the same
configuration as terminal runs. Wrapper endpoints must already be running.

Only one GUI-launched run can be active at a time. Stop terminates that run's
process group. It does not unload Ollama models: use the power button next to a
loaded model to release its memory. Runs launched outside this GUI are not
controlled by it. Per-part results are saved by the existing runners; interrupted
parts may not have a saved JSON report. Console logs are retained in `gui/logs/`.

The server binds to loopback only. Do not expose or proxy it publicly. The
interface uses bundled Lucide icons (ISC license) and optional Google Fonts.
