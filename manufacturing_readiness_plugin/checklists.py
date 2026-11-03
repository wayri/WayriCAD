"""Portable, revision-bound manufacturing checklists and native rule previews.

Profiles contain published limits, never manufacturing defaults. Compiling a
profile returns text for review and never writes project rules or board files.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


PROFILE_SCHEMA = 'wayricad.vendor-profile/v1'
CHECKLIST_SCHEMA = 'wayricad.manufacturing-checklist/v1'
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
STATUSES = frozenset(('PASS', 'FAIL', 'UNKNOWN', 'N/A'))
NATIVE_CONSTRAINTS = frozenset(('track_width', 'clearance', 'hole_size',
                                'annular_width', 'edge_clearance'))
# An order option is the supplier's quote label, not a conversion to physical
# starting or finished foil. Compilation only matches explicit scope values.
COPPER_BASES = frozenset(('starting', 'finished', 'vendor_order_option'))
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _keys(value, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object.')
    if not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('Missing or unsupported fields: ' + ', '.join(sorted(value.keys() ^ set(required))))


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or len(value) > 16384 or (not empty and not value.strip()):
        raise ValueError('Invalid ' + label + '.')
    if any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise ValueError('Control characters in ' + label + '.')
    return value


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Invalid identifier.')
    return value


def _number(value, label, *, positive=False):
    try:
        finite = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError('Expected finite number: ' + label)
    if value < 0 or (positive and value == 0):
        raise ValueError('Expected positive/nonnegative number: ' + label)
    return value


def _json_value(value, depth=0):
    if depth > 8:
        raise ValueError('JSON nesting is too deep.')
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _text(value, 'JSON string', empty=True)
    elif isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError('Nonfinite JSON number.')
    elif isinstance(value, list) and len(value) <= 10000:
        for item in value:
            _json_value(item, depth + 1)
    elif isinstance(value, dict) and len(value) <= 10000:
        for key, item in value.items():
            _text(key, 'JSON key')
            _json_value(item, depth + 1)
    else:
        raise ValueError('Unsupported JSON value or collection size.')


def _day(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Invalid date: ' + label)
    date.fromisoformat(value)


def _digest(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError('Expected lowercase SHA-256 digest.')


def profile_digest(profile):
    return hashlib.sha256(json.dumps(validate_profile(profile), sort_keys=True,
                                    ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def canonical_context(context):
    """Give equivalent process numbers one identity without guessing values.

    The GUI reads continuous quantities as floats and layer counts as ints.
    Partial contexts and explicit unknowns remain partial/unknown; this helper
    does not establish compatibility with a vendor profile. Other keys and
    strings are retained exactly. Profile and design-file bytes are untouched.
    """
    if not isinstance(context, dict):
        raise ValueError('Process context must be an object.')
    result = deepcopy(context)
    for key in ('copper_oz', 'inner_copper_oz', 'thickness_mm'):
        value = result.get(key)
        if key in result and value is not None:
            _number(value, 'selected ' + key, positive=True)
            result[key] = float(value)
    if 'layers' in result and result['layers'] is not None:
        value = _number(result['layers'], 'selected layer count', positive=True)
        if int(value) != value:
            raise ValueError('Selected layer count must be an integer.')
        result['layers'] = int(value)
    _json_value(result)
    return result


def validate_profile(profile):
    """Validate a portable profile; unknown limits must remain explicit nulls."""
    _keys(profile, ('schema', 'id', 'name', 'vendor', 'service', 'revision', 'process', 'sources', 'rules'), ('notes',))
    if profile['schema'] != PROFILE_SCHEMA:
        raise ValueError('Unsupported vendor-profile schema.')
    _identifier(profile['id'])
    for field in ('name', 'vendor', 'service', 'revision'):
        _text(profile[field], field)
    if 'notes' in profile:
        _text(profile['notes'], 'profile notes', empty=True)
    process = profile['process']
    _keys(process, ('board_type', 'copper_oz', 'layers'),
          ('notes', 'material', 'thickness_mm', 'finish', 'copper_basis', 'inner_copper_oz'))
    if process['board_type'] is not None:
        _text(process['board_type'], 'board type')
    if process.get('material') is not None:
        _text(process['material'], 'material')
    if 'copper_basis' in process and (not isinstance(process['copper_basis'], str) or process['copper_basis'] not in COPPER_BASES):
        raise ValueError('Unsupported copper basis; do not infer starting/finished copper from an order option.')
    for key in ('copper_oz', 'layers', 'thickness_mm', 'inner_copper_oz'):
        values = process.get(key)
        if values is not None:
            if not isinstance(values, list) or not values or len(values) > 256:
                raise ValueError('Invalid process scope: ' + key)
            for value in values:
                _number(value, key, positive=True)
                if key == 'layers' and int(value) != value:
                    raise ValueError('Layer counts must be integers.')
            if len(values) != len(set(values)):
                raise ValueError('Duplicate process values.')
    finishes = process.get('finish')
    if finishes is not None:
        if not isinstance(finishes, list) or not finishes or len(finishes) > 256:
            raise ValueError('Invalid process scope: finish')
        for finish in finishes:
            _text(finish, 'finish')
        if len(finishes) != len(set(finishes)):
            raise ValueError('Duplicate process finish.')
    if 'notes' in process:
        _text(process['notes'], 'process notes', empty=True)
    if not isinstance(profile['sources'], list) or len(profile['sources']) > 256:
        raise ValueError('Invalid source list.')
    source_ids = set()
    for source in profile['sources']:
        _keys(source, ('id', 'url', 'retrieved', 'verified', 'title'))
        identifier = _identifier(source['id'])
        if identifier in source_ids:
            raise ValueError('Duplicate source identifier.')
        source_ids.add(identifier)
        url = urlsplit(_text(source['url'], 'source URL'))
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Source URL must be an HTTPS public reference.')
        _text(source['title'], 'source title')
        _day(source['retrieved'], 'retrieved')
        if source['verified'] is not None:
            _day(source['verified'], 'verified')
    if not isinstance(profile['rules'], list) or len(profile['rules']) > 10000:
        raise ValueError('Invalid rules list.')
    rule_ids = set()
    for rule in profile['rules']:
        _keys(rule, ('id', 'title', 'category', 'backend', 'constraint', 'unit', 'minimum', 'maximum', 'source_ids'),
              ('applicability', 'severity', 'notes'))
        identifier = _identifier(rule['id'])
        if identifier in rule_ids:
            raise ValueError('Duplicate rule identifier.')
        rule_ids.add(identifier)
        _text(rule['title'], 'rule title')
        if rule['category'] not in ('DRC', 'DFM', 'DFA') or rule['backend'] not in ('native_drc', 'custom', 'manual'):
            raise ValueError('Unsupported rule category/backend.')
        if rule.get('severity', 'error') not in ('error', 'warning'):
            raise ValueError('Invalid severity.')
        if rule['constraint'] is not None:
            _identifier(rule['constraint'])
        if rule['unit'] not in (None, 'mm', 'ohm', 'ratio', 'count', 'degree', 'percent'):
            raise ValueError('Unsupported unit.')
        limits = [rule[key] for key in ('minimum', 'maximum') if rule[key] is not None]
        for value in limits:
            _number(value, 'rule limit')
        if len(limits) == 2 and rule['minimum'] > rule['maximum']:
            raise ValueError('Minimum exceeds maximum.')
        refs = rule['source_ids']
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError('Invalid rule sources.')
        if len(refs) != len(set(refs)) or any(ref not in source_ids for ref in refs):
            raise ValueError('Unknown/duplicate rule source.')
        if limits and (not refs or rule['unit'] is None):
            raise ValueError('Numeric vendor limits need sources and units.')
        if rule['backend'] == 'native_drc':
            if rule['constraint'] not in NATIVE_CONSTRAINTS or rule['unit'] != 'mm' or not limits:
                raise ValueError('Unsupported native DRC constraint or units.')
        applicability = rule.get('applicability', {})
        if not isinstance(applicability, dict):
            raise ValueError('Applicability must be an object.')
        _json_value(applicability)
        if 'notes' in rule:
            _text(rule['notes'], 'rule notes', empty=True)
    return deepcopy(profile)


def new_checklist(profile, selected_context=None):
    profile = validate_profile(profile)
    document = dict(schema=CHECKLIST_SCHEMA, profile=profile,
                    entries=[dict(rule_id=rule['id'], manual_evidence=[], waiver=None) for rule in profile['rules']], run=None)
    if selected_context is not None:
        document['selected_context'] = deepcopy(selected_context)
    return validate_checklist(document)


def validate_checklist(document):
    _keys(document, ('schema', 'profile', 'entries', 'run'), ('selected_context',))
    if document['schema'] != CHECKLIST_SCHEMA:
        raise ValueError('Unsupported checklist schema.')
    profile = validate_profile(document['profile'])
    if 'selected_context' in document:
        compile_native_rules(profile, document['selected_context'])
    rule_ids = {rule['id'] for rule in profile['rules']}
    if not isinstance(document['entries'], list) or len(document['entries']) != len(rule_ids):
        raise ValueError('Checklist must retain one entry per rule.')
    seen = set()
    for entry in document['entries']:
        _keys(entry, ('rule_id', 'manual_evidence', 'waiver'))
        if not isinstance(entry['rule_id'], str) or entry['rule_id'] not in rule_ids or entry['rule_id'] in seen:
            raise ValueError('Invalid/duplicate checklist rule.')
        seen.add(entry['rule_id'])
        if not isinstance(entry['manual_evidence'], list) or len(entry['manual_evidence']) > 1000:
            raise ValueError('Invalid manual evidence.')
        for evidence in entry['manual_evidence']:
            _keys(evidence, ('detail', 'recorded_at', 'source_sha256', 'profile_sha256'), ('uri', 'sha256', 'author', 'context_sha256'))
            _text(evidence['detail'], 'evidence detail')
            _text(evidence['recorded_at'], 'evidence date')
            _digest(evidence['source_sha256'])
            _digest(evidence['profile_sha256'])
            if 'context_sha256' in evidence:
                _digest(evidence['context_sha256'])
            for key in ('uri', 'author'):
                if key in evidence:
                    _text(evidence[key], key)
            if 'sha256' in evidence:
                _digest(evidence['sha256'])
        waiver = entry['waiver']
        if waiver is not None:
            _keys(waiver, ('reason', 'author', 'recorded_at', 'source_sha256', 'profile_sha256'), ('context_sha256',))
            for key in ('reason', 'author', 'recorded_at'):
                _text(waiver[key], 'waiver ' + key)
            _digest(waiver['source_sha256'])
            _digest(waiver['profile_sha256'])
            if 'context_sha256' in waiver:
                _digest(waiver['context_sha256'])
    run = document['run']
    if run is not None:
        _keys(run, ('source_sha256', 'profile_sha256', 'created_at', 'results'), ('context_sha256',))
        _digest(run['source_sha256']); _digest(run['profile_sha256'])
        if 'context_sha256' in run:
            _digest(run['context_sha256'])
        _text(run['created_at'], 'run date')
        if not isinstance(run['results'], list) or len(run['results']) > len(rule_ids):
            raise ValueError('Invalid run results.')
        seen = set()
        for result in run['results']:
            _keys(result, ('rule_id', 'status', 'message'), ('actual', 'object_ids', 'positions_mm'))
            if not isinstance(result['rule_id'], str) or not isinstance(result['status'], str) or \
                    result['rule_id'] not in rule_ids or result['rule_id'] in seen or result['status'] not in STATUSES:
                raise ValueError('Unknown/duplicate rule or invalid result status.')
            seen.add(result['rule_id'])
            _text(result['message'], 'result message', empty=True)
            if 'object_ids' in result and (not isinstance(result['object_ids'], list) or
                    any(not isinstance(value, str) or not value for value in result['object_ids'])):
                raise ValueError('Invalid object identities.')
            _json_value(result)
    _json_value(document)
    return deepcopy(document)


def record_run(document, source_sha256, results, *, created_at=None):
    document = validate_checklist(document)
    _digest(source_sha256)
    document['run'] = dict(source_sha256=source_sha256, profile_sha256=profile_digest(document['profile']),
                           created_at=created_at or datetime.now(timezone.utc).isoformat(), results=deepcopy(results))
    if 'selected_context' in document:
        document['run']['context_sha256'] = _context_digest(document)
    return validate_checklist(document)


def _context_digest(document):
    if 'selected_context' not in document:
        return None
    return hashlib.sha256(json.dumps(canonical_context(document['selected_context']), sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def add_manual_evidence(document, rule_id, source_sha256, detail, *, author=None, uri=None, sha256=None):
    document = validate_checklist(document)
    _digest(source_sha256)
    entry = next((row for row in document['entries'] if row['rule_id'] == rule_id), None)
    if entry is None:
        raise ValueError('Unknown checklist rule.')
    evidence = dict(detail=detail, recorded_at=datetime.now(timezone.utc).isoformat(),
                    source_sha256=source_sha256, profile_sha256=profile_digest(document['profile']))
    if 'selected_context' in document:
        evidence['context_sha256'] = _context_digest(document)
    for key, value in (('author', author), ('uri', uri), ('sha256', sha256)):
        if value is not None:
            evidence[key] = value
    entry['manual_evidence'].append(evidence)
    return validate_checklist(document)


def set_waiver(document, rule_id, source_sha256, reason, author):
    document = validate_checklist(document)
    _digest(source_sha256)
    entry = next((row for row in document['entries'] if row['rule_id'] == rule_id), None)
    if entry is None:
        raise ValueError('Unknown checklist rule.')
    entry['waiver'] = dict(reason=reason, author=author, recorded_at=datetime.now(timezone.utc).isoformat(),
                           source_sha256=source_sha256, profile_sha256=profile_digest(document['profile']))
    if 'selected_context' in document:
        entry['waiver']['context_sha256'] = _context_digest(document)
    return validate_checklist(document)


def checklist_state(document, source_sha256):
    """Derived display state: stale and waived checks never become a PASS."""
    document = validate_checklist(document)
    _digest(source_sha256)
    run = document['run']
    digest = profile_digest(document['profile'])
    context_digest = _context_digest(document)
    stale = run is None or run['source_sha256'] != source_sha256 or run['profile_sha256'] != digest or run.get('context_sha256') != context_digest
    results = {row['rule_id']: row for row in run['results']} if run else {}
    entries = {row['rule_id']: row for row in document['entries']}
    rows = []
    for rule in document['profile']['rules']:
        entry = entries[rule['id']]
        row = deepcopy(results.get(rule['id'], dict(rule_id=rule['id'], status='UNKNOWN', message='Not checked.')))
        row['recorded_status'] = row['status']
        if stale:
            row['status'] = 'UNKNOWN'
            row['message'] = 'Stale or missing run; rerun this check.'
        elif rule['backend'] == 'manual' and row['status'] == 'PASS' and not any(
                value['source_sha256'] == source_sha256 and value['profile_sha256'] == digest and
                value.get('context_sha256') == context_digest for value in entry['manual_evidence']):
            row['status'] = 'UNKNOWN'
            row['message'] = 'Manual check needs evidence for this source and profile.'
        row['stale'] = stale
        row['waiver'] = deepcopy(entry['waiver'])
        row['waiver_current'] = bool(entry['waiver'] and entry['waiver']['source_sha256'] == source_sha256 and
                                     entry['waiver']['profile_sha256'] == digest and
                                     entry['waiver'].get('context_sha256') == context_digest and not stale)
        row['manual_evidence'] = deepcopy(entry['manual_evidence'])
        rows.append(row)
    return dict(stale=stale, results=rows,
                passed=bool(rows) and not stale and all(row['status'] in ('PASS', 'N/A') and not row['waiver_current'] for row in rows))


def compile_native_rules(profile, context):
    """Return a reviewable .kicad_dru preview scoped to an exact selected process.

    Rules with additional applicability remain omitted with a reason: this
    compiler does not silently translate arbitrary conditions to global rules.
    """
    profile = validate_profile(profile)
    _keys(context, ('board_type', 'copper_oz', 'layers'),
          ('material', 'thickness_mm', 'finish', 'copper_basis', 'inner_copper_oz'))
    _text(context['board_type'], 'selected board type')
    _number(context['copper_oz'], 'selected copper weight', positive=True)
    _number(context['layers'], 'selected layer count', positive=True)
    if int(context['layers']) != context['layers']:
        raise ValueError('Selected layer count must be an integer.')
    if 'material' in context:
        _text(context['material'], 'selected material')
    if 'thickness_mm' in context:
        _number(context['thickness_mm'], 'selected board thickness', positive=True)
    if 'finish' in context:
        _text(context['finish'], 'selected finish')
    if 'copper_basis' in context and (not isinstance(context['copper_basis'], str) or context['copper_basis'] not in COPPER_BASES):
        raise ValueError('Choose an explicit starting, finished or vendor_order_option copper basis.')
    if 'inner_copper_oz' in context:
        _number(context['inner_copper_oz'], 'selected inner copper weight', positive=True)
    for field, supported in profile['process'].items():
        if field == 'notes':
            continue
        value = context.get(field)
        if supported is None or value is None or (value not in supported if isinstance(supported, list) else value != supported):
            raise ValueError('Unknown or incompatible process scope: ' + field)
    lines = ['(version 1)', '# Vendor profile ' + profile['id'] + ' revision ' + profile['revision'].replace('\n', ' ')]
    compiled, omitted = [], []
    compiled_constraints = {}
    sources = {source['id']: source for source in profile['sources']}
    for rule in profile['rules']:
        reason = None
        if rule['backend'] != 'native_drc':
            reason = 'Separate ' + rule['backend'] + ' backend required.'
        elif rule.get('applicability'):
            reason = 'Additional applicability needs its own scoped check.'
        elif any(sources[key]['verified'] is None for key in rule['source_ids']):
            reason = 'Published source has not been verified.'
        if reason:
            omitted.append(dict(rule_id=rule['id'], reason=reason))
            continue
        constraint = rule['constraint']
        if constraint in compiled_constraints:
            raise ValueError('Native rules ' + compiled_constraints[constraint] + ' and ' + rule['id'] +
                             ' both define unconditional ' + constraint + '. KiCad uses the last matching constraint; '
                             'combine the limits into one rule before compiling.')
        compiled_constraints[constraint] = rule['id']
        name = json.dumps(profile['id'] + ':' + rule['id'], ensure_ascii=False)
        terms = ' '.join('(' + label + ' ' + format(rule[key], '.12g') + 'mm)' for key, label in
                         (('minimum', 'min'), ('maximum', 'max')) if rule[key] is not None)
        severity = rule.get('severity', 'error')
        lines.append(f'(rule {name} (severity {severity}) (constraint {rule["constraint"]} {terms}))')
        compiled.append(rule['id'])
    return dict(text='\n'.join(lines) + '\n', compiled_rule_ids=compiled, omitted=omitted,
                profile_sha256=profile_digest(profile), context=deepcopy(context))


def _reject_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def _load(path, validator):
    with Path(path).open('rb') as stream:
        payload = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the size limit.')
    try:
        value = json.loads(payload.decode('utf-8-sig'), object_pairs_hook=_reject_duplicates,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number: ' + value)))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Malformed checklist/profile JSON.') from exc
    return validator(value)


def _save(path, document, validator):
    value = validator(document)
    payload = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the size limit.')
    destination = Path(path)
    if destination.suffix.lower() != '.json':
        raise ValueError('Use a separate .json checklist/profile destination.')
    descriptor, temporary = tempfile.mkstemp(prefix='.wayricad-checklist-', suffix='.json', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_profile(path):
    return _load(path, validate_profile)


def save_profile(path, profile):
    _save(path, profile, validate_profile)


def load_checklist(path):
    return _load(path, validate_checklist)


def save_checklist(path, document):
    _save(path, document, validate_checklist)
