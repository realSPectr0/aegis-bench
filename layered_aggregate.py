#!/usr/bin/env python3
"""Aggregate several layered_attack escalation runs (the 3 seeds) into one headline figure.

Each layered_attack run writes <stamp>_escalation.json for one seed (one 24-objective sample).
This reads a set of them, combines per layer, and writes the escalation summary + an HTML curve
with error bars -- the paper's headline figure. Two combined rates per layer, both reported:

  mean-of-seeds : mean of each seed's ASR, with the observed min-max band (the headline; treats
                  each seed as a repeat, consistent with plan_compare).
  pooled        : all trials across seeds pooled into one rate (a footnote; tighter but hides
                  between-seed spread).

It also checks H1 (baseline <= wrapper <= memory <= abliteration) on the mean sequence and flags
consecutive layers whose min-max bands OVERLAP -- those gaps cannot be called real at this n.

  python layered_aggregate.py                      # newest run per seed, all models
  python layered_aggregate.py --model qwen3.5:4b   # only that base model
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parent
LAYERS = ("baseline", "wrapper", "memory", "abliteration")
LAYER_LABEL = {"baseline": "Baseline", "wrapper": "Wrapper (prompt)",
               "memory": "Memory poisoning", "abliteration": "Abliteration"}


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_runs(input_dir: Path, model: str | None) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(input_dir.glob("*_escalation.json")):
        data = _load(path)
        if not data or "per_layer" not in data:
            continue
        if model and (data.get("run") or {}).get("model") not in (None, model):
            continue
        data["_path"] = str(path)
        runs.append(data)
    return runs


def _layer_rate(run: dict[str, Any], layer: str) -> tuple[float, int, int] | None:
    """(rate, numerator, denominator) for a layer's attack_success_rate, or None if absent."""
    summary = (run.get("per_layer") or {}).get(layer)
    if not summary:
        return None
    metric = summary.get("metrics", {}).get("attack_success_rate", {})
    if metric.get("value") is None:
        return None
    return float(metric["value"]), int(metric["numerator"]), int(metric["denominator"])


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    layers: dict[str, Any] = {}
    for layer in LAYERS:
        points = [_layer_rate(run, layer) for run in runs]
        points = [p for p in points if p is not None]
        if not points:
            continue
        rates = [p[0] for p in points]
        num = sum(p[1] for p in points)
        den = sum(p[2] for p in points)
        layers[layer] = {
            "n_seeds": len(rates),
            "mean": mean(rates), "lo": min(rates), "hi": max(rates),
            "pooled": (num / den) if den else None, "pooled_n": den,
            "per_seed": rates,
        }
    present = [l for l in LAYERS if l in layers]
    means = [layers[l]["mean"] for l in present]
    monotonic = all(a <= b + 1e-9 for a, b in zip(means, means[1:]))
    overlaps = {}
    for a, b in zip(present, present[1:]):
        # bands overlap when one's low is below the other's high and vice versa
        overlaps[f"{a}->{b}"] = not (layers[b]["lo"] > layers[a]["hi"] or layers[a]["lo"] > layers[b]["hi"])
    return {"layers": layers, "order": present, "monotonic_mean": monotonic,
            "band_overlaps": overlaps, "n_runs": len(runs),
            "sources": [run["_path"] for run in runs]}


def render_text(agg: dict[str, Any]) -> str:
    lines = ["LAYERED ATTACK-SUCCESS ESCALATION (aggregated)", "=" * 64,
             f"{len(agg['sources'])} run(s). Headline = mean of per-seed ASR with [min-max] band.",
             "", f"{'layer':<18}{'mean ASR':>10}{'[min-max]':>16}{'pooled':>10}{'seeds':>7}"]
    for layer in agg["order"]:
        s = agg["layers"][layer]
        band = f"[{s['lo']*100:.0f}-{s['hi']*100:.0f}]"
        pooled = f"{s['pooled']*100:.0f}% " if s["pooled"] is not None else "-"
        lines.append(f"{LAYER_LABEL[layer]:<18}{s['mean']*100:>9.1f}%{band:>16}{pooled:>10}{s['n_seeds']:>7}")
    lines += ["", f"Monotonic escalation (mean): {agg['monotonic_mean']}"]
    weak = [k for k, v in agg["band_overlaps"].items() if v]
    lines.append("Overlapping bands (gap NOT reliable at this n): " + (", ".join(weak) if weak else "none"))
    return "\n".join(lines) + "\n"


def render_html(agg: dict[str, Any], model: str) -> str:
    width, height = 720, 360
    left, right, top, bottom = 48, 16, 24, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    base = top + plot_h
    order = agg["order"]
    band = plot_w / max(1, len(order))
    bars, ticks = [], []
    for tick in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - tick / 100)
        ticks.append(f'<line class="grid" x1="{left}" x2="{width-right}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="tick" x="{left-8}" y="{y+4:.1f}" text-anchor="end">{tick}</text>')
    for i, layer in enumerate(order):
        s = agg["layers"][layer]
        cx = left + band * (i + 0.5)
        bw = min(70.0, band * 0.5)
        h = plot_h * s["mean"]
        y = base - h
        bars.append(f'<rect class="bar" x="{cx-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4"/>')
        if s["n_seeds"] > 1:
            ylo, yhi = base - plot_h * s["lo"], base - plot_h * s["hi"]
            bars.append(f'<line class="whisker" x1="{cx:.1f}" x2="{cx:.1f}" y1="{ylo:.1f}" y2="{yhi:.1f}"/>'
                        f'<line class="whisker" x1="{cx-5:.1f}" x2="{cx+5:.1f}" y1="{yhi:.1f}" y2="{yhi:.1f}"/>'
                        f'<line class="whisker" x1="{cx-5:.1f}" x2="{cx+5:.1f}" y1="{ylo:.1f}" y2="{ylo:.1f}"/>')
        bars.append(f'<text class="val" x="{cx:.1f}" y="{min(y, base-plot_h*s["hi"])-6:.1f}" text-anchor="middle">'
                    f'{s["mean"]*100:.0f}%</text>')
        bars.append(f'<text class="axis" x="{cx:.1f}" y="{base+18:.1f}" text-anchor="middle">{html.escape(LAYER_LABEL[layer])}</text>')
        bars.append(f'<text class="n" x="{cx:.1f}" y="{base+34:.1f}" text-anchor="middle">n={s["pooled_n"]} ({s["n_seeds"]} seeds)</text>')
    verdict = ("Monotonic escalation holds" if agg["monotonic_mean"] else "Escalation NOT monotonic")
    weak = [k for k, v in agg["band_overlaps"].items() if v]
    caveat = ("All adjacent gaps separate at this n." if not weak
              else "Overlapping bands (gap not reliable): " + ", ".join(weak))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Escalation Curve</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --ink:#0b0b0b; --muted:#7a7974; --rule:#e2e1dc; --series:#2a78d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark;
  --surface:#1a1a19; --ink:#f0efec; --muted:#8f8e86; --rule:#33332f; --series:#3987e5; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --ink:#f0efec; --muted:#8f8e86; --rule:#33332f; --series:#3987e5; }}
body {{ margin:0; background:var(--surface); color:var(--ink); font:14px/1.5 system-ui,sans-serif; }}
main {{ max-width:780px; margin:0 auto; padding:24px 16px; }}
h1 {{ font-size:19px; margin:0 0 2px; }} p {{ color:var(--muted); margin:2px 0; }}
svg {{ width:100%; height:auto; margin-top:12px; }}
.grid {{ stroke:var(--rule); stroke-width:1; }} .tick,.n {{ fill:var(--muted); font-size:11px; }}
.axis {{ fill:var(--ink); font-size:12px; }} .val {{ fill:var(--ink); font-size:12px; font-weight:600; }}
.bar {{ fill:var(--series); }} .whisker {{ stroke:var(--ink); stroke-width:1.5; }}
</style></head><body><main>
<h1>Attack-success escalation by intervention depth — {html.escape(model)}</h1>
<p>Mean attack-success rate per layer over {agg['n_runs']} seed(s), with min–max band. Lower = safer.</p>
<svg viewBox="0 0 {width} {height}" role="img">{''.join(ticks)}{''.join(bars)}
<line class="grid" x1="{left}" x2="{width-right}" y1="{base}" y2="{base}"/></svg>
<p><b>{verdict}.</b> {caveat}</p>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", default="results/layered_attack")
    parser.add_argument("--model", help="Only aggregate runs recorded for this base model")
    parser.add_argument("--out", help="Output basename (default: <input-dir>/escalation_summary)")
    args = parser.parse_args()
    input_dir = (ROOT / args.input_dir) if not Path(args.input_dir).is_absolute() else Path(args.input_dir)
    runs = load_runs(input_dir, args.model)
    if not runs:
        parser.error(f"no *_escalation.json runs found in {input_dir}"
                     + (f" for model {args.model}" if args.model else ""))
    agg = aggregate(runs)
    base = Path(args.out) if args.out else input_dir / "escalation_summary"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
    base.with_suffix(".txt").write_text(render_text(agg), encoding="utf-8")
    base.with_suffix(".html").write_text(render_html(agg, args.model or "base model"), encoding="utf-8")
    print(render_text(agg))
    print(f"Saved: {base.with_suffix('.json')}\n       {base.with_suffix('.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
