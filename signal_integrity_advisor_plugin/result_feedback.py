"""Compact UI labels derived from recorded SI evidence, without re-analysis."""
import math


def eye_feedback(eye):
    """Return a readable model name and tab text for a recorded eye result."""
    if not eye:
        return '', 'Eye / step'
    if eye.get('status') == 'UNAVAILABLE':
        return 'Eye unavailable', 'Eye / step · unavailable'
    if eye.get('model') == 'board-section-rlc-prbs7':
        return 'Board RLC eye', 'Eye / step · RLC'
    if eye.get('model') == 'uniform-lossless-line-prbs7':
        return 'Ideal-line eye', 'Eye / step · ideal'
    return 'Eye result', 'Eye / step'


def summary_text(values, report=None, *, saved_board=False):
    """Describe the displayed route rather than a different drafted study case."""
    report = report or {}
    path = report.get('path') or {}
    route = {key: path.get(name, values.get(key, ''))
             for key, name in (('net', 'net_name'), ('start', 'start_pad'), ('end', 'end_pad'))}
    if route['net']:
        message = route['net']+' · '+(route['start'] or 'Source?')+' → '+(route['end'] or 'Receiver?')
    else:
        message = '1 Set up a path · 2 Run SI · 3 Inspect the route and Details'
    delay = report.get('delay_ns')
    if isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay):
        message += f' · {delay:.4g} ns'
    eye = report.get('eye')
    caption, _ = eye_feedback(eye)
    if caption:
        message += ' · '+caption
    if saved_board:
        message += ' · Saved PCB snapshot'
    tooltip = message
    if eye and eye.get('status') == 'UNAVAILABLE':
        tooltip += '\n'+eye.get('reason', 'Review missing channel inputs.')
        tooltip += '\nOpen Setup for eye inputs and Details for extraction evidence.'
    elif eye and eye.get('model') == 'board-section-rlc-prbs7':
        tooltip += '\nLinear extracted-section RLC channel; review numerical checks and model limits in Details.'
    return message, tooltip
