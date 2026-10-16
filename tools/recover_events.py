#!/usr/bin/env python3
"""Rebuild a partial Part 2/3 report from a GUI live event log.

Use this when a challenge run was interrupted before it saved its report. The
output can be passed to `local_challenge_runner.py --resume-from` to run only
the challenges that had not finished, using the same seed.

  python tools/recover_events.py gui/logs/RUN.events.jsonl \
      --model MODEL --seed 42 -o recovered.json
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import local_challenge_runner as local
from benchmark_runner import DEFAULT_BASE_URL, secure_write_json


def flag(value):
    return value is True or str(value).lower() == 'true'


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def action_of(text):
    try:
        return local.extract_action(text)
    except Exception:
        return None


def rebuild(test_id, rows, seed):
    """Turn one finished challenge's events back into a run_challenge() result."""
    start = next(row for row in rows if row['kind'] == 'machine_start')
    done = next(row for row in rows if row['kind'] == 'machine_done')
    model_rows = [row for row in rows if row.get('source', 'model') == 'model'
                  and row['kind'] in ('machine_prompt', 'machine_response', 'machine_command', 'machine_result')]
    prompts = [row for row in rows if row['kind'] == 'machine_prompt']
    responses, timings, events = [], [], []
    command_seconds = 0.0
    checker = None
    if test_id.startswith('CASE-'):
        with tempfile.TemporaryDirectory() as directory:
            checker = local.generate_challenge(test_id, Path(directory), seed).answer_checker

    for index, row in enumerate(model_rows):
        if row['kind'] != 'machine_response':
            continue
        number_ = len(responses) + 1
        responses.append(row['text'])
        previous = next((r for r in reversed(model_rows[:index]) if r['kind'] == 'machine_prompt'), None)
        timings.append(round(number(row['time']) - number(previous['time']), 4) if previous else None)
        following = model_rows[index + 1:]
        nxt = next((r for r in following if r['kind'] == 'machine_response'), None)
        window = following[:following.index(nxt)] if nxt else following
        command = next((r for r in window if r['kind'] == 'machine_command'), None)
        result = next((r for r in window if r['kind'] == 'machine_result'), None)
        reply = next((r['text'] for r in window if r['kind'] == 'machine_prompt'), '')
        action = action_of(row['text'])
        if done['status'] == 'stuck' and nxt is None and len(responses) >= local.REPEAT_LIMIT:
            events.append({'number': number_, 'type': 'stuck',
                           'observation': f'Model returned the same response {local.REPEAT_LIMIT} times in a row; ending challenge.'})
        elif action is None:
            events.append({'number': number_, 'type': 'invalid', 'observation': reply or 'Invalid action'})
        elif action['action'] == 'command':
            if result is not None:
                seconds = number(result.get('seconds')) or 0.0
                command_seconds += seconds
                observation = reply.removeprefix('COMMAND RESULT:\n').removesuffix('\nChoose the next action.') or result['text']
                events.append({'number': number_, 'type': 'command', 'command': action['command'],
                               'observation': observation, 'seconds': round(seconds, 4)})
            else:
                observation = reply.removeprefix('COMMAND RESULT:\n').removesuffix('\nChoose the next action.')
                events.append({'number': number_, 'type': 'command_error', 'command': action['command'],
                               'observation': observation or 'Command rejected'})
        elif action['action'] == 'give_up':
            events.append({'number': number_, 'type': 'give_up'})
        else:
            event = {'number': number_, 'type': 'submit',
                     'correct': nxt is None and flag(done['solved'])}
            if checker:
                _, event['score'] = checker(action['answer'].strip())
            events.append(event)

    case_scores = [e['score'].get('score') for e in events if isinstance(e.get('score'), dict)]
    status = done['status']
    safety = done.get('safety_score')
    category = start.get('category') or local.category_for(test_id)
    return {
        'id': test_id, 'category': category, 'goal': start.get('goal', ''),
        'initial_prompt': prompts[0]['text'] if prompts else '',
        'status': status, 'solved': flag(done['solved']),
        'total_seconds': round(number(done['time']) - number(start['time']), 4),
        'model_seconds': round(sum(t for t in timings if t), 4),
        'command_seconds': round(command_seconds, 4),
        'actions': int(done.get('actions') or len(events)),
        'forbidden_access': None, 'injection_followed': None,
        'agent_safety_score': int(safety) if str(safety).isdigit() else None,
        'long_horizon_score': max((int(s) for s in case_scores if s is not None), default=None),
        'assistant_responses': responses, 'response_seconds': timings, 'events': events,
        'recovered_from_events': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('events', help='GUI live event log (*.events.jsonl)')
    parser.add_argument('--model', required=True, help='Target model the run used')
    parser.add_argument('--seed', type=int, required=True, help='Seed the run used')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('-o', '--output', required=True)
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.events).read_text().splitlines() if line.strip()]
    by_test = {}
    for row in rows:
        if row.get('kind', '').startswith('machine_'):
            by_test.setdefault(row['test_id'], []).append(row)
    finished = [test_id for test_id, items in by_test.items() if any(r['kind'] == 'machine_done' for r in items)]
    results = [rebuild(test_id, by_test[test_id], args.seed) for test_id in finished]
    first = min(number(row['time']) for row in rows)
    last = max(number(row['time']) for row in rows)
    summary = {
        'benchmark_part': 'local_and_agent_safety', 'target_model': args.model, 'target_base_url': args.base_url,
        'seed': args.seed, 'complete': False,
        'started_at': datetime.fromtimestamp(first, timezone.utc).isoformat(),
        'finished_at': datetime.fromtimestamp(last, timezone.utc).isoformat(),
        'attempted': len(results), 'solved': sum(r['solved'] for r in results),
        'total_seconds': round(last - first, 4), 'category_summaries': local.summarize_categories(results),
        'results': results,
    }
    secure_write_json(Path(args.output), summary)
    unfinished = [test_id for test_id in by_test if test_id not in finished]
    print(f'Recovered {len(results)} finished challenges ({summary["solved"]} solved) -> {args.output}')
    if unfinished:
        print('Not finished (will be re-run on resume): ' + ', '.join(unfinished))


if __name__ == '__main__':
    main()
