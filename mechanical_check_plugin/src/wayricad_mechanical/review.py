"""Read-only finding filters and human-readable mechanical review summaries."""
import math


_SEVERITIES = {'error': 0, 'warning': 1, 'info': 2}
_FILTERS = ('All', 'Errors', 'Warnings', 'Waived', 'Open')
_SORTS = ('Priority', 'Parts', 'Rule')
_SEARCH_FIELDS = ('summary', 'rule', 'evidence', 'action', 'waiver')


def _text(value):
    return '' if value is None else str(value)


def _refs(issue):
    refs = issue.get('refs') or ()
    return (refs,) if isinstance(refs, str) else tuple(refs)


def _priority(issue):
    severity = _text(issue.get('severity')).casefold()
    return bool(issue.get('waiver')), _SEVERITIES.get(severity, 3), severity


def filtered_findings(findings, query='', severity='All', sort_by='Priority'):
    """Return matching original dictionaries in deterministic review order.

    Whitespace-separated query tokens must all match human-facing fields.
    Geometry, sections and other analysis payloads are deliberately not read.
    Filtering and sorting never alter the findings or their source sequence.
    """
    if severity not in _FILTERS:
        raise ValueError('Unknown finding filter: ' + _text(severity))
    if sort_by not in _SORTS:
        raise ValueError('Unknown finding sort: ' + _text(sort_by))
    tokens = _text(query).casefold().split()
    result = []
    for issue in findings:
        waived = bool(issue.get('waiver'))
        level = _text(issue.get('severity')).casefold()
        if severity == 'Waived' and not waived:
            continue
        if severity in ('Errors', 'Warnings') and (waived or level != {'Errors': 'error', 'Warnings': 'warning'}[severity]):
            continue
        if severity == 'Open' and waived:
            continue
        if tokens:
            words = ' '.join([*map(_text, _refs(issue)), *(_text(issue.get(key)) for key in _SEARCH_FIELDS)]).casefold()
            if not all(token in words for token in tokens):
                continue
        result.append(issue)
    def key(issue):
        priority = _priority(issue)
        parts = tuple(sorted(_text(ref).casefold() for ref in _refs(issue)))
        rule = _text(issue.get('rule')).casefold()
        if sort_by == 'Parts':
            return parts, priority, rule
        if sort_by == 'Rule':
            return rule, priority, parts
        return priority, rule, parts
    return sorted(result, key=key)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _quantity(value, unit):
    if not _number(value):
        return 'Unknown'
    return f'{value:.6g}' + (' ' + unit if unit else '')


def finding_details(issue):
    """Describe an issue without confusing maxima with minimum clearances.

    Numeric measurements retain the report's declared unit. Missing or invalid
    values remain unknown; geometric witnesses and meshes are never serialized.
    Excess is computed only for explicit height or overlap-volume maxima when
    both the measurement and maximum are known.
    """
    rule = _text(issue.get('rule'))
    unit = _text(issue.get('unit')).strip()
    measured, limit = issue.get('measured'), issue.get('limit')
    if rule in ('height.maximum', 'height.zone', 'solid.collision', 'interboard.collision'):
        limit_label = 'Maximum'
        excess = _quantity(max(0, measured-limit), unit) if _number(measured) and _number(limit) else 'Unknown'
    elif rule in ('solid.proximity_warning', 'screen.proximity_warning'):
        limit_label, excess = 'Warning below', 'Not applicable'
    else:
        limit_label, excess = 'Required', 'Not applicable'
    severity = _text(issue.get('severity')).title() or 'Unknown'
    if issue.get('waiver'):
        severity += ' (waived)'
    return '\n'.join([
        'Summary: ' + (_text(issue.get('summary')) or 'Not supplied'),
        'Parts: ' + (', '.join(map(_text, _refs(issue))) or 'Not specified'),
        'Rule: ' + (rule or 'Not specified'),
        'Severity: ' + severity,
        'Measured: ' + _quantity(measured, unit),
        limit_label + ': ' + _quantity(limit, unit),
        'Unit: ' + (unit or 'Not specified'),
        'Excess: ' + excess,
        'Evidence: ' + (_text(issue.get('evidence')) or 'Not supplied'),
        'Suggested action: ' + (_text(issue.get('action')) or 'Not supplied'),
        'Waiver: ' + (_text(issue.get('waiver')) or 'None'),
    ])


def review_summary(report):
    """Count open issues and retain incomplete or unknown coverage honestly."""
    findings = report.get('findings') or ()
    errors = warnings = waived = 0
    for issue in findings:
        if issue.get('waiver'):
            waived += 1
        elif _text(issue.get('severity')).casefold() == 'error':
            errors += 1
        elif _text(issue.get('severity')).casefold() == 'warning':
            warnings += 1
    coverage = report.get('coverage')
    gaps = coverage.get('gaps') if isinstance(coverage, dict) else None
    known_coverage = isinstance(gaps, (list, tuple))
    declared = _text(report.get('status')).replace('_', ' ').upper() or 'UNKNOWN'
    status = declared
    if not known_coverage or gaps:
        status = 'INCOMPLETE'
    elif (errors or warnings) and declared in ('PASSED', 'PASSED WITH WAIVERS'):
        status = 'REVIEW REQUIRED'
    if status != declared:
        status += ' (reported: ' + declared + ')'
    counts = f'{errors} open errors · {warnings} open warnings · {waived} waived'
    coverage_text = f'{len(gaps)} coverage gaps' if known_coverage else 'Coverage unavailable; completeness unknown'
    return status + ' · ' + counts + '\n' + coverage_text
