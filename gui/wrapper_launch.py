"""Start a security wrapper (PentestGPT or CAI) in front of an Ollama model for one run.

The wrapper talks to Ollama's OpenAI-compatible endpoint, which cannot set the
context window, so the backend is a local alias of the model with num_ctx baked
in. The alias reuses the model's weights; nothing is downloaded.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WRAPPERS = ('pentestgpt', 'cai', 'vulnbot')


def public_name(wrapper, backend_model):
    """Model name the run is recorded under, e.g. pentestgpt-qwen3.5-9b."""
    return f'{wrapper}-' + re.sub(r'[^A-Za-z0-9.]+', '-', backend_model).strip('-')


def ollama_root(base_url):
    base = base_url.rstrip('/')
    return base[:-3] if base.endswith('/v1') else base


def context_alias(base_url, model, num_ctx):
    """Create (or refresh) `<model>-ctx<N>k` with num_ctx set and return its name."""
    if not num_ctx:
        return model
    alias = re.sub(r'[^A-Za-z0-9._-]+', '-', model) + f'-ctx{num_ctx // 1024}k'
    body = json.dumps({'model': alias, 'from': model, 'parameters': {'num_ctx': num_ctx},
                       'stream': False}).encode()
    request = urllib.request.Request(ollama_root(base_url) + '/api/create', data=body,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=300) as response:
        response.read()
    return alias


def pentestgpt_path():
    configured = os.getenv('PENTESTGPT_PATH')
    if configured:
        return Path(configured)
    for candidate in (Path.home() / 'Documents' / 'PentestGPT', Path('/tmp/PentestGPT')):
        if candidate.exists():
            return candidate
    return Path('/tmp/PentestGPT')


def vulnbot_path():
    configured = os.getenv('VULNBOT_PATH')
    if configured:
        return Path(configured)
    candidate = Path.home() / 'Documents' / 'VulnBot'
    return candidate if candidate.exists() else None


def wrapper_command(wrapper, backend_model, base_url, port, name):
    # The adapter runs in Clanker's own env (requests only) unless a wrapper ships
    # its dependencies in its own virtualenv, as PentestGPT does.
    python = sys.executable
    extra = []
    if wrapper == 'pentestgpt':
        path = pentestgpt_path()
        if not path.exists():
            raise RuntimeError(f'PentestGPT not found at {path}; set PENTESTGPT_PATH')
        venv_python = path / '.venv' / 'bin' / 'python'
        python = str(venv_python) if venv_python.exists() else python
        extra = ['--pentestgpt-path', str(path)]
    elif wrapper == 'vulnbot':
        path = vulnbot_path()
        if path:
            extra = ['--vulnbot-path', str(path)]
    elif os.getenv('CAI_PATH'):
        extra = ['--cai-path', os.environ['CAI_PATH']]
    return [python, '-u', str(ROOT / 'wrapper_server.py'), '--wrapper', wrapper,
            '--backend-model', backend_model, '--backend-base-url', base_url,
            '--port', str(port), '--model-name', name, *extra]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def start(wrapper, backend_model, base_url, num_ctx, log_path, health_timeout=120):
    """Launch the wrapper; returns (process, endpoint, public model name)."""
    if wrapper not in WRAPPERS:
        raise ValueError(f'Unknown wrapper {wrapper!r}')
    backend = context_alias(base_url, backend_model, num_ctx)
    name = public_name(wrapper, backend_model)
    port = free_port()
    log = open(log_path, 'w')
    process = subprocess.Popen(wrapper_command(wrapper, backend, base_url, port, name), cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + health_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'{wrapper} wrapper exited at startup:\n' + Path(log_path).read_text()[-2000:])
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2):
                return process, f'http://127.0.0.1:{port}/v1', name
        except OSError:
            time.sleep(0.5)
    process.terminate()
    raise RuntimeError(f'{wrapper} wrapper did not become ready in {health_timeout}s')
