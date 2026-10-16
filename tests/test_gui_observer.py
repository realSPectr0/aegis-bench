import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
import observe_questions as observer
import codex_models
from cli import ControlPanel


class ObserverTests(unittest.TestCase):
    def test_codex_catalog_filters_hidden_models_and_preserves_ids(self):
        rows = codex_models.normalize([
            {'model': 'visible-model', 'displayName': 'Visible Model'},
            {'slug': 'hidden-model', 'visibility': 'hide'},
            {'id': 'also-hidden', 'hidden': True},
            {'slug': 'visible-model'},
        ])
        self.assertEqual(rows, [{'id': 'visible-model', 'name': 'Visible Model'}])

    def test_judge_picker_stores_model_id_not_display_name(self):
        ui = ControlPanel.__new__(ControlPanel)
        ui.tab, ui.focus, ui.cursor = 0, 'setup', 3
        ui.config = {'judge': ''}
        ui.judge_models = [{'id': 'judge-id', 'name': 'Judge Display Name'}]
        ui.judge_source = 'test catalog'
        with patch.object(ui, 'pick', return_value='Judge Display Name / judge-id'):
            ui.enter()
        self.assertEqual(ui.config['judge'], 'judge-id')

    def test_target_and_judge_events_preserve_transcript_and_grade(self):
        test = {'id': 'CONTROL', 'turns': ['Return hello'], 'expected_behavior': 'comply'}
        grade = {'score': 9, 'label': 'useful', 'rationale': 'Correct answer'}

        class Client:
            model = 'test'

            def complete(self, messages, **kwargs):
                return 'hello', {'latency_seconds': 0}

        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / 'events.jsonl'
            with patch.dict(os.environ, {'CLANKER_EVENTS': str(events)}), \
                    patch.object(observer.runner, 'run_test', observer.runner.run_test), \
                    patch.object(observer.runner, 'judge_transcript', return_value=grade):
                observer.install()
                transcript, calls = observer.runner.run_test(Client(), test, 'Be helpful')
                result = observer.runner.judge_transcript(Client(), test, transcript)
            rows = [json.loads(line) for line in events.read_text().splitlines()]
        self.assertEqual([row['kind'] for row in rows], ['question', 'target_answer', 'judge_started', 'judge_grade'])
        self.assertEqual(rows[2]['transcript'], transcript)
        self.assertEqual(result, grade)
        self.assertEqual(rows[3]['grade'], grade)
        self.assertEqual(calls, [{'latency_seconds': 0}])

    def test_results_page_groups_parts_and_marks_missing_reports(self):
        ui = ControlPanel.__new__(ControlPanel)
        ui.rows = [{'path': 'run/a.json', 'part': 'Safety questions', 'model': 'qwen', 'date': '2026-10-15', 'metrics': []},
                   {'path': 'run/b.json', 'part': 'Agent safety', 'model': 'qwen', 'date': '2026-10-15', 'metrics': []}]
        ui.build_groups()
        self.assertEqual(len(ui.groups), 1)
        ui.cursor = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text(json.dumps({'results': [{'id': 'TEST', 'grade': {'score': 9, 'rationale': 'Useful'}}]}))
            with patch('server.report_path', return_value=path):
                ui.open_group()
        content = '\n'.join(ui.page_detail)
        self.assertIn('SAFETY QUESTIONS', content)
        self.assertIn('LOCAL CHALLENGES', content)
        self.assertIn('AGENT SAFETY', content)
        self.assertIn('No saved report for this part', content)
        self.assertIn('9/10', content)


if __name__ == '__main__':
    unittest.main()
