#!/usr/bin/env python3
"""Local benchmark control panel. Run with: python gui/server.py"""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = ROOT / 'results'
sys.path.insert(0, str(ROOT))
import grading_scale
LOCK = threading.Lock()
ACTIVE = None


def ollama(path, data=None, timeout=10):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/' + path, data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def report_path(relative):
    path = (RESULTS / relative).resolve()
    if not path.is_relative_to(RESULTS) or path.suffix not in ('.json', '.txt') or not path.is_file():
        raise ValueError('Report not found')
    return path


def metrics(data):
    values = []
    if data.get('scale_version') == grading_scale.SCALE_VERSION:
        for name, group in data.get('research_area_summaries', {}).items():
            if group.get('pass_rate') is not None:
                values.append({'name': name, 'value': group['pass_rate'], 'unit': '% pass', 'direction': 'higher'})
        return values
    for name, group in data.get('research_area_summaries', {}).items():
        values.append({'name': name, 'value': group.get('mean'), 'unit': '/10',
                       'direction': 'lower' if group.get('expected_behavior') == 'refuse' else 'higher'})
    if not values:
        for name, group in data.get('behavior_summaries', {}).items():
            values.append({'name': name, 'value': group.get('mean'), 'unit': '/10',
                           'direction': 'lower' if name == 'refuse' else 'higher'})
    for name, group in data.get('category_summaries', {}).items():
        values.append({'name': name, 'value': group.get('solve_rate'), 'unit': '%', 'direction': 'higher'})
        if group.get('mean_agent_safety') is not None:
            values.append({'name': 'injection_safety', 'value': group['mean_agent_safety'], 'unit': '/10', 'direction': 'higher'})
    return values


def reports():
    rows = []
    for path in RESULTS.rglob('*.json'):
        if path.is_relative_to(HERE) or path.name == 'combined_summary.json':
            continue
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('results'), list):
                continue
            part = 'Legacy Bandit' if 'bandit' in path.stem else 'Agent safety' if 'agent_safety' in path.stem else 'Local challenges' if 'category_summaries' in data else 'Safety questions'
            rows.append({'path': str(path.relative_to(RESULTS)), 'model': data.get('target_model', 'Unknown'),
                         'part': part, 'date': data.get('started_at', ''), 'mtime': path.stat().st_mtime,
                         'count': len(data['results']), 'metrics': metrics(data),
                         'seed': data.get('seed'), 'suite_version': data.get('suite_version')})
        except (OSError, ValueError, TypeError):
            continue
    return sorted(rows, key=lambda row: row['mtime'], reverse=True)


def run_rows(relative):
    """All part reports belonging to the same run as the given report."""
    folder = report_path(relative).parent
    if folder == RESULTS.resolve():
        return [row for row in reports() if row['path'] == relative]
    return [row for row in reports() if (RESULTS / row['path']).resolve().parent == folder]


def export_pdf(relative, summary=False):
    """Export both PDFs for the run; returns the summary or the full report."""
    import report_pdf
    rows = run_rows(relative)
    if not rows:
        raise ValueError('Report not found')
    path = report_pdf.export_rows(rows, report_path)
    return report_pdf.summary_path(path) if summary else path


def launch(config):
    global ACTIVE
    model = str(config.get('model', '')).strip()
    endpoint = str(config.get('endpoint', '')).strip()
    parsed = urlparse(endpoint)
    if not model or len(model) > 200 or parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Enter a model and valid HTTP API endpoint')
    parts = config.get('parts', [])
    if not parts or any(part not in ('questions', 'local', 'agent-safety') for part in parts):
        raise ValueError('Select at least one benchmark part')
    actions, seed = int(config.get('actions', 200)), int(config.get('seed', 42))
    if not 1 <= actions <= 200:
        raise ValueError('Action limit must be between 1 and 200')
    # Request maximum reasoning by default. A model with no thinking mode makes
    # Ollama reject the request outright, so ChatClient detects that once and
    # retries without it -- the flag is safe to pass for every model.
    thinking = str(config.get('thinking', 'high')).strip() or 'high'
    command = [sys.executable, '-u', str(HERE / 'run_observed.py'), '--model', model,
               '--base-url', endpoint, '--seed', str(seed), '--local-max-actions', str(actions),
               '--output-dir', str(RESULTS)]
    if thinking != 'off':
        command += ['--thinking', thinking]
    judge = str(config.get('judge', '')).strip()
    judge_provider = str(config.get('judge_provider', '')).strip()
    if not judge_provider and judge.startswith('claude-'):
        judge_provider = 'anthropic'
    if judge_provider == 'anthropic' and not os.environ.get('ANTHROPIC_API_KEY'):
        judge_provider = 'claude-cli'  # no API key: use the logged-in Claude Code CLI instead
    if judge_provider in ('anthropic', 'claude-cli'):
        command += ['--judge-provider', judge_provider]
        if judge:
            command += ['--judge-model', judge]
    elif judge:
        command += ['--codex-judge-model', judge]
    for part in ('questions', 'local', 'agent-safety'):
        if part not in parts:
            command.append('--skip-' + part)
    wrapper = config.get('wrapper') or None
    if wrapper:
        if wrapper not in ('pentestgpt', 'cai', 'vulnbot'):
            raise ValueError('Unknown wrapper')
        # run_observed starts the wrapper in front of the model at `endpoint`.
        command += ['--wrapper', wrapper]
    if config.get('resume'):
        run_dir = (RESULTS / str(config['resume'])).resolve()
        if run_dir.parent != RESULTS.resolve() or not run_dir.is_dir():
            raise ValueError('Resume folder must be a run folder inside results/')
        command += ['--resume-run', str(run_dir)]
    with LOCK:
        if ACTIVE and ACTIVE['process'].poll() is None:
            raise ValueError('A GUI run is already active')
        logdir = HERE / 'logs'
        logdir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        log = logdir / (stamp + '.log')
        events = logdir / (stamp + '.events.jsonl')
        with log.open('w') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True, env={**os.environ, 'PYTHONUNBUFFERED': '1',
                                                                    'CLANKER_EVENTS': str(events)})
        ACTIVE = {'process': process, 'model': model, 'started': time.time(), 'log': log,
                  'events': events, 'stopped': False}
    return {'ok': True}


def stop():
    with LOCK:
        active = ACTIVE
        if not active or active['process'].poll() is not None:
            return {'ok': True}
        active['stopped'] = True
        os.killpg(active['process'].pid, signal.SIGINT)

    def cleanup():
        try:
            active['process'].wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The runner may exit before a child; clean up its entire process group.
        try:
            os.killpg(active['process'].pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    threading.Thread(target=cleanup, daemon=False).start()
    return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, mime='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == '/api/reports':
                return self.send(reports())
            if parsed.path == '/api/report':
                path = report_path(parse_qs(parsed.query).get('path', [''])[0])
                return self.send(path.read_bytes(), mime='application/json' if path.suffix == '.json' else 'text/plain; charset=utf-8')
            if parsed.path == '/api/report.pdf':
                query = parse_qs(parsed.query)
                path = export_pdf(query.get('path', [''])[0], summary=query.get('kind') == ['summary'])
                return self.send(path.read_bytes(), mime='application/pdf')
            if parsed.path == '/api/status':
                active = ACTIVE
                value = None
                if active:
                    code = active['process'].poll()
                    with active['log'].open('rb') as stream:
                        stream.seek(max(0, active['log'].stat().st_size - 65000))
                        log = stream.read().decode('utf-8', errors='replace')
                    if code is not None and 'ended' not in active:
                        active['ended'] = time.time()
                    value = {'model': active['model'], 'seconds': int(active.get('ended', time.time()) - active['started']),
                             'status': 'running' if code is None else 'stopped' if active['stopped'] else 'complete' if code == 0 else 'failed',
                             'log': log, 'exit_code': code}
                return self.send({'run': value})
            if parsed.path == '/api/models':
                try:
                    installed, loaded = ollama('api/tags'), ollama('api/ps')
                    return self.send({'online': True, 'models': installed.get('models', []), 'loaded': loaded.get('models', [])})
                except Exception as exc:
                    return self.send({'online': False, 'models': [], 'loaded': [], 'error': str(exc)})
            if parsed.path == '/api/target-models':
                endpoint = parse_qs(parsed.query).get('endpoint', ['http://127.0.0.1:8080/v1'])[0]
                target = urlparse(endpoint)
                if target.scheme not in ('http', 'https') or not target.hostname:
                    raise ValueError('Invalid API endpoint')
                try:
                    with urllib.request.urlopen(endpoint.rstrip('/') + '/models', timeout=5) as response:
                        models = json.load(response).get('data', [])
                    return self.send({'online': True, 'models': models})
                except Exception as exc:
                    return self.send({'online': False, 'models': [], 'error': str(exc)})
            files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/lucide.js': 'lucide.js'}
            if parsed.path in files:
                mime = 'text/html; charset=utf-8' if parsed.path == '/' else 'text/css' if parsed.path.endswith('.css') else 'application/javascript'
                return self.send((HERE / files[parsed.path]).read_bytes(), mime=mime)
            self.send({'error': 'Not found'}, 404)
        except (ValueError, OSError) as exc:
            self.send({'error': str(exc)}, 400)

    def do_POST(self):
        # Reject cross-site browser requests to this local process controller.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.send({'error': 'Origin rejected'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send({'error': 'JSON required'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/start':
                return self.send(launch(data))
            if self.path == '/api/stop':
                return self.send(stop())
            if self.path == '/api/unload':
                name = data.get('model')
                if name not in [model['name'] for model in ollama('api/ps').get('models', [])]:
                    raise ValueError('Model is not loaded')
                ollama('api/generate', {'model': name, 'keep_alive': 0})
                return self.send({'ok': True})
            self.send({'error': 'Not found'}, 404)
        except (ValueError, OSError, TypeError) as exc:
            self.send({'error': str(exc)}, 400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'AegisBench: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop()
    finally:
        server.server_close()
