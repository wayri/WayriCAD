"""Bounded text and contact resolution for one Quick PI rail with grouped loads."""
import math
import re


ACTION = 'quick-pi.grouped'
_REFERENCE = r'[A-Z][A-Z0-9_-]*\d'
_PIN = r'[A-Z0-9_][A-Z0-9_.-]{0,31}'
_PAD = rf'{_REFERENCE}\.{_PIN}'
_DECIMAL = r'(?:\d+(?:\.\d+)?|\.\d+)'
_AMP = rf'(?P<amps>{_DECIMAL})\s*(?P<unit>mA|A|amps?)\b'
_FROM = re.compile(
    rf'\bfrom\s+(?P<source>{_REFERENCE}\b.*?)\s+to\s+(?P<loads>{_REFERENCE}\b.*)',
    re.I,
)
_REPLY = re.compile(
    rf'^(?:(?:use|change(?: the endpoints)? to)\s+)?(?:from\s+)?'
    rf'(?P<source>{_REFERENCE}\b.*?)\s+to\s+(?P<loads>{_REFERENCE}\b.*)',
    re.I,
)
_UNIT_SPLIT = re.compile(rf'\s*(?:\||,\s*(?:and\s+)?|\band\b)\s*(?={_REFERENCE}\b)', re.I)
_TAIL = re.compile(
    r'\s+(?:with\b|each\b|consuming\b|drawing\b|draws?\b|at\s+(?:\d|\.\d)|(?:and\s+)?(?:the\s+)?(?:input|source|supply)\s+voltage\b|using\b)',
    re.I,
)


def _amps(match):
    value = float(match['amps']) * (.001 if match['unit'].casefold() == 'ma' else 1.)
    if not math.isfinite(value) or not 0 < value <= 1e12:
        raise ValueError('A load needs a finite positive current in A or mA.')
    return value


def contact(raw):
    """Return the footprint reference and optionally explicit pad labels."""
    raw = raw.strip()
    listed = re.fullmatch(rf'({_REFERENCE})\s+(?:pads?|pins?)\s+(.+)', raw, re.I)
    if listed:
        pins = re.split(r'\s*(?:,\s*(?:and\s+)?|\band\b|\+)\s*', listed[2], flags=re.I)
        if not pins or any(not re.fullmatch(_PIN, pin, re.I) for pin in pins):
            raise ValueError('List exact pin numbers, for example U1 pins 1, 2 and 6.')
        return listed[1], [listed[1] + '.' + pin for pin in pins]
    pads = re.split(r'\s*\+\s*', raw)
    if all(re.fullmatch(_PAD, pad, re.I) for pad in pads):
        references = {pad.split('.', 1)[0].casefold() for pad in pads}
        if len(references) != 1:
            raise ValueError('A contact group must use pads on the same footprint.')
        return pads[0].split('.', 1)[0], pads
    if re.fullmatch(_REFERENCE, raw, re.I):
        return raw, []
    raise ValueError('Use a saved reference or a pad group, for example J1.1+J1.2.')


def load_units(raw):
    """Read one or more independently loaded footprint contacts."""
    before, *reuse = re.split(r'\s+and\s+same\s+pins\s+(?:for|on)\s+', raw, maxsplit=1, flags=re.I)
    result = []
    for unit in _UNIT_SPLIT.split(before.strip()):
        label, sep, demand = unit.partition('@')
        ref, pads = contact(label)
        current = None
        if sep:
            match = re.fullmatch(_AMP, demand.strip(), re.I)
            if not match:
                raise ValueError('Use an explicit load current, for example U1.1 @ 4 A.')
            current = _amps(match)
        result.append((ref, pads, current))
    if reuse:
        if not result[-1][1]:
            raise ValueError('List the pin numbers before asking for the same pins on other parts.')
        pins = [pad.split('.', 1)[1] for pad in result[-1][1]]
        for peer in _UNIT_SPLIT.split(reuse[0]):
            if not re.fullmatch(_REFERENCE, peer, re.I):
                raise ValueError('List saved footprint references after "same pins for".')
            result.append((peer, [peer + '.' + pin for pin in pins], None))
    if not 1 <= len(result) <= 32:
        raise ValueError('Choose one to 32 independently loaded pad groups.')
    return result


def format_units(units):
    return ' | '.join(('+'.join(pads) if pads else ref) + (f' @ {amps:.12g} A' if amps is not None else '')
                      for ref, pads, amps in units)


def endpoint_slots(text, *, reply=False):
    match = _REPLY.search(text.strip()) if reply else _FROM.search(text)
    if not match:
        return {}
    source = match['source'].strip()
    destinations = _TAIL.split(match['loads'], maxsplit=1)[0].rstrip(' ,.?!')
    try:
        source_ref, source_pads = contact(source)
        units = load_units(destinations)
    except ValueError:
        return {}
    return {'source_unit': '+'.join(source_pads) if source_pads else source_ref,
            'load_units': format_units(units)}


def wants_groups(text, inventory=None, net=None):
    endpoints = endpoint_slots(text)
    if not endpoints:
        matched = _FROM.search(text)
        if not matched:
            return False
        destinations = _TAIL.split(matched['loads'], maxsplit=1)[0]
        return (len(_UNIT_SPLIT.split(destinations)) > 1 or
                bool(re.search(r'\b(?:pads?|pins?)\b|\+', matched['source'] + ' ' + destinations, re.I)))
    units = load_units(endpoints['load_units'])
    source = contact(endpoints['source_unit'])
    if len(units) > 1 or len(source[1]) > 1 or len(units[0][1]) > 1:
        return True
    if inventory is None:
        return False
    net = net or named_net(text)
    nets = inventory.net_matches(net) if net else []
    return len(nets) == 1 and any(
        not pads and len(inventory.pads_for(ref, nets[0])) > 1
        for ref, pads in (source, (units[0][0], units[0][1]))
    )


def named_net(text):
    """Read the name before the source clause, e.g. 'PI on PWR from J1...'."""
    pattern = r'\bon\s+(?:the\s+)?(?:(?:net|rail)\s+)?(?:"([^"]+)"|\'([^\']+)\'|([^\s,;]+))(?=\s+from\b)'
    match = re.search(pattern, text, re.I)
    return next((value for value in match.groups() if value), None) if match else None


def slots(text):
    values = endpoint_slots(text)
    net = named_net(text)
    if net:
        values['net'] = net
    voltage = re.search(rf'\b(?:input\s+|source\s+|supply\s+)?voltage\s*(?:is\s+|[:=]\s*)?({_DECIMAL})\s*(?:V|volts?)\b', text, re.I)
    if voltage:
        values['voltage'] = float(voltage[1])
    units = load_units(values['load_units']) if 'load_units' in values else []
    common = re.search(rf'\b(?:each(?:\s+(?:of\s+(?:these|them|the\s+loads)))?(?:\s+(?:consuming|draws?|drawing|uses?|at))?|per\s+load(?:\s+at)?)\s+{_AMP}', text, re.I)
    if not common:
        common = re.search(rf'{_AMP}\s+(?:each|per\s+(?:load|part|component))\b', text, re.I)
    if common is None and len(units) == 1 and units[0][2] is None:
        common = re.search(rf'(?<![\w.]){_AMP}', text, re.I)
    if common is not None:
        # Typed planner reports nonfinite or nonpositive values as questions.
        values['current'] = float(common['amps']) * (.001 if common['unit'].casefold() == 'ma' else 1.)
    return values


def common_current_needed(values):
    return 'load_units' not in values or any(amps is None for _, _, amps in load_units(values['load_units']))


def resolve_contacts(params, inventory, assumptions):
    """Find saved contacts on the reviewed net, without implicitly grouping pads."""
    errors = {}
    net = params.get('net')
    source = contact(params['source_unit']) if 'source_unit' in params else None
    loads = load_units(params['load_units']) if 'load_units' in params else []
    if net is None and source and loads:
        candidates = [inventory.contact_nets(ref, pads) for ref, pads in
                      [source, *((ref, pads) for ref, pads, _ in loads)]]
        shared = set.intersection(*candidates)
        if len(shared) == 1:
            net = params['net'] = next(iter(shared))
            assumptions.append('Saved source and load contacts share ' + net + '.')
        elif len(shared) > 1:
            errors['net'] = (sorted(shared)[:40], 'These contacts share several nets. Choose the rail to analyze.')
    if net is None:
        return errors

    def resolve(ref, pads):
        candidates = inventory.pads_for(ref, net)
        if pads:
            exact = [inventory.pad_aliases.get(pad.casefold()) for pad in pads]
            if all(pad and pad in candidates for pad in exact):
                return exact, [], ''
            bad = ', '.join(raw for raw, actual in zip(pads, exact) if not actual or actual not in candidates)
            return None, candidates[:40], f'{bad} is missing, ambiguous or on a different net.'
        if len(candidates) == 1:
            return candidates, [], ''
        if not candidates:
            return None, [], f'{ref} has no unambiguous saved pads on this net.'
        return None, ['+'.join(candidates), *candidates[:39]], f'{ref} has {len(candidates)} same-net pads. Choose a pad or confirm a group.'

    if source:
        chosen, options, error = resolve(*source)
        if chosen:
            params['source_unit'] = '+'.join(chosen)
        else:
            errors['source_unit'] = options, error

    selected = []
    proposal = []
    issues = []
    for ref, pads, amps in loads:
        resolved, options, error = resolve(ref, pads)
        if resolved:
            selected.append((ref, resolved, amps))
            proposal.append((ref, resolved, amps))
        else:
            if options:
                proposal.append((ref, options[0].split('+'), amps))
            issues.append(error)
    if issues:
        options = [format_units(proposal)] if len(proposal) == len(loads) else []
        errors['load_units'] = options, ' '.join(issues) + ' Each footprint group draws its own assigned current.'
    elif loads:
        params['load_units'] = format_units(selected)
    return errors


def reply_slots(params, text):
    """Update only endpoints or explicit clarifications of this DC study."""
    endpoints = endpoint_slots(text, reply=True)
    if not endpoints:
        if re.fullmatch(r'\s*(?:use\s+)?(?:group\s+all(?:\s+same-net\s+(?:pins|pads))?|all\s+same-net\s+pads)\s*[.!]?\s*', text, re.I):
            return {'_confirm_groups': True}
        source = re.fullmatch(r'\s*(?:use\s+)?source(?:\s+contacts?)?\s+(.*?)\s*[.!]?\s*', text, re.I)
        if source:
            try:
                ref, pads = contact(source[1])
                return {'source_unit': '+'.join(pads) if pads else ref}
            except ValueError:
                return {}
        loads = re.fullmatch(r'\s*(?:use\s+)?(?:to|sinks?|loads?)\s+(.*?)\s*[.!]?\s*', text, re.I)
        if not loads:
            return {}
        try:
            endpoints['load_units'] = format_units(load_units(loads[1]))
        except ValueError:
            return {}
    original = load_units(params['load_units']) if 'load_units' in params else []
    supplied = load_units(endpoints['load_units'])
    by_ref = {unit[0].casefold(): unit for unit in supplied}
    # A reply can name one unresolved unit without dropping other loads or their
    # previously reviewed currents. Explicit duplicate references use the full list.
    if original and len(by_ref) == len(supplied) and len({u[0].casefold() for u in original}) == len(original):
        if not set(by_ref) <= {u[0].casefold() for u in original}:
            return {}
        merged = []
        for ref, pads, amps in original:
            edit = by_ref.get(ref.casefold())
            if edit:
                merged.append((edit[0], edit[1], amps if edit[2] is None else edit[2]))
            else:
                merged.append((ref, pads, amps))
        endpoints['load_units'] = format_units(merged)
    return endpoints


def bind(values):
    source = contact(values['source_unit'])[1]
    if not source:
        raise ValueError('Choose the exact source pads before running.')
    occupied = set()
    output = []
    loads = load_units(values['load_units'])
    for index, (ref, pads, amps) in enumerate([('', source, None), *loads]):
        if not pads:
            raise ValueError(f'Choose the exact pads for {ref} before running.')
        keys = {pad.casefold() for pad in pads}
        if len(keys) != len(pads) or occupied & keys:
            raise ValueError('A physical pad can appear only once across the source and load groups.')
        occupied.update(keys)
        if not index:
            continue
        amps = values.get('current') if amps is None else amps
        if amps is None:
            raise ValueError(f'Provide the current for {ref}. A total rail current cannot be duplicated across groups.')
        label = ref
        if sum(other.casefold() == ref.casefold() for other, _, _ in loads) > 1:
            label += ' (' + ', '.join(pad.split('.', 1)[1] for pad in pads) + ')'
        output.append(dict(id=f'load-{index}', label=label, terminals=pads, current_A=amps))
    return source, output
