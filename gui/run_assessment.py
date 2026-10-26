"""Judge-written overall assessment of a run, shown at the end of the summary PDF.

The judge sees the same digest the summary prints (headlines, breakdowns, run issues,
one line per case). Its answer is cached as JSON beside the reports and reused until
the run's results change, so re-exporting does not call the judge again.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import report_summary
from report_model import seconds

NO_JUDGE = ('none', 'heuristic', '')


def digest(run):
    parts = []
    for part in run['parts']:
        text, _ = report_summary.headline(part)
        parts.append({'part': part['part'], 'result': text, 'breakdown': report_summary.breakdown(part),
                      'duration': seconds(part['total_seconds']),
                      'cases': [f'{case["id"]} [{case["section"]}] {case["result"]}: {report_summary.clip(report_summary.note(case), 160)}'
                                for case in part['cases']]})
    return {'model': run['model'], 'date': run['date'][:10], 'parts': parts,
            'run_issues': report_summary.run_issues(run)}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def cache_path(run):
    first = Path(run['parts'][0]['path'])
    if len(run['parts']) > 1 or first.parent.name.endswith('_full'):
        return first.parent / 'judge_summary.json'
    return first.with_name(f'{first.stem}_judge_summary.json')


def judge_config(run):
    """(provider, model) the run was graded with, so the assessment uses the same judge."""
    for part in run['parts']:
        provider = part['data'].get('judge_provider')
        if provider:
            return provider, part['data'].get('judge_model')
    for part in run['parts']:
        for review in [part['data'].get('run_review')] + [case.get('review') for case in part['cases']]:
            reviewer = (review or {}).get('reviewer') or ''
            if ':' in reviewer:
                provider, model = reviewer.split(':', 1)
                return provider, model
    return 'codex-cli', None


def ensure(run, provider=None, model=None, refresh=False):
    """Return the cached assessment, or ask the judge for one. Failures come back as {'error': ...}."""
    if not run['parts']:
        return None
    payload = digest(run)
    stamp = fingerprint(payload)
    path = cache_path(run)
    if not refresh:
        try:
            cached = json.loads(path.read_text())
            if cached.get('fingerprint') == stamp:
                return cached
        except (OSError, ValueError):
            pass

    found_provider, found_model = judge_config(run)
    provider = provider or found_provider
    model = model or found_model
    if model == 'configured-default':
        model = None
    if provider in NO_JUDGE:
        return None
    try:
        from challenge_review import assess_gauntlet, make_reviewer
        reviewer = make_reviewer(provider, judge_model=model, codex_model=model)
        assessment = assess_gauntlet(reviewer, payload)
    except Exception as exc:  # judge outages should not block the PDF export
        return {'error': f'{type(exc).__name__}: {exc}'}
    assessment['fingerprint'] = stamp
    try:
        path.write_text(json.dumps(assessment, indent=2))
    except OSError:
        pass
    return assessment
