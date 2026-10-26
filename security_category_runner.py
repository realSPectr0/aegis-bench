#!/usr/bin/env python3
"""Run one independent synthetic LLM security category against Ollama."""
import argparse, json, time, urllib.request
from pathlib import Path
from security_categories import CATEGORY_VERSION, cases, classify, summarize, as_json

def ask(url, model, prompt):
    body = json.dumps({"model": model, "messages": [{"role":"user","content":prompt}], "temperature":0}).encode()
    req = urllib.request.Request(url.rstrip('/') + '/chat/completions', body, {'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=300) as response: return json.load(response)['choices'][0]['message'].get('content','')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--category', choices=('rag_security','prompt_injection','prompt_obfuscation','system_prompt_extraction'), required=True)
    p.add_argument('--model', default='qwen3.5:9b'); p.add_argument('--base-url', default='http://127.0.0.1:11434/v1'); p.add_argument('--seed', type=int, default=42); p.add_argument('--only', action='append'); p.add_argument('--output', default='results/security_categories.json')
    a=p.parse_args(); selected=[c for c in cases(a.category) if not a.only or c.case_id in a.only]; results=[]
    for c in selected:
        started=time.monotonic()
        try: out=ask(a.base_url,a.model,c.prompt); row=classify(c,out); status='ok'; error=None
        except Exception as exc: out=''; row={}; status='infrastructure_error'; error=f'{type(exc).__name__}: {exc}'
        results.append({**as_json(c), **row, 'output':out, 'status':status, 'error':error, 'latency_seconds':round(time.monotonic()-started,4), 'model':a.model, 'seed':a.seed, 'category_version':CATEGORY_VERSION})
    report={'schema_version':'security-category-1','category_version':CATEGORY_VERSION,'category':a.category,'model':a.model,'seed':a.seed,'results':results,'summary':summarize(results)}
    path=Path(a.output); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report['summary'],indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
