"""Local design guidance grounded in saved-board net and pad identities."""
import re


_QUESTION = re.compile(r'^\s*(?:what|which|where|why|how|should|can|explain|recommend|suggest|show\s+(?:me\s+)?(?:the\s+)?(?:pins|pads|parts|net context))\b', re.I)
_EXECUTE = re.compile(r'^\s*(?:(?:can|could|would)\s+you\s+|please\s+)?(?:run|simulate|calculate|measure|check|extract|analy[sz]e)\b', re.I)
_PIN_QUESTION = re.compile(r'\b(?:pins?|pads?|connect(?:ed|ions?|s)?|net context|nets|components?|parts?)\b', re.I)
_REFERENCE = re.compile(r'(?<![\w.])([A-Z]+[A-Z0-9_-]*\d)(?![\w.])', re.I)


def context_net(text, inventory, selected_nets=(), active_net=None):
    """Resolve uniquely named PCB nets. Use selection or the reviewed plan only with context."""
    if inventory is None:
        return None
    names = re.findall(r'"([^"]+)"|([\w/+.&$#:-]+)', text)
    matches = {net for quoted, token in names
               for net in (inventory.net_matches(quoted or token) or
                           (inventory.net_matches(token.rstrip('.:')) if token else []))}
    if len(matches) == 1:
        return next(iter(matches))
    if matches:
        return None
    if active_net and re.search(r'\b(?:this|that|current|same)\b', text, re.I):
        if active_net in inventory.nets:
            return active_net
    if len(selected_nets) == 1 and selected_nets[0] in inventory.nets:
        return selected_nets[0]
    return None


def completions(inventory, fragment, net=None):
    """Rank pads attached to the named rail first while keeping ordinary name completion."""
    if not net or not fragment:
        return inventory.suggestions(fragment)
    candidates = inventory.suggestions(fragment, limit=32)
    relevant_refs = {pad.rsplit('.', 1)[0] for pad, nets in inventory.pads.items() if net in nets}
    def matches(row):
        kind, name, _ = row
        if kind == 'Pad':
            return net in inventory.pads[name]
        if kind == 'Part':
            return name in relevant_refs
        return name == net
    return sorted(candidates, key=lambda row: not matches(row))[:8]


def _pin_context(text, inventory, net):
    relevant = {}
    for pad, nets in inventory.pads.items():
        if net in nets:
            ref = pad.rsplit('.', 1)[0]
            relevant.setdefault(ref, []).append(pad)
    references = {match.group(1).casefold() for match in _REFERENCE.finditer(text)}
    chosen = [ref for ref in sorted(relevant) if ref.casefold() in references]
    ordered = chosen or sorted(relevant)
    lines = [f'{net} · {sum(map(len, relevant.values()))} saved pad identifiers on {len(relevant)} parts.']
    if references and not chosen:
        known = references.intersection(inventory.ref_aliases)
        if known:
            refs = ', '.join(sorted(inventory.ref_aliases[ref] for ref in known))
            lines.append(f'Saved parts with no matching pad on this net: {refs}.')
    for ref in ordered[:8]:
        pads = sorted(relevant[ref])
        values = ', '.join(pads[:12])
        remaining = f' and {len(pads)-12} more' if len(pads) > 12 else ''
        part = inventory.parts.get(ref, '').strip()[:60]
        group = ' · possible pad group' if len(pads) > 1 else ''
        lines.append(f'{ref}' + (f' ({part})' if part else '') + f' · {values}{remaining}{group}')
    if len(ordered) > 8:
        lines.append('Name a reference to narrow the list.')
    return lines


def _component_nets(text, inventory):
    if inventory is None:
        return []
    aliases = (match.group(1).casefold() for match in _REFERENCE.finditer(text))
    refs = list(dict.fromkeys(inventory.ref_aliases[alias] for alias in aliases if alias in inventory.ref_aliases))[:8]
    if not refs:
        return []
    by_ref = {ref: set() for ref in refs}
    for pad, nets in inventory.pads.items():
        ref = pad.rsplit('.', 1)[0]
        if ref in by_ref:
            by_ref[ref].update(nets)
    lines = []
    if len(refs) > 1:
        shared = sorted(set.intersection(*by_ref.values()))
        shown = ', '.join(shared[:8])
        lines.append('Shared saved nets · ' + (shown or 'None found') + (f' and {len(shared)-8} more' if len(shared) > 8 else ''))
    for ref, nets in by_ref.items():
        shown = ', '.join(sorted(nets)[:8])
        lines.append(f'{ref} · {shown or "No net-assigned pads"}' + (f' and {len(nets)-8} more' if len(nets) > 8 else ''))
    return lines


_GUIDES = (
    (r'\b(?:decoupl\w*|bypass|shunt cap\w*)\b', 'Decoupling',
     'Compare the capacitor at the same load port, including its effective capacitance, ESR, ESL and supply/return mounting path. For a load-step study, enter those circuit values and the current edge. Use half-step results to check time resolution.'),
    (r'\b(?:quick\s*si|signal integrity|crosstalk|diff(?:erential)? pairs?|impedance|return via)\b', 'Quick SI',
     'Start with exact driver and receiver pads and the reference copper on each section. Check from pad to pad for layer transitions, plane gaps and return stitching. State the rise time and termination before interpreting an eye estimate.'),
    (r'\b(?:thermal|therm|cooling|hotspots?)\b', 'QuickTherm',
     'Assign actual heat dissipated to each part. Include the board stackup, ambient and heat-transfer boundaries. Add thermal mass and a time profile for a transient study.'),
    (r'\b(?:emerge|antenna|radiation|waveguide)\b', 'Quick EMerge',
     'Preview the antenna or saved PCB rule area. Check each feed, its return conductor, material and air boundary. Review network and radiation results across mesh and boundary refinements.'),
    (r'\b(?:quick\s*pi|power integrity|voltage drop|rail|load step|current|power bus|sink|return path)\b', 'Quick PI',
     'Start with the supply rail, physical source pads, separate load groups and total demand for each load. Group same-net pins only when they represent one electrical endpoint. Include explicit ground-return contacts when you need the delivered loop voltage.'),
)


def guidance(text, inventory=None, *, selected_nets=(), active_net=None):
    """Return bounded study guidance for design questions, or defer to the tool planner."""
    if not _QUESTION.search(text) or _EXECUTE.search(text):
        return None
    net = context_net(text, inventory, selected_nets, active_net)
    pin_question = bool(_PIN_QUESTION.search(text))
    topics = [(title, explanation) for pattern, title, explanation in _GUIDES if re.search(pattern, text, re.I)]
    if not topics and not pin_question and not (net and re.search(r'\bnet\b', text, re.I)):
        return None
    lines = []
    if net:
        lines.extend(_pin_context(text, inventory, net))
        if pin_question:
            lines.append('Saved connectivity can identify candidates. Confirm which pads source and consume current before running a study.')
    elif pin_question:
        lines.extend(_component_nets(text, inventory))
        if lines:
            lines.append('Choose a net from this list to see its saved pads and possible groups.')
        else:
            lines.append('Choose the saved PCB and name one exact net or select it in PCB Editor to see the connected parts and pins.')
    if topics and lines:
        lines.append('')
    for title, explanation in topics[:2]:
        lines.append(f'{title} · {explanation}')
    return '\n'.join(lines)
