"""Ordered fanout rules; global scope remains the outer selection boundary."""
import fnmatch

MATCH_FIELDS = {'net', 'netclass', 'ref', 'pad'}
GROUP_CONTROL_FIELDS = {'groups', 'unmatched', 'scope', 'ref', 'net_filter', 'netclass_filter'}


def validate_groups(groups, unmatched, setting_names):
    if unmatched not in ('defaults', 'skip', 'error'):
        raise ValueError('unmatched must be defaults, skip or error.')
    if not isinstance(groups, list) or len(groups) > 64:
        raise ValueError('groups must be a list of at most 64 ordered rules.')
    names = set()
    for index, rule in enumerate(groups):
        if not isinstance(rule, dict) or set(rule) - {'name', 'match', 'settings'}:
            raise ValueError(f'Group {index + 1}: expected name, match and settings.')
        name = rule.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names or name == 'Defaults':
            raise ValueError('Group names must be unique, nonempty, at most 80 characters; Defaults is reserved.')
        names.add(name)
        match = rule.get('match', {})
        if not isinstance(match, dict) or set(match) - MATCH_FIELDS:
            raise ValueError(name + ': match supports net, netclass, ref and pad.')
        for key, value in match.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise ValueError(name + ': match values must be nonempty text up to 512 characters.')
            if key != 'netclass' and not any(p.strip() for p in value.split(',')):
                raise ValueError(name + ': provide a wildcard or exact pad/net/reference.')
        settings = rule.get('settings', {})
        if not isinstance(settings, dict) or set(settings) - (set(setting_names) - GROUP_CONTROL_FIELDS):
            raise ValueError(name + ': overrides must be routing geometry/pair settings; select pads in match.')
        for key in ('add_vias','use_netclass_rules'):
            if key in settings and type(settings[key]) is not bool:
                raise ValueError(name + ': '+key+' must be a JSON boolean.')
    return groups


def matches(rule, footprint, pad, classes, netclass_match):
    match = rule.get('match', {})
    for key, value in [('net', str(pad.GetNetname())), ('ref', str(footprint.GetReference())), ('pad', str(pad.GetNumber()))]:
        patterns = match.get(key, '*')
        if key == 'ref': value, patterns = value.upper(), patterns.upper()
        if not any(fnmatch.fnmatchcase(value, p.strip()) for p in patterns.split(',') if p.strip()):
            return False
    return netclass_match(pad, match.get('netclass', 'All netclasses'), classes)
