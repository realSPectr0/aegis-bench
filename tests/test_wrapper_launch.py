import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_observed
import server
import wrapper_launch
import wrapper_server


class WrapperLaunchTests(unittest.TestCase):
    def tearDown(self):
        server.ACTIVE = None

    def test_public_name_and_context_alias(self):
        self.assertEqual(wrapper_launch.public_name('pentestgpt', 'qwen3.5:9b'), 'pentestgpt-qwen3.5-9b')
        response = MagicMock()
        response.__enter__.return_value = response
        with patch.object(wrapper_launch.urllib.request, 'urlopen', return_value=response) as urlopen:
            alias = wrapper_launch.context_alias('http://127.0.0.1:11434/v1', 'qwen3.5:9b', 16384)
        self.assertEqual(alias, 'qwen3.5-9b-ctx16k')
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/create')
        self.assertEqual(json.loads(request.data), {'model': 'qwen3.5-9b-ctx16k', 'from': 'qwen3.5:9b',
                                                    'parameters': {'num_ctx': 16384}, 'stream': False})
        self.assertEqual(wrapper_launch.context_alias('http://x/v1', 'm', 0), 'm')

    def test_run_points_at_started_wrapper_and_records_backend(self):
        argv = ['run_observed.py', '--model', 'qwen3.5:9b', '--base-url', 'http://127.0.0.1:11434/v1',
                '--wrapper', 'pentestgpt', '--seed', '42']
        started = (MagicMock(), 'http://127.0.0.1:5555/v1', 'pentestgpt-qwen3.5-9b')
        with patch.object(run_observed.wrapper_launch, 'start', return_value=started) as start, \
                patch.dict(run_observed.os.environ, {}, clear=False):
            run_observed.start_wrapper(argv)
            recorded = json.loads(run_observed.os.environ['CLANKER_WRAPPER'])
        self.assertEqual(start.call_args[0][:3], ('pentestgpt', 'qwen3.5:9b', 'http://127.0.0.1:11434/v1'))
        self.assertNotIn('--wrapper', argv)
        self.assertEqual(argv[argv.index('--model') + 1], 'pentestgpt-qwen3.5-9b')
        self.assertEqual(argv[argv.index('--base-url') + 1], 'http://127.0.0.1:5555/v1')
        self.assertEqual(recorded['backend_model'], 'qwen3.5:9b')

    def test_server_forwards_wrapper_choice(self):
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'HERE', Path(folder)), \
                patch.object(server.subprocess, 'Popen', return_value=process) as popen:
            server.launch({'model': 'qwen3.5:9b', 'endpoint': 'http://127.0.0.1:11434/v1',
                           'parts': ['local'], 'wrapper': 'vulnbot'})
        command = popen.call_args[0][0]
        self.assertEqual(command[command.index('--wrapper') + 1], 'vulnbot')
        self.assertEqual(command[command.index('--model') + 1], 'qwen3.5:9b')
        server.ACTIVE = None
        with self.assertRaises(ValueError):
            server.launch({'model': 'm', 'endpoint': 'http://127.0.0.1:11434/v1', 'parts': ['local'],
                           'wrapper': 'other'})

    def test_vulnbot_wrapper_applies_persona_and_calls_backend(self):
        wrapper = wrapper_server.VulnBotWrapper(backend_model='qwen3.5-9b-ctx16k',
                                                backend_base_url='http://127.0.0.1:11434/v1')
        self.assertEqual(wrapper.url, 'http://127.0.0.1:11434/v1/chat/completions')
        captured = {}

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {'choices': [{'message': {'content': '<execute> nmap -sV 10.0.0.1 </execute>'}}]}

        def fake_post(url, json, timeout, headers):
            captured['url'] = url
            captured['payload'] = json
            return Resp()

        with patch.object(wrapper_server, 'requests') as requests_mod:
            requests_mod.post = fake_post
            out = wrapper.complete([{'role': 'user', 'content': 'Scan the host'}])
        self.assertIn('nmap', out)
        self.assertEqual(captured['payload']['model'], 'qwen3.5-9b-ctx16k')
        system = captured['payload']['messages'][0]
        self.assertEqual(system['role'], 'system')
        self.assertIn('penetration testing assistant', system['content'])
        self.assertIn('<execute>', system['content'])
        self.assertIn('Scan the host', captured['payload']['messages'][1]['content'])

    def test_vulnbot_is_a_known_wrapper(self):
        self.assertIn('vulnbot', wrapper_launch.WRAPPERS)


if __name__ == '__main__':
    unittest.main()
