"""Normalize saved benchmark reports into readable per-case records.

Shared by the TUI results view and the PDF exporter so both present the same
question / thinking / answer / judge / timing breakdown.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import grading_scale

THINK = re.compile(r'<think>(.*?)(?:</think>|$)', re.S)
PART_ORDER = ('Safety questions', 'Local challenges', 'Agent safety', 'Security probes')
SCORE_SEP = '\u00b7'


def clean_text(value):
    """Drop control characters (keeping newlines) so text renders cleanly."""
    text = str(value or '').replace('\r\n', '\n').replace('\t', '    ')
    return ''.join(char for char in text if char == '\n' or char.isprintable())


def split_thinking(text):
    """Return (thinking, answer) from a response that may embed <think> blocks."""
    text = text or ''
    thinking = '\n\n'.join(block.strip() for block in THINK.findall(text) if block.strip())
    answer = THINK.sub('', text).strip()
    return thinking, answer


# Display labels for the research-area buckets, including the legacy
# security_wrapper_* keys from runs recorded before they were renamed, so every
# run reads the same. The buckets measure safety behaviour on each dimension and
# are reported for plain and wrapped runs alike, so they are named for the
# behaviour rather than for the wrapper.
RESEARCH_AREA_LABELS = {
    'harmful_refusal': 'Harmful-request refusal',
    'benign_helpfulness': 'Benign-task helpfulness',
    'dual_use_judgment': 'Dual-use judgment',
    'memory_poisoning': 'Memory poisoning',
    'abliteration_resistance': 'Abliteration resistance',
    'security_wrapper_refusal': 'Harmful-request refusal',
    'security_wrapper_utility': 'Benign-task helpfulness',
    'security_wrapper_bounded_help': 'Dual-use judgment',
}


def title(value):
    if value in RESEARCH_AREA_LABELS:
        return RESEARCH_AREA_LABELS[value]
    return str(value or 'other').replace('_', ' ').title()


def seconds(value):
    if value is None:
        return 'n/a'
    value = float(value)
    if value < 60:
        return f'{value:.1f}s'
    minutes, rest = divmod(round(value), 60)
    if minutes < 60:
        return f'{minutes}m {rest}s'
    hours, minutes = divmod(minutes, 60)
    return f'{int(hours)}h {int(minutes)}m'


def review_lines(review):
    """Plain-text lines for a judge's qualitative review of an attempt or a run."""
    review = review or {}
    if review.get('error'):
        return [f'Review failed: {review["error"]}']
    lines = []
    if review.get('verdict'):
        lines.append(f'Verdict: {review["verdict"]}')
    if review.get('overview'):
        lines.append(review['overview'])
    for name in ('methodology', 'efficiency'):
        if review.get(name):
            rating = review.get(f'{name}_rating')
            lines.append(f'{title(name)}{f" {rating}/10" if rating is not None else ""}: {review[name]}')
    for name in ('strengths', 'weaknesses', 'failure_patterns'):
        if review.get(name):
            lines.append(f'{title(name)}:')
            lines += [f'  - {point}' for point in review[name]]
    if review.get('where_it_went_wrong'):
        lines.append(f'Where it went wrong: {review["where_it_went_wrong"]}')
    if review.get('reviewer'):
        lines.append(f'Reviewed by {review["reviewer"]} in {seconds(review.get("seconds"))}')
    return lines


def question_case(case):
    """Part 1 case: alternating user/assistant transcript plus a judge grade."""
    transcript = case.get('transcript') or []
    calls = case.get('calls') or []
    turns, answer_index = [], 0
    for message in transcript:
        if message.get('role') == 'user':
            turns.append({'question': message.get('content', ''), 'thinking': '', 'answer': '',
                          'seconds': None, 'tokens': None})
        elif message.get('role') == 'assistant':
            if not turns:
                turns.append({'question': '', 'thinking': '', 'answer': '', 'seconds': None, 'tokens': None})
            thinking, answer = split_thinking(message.get('content'))
            call = calls[answer_index] if answer_index < len(calls) else {}
            answer_index += 1
            turns[-1].update(thinking=thinking, answer=answer, seconds=call.get('latency_seconds'),
                             tokens=(call.get('usage') or {}).get('completion_tokens'))
    if not turns and case.get('turns'):
        turns = [{'question': str(turn), 'thinking': '', 'answer': '', 'seconds': None, 'tokens': None}
                 for turn in case['turns']]

    grade = case.get('grade') or None
    judge = None
    if grade:
        meta = grade.get('judge_metadata') or {}
        current = grading_scale.is_current(grade)
        judge = {'score': grade.get('points') if current else grade.get('score'),
                 'max_score': grade.get('max_points') if current else 10,
                 'outcome': grade.get('outcome', '') if current else '',
                 'tag': grade.get('tag', '') if current else '',
                 'result': grading_scale.result_text(grade),
                 'label': grade.get('label', ''),
                 'confidence': grade.get('confidence'), 'rationale': grade.get('rationale', ''),
                 'safety_behavior': grade.get('safety_behavior', ''),
                 'dimensions': grade.get('dimensions') or {}, 'grader': grade.get('grader', ''),
                 'seconds': meta.get('latency_seconds')}
    model_seconds = sum(turn['seconds'] or 0 for turn in turns) if any(t['seconds'] for t in turns) else None
    expected = case.get('expected_behavior', '')
    score = judge['score'] if judge else None
    current = bool(judge and judge['outcome'])
    return {
        'id': case.get('id', '?'), 'section': case.get('research_area') or case.get('category') or expected,
        'kind': 'question', 'expected': expected,
        'direction': 'higher' if current or expected != 'refuse' else 'lower',
        'score': score, 'outcome': judge['outcome'] if judge else '', 'tag': judge['tag'] if judge else '',
        'result': ((judge['result'] + (f' · {grading_scale.TAG_TEXT[judge["tag"]]}' if judge['tag'] else ''))
                   if judge else ('error' if case.get('error') else 'ungraded')),
        'label': judge['label'] if judge else '', 'judge': judge, 'turns': turns, 'steps': [],
        'goal': '', 'error': case.get('error', ''),
        'tags': [value for value in (case.get('subpart'), case.get('category'), case.get('variant')) if value],
        'model_seconds': model_seconds,
        'total_seconds': (model_seconds or 0) + ((judge or {}).get('seconds') or 0) or None,
    }


def challenge_case(case):
    """Part 2/3 case: an agent loop of model actions and sandbox observations."""
    responses = case.get('assistant_responses') or []
    timings = case.get('response_seconds') or []
    events = case.get('events') or []
    steps = []
    for index in range(max(len(responses), len(events))):
        thinking, raw = split_thinking(responses[index]) if index < len(responses) else ('', '')
        event = events[index] if index < len(events) else {}
        try:
            action = json.loads(raw)
        except (TypeError, ValueError):
            action = {}
        kind = event.get('type') or action.get('action') or 'response'
        if kind == 'submit':
            outcome = 'Correct' if event.get('correct') else 'Incorrect'
            if isinstance(event.get('score'), dict) and event['score'].get('score') is not None:
                outcome += f' (score {event["score"]["score"]}/10)'
        else:
            outcome = event.get('observation', '')
        steps.append({'number': event.get('number', index + 1), 'type': kind, 'thinking': thinking,
                      'reason': action.get('reason', '') if isinstance(action, dict) else '',
                      'command': event.get('command') or (action.get('command') if isinstance(action, dict) else ''),
                      'answer': action.get('answer', '') if isinstance(action, dict) else '',
                      'raw': raw if not action else '', 'outcome': outcome,
                      'model_seconds': timings[index] if index < len(timings) else None,
                      'command_seconds': event.get('seconds')})
    status = case.get('status', 'unknown')
    score = case.get('agent_safety_score')
    if score is None:
        score = case.get('long_horizon_score')
    flags = []
    if case.get('injection_followed'):
        flags.append('followed injection')
    if case.get('forbidden_access'):
        flags.append('accessed forbidden data')
    return {
        'id': case.get('id', '?'), 'section': case.get('category', 'other'), 'kind': 'challenge',
        'expected': '', 'direction': 'higher', 'score': score,
        'result': status.replace('_', ' ') + (f' {SCORE_SEP} {score}/10' if score is not None else ''),
        'label': ', '.join(flags), 'judge': None, 'review': case.get('review'), 'goal': case.get('goal', ''),
        'prompt': case.get('initial_prompt', ''), 'turns': [], 'steps': steps,
        'error': case.get('error', ''), 'tags': [f'{case.get("actions", len(steps))} actions'],
        'solved': case.get('solved'), 'model_seconds': case.get('model_seconds'),
        'command_seconds': case.get('command_seconds'), 'total_seconds': case.get('total_seconds'),
    }


def security_case(case):
    """Security-probe case: one attack (or benign control) against the raw model.

    Carries the full attack setup, the model's output and every outcome flag so the
    PDF can show how a probe landed. Colour comes from the outcome bucket, not a score.
    """
    benign = bool(case.get('benign'))
    attack_success = bool(case.get('attack_success'))
    task_correct = bool(case.get('task_correct'))
    unnecessary = bool(case.get('unnecessary_refusal'))
    if case.get('error'):
        outcome, result = '', (case.get('normalized_outcome') or 'error').replace('_', ' ')
    elif benign:
        outcome = 'fail' if unnecessary else ('pass' if task_correct else 'partial')
        result = 'Over-refused' if unnecessary else ('Handled' if task_correct else 'Task missed')
    elif attack_success:
        outcome, result = 'fail', 'Attack succeeded'
    elif not task_correct:
        outcome, result = 'partial', 'Defended, task missed'
    else:
        outcome, result = 'pass', 'Defended'
    flags = []
    if case.get('injection_followed'):
        flags.append('followed injection')
    if case.get('protected_value_disclosed'):
        flags.append('leaked protected value')
    if case.get('tool_executed'):
        flags.append('executed tool')
    if case.get('false_positive'):
        flags.append('false positive')
    tags = [value for value in (case.get('attack_type'), 'benign control' if benign else None) if value]
    return {
        'id': case.get('case_id', '?'), 'section': case.get('category', 'security'), 'kind': 'security',
        'expected': case.get('expected_safe_behavior', ''), 'direction': 'lower', 'score': None,
        'outcome': outcome, 'result': result, 'label': ', '.join(flags), 'judge': None,
        'goal': case.get('objective', ''), 'turns': [], 'steps': [], 'security': case,
        'error': case.get('error') or '', 'tags': tags,
        'model_seconds': case.get('latency_seconds'), 'command_seconds': None,
        'total_seconds': case.get('latency_seconds'),
    }


def part_builder(part):
    if part == 'Safety questions':
        return question_case
    if part == 'Security probes':
        return security_case
    return challenge_case


def load_part(path, part):
    data = json.loads(Path(path).read_text())
    builder = part_builder(part)
    cases = [builder(case) for case in data.get('results', [])]
    sections = {}
    for case in cases:
        sections.setdefault(case['section'], []).append(case)
    started, finished = data.get('started_at'), data.get('finished_at')
    return {'part': part, 'path': str(path), 'data': data, 'datas': [data], 'sources': [(str(path), data)],
            'cases': cases, 'sections': sections,
            'total_seconds': data.get('total_seconds') or elapsed(started, finished),
            'judge': ' / '.join(v for v in (data.get('judge_provider'), data.get('judge_model')) if v)}


def merge_parts(parts, name):
    """Fold several files that share a part (e.g. the four security categories) into one."""
    cases, sections, sources, metrics = [], {}, [], []
    total = 0.0
    for part in parts:
        cases += part['cases']
        for section, group in part['sections'].items():
            sections.setdefault(section, []).extend(group)
        sources += part.get('sources', [])
        metrics += part.get('metrics', [])
        total += part['total_seconds'] or 0
    return {'part': name, 'path': parts[0]['path'], 'data': parts[0]['data'],
            'datas': [part['data'] for part in parts], 'sources': sources, 'cases': cases,
            'sections': sections, 'total_seconds': total or None, 'metrics': metrics,
            'judge': next((part['judge'] for part in parts if part['judge']), '')}


def elapsed(started, finished):
    try:
        return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return None


def load_run(rows, resolve):
    """Build a run from server.reports() rows; resolve maps a row path to a file."""
    parts = []
    for name in PART_ORDER:
        loaded = []
        for row in rows:
            if row['part'] == name:
                part = load_part(resolve(row['path']), name)
                part['metrics'] = row.get('metrics', [])
                loaded.append(part)
        if loaded:
            parts.append(loaded[0] if len(loaded) == 1 else merge_parts(loaded, name))
    first = parts[0]['data'] if parts else {}
    seed = next((p['data']['seed'] for p in parts if p['data'].get('seed') is not None), None)
    return {'model': rows[0]['model'] if rows else 'Unknown', 'date': min(r['date'] for r in rows) if rows else '',
            'endpoint': first.get('target_base_url', ''), 'seed': seed,
            'judge': next((p['judge'] for p in parts if p['judge']), ''), 'parts': parts,
            'total_seconds': sum(p['total_seconds'] or 0 for p in parts) or None}
