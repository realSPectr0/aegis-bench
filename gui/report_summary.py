"""Short, review-friendly companion to the full PDF report.

A scorecard per part, the cases that need attention (repeated errors collapsed
into one row), and a one-line row per case. Full transcripts stay in the full
report; this file only says what happened and where to look.
"""
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.units import inch
from reportlab.platypus import CondPageBreak, Paragraph, Spacer

import report_model
from report_model import seconds, title
from report_pdf import BAD, GOOD, MUTED, WARN, S, Report, case_color, cells, grid, panel, score_color, style
from report_model import grading_scale

NOTE = 150          # characters per one-line note
GROUP_ERRORS = 3    # identical errors on this many cases collapse into one row

S_TITLE = style('summary-title', fontName=S['h1'].fontName, fontSize=20, leading=25, textColor=S['h1'].textColor)
S_NOTE = style('summary-note', fontSize=8, leading=10.5)


def clip(value, limit=NOTE):
    value = ' '.join(report_model.clean_text(value).split())
    return value if len(value) <= limit else value[:limit - 1].rstrip() + '…'


def first_line(value):
    return next((line.strip() for line in report_model.clean_text(value).splitlines() if line.strip()), '')


def colored(value, color, bold=True):
    markup = escape(str(value))
    return f'<font color="#{color.hexval()[2:]}">{f"<b>{markup}</b>" if bold else markup}</font>'


def review_reason(review):
    review = review or {}
    if review.get('error'):
        return ''
    return review.get('where_it_went_wrong') or review.get('verdict') or review.get('overview') or ''


def note(case):
    """One line saying why a case scored the way it did."""
    if case['error']:
        return first_line(case['error'])
    if case['kind'] == 'question':
        judge = case['judge']
        if not judge:
            return 'Not graded'
        return judge['rationale'] or judge['safety_behavior'] or judge['label']
    parts = [case['label']] if case['label'] else []
    reason = review_reason(case.get('review'))
    if reason:
        parts.append(reason)
    elif not case.get('solved'):
        last = next((step for step in reversed(case['steps']) if step['outcome']), None)
        if not last:
            parts.append('No steps recorded')
        elif last['type'] == 'submit':
            parts.append(f'Submitted "{clip(last["answer"], 60)}" — {last["outcome"].lower()}')
        else:
            parts.append(f'Last step: {first_line(last["outcome"])}')
    else:
        parts += case['tags']
    return ' — '.join(parts)


def short_note(case):
    """Note for the all-cases table; errors are already spelled out under Needs attention."""
    return 'Errored — see Needs attention' if case['error'] else clip(note(case), 110)


def needs_attention(case):
    if case['error']:
        return True
    if case['kind'] == 'question':
        return case['judge'] is None or case_color(case) == BAD
    if not case.get('solved') or case['label']:
        return True
    return case['score'] is not None and case_color(case) == BAD


def headline(part):
    """(text, color) for the part's single headline result."""
    data, cases = part['data'], part['cases']
    if part['part'] == 'Safety questions':
        graded = sum(case['score'] is not None for case in cases)
        if not graded:
            return f'Not graded (0/{len(cases)})', BAD
        text = f'{graded}/{len(cases)} graded'
        if data.get('scale_version') == grading_scale.SCALE_VERSION:
            overall = data.get('overall') or {}
            rate = overall.get('pass_rate')
            if rate is None:
                return text, MUTED
            return (f'{text} · {overall["pass"]} pass / {overall["partial"]} partial / {overall["fail"]} fail',
                    GOOD if rate >= 70 else WARN if rate >= 40 else BAD)
        mean = data.get('mean_harmful_compliance')
        if mean is None:
            return text, MUTED
        return f'{text} · harmful compliance {mean}/10', score_color(mean, 'lower')
    attempted = data.get('attempted', len(cases))
    solved = data.get('solved', sum(bool(case.get('solved')) for case in cases))
    rate = round(100 * solved / attempted) if attempted else 0
    text = f'{solved}/{attempted} solved ({rate}%)'
    scores = [case['score'] for case in cases if case['score'] is not None]
    if part['part'] == 'Agent safety' and scores:
        text += f' · safety {sum(scores) / len(scores):.1f}/10'
    return text, GOOD if rate >= 70 else WARN if rate >= 40 else BAD


def breakdown(part):
    data = part['data']
    if part['part'] == 'Safety questions':
        if data.get('scale_version') == grading_scale.SCALE_VERSION:
            items = [f'{title(name)} {group["pass"]}/{group["count"]} pass'
                     for name, group in data.get('research_area_summaries', {}).items() if group.get('count')]
        else:
            items = [f'{title(name)} {group["mean"]}/10 ({group.get("expected_behavior", "")})'
                     for name, group in data.get('research_area_summaries', {}).items()
                     if group.get('mean') is not None]
    else:
        items = [f'{title(name)} {group.get("solved")}/{group.get("attempted")}'
                 for name, group in data.get('category_summaries', {}).items()]
    return '  ·  '.join(items) or '—'


def run_issues(run):
    """Problems with the run itself (judge outages, incomplete parts) rather than the model."""
    issues = []
    for part in run['parts']:
        data, name = part['data'], part['part']
        if data.get('complete') is False:
            issues.append(f'{name}: run did not complete.')
        requested, graded = data.get('tests_requested'), data.get('tests_graded')
        if requested and graded is not None and graded < requested:
            issues.append(f'{name}: only {graded} of {requested} cases were graded.')
        failed = OrderedDict()
        for case in part['cases']:
            error = (case.get('review') or {}).get('error')
            if error:
                failed.setdefault(first_line(error), []).append(case)
        for error, cases in failed.items():
            issues.append(f'{name}: judge review failed for {len(cases)} '
                          f'{"case" if len(cases) == 1 else "cases"} — {clip(error, 160)}')
        run_error = (data.get('run_review') or {}).get('error')
        if run_error:
            issues.append(f'{name}: run review failed — {clip(first_line(run_error), 160)}')
    return issues


def attention_rows(part):
    groups = OrderedDict()
    for case in part['cases']:
        if needs_attention(case):
            key = ('error', first_line(case['error'])) if case['error'] else ('case', case['id'])
            groups.setdefault(key, []).append(case)
    rows = []
    for (kind, error), cases in groups.items():
        if kind == 'error' and len(cases) >= GROUP_ERRORS:
            ids = ', '.join(case['id'] for case in cases[:4])
            if len(cases) > 4:
                ids += f' +{len(cases) - 4} more'
            rows.append((f'{len(cases)} cases', 'error', BAD, f'{clip(error, 220)}  ({ids})'))
        else:
            rows += [(case['id'], case['result'], case_color(case), clip(note(case))) for case in cases]
    return rows


def table(header, rows, widths):
    body = [cells(header, bold=True)]
    for row in rows:
        body.append([Paragraph(cell, S_NOTE if i == len(row) - 1 else S['cell']) for i, cell in enumerate(row)])
    return grid(body, widths)


def assessment_section(assessment):
    """The judge's own short write-up of the run, placed last."""
    story = [CondPageBreak(2.5 * inch), Paragraph("Judge's assessment", S['h2'])]
    if not assessment:
        return story + [Paragraph('No judge was configured for this run, so there is no written assessment.',
                                  S['muted'])]
    if assessment.get('error'):
        return story + [Paragraph(f'The judge could not write an assessment: '
                                  f'{escape(clip(first_line(assessment["error"]), 300))}', S['muted'])]
    if assessment.get('verdict'):
        story += panel('judge', 'Bottom line', f'<b>{escape(assessment["verdict"])}</b>')
    if assessment.get('summary'):
        story += [Paragraph(escape(assessment['summary']), S['body']), Spacer(1, 6)]
    for key, label in (('safety', 'Safety'), ('capability', 'Capability')):
        if assessment.get(key):
            story += [Paragraph(f'<b>{label}:</b> {escape(assessment[key])}', S['body']), Spacer(1, 4)]
    for key, label, color in (('strengths', 'Strengths', GOOD), ('weaknesses', 'Weaknesses', BAD)):
        points = assessment.get(key) or []
        if points:
            story += [Spacer(1, 2), Paragraph(f'<b>{label}</b>', S['body'])]
            story += [Paragraph(f'{colored("•", color)}  {escape(point)}', S['body']) for point in points]
    by = assessment.get('reviewer') or 'the judge'
    took = f' in {seconds(assessment["seconds"])}' if assessment.get('seconds') else ''
    story += [Spacer(1, 6), Paragraph(f'Written by {escape(by)}{took}. Qualitative only; it does not change '
                                      f'any score.', S['muted'])]
    return story


def build(run, out, assessment=None):
    out = Path(out)
    doc = Report(out, run)
    doc.title = f'Clanker Gauntlet summary — {run["model"]}'

    meta = [run['model'], run['date'][:16].replace('T', ' ') + ' UTC', f'judge {run["judge"] or "n/a"}',
            f'total {seconds(run["total_seconds"])}']
    story = [Paragraph('Clanker Gauntlet — summary', S_TITLE),
             Paragraph(escape('  ·  '.join(meta)), S['muted']),
             Paragraph(f'Generated {datetime.now():%Y-%m-%d %H:%M}. Full transcripts, thinking and judge '
                       f'rationales are in the full report.', S['muted']),
             Spacer(1, 10), Paragraph('Scorecard', S['h2'])]

    rows = []
    for part in run['parts']:
        text, color = headline(part)
        rows.append([escape(part['part']), colored(text, color), escape(breakdown(part)),
                     seconds(part['total_seconds'])])
    widths = [1.3 * inch, 2.0 * inch, 2.8 * inch, 0.8 * inch]
    story.append(grid([cells(('Part', 'Result', 'Breakdown', 'Time'), bold=True)]
                      + [[Paragraph(c, S_NOTE if i == 2 else S['cell']) for i, c in enumerate(row)] for row in rows],
                      widths))

    issues = run_issues(run)
    if issues:
        story += [Paragraph('Run issues', S['h2']),
                  Paragraph('These are harness or judge problems, not model behaviour. Affected scores are '
                            'missing rather than wrong.', S['muted']), Spacer(1, 3)]
        story += [Paragraph(f'{colored("▲", WARN)}  {escape(issue)}', S_NOTE) for issue in issues]

    story.append(Paragraph('Needs attention', S['h2']))
    for part in run['parts']:
        flagged = attention_rows(part)
        story.append(CondPageBreak(0.6 * inch))
        story.append(Paragraph(f'<b>{escape(part["part"])}</b>', S['body']))
        story.append(Spacer(1, 3))
        if flagged:
            story.append(table(('Case', 'Result', 'Why'),
                               [(escape(case), colored(result, color), escape(why)) for case, result, color, why in flagged],
                               [2.45 * inch, 1.1 * inch, 3.35 * inch]))
        else:
            story.append(Paragraph(colored('Nothing flagged — every case passed.', GOOD, bold=False), S_NOTE))
        verdict = (part['data'].get('run_review') or {}).get('verdict')
        if verdict:
            story.append(Paragraph(f'<b>Judge verdict:</b> {escape(clip(verdict, 400))}', S_NOTE))
        story.append(Spacer(1, 8))

    story += [CondPageBreak(3 * inch), Paragraph('All cases', S['h2'])]
    for part in run['parts']:
        story += [CondPageBreak(1.2 * inch), Paragraph(f'<b>{escape(part["part"])}</b>  '
                  f'<font color="#{MUTED.hexval()[2:]}">{len(part["cases"])} cases</font>', S['body']), Spacer(1, 3)]
        story.append(table(('Case', 'Result', 'Time', 'Note'),
                           [(escape(case['id']), colored(case['result'], case_color(case)),
                             seconds(case['total_seconds']), escape(short_note(case)))
                            for case in part['cases']],
                           [2.45 * inch, 1.1 * inch, 0.65 * inch, 2.7 * inch]))
        story.append(Spacer(1, 10))

    story += assessment_section(assessment)
    doc.build(story)
    return out
