"""Bounded endpoint-partition comparison, not Gerber geometry reconstruction.

Adapters: load_netlist(path) -> JSON-safe loaded model; compare_netlists(a, b,
confirm_independent_cam=False) accepts those models or file paths. No writes,
network, native bindings or dependencies. Unreadable/oversized files, malformed
JSON, duplicate JSON keys and unsupported JSON schemas raise ValueError/OSError.
Recoverable IPC/terminal defects produce complete=False and structured issues.

Normalized CAM input (UTF-8 JSON, exact case-sensitive endpoint identities)::

    {"schema":"wayricad.fab-netlist/v1", "units":"mm",
     "terminals":[{"reference":"U1","pin":"1","net":"GND",
                   "x_mm":1.0,"y_mm":2.0}],
     "provenance":{"origin":"cam","producer":"Reviewed CAM extractor"}}

Only schema/units/terminals/provenance are accepted at the top level. Terminal
keys are reference/pin/net and optional x_mm/y_mm (both or neither). net must
be a nonempty string or null; null and reserved "N/C" mean separate isolated
terminals, NEVER one shared disconnected net. Names are labels of partitions,
not cross-file correspondence. Coordinates are validated but never used to
guess endpoint identity. Provenance is bounded inert JSON, not authentication.

Loaded schema: wayricad.fab-netlist-loaded/v1; source={sha256,bytes,format,units},
provenance, terminals, issues, coverage, complete, model_sha256. Terminals carry
reference/pin/net/net_name/x_mm/y_mm/line. model_sha256 detects accidental edits
to a loaded model; it is not an authenticity signature. Reload changed sources.

Output schema: wayricad.fab-compare/v1; created_utc, units, sources, provenance,
status, summary, shorts, opens, coverage, issues, independence, limits.
shorts[*]={observed_net,design_nets,design_groups,endpoints};
opens[*]={design_net,observed_nets,observed_groups,endpoints}. Group entries
retain every original display name and exact endpoint, without pin-pair cliques.
FAIL takes precedence for proven shared-endpoint shorts/opens. Otherwise defects,
missing/extra endpoints, absent independence confirmation or identical source/
normalized content yield UNKNOWN. Only complete, independently confirmed input
partitions can MATCH. MATCH is NOT fabrication verification or release approval.

IPC subset: fixed-column 317/327/367, ASCII CODE 00, UNITS CUST 0 (0.00254 mm),
optional JOB/VER/IMAGE PRIMARY/arrayDim N and fixed-column NNAME aliases.
Other units/records/transforms are UNKNOWN, not silently inferred. 367 is
mechanical. Unidentified via/midpoint records are counted but cannot establish
component-pin coverage. Full-width ref/pin fields and unaliased 14-char net
IDs may have been truncated; those identities are excluded from proofs.
NNAME source names filling 58 columns may still be truncated (reported).

Primary layout/unit references, checked alongside an installed KiCad 10.0.6
native PIC-programmer export (compact 73-column records):
https://docs.kicad.org/doxygen/export__d356_8cpp_source.html
https://github.com/KiCad/kicad-source-mirror/blob/10.0/pcbnew/exporters/export_d356.cpp
See write_D356_records, iu_to_d356, and writer headers. This is a conservative
subset parser, not certification against the complete proprietary IPC standard.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

INPUT_SCHEMA = 'wayricad.fab-netlist/v1'
LOADED_SCHEMA = 'wayricad.fab-netlist-loaded/v1'
REPORT_SCHEMA = 'wayricad.fab-compare/v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 100000
MAX_LINES = 200000
MAX_NODES = 2000000
MAX_ISSUES = 200
MAX_COORD_MM = 1000000
LIMITS = [
    'Exact case-sensitive (reference,pin) partition comparison; no name-only or coordinate matching.',
    'No Gerber reconstruction, manufacturing geometry check, impedance check or fabrication approval.',
    'IPC subset 317/327/367, CODE 00, CUST 0 only; aliases do not recover already truncated source names.',
    'Ambiguous/conflicting endpoints are excluded; missing/extra pins and incomplete input block MATCH.',
    'Ignored vias/mechanical features are not proof of component-pin or full copper coverage.',
    'CAM independence is an explicit reviewer confirmation, not authenticated by a filename or producer claim.',
    'MATCH means matching supplied partitions only, never fab verified.',
]


def _digest(value):
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
    for piece in encoder.iterencode(value):
        digest.update(piece.encode('ascii'))
    return digest.hexdigest()


def _text(value, name, maximum=128, identity=False):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or value != value.strip() or not value.isprintable()
            or identity and any(ch.isspace() for ch in value)):
        raise ValueError(f'{name} must be bounded printable text without ambiguous whitespace.')
    return value


def _coordinate(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or abs(value) > MAX_COORD_MM or not math.isfinite(value)):
        raise ValueError('Coordinates must be finite millimetres within the supported bound.')
    return float(value)


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('Non-finite JSON number: ' + value)

    try:
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid bounded UTF-8 netlist JSON.') from exc
    _tree(value, MAX_NODES)
    return value


def _tree(value, maximum=MAX_NODES):
    count = 0
    stack = [(iter((value,)), 0)]
    while stack:
        iterator, depth = stack[-1]
        try:
            item = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        count += 1 + (len(item) if isinstance(item, dict) else 0)
        if count > maximum or depth > 16:
            raise ValueError('Netlist JSON exceeds aggregate node/depth bounds.')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('Non-finite JSON number.')
        if isinstance(item, str) and len(item) > 4096:
            raise ValueError('Netlist JSON string exceeds its bound.')
        if isinstance(item, dict):
            stack.append((iter(item.values()), depth + 1))
        elif isinstance(item, list):
            stack.append((iter(item), depth + 1))


def _base(data, fmt):
    return dict(schema=LOADED_SCHEMA,
                source=dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), format=fmt, units=None),
                provenance={}, terminals=[], issues=[], complete=True,
                coverage=dict(records=0, accepted_terminals=0, ignored_vias=0,
                              ignored_mechanical=0, ignored_unidentified=0,
                              unsupported_records=0, invalid_records=0,
                              ambiguous_records=0, duplicate_records=0, issue_count=0))


def _issue(model, code, message, line=None):
    model['complete'] = False
    model['coverage']['issue_count'] += 1
    if len(model['issues']) < MAX_ISSUES:
        model['issues'].append(dict(code=code, message=message, line=line))


def _finish(model):
    # Remove every occurrence of duplicate/conflicting endpoint identities.
    indexed = {}
    blocked = set()
    for terminal in model['terminals']:
        key = (terminal['reference'], terminal['pin'])
        if key in indexed or key in blocked:
            previous = indexed.pop(key, None)
            code = 'conflicting_assignment' if previous and previous['net'] != terminal['net'] else 'duplicate_endpoint'
            _issue(model, code, 'Duplicate/conflicting component-pin identity; all occurrences excluded.', terminal['line'])
            model['coverage']['duplicate_records'] += 1
            blocked.add(key)
        else:
            indexed[key] = terminal
    model['terminals'] = sorted(indexed.values(), key=lambda t: (t['reference'], t['pin']))
    model['coverage']['accepted_terminals'] = len(model['terminals'])
    if not model['terminals']:
        _issue(model, 'empty_terminals', 'No unambiguous component-pin terminals were parsed.')
    model['model_sha256'] = _digest(model)
    return model


def _normalized(data):
    value = _json(data)
    if (not isinstance(value, dict) or set(value) - {'schema', 'units', 'terminals', 'provenance'}
            or value.get('schema') != INPUT_SCHEMA or value.get('units') != 'mm'):
        raise ValueError('Expected wayricad.fab-netlist/v1 with units mm and supported fields.')
    records = value.get('terminals')
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError('terminals must be an array of at most 100000 records.')
    provenance = value.get('provenance', {})
    if not isinstance(provenance, dict):
        raise ValueError('provenance must be an inert JSON object.')
    _tree(provenance, 10000)
    model = _base(data, INPUT_SCHEMA)
    model['source']['units'] = 'mm'
    model['provenance'] = provenance
    for number, record in enumerate(records, 1):
        model['coverage']['records'] += 1
        try:
            if (not isinstance(record, dict) or set(record) - {'reference', 'pin', 'net', 'x_mm', 'y_mm'}
                    or not {'reference', 'pin', 'net'}.issubset(record)):
                raise ValueError('Terminal has unsupported or missing fields.')
            reference = _text(record['reference'], 'reference', identity=True)
            pin = _text(record['pin'], 'pin', identity=True)
            net = record['net']
            if net is not None:
                net = _text(net, 'net', 1024)
            if net == 'N/C':
                net = None
            if ('x_mm' in record) != ('y_mm' in record):
                raise ValueError('Coordinates must be supplied as a pair.')
            x = _coordinate(record['x_mm']) if 'x_mm' in record else None
            y = _coordinate(record['y_mm']) if 'y_mm' in record else None
            model['terminals'].append(dict(reference=reference, pin=pin, net=net,
                net_name=net if net is not None else 'N/C', x_mm=x, y_mm=y, line=number))
        except ValueError as exc:
            model['coverage']['invalid_records'] += 1
            _issue(model, 'invalid_terminal', str(exc), number)
    return _finish(model)


def _ipc(data):
    if any(byte < 32 and byte not in (10, 13) for byte in data):
        raise ValueError('IPC input contains unsupported ASCII control characters.')
    try:
        text = data.decode('ascii')
    except UnicodeError as exc:
        raise ValueError('IPC CODE 00 requires ASCII input.') from exc
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError('IPC netlist exceeds 200000 lines.')
    model = _base(data, 'ipc-d-356')
    parameters, aliases, raw = {}, {}, []
    invalid_aliases = set()
    ended = False
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if len(line) > 256 or any(ord(ch) < 32 or ord(ch) > 126 for ch in line):
            model['coverage']['invalid_records'] += 1
            _issue(model, 'invalid_line', 'IPC line contains controls or exceeds 256 columns.', number)
            continue
        if line.startswith('C'):
            continue
        if ended:
            _issue(model, 'data_after_end', 'Unexpected data after IPC end record.', number)
            continue
        if line.rstrip() == '999':
            ended = True
            continue
        if line.startswith('P  '):
            if line.startswith('P  NNAME'):
                if len(line) > 80 or len(line) < 15 or line[13] != ' ' or line[72:].strip():
                    _issue(model, 'invalid_alias', 'Malformed fixed-column NNAME alias.', number)
                    continue
                alias, name = line[8:13].rstrip(), line[14:72].rstrip()
                try:
                    _text(alias, 'NNAME alias', 5, True)
                    _text(name, 'NNAME source name', 58)
                except ValueError as exc:
                    _issue(model, 'invalid_alias', str(exc), number)
                    continue
                if alias in aliases:
                    invalid_aliases.add(alias)
                    _issue(model, 'duplicate_alias', 'Repeated NNAME alias is ambiguous.', number)
                aliases[alias] = name
                if len(name) == 58 or '?' in name:
                    _issue(model, 'truncated_net_name', 'NNAME display name may be truncated/sanitized; full original name unavailable.', number)
                continue
            parts = line[3:].split(None, 1)
            key, value = parts[0].upper() if parts else '', parts[1].strip() if len(parts) == 2 else ''
            if key in parameters:
                _issue(model, 'duplicate_parameter', 'Repeated IPC parameter: ' + key, number)
                if parameters[key] != value:
                    parameters[key] = None
            else:
                parameters[key] = value
            if key not in {'CODE', 'UNITS', 'JOB', 'VER', 'IMAGE', 'ARRAYDIM'}:
                _issue(model, 'unsupported_parameter', 'Unsupported IPC parameter: ' + key, number)
            continue
        model['coverage']['records'] += 1
        if model['coverage']['records'] > MAX_RECORDS:
            raise ValueError('IPC netlist exceeds 100000 test records.')
        if line[:3] not in {'317', '327', '367'}:
            model['coverage']['unsupported_records'] += 1
            _issue(model, 'unsupported_record', 'Unsupported IPC record type: ' + line[:3], number)
            continue
        # Fixed columns, including both installed compact and padded tails.
        valid = (73 <= len(line) <= 80 and line[17:20] == '   '
                 and line[31] in ' M'
                 and re.fullmatch(r'(?:D\d{4}[PU]| {6})', line[32:38])
                 and re.fullmatch(r'A\d{2}X[+-]\d{6}Y[+-]\d{6}X\d{4}Y\d{4}R\d{3}', line[38:71])
                 and re.fullmatch(r' ?S[0-3] *', line[71:]))
        if not valid:
            model['coverage']['invalid_records'] += 1
            _issue(model, 'invalid_record', 'Malformed/truncated fixed-column test record.', number)
            continue
        net, reference, pin = line[3:17].rstrip(), line[20:26].rstrip(), line[27:31].rstrip()
        if line[26] != ('-' if pin else ' '):
            _issue(model, 'invalid_pin_separator', 'Pin separator does not match the fixed pin field.', number)
            model['coverage']['invalid_records'] += 1
            continue
        if line[:3] == '367':
            model['coverage']['ignored_mechanical'] += 1
            if net not in ('', 'N/C'):
                _issue(model, 'mechanical_net', 'Mechanical record unexpectedly declares an electrical net.', number)
            continue
        if not pin and (reference == 'VIA' or not reference and line[31] == 'M'):
            model['coverage']['ignored_vias'] += 1
            continue
        if not reference or not pin:
            model['coverage']['ignored_unidentified'] += 1
            _issue(model, 'unidentified_terminal', 'Component testpoint lacks exact reference/pin identity.', number)
            continue
        if not net:
            model['coverage']['invalid_records'] += 1
            _issue(model, 'missing_net', 'Blank signal field is not an explicit N/C assignment.', number)
            continue
        try:
            _text(reference, 'reference', 6, True)
            _text(pin, 'pin', 4, True)
            if net:
                _text(net, 'net', 14)
        except ValueError as exc:
            model['coverage']['invalid_records'] += 1
            _issue(model, 'invalid_identity', str(exc), number)
            continue
        if len(reference) == 6 or len(pin) == 4 or '?' in reference + pin:
            model['coverage']['ambiguous_records'] += 1
            _issue(model, 'ambiguous_endpoint', 'Full-width/sanitized reference or pin may be truncated; excluded.', number)
            continue
        x, y = int(line[42:49]), int(line[50:57])
        if abs(x) == 999999 or abs(y) == 999999:
            _issue(model, 'coordinate_clamp', 'Coordinate reaches the exporter clamp; exact position unavailable.', number)
        if int(line[68:71]) > 360:
            _issue(model, 'invalid_rotation', 'Rotation exceeds 360 degrees.', number)
            model['coverage']['invalid_records'] += 1
            continue
        raw.append(dict(reference=reference, pin=pin, net=net or None, x_mm=x*.00254, y_mm=y*.00254, line=number))
    if not ended:
        _issue(model, 'missing_end', 'Missing IPC 999 end record.')
    by_name = defaultdict(set)
    for alias, name in aliases.items():
        by_name[name].add(alias)
    for name, alias_ids in by_name.items():
        if len(alias_ids) > 1:
            invalid_aliases.update(alias_ids)
            _issue(model, 'conflicting_aliases', 'Multiple aliases declare the same original signal name; identity is ambiguous.')
    if parameters.get('CODE') != '00':
        _issue(model, 'unsupported_code', 'Only explicit IPC CODE 00 is supported.')
    if parameters.get('UNITS') != 'CUST 0':
        _issue(model, 'unsupported_units', 'Only explicit CUST 0 decimil units are supported; no unit guessing.')
    else:
        model['source']['units'] = 'decimil (0.00254 mm)'
    for key, allowed in (('VER', {'IPC-D-356', 'IPC-D-356A'}), ('IMAGE', {'PRIMARY'}), ('ARRAYDIM', {'N'})):
        if key in parameters and parameters[key] not in allowed:
            _issue(model, 'unsupported_parameter_value', 'Unsupported IPC ' + key + ' value.')
    if parameters.get('CODE') == '00' and parameters.get('UNITS') == 'CUST 0':
        for terminal in raw:
            net = terminal['net']
            if net in invalid_aliases or net is not None and len(net) == 14 and net not in aliases:
                model['coverage']['ambiguous_records'] += 1
                _issue(model, 'ambiguous_net', 'Net ID may be truncated/colliding; partition evidence excluded.', terminal['line'])
                continue
            terminal['net'] = None if net == 'N/C' else net
            terminal['net_name'] = aliases.get(net, net) if terminal['net'] is not None else 'N/C'
            model['terminals'].append(terminal)
    model['provenance'] = dict(declared_version=parameters.get('VER'), parser='bounded IPC-D-356 subset')
    return _finish(model)


def load_netlist(path):
    """Read a bounded source once; SHA-256 is over those exact original bytes."""
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Fabrication netlist exceeds 16 MiB.')
    if data.lstrip(b'\xef\xbb\xbf \t\r\n').startswith((b'{', b'[')):
        return _normalized(data)
    return _ipc(data)


def _model(value):
    if isinstance(value, (str, Path)):
        return load_netlist(value)
    if not isinstance(value, dict) or value.get('schema') != LOADED_SCHEMA:
        raise ValueError('Supply a path or an unchanged load_netlist result.')
    _tree(value, MAX_NODES * 3)
    content = {key: item for key, item in value.items() if key != 'model_sha256'}
    if value.get('model_sha256') != _digest(content):
        raise ValueError('Loaded netlist changed; reload its original source.')
    return value


def _endpoint(key):
    return dict(reference=key[0], pin=key[1])


def _group(terminal):
    return ('net', terminal['net']) if terminal['net'] is not None else ('nc', terminal['reference'], terminal['pin'])


def compare_netlists(reference, observed, confirm_independent_cam=False):
    """Compare partitions using O(N) incidence sets plus deterministic sorting."""
    if not isinstance(confirm_independent_cam, bool):
        raise ValueError('confirm_independent_cam must be an explicit boolean.')
    ref, obs = _model(reference), _model(observed)
    a = {(t['reference'], t['pin']): t for t in ref['terminals']}
    b = {(t['reference'], t['pin']): t for t in obs['terminals']}
    common = set(a) & set(b)
    missing, extra = sorted(set(a)-set(b)), sorted(set(b)-set(a))
    incidence_a, incidence_b = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for key in sorted(common):
        ga, gb = _group(a[key]), _group(b[key])
        incidence_a[ga][gb].append(key)
        incidence_b[gb][ga].append(key)

    def endpoints(keys):
        return [dict(**_endpoint(key), reference_net=a[key]['net_name'], observed_net=b[key]['net_name']) for key in sorted(keys)]

    def groups(parts, models):
        return [dict(net=models[keys[0]]['net'], name=models[keys[0]]['net_name'],
                     endpoints=[_endpoint(key) for key in keys])
                for _group_id, keys in sorted(parts.items())]

    shorts, opens = [], []
    for group_id, parts in sorted(incidence_b.items()):
        if len(parts) > 1:
            keys = [key for subset in parts.values() for key in subset]
            shorts.append(dict(observed_net=b[keys[0]]['net_name'],
                design_nets=[item['name'] for item in groups(parts, a)],
                design_groups=groups(parts, a), endpoints=endpoints(keys)))
    for group_id, parts in sorted(incidence_a.items()):
        if len(parts) > 1:
            keys = [key for subset in parts.values() for key in subset]
            opens.append(dict(design_net=a[keys[0]]['net_name'],
                observed_nets=[item['name'] for item in groups(parts, b)],
                observed_groups=groups(parts, b), endpoints=endpoints(keys)))
    issues = [dict(side=side, **item) for side, model in (('reference', ref), ('observed', obs)) for item in model['issues']]
    if missing:
        issues.append(dict(side='comparison', code='missing_pins', line=None, message='Reference endpoints are absent from the observed netlist.'))
    if extra:
        issues.append(dict(side='comparison', code='extra_pins', line=None, message='Observed endpoints are absent from the reference netlist.'))
    same_source = ref['source']['sha256'] == obs['source']['sha256']
    def semantic_digest(model):
        digest = hashlib.sha256()
        for terminal in model['terminals']:
            item = {key: terminal[key] for key in ('reference', 'pin', 'net', 'x_mm', 'y_mm')}
            digest.update(_digest(item).encode('ascii'))
        return digest.hexdigest()
    same_content = semantic_digest(ref) == semantic_digest(obs)
    if not confirm_independent_cam:
        issues.append(dict(side='comparison', code='independence_unconfirmed', line=None, message='Review and confirm an independently extracted CAM netlist.'))
    if same_source or same_content:
        issues.append(dict(side='comparison', code='self_comparison', line=None, message='Identical source/normalized connectivity is not independent CAM evidence.'))
    complete = ref['complete'] and obs['complete'] and not missing and not extra and bool(common)
    status = 'FAIL' if shorts or opens else 'MATCH' if complete and confirm_independent_cam and not same_source and not same_content else 'UNKNOWN'
    return dict(schema=REPORT_SCHEMA, created_utc=datetime.now(timezone.utc).isoformat(), units='mm',
        sources=dict(reference=ref['source'], observed=obs['source']),
        provenance=dict(reference=ref['provenance'], observed=obs['provenance']),
        status=status, fabrication_verified=False,
        summary=dict(short_groups=len(shorts), open_groups=len(opens), missing_pins=len(missing),
                     extra_pins=len(extra), matched_pins=len(common), complete=complete),
        shorts=shorts, opens=opens,
        coverage=dict(reference=ref['coverage'], observed=obs['coverage'], shared_terminals=len(common),
                      missing_pins=[_endpoint(key) for key in missing], extra_pins=[_endpoint(key) for key in extra]),
        issues=issues, independence=dict(confirmed=confirm_independent_cam, identical_source=same_source,
                                       identical_normalized_content=same_content), limits=list(LIMITS))
