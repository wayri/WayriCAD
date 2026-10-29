"""Reviewed power intent, independent of copper solving and native GUI imports.

Edges describe energy flow only. They never join nets, create a resistor model,
or identify an isolated secondary with the primary reference.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

KINDS = ('rail', 'source', 'load', 'dcdc', 'isolated_dcdc', 'ldo')
MAX_NODES = 256
MAX_EDGES = 512
MAX_FILE_BYTES = 2 * 1024 * 1024


def empty_tree(source=None):
    return {'schema': 1, 'source': deepcopy(source or {}), 'nodes': [], 'edges': []}


def new_node(identifier, kind='rail', label=None):
    if kind not in KINDS:
        raise ValueError('Unknown power-tree node kind.')
    node = {'id': identifier, 'kind': kind, 'label': label or identifier,
            'reviewed': False, 'confidence': 'manual', 'evidence': []}
    if kind == 'rail':
        node.update(net='', return_net='', voltage_v=None, domain='')
    else:
        node.update(reference='', footprint_uuid='')
    return node


def new_edge(source, target):
    return {'source': source, 'target': target, 'reviewed': False,
            'evidence': ['Manual energy-flow connection; not an electrical short.']}


def _text(value, name, required=False):
    if not isinstance(value, str) or len(value) > 2048 or (required and not value.strip()):
        raise ValueError(name + ' must be bounded text' + (' and nonempty.' if required else '.'))
    return value


def _evidence(row, name):
    if type(row.get('reviewed', False)) is not bool:
        raise ValueError(name + ': reviewed must be true or false.')
    evidence = row.get('evidence', [])
    if not isinstance(evidence, list) or len(evidence) > 32:
        raise ValueError(name + ': evidence must be a bounded list of text.')
    for entry in evidence:
        _text(entry, name + ' evidence')


def validate_power_tree(tree, *, require_reviewed=False, inventory=None):
    """Return a detached normalized document or raise ValueError.

    Drafts can contain unknown voltages/references and disconnected candidates.
    Reviewed validation requires complete rail references, device ports, and
    explicit review of every node and edge. No numerical conversion is solved.
    """
    if not isinstance(tree, dict) or type(tree.get('schema')) is not int or tree['schema'] != 1:
        raise ValueError('Power tree requires schema 1.')
    if set(tree) - {'schema', 'source', 'nodes', 'edges'}:
        raise ValueError('Unknown power-tree document field.')
    source = tree.get('source', {})
    if not isinstance(source, dict):
        raise ValueError('Power-tree source must be an evidence mapping.')
    try:
        encoded = json.dumps(tree, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('Power tree must contain finite JSON data.') from exc
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError('Power tree exceeds the 2 MiB document budget.')
    nodes, edges = tree.get('nodes'), tree.get('edges')
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ValueError('Power tree supports at most 256 nodes.')
    if require_reviewed and not nodes:
        raise ValueError('A reviewed power tree needs at least one source and rail.')
    if not isinstance(edges, list) or len(edges) > MAX_EDGES:
        raise ValueError('Power tree supports at most 512 edges.')
    index = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError('Each power-tree node must be an object.')
        allowed = {'id', 'kind', 'label', 'reviewed', 'confidence', 'evidence',
                   'net', 'return_net', 'voltage_v', 'domain', 'reference', 'footprint_uuid'}
        if set(node) - allowed:
            raise ValueError('Unknown power-tree node field.')
        identifier = _text(node.get('id'), 'Node ID', True)
        if identifier in index:
            raise ValueError('Power-tree node IDs must be unique.')
        kind = node.get('kind')
        if kind not in KINDS:
            raise ValueError(identifier + ': unsupported node kind.')
        _text(node.get('label', identifier), identifier + ' label', True)
        if node.get('confidence', 'manual') not in ('manual', 'explicit_metadata', 'candidate'):
            raise ValueError(identifier + ': unsupported confidence.')
        _evidence(node, identifier)
        if require_reviewed and not node.get('reviewed'):
            raise ValueError(identifier + ': review this node first.')
        if kind == 'rail':
            for key in ('net', 'return_net', 'domain'):
                _text(node.get(key, ''), identifier + ' ' + key, require_reviewed)
            if node.get('net') and node.get('net') == node.get('return_net'):
                raise ValueError(identifier + ': rail and return must be distinct nets.')
            voltage = node.get('voltage_v')
            if voltage is not None and (isinstance(voltage, bool) or not isinstance(voltage, (float, int)) or not math.isfinite(voltage)):
                raise ValueError(identifier + ': voltage_v must be finite or null.')
            if require_reviewed and voltage is None:
                raise ValueError(identifier + ': enter signed voltage relative to its return.')
        else:
            for key in ('reference', 'footprint_uuid'):
                _text(node.get(key, ''), identifier + ' ' + key)
        index[identifier] = node
    net_domains = {}
    for node in nodes:
        if node['kind'] != 'rail' or not node.get('domain'):
            continue
        for net in (node.get('net'), node.get('return_net')):
            if not net:
                continue
            if net in net_domains and net_domains[net] != node['domain']:
                raise ValueError(net + ': the same electrical net cannot belong to separate isolation domains.')
            net_domains[net] = node['domain']
    rail_nets = set()
    for node in nodes:
        net = node.get('net') if node['kind'] == 'rail' else None
        if net:
            if net in rail_nets:
                raise ValueError(net + ': use one rail node per physical net; duplicate rails can conceal conflicting voltages or multiple feeds.')
            rail_nets.add(net)
    incoming = {key: [] for key in index}
    outgoing = {key: [] for key in index}
    seen = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) - {'source', 'target', 'reviewed', 'evidence'}:
            raise ValueError('Invalid power-tree edge fields.')
        start, end = edge.get('source'), edge.get('target')
        if not isinstance(start, str) or not isinstance(end, str) or start not in index or end not in index or start == end:
            raise ValueError('Each edge needs two distinct existing node IDs.')
        if (start, end) in seen:
            raise ValueError('Duplicate power-tree edge.')
        seen.add((start, end)); _evidence(edge, start + ' -> ' + end)
        if require_reviewed and not edge.get('reviewed'):
            raise ValueError(start + ' -> ' + end + ': review this connection first.')
        a, b = index[start]['kind'], index[end]['kind']
        if (a == 'rail') == (b == 'rail') or a == 'load' or b == 'source':
            raise ValueError('Energy edges must alternate devices and rails, from a source toward loads.')
        outgoing[start].append(end); incoming[end].append(start)
    # Kahn traversal is bounded and avoids recursive graph-depth limits.
    counts = {key: len(value) for key, value in incoming.items()}
    pending = [key for key, count in counts.items() if not count]
    visited = 0
    while pending:
        key = pending.pop(); visited += 1
        for target in outgoing[key]:
            counts[target] -= 1
            if counts[target] == 0:
                pending.append(target)
    if visited != len(index):
        raise ValueError('Power tree must be acyclic; feedback/control loops are not energy edges.')
    for key, node in index.items():
        kind = node['kind']; ins, outs = incoming[key], outgoing[key]
        if len(ins) > 1:
            raise ValueError(key + ': multiple feeds need an explicit supported combining model; split the intent graph.')
        if kind not in ('rail', 'load') and len(outs) > 1:
            raise ValueError(key + ': model one output per converter/source; use separate devices for multiple outputs.')
        if require_reviewed:
            expected = (0, 1) if kind == 'source' else (1, 0) if kind == 'load' else (1, 1)
            if kind == 'rail':
                if not ins:
                    raise ValueError(key + ': connect an explicit upstream source or converter.')
            elif (len(ins), len(outs)) != expected:
                raise ValueError(key + ': complete the input/output rail connections.')
        if kind in ('dcdc', 'isolated_dcdc', 'ldo') and ins and outs:
            a, b = index[ins[0]], index[outs[0]]
            if kind == 'isolated_dcdc':
                if a.get('return_net') and a.get('return_net') == b.get('return_net'):
                    raise ValueError(key + ': isolated converter must keep primary and secondary returns separate.')
                if a.get('domain') and a.get('domain') == b.get('domain'):
                    raise ValueError(key + ': isolated converter needs separate declared isolation domains.')
            else:
                if a.get('domain') and b.get('domain') and a['domain'] != b['domain']:
                    raise ValueError(key + ': a non-isolated converter cannot bridge isolation domains.')
                if a.get('return_net') and b.get('return_net') and a['return_net'] != b['return_net']:
                    raise ValueError(key + ': non-isolated input/output must use the same declared reference.')
    if inventory is not None:
        saved_hash = source.get('source_sha256')
        current_hash = inventory.get('source_sha256')
        if saved_hash and current_hash and saved_hash != current_hash:
            raise ValueError('The source board changed. Review a new power-tree draft against the current board.')
        nets = set(inventory.get('nets', [])) | {row.get('net') for row in inventory.get('terminals', [])}
        owners = {row.get('footprint_uuid') for row in inventory.get('terminals', [])}
        for node in nodes:
            if node['kind'] == 'rail':
                for field in ('net', 'return_net'):
                    if node.get(field) and node[field] not in nets:
                        raise ValueError(node['id'] + ': ' + field + ' no longer exists on the board.')
            elif node.get('footprint_uuid') and node['footprint_uuid'] not in owners:
                raise ValueError(node['id'] + ': footprint no longer exists on the board.')
    result = deepcopy(tree)
    result.setdefault('source', {})
    return result


def infer_power_tree(inventory, source=None):
    """Suggest intent for review; never infer an electrical component model.

    ``terminals`` uses Quick PI's normal pad inventory. Optional
    ``component_properties`` can carry explicit ``QuickPI:Role``, ``InputNet``,
    ``OutputNet``, ``InputReturn``, ``OutputReturn``, ``InputDomain`` and
    ``OutputDomain`` fields, each prefixed ``QuickPI:``. Net-pair declarations
    must actually occur on that saved footprint. Missing data stays unknown.
    """
    tree = empty_tree(source)
    terminals = inventory.get('terminals', [])
    nets = sorted({str(net) for net in inventory.get('nets', []) if net} |
                  {str(row['net']) for row in terminals if row.get('net')})
    rails = {}

    def rail(net, return_net='', domain=''):
        key = (net, return_net, domain)
        if key not in rails:
            node = new_node('rail-' + str(len(rails) + 1), label=net)
            node.update(net=net, return_net=return_net, domain=domain, confidence='candidate',
                        evidence=['Saved net name; voltage, reference and power role require review.'])
            tree['nodes'].append(node); rails[key] = node
        return rails[key]

    grouped = {}
    for row in terminals:
        if row.get('footprint_uuid'):
            grouped.setdefault(row['footprint_uuid'], []).append(row)
    for owner, pads in sorted(grouped.items()):
        first = pads[0]
        props = first.get('component_properties', {})
        if not isinstance(props, dict):
            props = {}
        declared = props.get('QuickPI:Role')
        value = str(first.get('component_value', ''))
        kind = declared if declared in KINDS and declared != 'rail' else None
        if kind is None:
            if re.search(r'\b(isolated)\b.*\b(dc[/ -]?dc|converter)\b', value, re.I):
                kind = 'isolated_dcdc'
            elif re.search(r'\bLDO\b|\blinear regulator\b', value, re.I):
                kind = 'ldo'
            elif re.search(r'\bDC[/ -]?DC\b|\b(buck|boost) converter\b', value, re.I):
                kind = 'dcdc'
        if kind is None:
            continue
        ref = first.get('reference') or str(first.get('label', '')).rsplit('.', 1)[0]
        node = new_node('device-' + str(len(tree['nodes']) + 1), kind, ref or owner)
        node.update(reference=ref, footprint_uuid=owner,
                    confidence='explicit_metadata' if declared == kind else 'candidate',
                    evidence=[('Saved QuickPI:Role = ' + kind) if declared == kind else
                              ('Saved value contains a converter description: ' + value)])
        tree['nodes'].append(node)
        connected = {pad.get('net') for pad in pads if pad.get('net')}
        for direction, enabled in (('Input', kind != 'source'), ('Output', kind != 'load')):
            net = props.get('QuickPI:' + direction + 'Net', '')
            ret = props.get('QuickPI:' + direction + 'Return', '')
            domain = props.get('QuickPI:' + direction + 'Domain', '')
            if isinstance(net, str) and isinstance(ret, str) and net and ret and net in connected and ret in connected and net != ret:
                node_count, edge_count, old_rails = len(tree['nodes']), len(tree['edges']), dict(rails)
                target = rail(net, ret, str(domain))
                if len(target['evidence']) < 31:
                    target['evidence'].append('Saved explicit net pair on ' + (ref or owner) + '; review intent and voltage.')
                edge = new_edge(target['id'], node['id']) if direction == 'Input' else new_edge(node['id'], target['id'])
                edge['evidence'] = ['Saved explicit QuickPI:' + direction + 'Net/Return, verified against footprint pad nets.']
                tree['edges'].append(edge)
                try:
                    validate_power_tree(tree)
                except ValueError as exc:
                    # Contradictory saved metadata stays a candidate for review;
                    # it cannot silently collapse an isolation boundary.
                    del tree['nodes'][node_count:]; del tree['edges'][edge_count:]; rails = old_rails
                    node['evidence'].append('Rejected ' + direction.lower() + ' metadata connection: ' + str(exc))
    covered = {node['net'] for node in rails.values()}
    for net in nets:
        if net not in covered and re.search(r'(^|/)([+-]\d|V(?:CC|DD|SS|IN|OUT|BAT|BUS)(?:$|[_\d])|\d+V\d*)', net, re.I):
            rail(net)
    return validate_power_tree(tree)


def load_power_tree(path, **validation):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Power tree exceeds the 2 MiB document budget.')
    try:
        return validate_power_tree(json.loads(path.read_text(encoding='utf-8')), **validation)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError('Power tree must be UTF-8 schema-1 JSON.') from exc


def save_power_tree(path, tree, **validation):
    document = validate_power_tree(tree, **validation)
    path = Path(path)
    if path.suffix.lower() != '.json':
        raise ValueError('Choose a .json power-tree destination; design files cannot be overwritten.')
    from wayricad_runtime.report_ui import publish_documents
    source = document.get('source', {})
    protected = [source.get(key) for key in ('board_path', 'study_input_path', 'source_path') if source.get(key)]
    publish_documents({path: json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n'}, sources=protected)
    return document
