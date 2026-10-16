"""Expose question/judge progress without changing benchmark grading."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import benchmark_runner as runner


def emit(kind, test_id, **fields):
    filename = os.environ.get('CLANKER_EVENTS')
    if not filename:
        return
    event = {'kind': kind, 'test_id': test_id, 'time': time.time(), **fields}
    try:
        descriptor = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(event) + '\n')
    except OSError as exc:
        print(f'Observer log unavailable: {exc}', file=sys.stderr)


def install():
    original_test = runner.run_test
    original_judge = runner.judge_transcript

    def run_test(client, test, system_prompt):
        class ObservedTarget:
            def complete(self, messages, **kwargs):
                emit('question', test['id'], text=messages[-1]['content'])
                try:
                    answer, metadata = client.complete(messages, **kwargs)
                except Exception as exc:
                    emit('target_error', test['id'], text=str(exc))
                    raise
                emit('target_answer', test['id'], text=answer)
                return answer, metadata
        return original_test(ObservedTarget(), test, system_prompt)

    def judge_transcript(judge, test, transcript):
        emit('judge_started', test['id'], judge=getattr(judge, 'model', None) or 'Configured default',
             expected_behavior=test.get('expected_behavior', 'refuse'), transcript=transcript)
        try:
            grade = original_judge(judge, test, transcript)
        except Exception as exc:
            emit('judge_error', test['id'], text=str(exc))
            raise
        emit('judge_grade', test['id'], grade=grade)
        return grade

    runner.run_test = run_test
    runner.judge_transcript = judge_transcript


if __name__ == '__main__':
    install()
    raise SystemExit(runner.main())
