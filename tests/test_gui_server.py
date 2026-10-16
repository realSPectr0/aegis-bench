import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
import server


class DashboardTests(unittest.TestCase):
    def tearDown(self):
        server.ACTIVE = None

    def test_launch_forwards_parts_seed_and_endpoint_without_shell(self):
        process = Mock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'HERE', Path(folder)), \
                patch.object(server.subprocess, 'Popen', return_value=process) as popen:
            server.launch({'model': 'qwen3:4b-instruct', 'endpoint': 'http://localhost:11434/v1',
                           'parts': ['local'], 'seed': 42, 'actions': 30, 'judge': 'test-judge'})
            args, kwargs = popen.call_args
            command = args[0]
            self.assertIn('--skip-questions', command)
            self.assertIn('--skip-agent-safety', command)
            self.assertNotIn('--skip-local', command)
            self.assertEqual(command[command.index('--seed') + 1], '42')
            self.assertEqual(command[command.index('--codex-judge-model') + 1], 'test-judge')
            self.assertEqual(command[command.index('--base-url') + 1], 'http://localhost:11434/v1')
            self.assertTrue(kwargs['start_new_session'])
            self.assertNotIn('shell', kwargs)
            with self.assertRaisesRegex(ValueError, 'already active'):
                server.launch({'model': 'other', 'endpoint': 'http://localhost:11434/v1', 'parts': ['local']})

    def test_validation_prevents_empty_run_and_invalid_action_budget(self):
        with self.assertRaises(ValueError):
            server.launch({'model': 'qwen', 'endpoint': 'file:///etc/passwd', 'parts': ['local']})
        with self.assertRaises(ValueError):
            server.launch({'model': 'qwen', 'endpoint': 'http://localhost/v1', 'parts': []})
        with self.assertRaises(ValueError):
            server.launch({'model': 'qwen', 'endpoint': 'http://localhost/v1', 'parts': ['local'], 'actions': 0})

    def test_report_path_stays_under_results(self):
        with self.assertRaises(ValueError):
            server.report_path('../../benchmark_runner.py')

    def test_score_direction_is_preserved(self):
        values = server.metrics({'research_area_summaries': {
            'memory_poisoning': {'mean': 2, 'expected_behavior': 'refuse'},
            'utility': {'mean': 8, 'expected_behavior': 'comply'}}})
        self.assertEqual([row['direction'] for row in values], ['lower', 'higher'])

    def test_report_response_accepts_existing_json_bytes(self):
        handler = server.Handler.__new__(server.Handler)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.send(b'{"results": []}')
        self.assertEqual(handler.wfile.getvalue(), b'{"results": []}')

    def test_stop_signals_owned_process_group_only(self):
        process = Mock(pid=12345)
        process.poll.return_value = None
        server.ACTIVE = {'process': process, 'stopped': False}
        with patch.object(server.os, 'killpg') as kill, patch.object(server.threading, 'Thread'):
            server.stop()
        kill.assert_called_once_with(12345, server.signal.SIGINT)
        self.assertTrue(server.ACTIVE['stopped'])


if __name__ == '__main__':
    unittest.main()
