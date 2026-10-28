#!/usr/bin/env python3
"""Side-by-side comparison of one model's planned runs: bare metal, the three
memory-poisoning conditions, and the abliterated model.

Each run is found under results/ by its run_config.json, so re-running this after a run
finishes fills its column in. Runs not found yet show as "pending"; metrics a run did not
measure show as "n/a" (never as 0). Writes comparison.md and comparison.html to
results/plan_comparison/<model>/. Plans are remembered in results/plan_comparison/plans.json,
and gauntlet_runner re-renders every saved plan when a run finishes.

  python plan_compare.py --model qwen3.5:4b \\
      --abliterated hf.co/mradermacher/Qwen3.5-4B-abliterated-GGUF:Q4_K_M
  python plan_compare.py            # re-render every saved plan
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
import sys
sys.path.insert(0, str(ROOT))
import local_challenge_runner  # noqa: E402

CURRENT_SUITE = local_challenge_runner.LOCAL_SUITE_VERSION
OUT = RESULTS / "plan_comparison"
PLANS = OUT / "plans.json"

SLOTS = (
    ("bare", "Bare metal"),
    ("wrapper", "AegisAgent"),
    ("mp_clean", "MP clean"),
    ("mp_poisoned", "MP poisoned"),
    ("mp_safeguarded", "MP safeguarded"),
    ("abliterated", "Abliterated"),
)
WRAPPER = "aegisagent"   # the prompt-layer framework slot
PENDING, NA = "pending", "n/a"

# (key, label, better-when, group). Every value is a (numerator, denominator) count.
ROWS = (
    ("local", "Local challenges solved", "higher", "Capability"),
    ("mp_task", "Memory-poisoning tasks completed", "higher", "Capability"),
    ("p1_pass", "Safety questions passed", "higher", "Safety"),
    ("harmful", "Harmful requests refused", "higher", "Safety"),
    ("benign", "Benign requests fully helped", "higher", "Safety"),
    ("unsafe", "Unsafe answers", "lower", "Safety"),
    ("probe_asr", "Security-probe attack success", "lower", "Attack"),
    ("inject", "Injected instructions followed", "lower", "Attack"),
    ("mp_attack", "Memory-poisoning attack success", "lower", "Attack"),
)
PANELS = ("local", "harmful", "probe_asr", "mp_attack")

# Local challenges dropped from every run's capability score: no configuration solved them
# across the post-2026-10-16 runs (floor effect, zero discriminating information). Each was
# checked to be solvable with a reference fix, so these are hard items, not broken ones.
EXCLUDED = ("SCODE-001", "WEB-002", "WEB-004")
EXCLUSION_NOTE = (f"Excluded from local capability in every run: {', '.join(EXCLUDED)}. No configuration "
                  "has solved them since 2026-10-16 (floor effect), so they cannot separate runs; each was "
                  "verified solvable with a reference fix.")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _reports(run_dir: Path) -> list[Path]:
    return [path for path in sorted(run_dir.glob("*.json"))
            if path.name not in ("run_config.json", "combined_summary.json")]


def slot_for(config: dict[str, Any], model: str, abliterated: str | None) -> str | None:
    """Which plan slot a run fills, or None when it belongs to no slot (e.g. a wrapper run)."""
    if not config:
        return None
    wrapper = config.get("wrapper")
    tag = config.get("model")
    memory = bool(config.get("run_memory_poisoning"))
    condition = config.get("condition") or "clean"
    if wrapper:
        # run_config records the wrapper and the backend model it ran in front of.
        name = wrapper.get("wrapper") if isinstance(wrapper, dict) else wrapper
        backend = wrapper.get("backend_model") if isinstance(wrapper, dict) else tag
        return "wrapper" if name == WRAPPER and backend == model and not memory else None
    if abliterated and tag == abliterated:
        return None if memory else "abliterated"
    if tag != model:
        return None
    if memory:
        return f"mp_{condition}"
    return "bare" if condition == "clean" else None


def _current_suite(run_dir: Path) -> bool:
    """A run counts only if its local report is the current suite version, so repeats never
    mix benchmark versions. Runs with no local report (rare) are accepted as current."""
    local = next(iter(run_dir.glob("*_local.json")), None)
    if local is None:
        return True
    data = _load(local) or {}
    return data.get("suite_version") == CURRENT_SUITE


def find_runs(model: str, abliterated: str | None) -> dict[str, list[Path]]:
    """All current-suite run directories for each slot, newest first (for repeat aggregation)."""
    found: dict[str, list[Path]] = {}
    for run_dir in sorted(RESULTS.glob("*_full"), reverse=True):
        slot = slot_for(_load(run_dir / "run_config.json") or {}, model, abliterated)
        if slot and _reports(run_dir) and _current_suite(run_dir):
            found.setdefault(slot, []).append(run_dir)
    return found


def aggregate(run_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    """Per-metric stats across repeats: mean / min / max of the percentage, and run count.

    A metric is included for the runs that measured it; `last` keeps the newest run's raw
    counts so a single-run column can still show the n/N it came from.
    """
    per_run = [metrics(run_dir) for run_dir in run_dirs]
    stats: dict[str, dict[str, Any]] = {}
    keys = {key for run in per_run for key in run}
    for key in keys:
        values = [pct(run[key]) for run in per_run if key in run]
        counts = [run[key] for run in per_run if key in run]
        stats[key] = {"n": len(values), "mean": sum(values) / len(values),
                      "lo": min(values), "hi": max(values), "last": counts[0]}
    return stats


def metrics(run_dir: Path) -> dict[str, tuple[int, int]]:
    """Every comparison metric the run's report files contain, as (numerator, denominator)."""
    out: dict[str, tuple[int, int]] = {}
    attacks = succeeded = 0
    parts: dict[str, list[dict[str, Any]]] = {}
    for path in _reports(run_dir):
        data = _load(path)
        if not isinstance(data, dict):
            continue
        if "tests_requested" in data:
            overall = data.get("overall") or {}
            if overall.get("count"):
                out["p1_pass"] = (overall.get("pass", 0), overall["count"])
                out["unsafe"] = ((overall.get("tags") or {}).get("unsafe", 0), overall["count"])
            areas = data.get("research_area_summaries") or {}
            for key, area in (("harmful", "harmful_refusal"), ("benign", "benign_helpfulness")):
                group = areas.get(area) or {}
                if group.get("count"):
                    out[key] = (group.get("pass", 0), group["count"])
        elif str(data.get("schema_version", "")).startswith("security-category"):
            for case in data.get("results") or []:
                if case.get("benign") or case.get("error"):
                    continue
                attacks += 1
                succeeded += bool(case.get("attack_success"))
        elif data.get("benchmark_part") == "local_and_agent_safety":
            results = data.get("results") or []
            categories = {case.get("category") for case in results}
            part = ("memory_poisoning" if categories == {"memory_poisoning"}
                    else "agent_safety" if categories == {"agent_safety"} else "local")
            parts[part] = results  # sorted file names: a resumed part's newest report wins
    if attacks:
        out["probe_asr"] = (succeeded, attacks)
    if parts.get("local"):
        cases = [case for case in parts["local"] if case.get("id") not in EXCLUDED]
        out["local"] = (sum(case.get("status") == "solved" for case in cases), len(cases))
    if parts.get("agent_safety"):
        cases = parts["agent_safety"]
        out["inject"] = (sum(bool(case.get("injection_followed")) for case in cases), len(cases))
    if parts.get("memory_poisoning"):
        cases = parts["memory_poisoning"]
        out["mp_attack"] = (sum(bool(case.get("injection_followed") or case.get("forbidden_access"))
                                for case in cases), len(cases))
        out["mp_task"] = (sum(case.get("status") == "solved" for case in cases), len(cases))
    return out


def pct(ratio: tuple[int, int]) -> float:
    return 100 * ratio[0] / ratio[1] if ratio[1] else 0.0


def collect(model: str, abliterated: str | None) -> list[dict[str, Any]]:
    runs = find_runs(model, abliterated)
    return [{"slot": slot, "label": label, "runs": runs.get(slot, []),
             "agg": aggregate(runs[slot]) if slot in runs else {}} for slot, label in SLOTS]


def cell(column: dict[str, Any], key: str) -> str:
    if not column["runs"]:
        return PENDING
    stat = column["agg"].get(key)
    if stat is None:
        return NA
    if stat["n"] == 1:
        num, den = stat["last"]
        return f"{stat['mean']:.0f}% ({num}/{den})"
    return f"{stat['mean']:.0f}% [{stat['lo']:.0f}–{stat['hi']:.0f}] n={stat['n']}"


def render_markdown(model: str, columns: list[dict[str, Any]]) -> str:
    lines = [f"# Run plan comparison: {model}", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. *pending* = run not found yet; "
             "*n/a* = the run did not measure it.", "", EXCLUSION_NOTE, "",
             "| Metric | Better | " + " | ".join(column["label"] for column in columns) + " |",
             "|---|---|" + "---|" * len(columns)]
    for key, label, better, _group in ROWS:
        lines.append(f"| {label} | {better} | " + " | ".join(cell(column, key) for column in columns) + " |")
    lines += ["", f"Only current suite v{CURRENT_SUITE} runs are counted; cells show mean [min–max] n across repeats.", "", "Runs:"]
    for column in columns:
        names = ", ".join(run.name for run in column["runs"]) or PENDING
        lines.append(f"- {column['label']} ({len(column['runs'])}): {names}")
    return "\n".join(lines) + "\n"


def _bar_path(x: float, w: float, base: float, h: float) -> str:
    """Bar with 4px rounded data end, square at the baseline."""
    r = min(4.0, h, w / 2)
    top = base - h
    return (f"M{x:.1f},{base:.1f} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f} V{base:.1f} Z")


def panel_svg(key: str, columns: list[dict[str, Any]]) -> str:
    width, height = 360, 230
    left, right, top, bottom = 34, 8, 18, 58
    plot_w, plot_h = width - left - right, height - top - bottom
    base = top + plot_h
    band = plot_w / len(columns)
    bar_w = min(32.0, band * 0.5)
    out = []
    for tick in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - tick / 100)
        out.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{left - 6}" y="{y + 3.5:.1f}" text-anchor="end">{tick}</text>')
    for index, column in enumerate(columns):
        cx = left + band * (index + 0.5)
        x = cx - bar_w / 2
        stat = column["agg"].get(key) if column["runs"] else None
        state = PENDING if not column["runs"] else NA
        name = html.escape(column["label"])
        if stat is None:
            out.append(f'<rect class="empty" x="{x:.1f}" y="{base - 26:.1f}" width="{bar_w:.1f}" height="26" rx="4"/>')
            out.append(f'<text class="state" x="{cx:.1f}" y="{base - 32:.1f}" text-anchor="middle">{state}</text>')
            tip = f"{name}: {state}"
        else:
            value = stat["mean"]
            h = plot_h * value / 100
            if h > 0:
                out.append(f'<path class="bar" d="{_bar_path(x, bar_w, base, h)}"/>')
            if stat["n"] > 1:
                # min-max whisker across repeats
                ylo, yhi = base - plot_h * stat["lo"] / 100, base - plot_h * stat["hi"] / 100
                out.append(f'<line class="whisker" x1="{cx:.1f}" x2="{cx:.1f}" y1="{ylo:.1f}" y2="{yhi:.1f}"/>')
                out.append(f'<line class="whisker" x1="{cx-4:.1f}" x2="{cx+4:.1f}" y1="{yhi:.1f}" y2="{yhi:.1f}"/>')
                out.append(f'<line class="whisker" x1="{cx-4:.1f}" x2="{cx+4:.1f}" y1="{ylo:.1f}" y2="{ylo:.1f}"/>')
            top_y = min(base - h, base - plot_h * stat["hi"] / 100)
            out.append(f'<text class="value" x="{cx:.1f}" y="{top_y - 6:.1f}" text-anchor="middle">'
                       f'{value:.0f}%</text>')
            tip = (f"{name}: mean {value:.0f}%" + (f" [{stat['lo']:.0f}–{stat['hi']:.0f}] over {stat['n']} runs"
                   if stat["n"] > 1 else f" ({stat['last'][0]}/{stat['last'][1]})"))
        words = column["label"].split(" ", 1)
        out.append(f'<text class="axis" x="{cx:.1f}" y="{base + 16:.1f}" text-anchor="middle">'
                   + "".join(f'<tspan x="{cx:.1f}" dy="{0 if i == 0 else 12}">{html.escape(word)}</tspan>'
                             for i, word in enumerate(words)) + "</text>")
        if stat is not None:
            out.append(f'<text class="n" x="{cx:.1f}" y="{base + 46:.1f}" text-anchor="middle">'
                       f'{stat["n"]} run{"s" if stat["n"] != 1 else ""}</text>')
        out.append(f'<rect class="hit" x="{cx - band / 2:.1f}" y="{top}" width="{band:.1f}" '
                   f'height="{plot_h + bottom:.1f}" data-tip="{tip}"/>')
    out.append(f'<line class="baseline" x1="{left}" x2="{width - right}" y1="{base:.1f}" y2="{base:.1f}"/>')
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(key)}">'
            + "".join(out) + "</svg>")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Run Plan Comparison</title>
<style>
:root {{ color-scheme: light; --surface-1:#fcfcfb; --surface-2:#f3f2ef; --text-primary:#0b0b0b;
  --text-secondary:#52514e; --text-muted:#7a7974; --rule:#e2e1dc; --series-1:#2a78d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark;
  --surface-1:#1a1a19; --surface-2:#232321; --text-primary:#f0efec; --text-secondary:#c3c2b7;
  --text-muted:#8f8e86; --rule:#33332f; --series-1:#3987e5; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface-1:#1a1a19; --surface-2:#232321;
  --text-primary:#f0efec; --text-secondary:#c3c2b7; --text-muted:#8f8e86; --rule:#33332f; --series-1:#3987e5; }}
body {{ margin:0; background:var(--surface-1); color:var(--text-primary);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 40px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:15px; margin:0 0 2px; }}
.sub, .note {{ color:var(--text-secondary); margin:0 0 18px; }}
.grid4 {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }}
@media (max-width:760px) {{ .grid4 {{ grid-template-columns:minmax(0,1fr); }} }}
.card {{ background:var(--surface-2); border-radius:10px; padding:14px 14px 6px; }}
.card p {{ color:var(--text-muted); font-size:12px; line-height:1.4; min-height:2.8em; margin:0 0 6px; }}
svg {{ width:100%; height:auto; display:block; }}
.grid {{ stroke:var(--rule); stroke-width:1; }} .baseline {{ stroke:var(--text-muted); stroke-width:1; }} .whisker {{ stroke:var(--text-secondary); stroke-width:1.5; }}
.tick, .n {{ fill:var(--text-muted); font-size:10px; }} .axis {{ fill:var(--text-secondary); font-size:11px; }}
.value {{ fill:var(--text-primary); font-size:11px; font-weight:600; }}
.state {{ fill:var(--text-muted); font-size:10px; font-style:italic; }}
.bar {{ fill:var(--series-1); }}
.empty {{ fill:none; stroke:var(--text-muted); stroke-dasharray:3 3; stroke-width:1; }}
.hit {{ fill:transparent; cursor:default; }}
.wrap {{ overflow-x:auto; margin-top:28px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--rule); white-space:nowrap; }}
th {{ color:var(--text-secondary); font-weight:600; }} td.state {{ color:var(--text-muted); font-style:italic; }}
#tip {{ position:fixed; pointer-events:none; background:var(--text-primary); color:var(--surface-1);
  padding:4px 8px; border-radius:6px; font-size:12px; display:none; z-index:2; }}
</style></head><body><main>
<h1>Run plan comparison: {model}</h1>
<p class="sub">Generated {generated}. Dashed slots are <i>pending</i> (run not found yet) or <i>n/a</i>
(the run did not measure it). The n under each bar is the sample size; with n this small a one-case
difference moves the bar a lot.</p>
<p class="sub">{exclusion}</p>
<div class="grid4">{panels}</div>
<div class="wrap"><table><thead><tr><th>Metric</th><th>Better</th>{heads}</tr></thead><tbody>{rows}</tbody></table></div>
<p class="note">Runs: {runs}</p>
</main><div id="tip"></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el => {{
  el.addEventListener('mousemove', e => {{ tip.textContent = el.dataset.tip; tip.style.display = 'block';
    tip.style.left = (e.clientX + 12) + 'px'; tip.style.top = (e.clientY + 12) + 'px'; }});
  el.addEventListener('mouseleave', () => {{ tip.style.display = 'none'; }});
}});
</script></body></html>
"""

PANEL_NOTES = {
    "local": "Capability: share of local challenges solved. Higher is better.",
    "harmful": "Safety: harmful requests refused (Part 1). Higher is better.",
    "probe_asr": "Attack: security-probe attack success, all four categories pooled. Lower is better.",
    "mp_attack": "Attack: retrieved poisoned memory changed the agent's behavior. Lower is better.",
}


def render_html(model: str, columns: list[dict[str, Any]]) -> str:
    labels = {key: label for key, label, _better, _group in ROWS}
    panels = "".join(f'<section class="card"><h2>{html.escape(labels[key])}</h2>'
                     f"<p>{html.escape(PANEL_NOTES[key])}</p>{panel_svg(key, columns)}</section>"
                     for key in PANELS)
    heads = "".join(f"<th>{html.escape(column['label'])}</th>" for column in columns)
    rows = []
    for key, label, better, _group in ROWS:
        cells = []
        for column in columns:
            value = cell(column, key)
            cells.append(f'<td class="state">{value}</td>' if value in (PENDING, NA)
                         else f"<td>{html.escape(value)}</td>")
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{better}</td>{''.join(cells)}</tr>")
    runs = "; ".join(f"{html.escape(column['label'])} ({len(column['runs'])}): "
                     + (", ".join(html.escape(r.name) for r in column["runs"]) or PENDING) for column in columns)
    return PAGE.format(model=html.escape(model), generated=f"{datetime.now():%Y-%m-%d %H:%M}",
                       panels=panels, heads=heads, rows="".join(rows), runs=runs,
                       exclusion=html.escape(EXCLUSION_NOTE))


def load_plans() -> list[dict[str, Any]]:
    plans = _load(PLANS)
    return plans if isinstance(plans, list) else []


def save_plan(model: str, abliterated: str | None) -> None:
    plans = [plan for plan in load_plans() if plan.get("model") != model]
    plans.append({"model": model, "abliterated": abliterated})
    OUT.mkdir(parents=True, exist_ok=True)
    PLANS.write_text(json.dumps(plans, indent=2) + "\n", encoding="utf-8")


def render(model: str, abliterated: str | None) -> Path:
    """Write comparison.md and comparison.html for one plan; returns the HTML path."""
    columns = collect(model, abliterated)
    folder = OUT / re.sub(r"[^A-Za-z0-9._-]+", "_", model)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "comparison.md").write_text(render_markdown(model, columns), encoding="utf-8")
    page = folder / "comparison.html"
    page.write_text(render_html(model, columns), encoding="utf-8")
    return page


def refresh_all() -> list[Path]:
    """Re-render every saved plan (called by gauntlet_runner when a run finishes)."""
    return [render(plan["model"], plan.get("abliterated")) for plan in load_plans() if plan.get("model")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="Base model tag; saves/updates this plan")
    parser.add_argument("--abliterated", help="Abliterated model tag for the abliteration slot")
    args = parser.parse_args()
    if args.model:
        save_plan(args.model, args.abliterated)
    pages = refresh_all()
    if not pages:
        parser.error("no saved plans yet; pass --model (and --abliterated) once")
    for page in pages:
        print(f"{page.with_name('comparison.md')}\n{page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
