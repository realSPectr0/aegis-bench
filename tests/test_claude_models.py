import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
import benchmark_runner
import claude_models


class Response:
    def __init__(self, status, body, text=''):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise benchmark_runner.requests.HTTPError(str(self.status_code))


class ClaudeModelTests(unittest.TestCase):
    def test_discover_pages_through_catalog(self):
        pages = [Response(200, {'data': [{'id': 'claude-a', 'display_name': 'A'}], 'has_more': True, 'last_id': 'claude-a'}),
                 Response(200, {'data': [{'id': 'claude-b'}], 'has_more': False})]
        with patch.object(claude_models.requests, 'get', side_effect=pages) as get:
            rows = claude_models.discover_models(api_key='k')
        self.assertEqual(rows, [{'id': 'claude-a', 'name': 'A'}, {'id': 'claude-b', 'name': 'claude-b'}])
        self.assertEqual(get.call_args.kwargs['params']['after_id'], 'claude-a')

    def test_discover_requires_key(self):
        with patch.dict(claude_models.os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                claude_models.discover_models()

    def test_client_drops_rejected_temperature_and_joins_text_blocks(self):
        sent = []

        def post(url, headers, json, timeout):
            sent.append(dict(json))
            if 'temperature' in json:
                return Response(400, {}, '{"error":{"message":"temperature is not supported"}}')
            return Response(200, {'content': [{'type': 'thinking', 'thinking': 'x'},
                                              {'type': 'text', 'text': '{"score":9}'}]})

        client = benchmark_runner.AnthropicClient(model='claude-opus-5-5', api_key='k')
        with patch.object(benchmark_runner.requests, 'post', side_effect=post):
            text, metadata = client.complete([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(text, '{"score":9}')
        self.assertNotIn('temperature', sent[-1])
        self.assertEqual(metadata['provider'], 'anthropic')


if __name__ == '__main__':
    unittest.main()
