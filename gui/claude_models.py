"""List the Claude models the Anthropic API currently serves to this key."""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from benchmark_runner import ANTHROPIC_MODELS


def fallback_models():
    return [{'id': slug, 'name': name} for slug, name in ANTHROPIC_MODELS]


def discover_models(api_key=None, timeout=8):
    """Return every model from GET /v1/models, newest first. Needs ANTHROPIC_API_KEY."""
    key = api_key or os.getenv('ANTHROPIC_API_KEY')
    if not key:
        raise ValueError('ANTHROPIC_API_KEY is not set')
    headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    rows, after = [], None
    while True:
        params = {'limit': 1000}
        if after:
            params['after_id'] = after
        response = requests.get('https://api.anthropic.com/v1/models', headers=headers,
                                params=params, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        rows.extend(body.get('data', []))
        if not body.get('has_more') or not body.get('last_id'):
            break
        after = body['last_id']
    seen, result = set(), []
    for row in rows:
        slug = row.get('id')
        if slug and slug not in seen:
            seen.add(slug)
            result.append({'id': slug, 'name': row.get('display_name') or slug})
    return result
