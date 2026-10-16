"""Read Codex's model catalog without starting an inference turn."""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path


def normalize(rows):
    result = []
    seen = set()
    for row in rows:
        slug = row.get('model') or row.get('slug') or row.get('id')
        if not slug or row.get('hidden') or row.get('visibility') == 'hide' or slug in seen:
            continue
        seen.add(slug)
        result.append({'id': slug, 'name': row.get('displayName') or row.get('display_name') or slug})
    return result


def cached_models():
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    try:
        return normalize(json.loads((home / 'models_cache.json').read_text()).get('models', []))
    except (OSError, ValueError, TypeError):
        return []


def discover_models(timeout=8):
    process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                continue
        messages.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()

    def request(identifier, method, params):
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex model discovery timed out')
            try:
                message = messages.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError('Codex model discovery timed out') from None
            if message is None:
                raise RuntimeError('Codex model discovery closed')
            if message.get('id') == identifier:
                if 'error' in message:
                    raise RuntimeError(message['error'].get('message', 'Codex catalog error'))
                return message['result']

    try:
        request(1, 'initialize', {'clientInfo': {'name': 'clanker_benchmark', 'title': 'Clanker Gauntlet', 'version': '1.0'}})
        send({'method': 'initialized', 'params': {}})
        rows, cursor, identifier = [], None, 2
        while True:
            result = request(identifier, 'model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
            rows.extend(result.get('data', []))
            cursor = result.get('nextCursor')
            if not cursor:
                break
            identifier += 1
        return normalize(rows)
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader.join(timeout=1)
        process.stdin.close()
        process.stdout.close()
