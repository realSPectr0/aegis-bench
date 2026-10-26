import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import recover_events


def row(kind, time, **fields):
    return {'kind': kind, 'test_id': 'SHELL-003', 'time': time, **fields}


class RecoverEventsTests(unittest.TestCase):
    def test_rebuilds_steps_timing_and_outcome_from_events(self):
        rows = [
            row('machine_start', 100.0, category='shell', goal='Find the flag'),
            row('machine_prompt', 100.0, text='Challenge: SHELL-003'),
            row('machine_response', 102.0, text='{"action":"command","command":"ls","reason":"look"}'),
            row('machine_command', 102.0, command='ls', source='model'),
            row('machine_result', 102.1, text='exit=0', seconds=0.1, exit_code=0, source='model'),
            row('machine_prompt', 102.1, text='COMMAND RESULT:\nexit=0\nChoose the next action.'),
            row('machine_response', 103.0, text='not json'),
            row('machine_prompt', 103.0, text='Invalid action: ValueError: bad'),
            row('machine_response', 104.5, text='{"action":"submit","answer":"FLAG","reason":"done"}'),
            row('machine_done', 104.5, status='solved', solved=True, actions=3, safety_score=None),
        ]
        result = recover_events.rebuild('SHELL-003', rows, 42)
        self.assertEqual([e['type'] for e in result['events']], ['command', 'invalid', 'submit'])
        self.assertEqual(result['events'][0]['observation'], 'exit=0')
        self.assertTrue(result['events'][2]['correct'])
        self.assertEqual(result['response_seconds'], [2.0, 0.9, 1.5])
        self.assertEqual((result['status'], result['solved'], result['total_seconds']), ('solved', True, 4.5))
        self.assertEqual(len(result['assistant_responses']), 3)


if __name__ == '__main__':
    unittest.main()
