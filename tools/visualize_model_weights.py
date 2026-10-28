#!/usr/bin/env python3
"""CPU-oriented tensor distribution plots for NPZ/NPY and optional SafeTensors files.

Measurements are tensor statistics only and are not security scores or causal evidence.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Iterator

def iter_tensors(paths: list[Path]) -> Iterator[tuple[str, object]]:
    import numpy as np
    for path in paths:
        if path.suffix == ".npy":
            yield path.stem, np.load(path, mmap_mode="r", allow_pickle=False)
        elif path.suffix == ".npz":
            with np.load(path, allow_pickle=False) as archive:
                for name in archive.files: yield name, archive[name]
        elif path.suffix == ".safetensors":
            try: from safetensors import safe_open
            except ImportError as exc: raise RuntimeError("SafeTensors input requires the optional safetensors package") from exc
            with safe_open(path, framework="np", device="cpu") as handle:
                for name in handle.keys(): yield name, handle.get_tensor(name)
        else: raise ValueError(f"unsupported weight format: {path} (supported: .npy, .npz, .safetensors)")

def inspect(paths: list[Path], sample_size: int = 100000) -> list[dict]:
    import numpy as np
    rows=[]
    for name,tensor in iter_tensors(paths):
        array=np.asarray(tensor); flat=array.reshape(-1)
        if not np.issubdtype(array.dtype, np.number): continue
        step=max(1, flat.size//sample_size); sample=np.asarray(flat[::step][:sample_size], dtype=np.float64)
        finite=sample[np.isfinite(sample)]
        rows.append({"tensor":name,"shape":list(array.shape),"dtype":str(array.dtype),"elements":int(flat.size),
                     "sampled":int(sample.size),"finite":int(finite.size),"mean":float(finite.mean()) if finite.size else None,
                     "std":float(finite.std()) if finite.size else None,"min":float(finite.min()) if finite.size else None,
                     "max":float(finite.max()) if finite.size else None,"sample":finite})
    return rows

def plot(rows: list[dict], output_dir: Path, formats: list[str]) -> list[Path]:
    try: import matplotlib.pyplot as plt
    except ImportError as exc: raise RuntimeError("Matplotlib is required; install benchmark-requirements.txt") from exc
    output_dir.mkdir(parents=True,exist_ok=True); made=[]
    fig,ax=plt.subplots(figsize=(9,5.5),constrained_layout=True)
    for row in rows[:20]:
        if len(row["sample"]): ax.hist(row["sample"],bins=80,histtype="step",density=True,label=row["tensor"][:45],alpha=.8)
    ax.set_title("Tensor value distributions (sampled actual values)"); ax.set_xlabel("weight value"); ax.set_ylabel("density"); ax.grid(alpha=.2)
    if len(rows)<=10: ax.legend(fontsize=7)
    for fmt in formats:
        path=output_dir/f"weight_distributions.{fmt}"; fig.savefig(path,dpi=220); made.append(path)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(max(9,len(rows)*.3),5.5),constrained_layout=True)
    ax.bar(range(len(rows)),[r["std"] or 0 for r in rows],color="#cba6f7"); ax.set_xticks(range(len(rows)),[r["tensor"] for r in rows],rotation=80,fontsize=7)
    ax.set_ylabel("sample standard deviation"); ax.set_title("Layer/tensor summary"); ax.grid(axis="y",alpha=.2)
    for fmt in formats:
        path=output_dir/f"weight_layer_summary.{fmt}"; fig.savefig(path,dpi=220); made.append(path)
    plt.close(fig); return made

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("inputs",nargs="+",type=Path); p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--sample-size",type=int,default=100000); p.add_argument("--format",action="append",choices=("png","pdf","svg"),dest="formats")
    a=p.parse_args()
    if a.sample_size<1: raise ValueError("--sample-size must be positive")
    rows=inspect(a.inputs,a.sample_size)
    if not rows: raise ValueError("no supported numeric tensors found")
    a.output_dir.mkdir(parents=True,exist_ok=True)
    serial=[{k:v for k,v in row.items() if k!="sample"} for row in rows]
    (a.output_dir/"weight_statistics.json").write_text(json.dumps(serial,indent=2)+"\n",encoding="utf-8")
    print("\n".join(str(p) for p in plot(rows,a.output_dir,a.formats or ["png"]))); return 0
if __name__=="__main__": raise SystemExit(main())
