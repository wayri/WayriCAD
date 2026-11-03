"""Bounded whole-board section extraction and explicit net bundles.

Every physical section is measured independently. Summing a branched net's
section resistances would not give its terminal impedance, so no such value is
reported. Bundle membership does not imply a coupled transmission-line model.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from .copper_path import CopperGeometry, IU, distance, ground_name, point


def normalize_bundles(document, available):
    """Validate a portable bundle definition against exact saved net names."""
    if document is None:
        return []
    if isinstance(document, dict):
        if document.get('schema') != 'wayricad.rlc-bundles/v1':
            raise ValueError('Unsupported RLC bundle schema.')
        document = document.get('bundles')
    if not isinstance(document, list) or len(document) > 1024:
        raise ValueError('Provide at most 1024 named RLC bundles.')
    names = set(); result = []; available = set(available)
    for row in document:
        if not isinstance(row, dict):
            raise ValueError('Each bundle must be an object.')
        name = row.get('name'); nets = row.get('nets')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Bundle names must be nonempty and unique.')
        if not isinstance(nets, list) or not nets or any(not isinstance(net, str) for net in nets):
            raise ValueError('Each bundle needs an explicit list of saved net names.')
        if len(nets) != len(set(nets)):
            raise ValueError('A bundle cannot repeat a net.')
        missing = set(nets) - available
        if missing:
            raise ValueError('Unknown bundle nets: ' + ', '.join(sorted(missing)))
        names.add(name)
        result.append({'name': name, 'nets': list(nets)})
    return result


class _ReferenceGeometry(CopperGeometry):
    """Infer geometric reference candidates without requiring a ground name."""
    def reference_candidates(self, signal_layer, a, b, width_mm, net):
        candidates = []
        for layer in self.layers:
            if layer == signal_layer:
                continue
            candidates.extend(super().reference(signal_layer, a, b, width_mm,
                              self.engine._layer_name(layer), net, all_matches=True))
        return sorted(candidates, key=lambda row: (row[0], row[1], row[3]['net'], row[3]['id']))

    def reference(self, signal_layer, a, b, width_mm, reference_layer='Auto', net='', all_matches=False):
        if reference_layer not in ('Auto', '', None):
            return super().reference(signal_layer, a, b, width_mm, reference_layer, net, all_matches)
        rows = self.reference_candidates(signal_layer, a, b, width_mm, net)
        # Overlapping candidates on one layer are ambiguous; never choose by
        # ordering/name. Separate symmetric planes are retained for the engine.
        counts = Counter(row[1] for row in rows)
        rows = [row for row in rows if counts[row[1]] == 1]
        if all_matches:
            return rows
        return rows[0] if rows else None


def _uuid(item):
    return str(item.m_Uuid.AsString())


def _edges(engine, geometry, item):
    pcb = geometry.pcb
    if isinstance(item, pcb.PCB_VIA):
        span = [layer for layer in geometry.layers if item.IsOnLayer(layer)]
        position = point(item.GetPosition())
        for a, b in zip(span, span[1:]):
            yield dict(kind='via', item=item, layer=a, end_layer=b, a=position, b=position,
                       length_mm=engine.via_span_mm(a, b), drill_mm=item.GetDrillValue()/IU)
    elif isinstance(item, pcb.PCB_ARC):
        for a, b, scale in geometry.arc_pieces(item):
            yield dict(kind='track', item=item, layer=item.GetLayer(), a=a, b=b,
                       length_mm=distance(a, b)*scale, width_mm=item.GetWidth()/IU,
                       geometry='arc (exact length, 1 um chord approximation)')
    elif isinstance(item, pcb.PCB_TRACK):
        a, b = point(item.GetStart()), point(item.GetEnd())
        yield dict(kind='track', item=item, layer=item.GetLayer(), a=a, b=b,
                   length_mm=distance(a, b), width_mm=item.GetWidth()/IU, geometry='straight')


def _candidate_rows(geometry, edge, net):
    if edge['kind'] != 'track':
        return []
    width = edge['width_mm'] + (.002 if edge.get('geometry', '').startswith('arc') else 0.)
    if isinstance(geometry, _ReferenceGeometry):
        rows = geometry.reference_candidates(edge['layer'], edge['a'], edge['b'], width, net)
    else:
        rows = geometry.reference(edge['layer'], edge['a'], edge['b'], width, 'Auto', net, all_matches=True)
    return [{'layer': name, 'net': island['net'], 'island_id': island['id'],
             'dielectric_height_mm': height, 'relative_permittivity': er,
             'coverage': 'entire_section_corridor', 'named_ground': ground_name(island['net'])}
            for height, name, er, island in rows]


def available_nets(engine):
    """Include orphan routing/zone nets and unassigned routing, not only pads."""
    names = set(engine.net_names())
    names.update(str(item.GetNetname()) for item in engine.board.GetTracks())
    names.update(str(zone.GetNetname()) for zone in engine.board.Zones()
                 if not getattr(zone, 'GetIsRuleArea', lambda: False)())
    return sorted(names)


def extract_board(engine, nets=None, bundles=None, frequency_mhz=100., infer_references=True,
                  max_sections=20000, cancelled=None, progress=None):
    """Inventory selected/all nets and extract supported physical sections.

    ``cancelled`` is an optional zero-argument callback; ``progress`` receives
    (completed physical items, total physical items). No board writes or fills.
    Saved-file callers must additionally guard their source bytes before/after.
    """
    if isinstance(frequency_mhz, bool) or not math.isfinite(frequency_mhz) or frequency_mhz < 0:
        raise ValueError('Frequency must be finite and non-negative.')
    if isinstance(max_sections, bool) or not isinstance(max_sections, int) or not 1 <= max_sections <= 1000000:
        raise ValueError('Section budget must be an integer from 1 to 1000000.')
    available = available_nets(engine)
    definitions = normalize_bundles(bundles, available)
    if nets is not None and (not isinstance(nets, (list, tuple, set)) or any(not isinstance(net, str) for net in nets)):
        raise ValueError('Select exact net names as a list.')
    selected = sorted(set(available if nets is None and not definitions else nets or []) |
                      {net for row in definitions for net in row['nets']})
    if set(selected) - set(available):
        raise ValueError('Unknown selected nets: ' + ', '.join(sorted(set(selected)-set(available))))
    # One geometry snapshot/cache per operation. Normal interactive measure()
    # still invalidates its own cache after live edits.
    geometry = _ReferenceGeometry(engine) if infer_references else CopperGeometry(engine)
    engine._geometry_cache = geometry
    # _new_result reads saved stackup provenance. Read once, rather than
    # reparsing a whole PCB for every physical section on a large board.
    prototype = engine._new_result('', '', '', 'Auto')
    rows = {net: {'net': net, 'display_name': net or '(unassigned copper)', 'status': 'partial', 'sections': [], 'zones': [],
                  'pads': engine.pads_for_net(net), 'physical_item_count': 0,
                  'net_equivalent_impedance_ohm': None,
                  'topology': 'physical_sections_not_terminal_network'} for net in selected}
    items = [item for item in engine.board.GetTracks() if str(item.GetNetname()) in rows]
    items.sort(key=lambda item: (str(item.GetNetname()), _uuid(item)))
    completed = 0; section_count = 0; reason = None; omitted = []
    for index, item in enumerate(items):
        if cancelled is not None and cancelled():
            reason = 'cancelled'; omitted.extend(_uuid(other) for other in items[index:]); break
        net = str(item.GetNetname()); row = rows[net]; uid = _uuid(item)
        item_sections = 0
        for piece, edge in enumerate(_edges(engine, geometry, item)):
            if cancelled is not None and cancelled():
                reason = 'cancelled'; break
            if section_count >= max_sections:
                reason = 'section_budget_exceeded'; break
            result = deepcopy(prototype)
            result.net_name = net
            engine._measure_edges(result, [edge], frequency_mhz, 'Auto')
            candidates = _candidate_rows(geometry, edge, net)
            for section in result.as_report()['segments']:
                section.update(section_id=f'{uid}:{piece}', reference_candidates=candidates,
                               blockers=list(result.blockers))
                section['reference_inference'] = 'saved_filled_geometry' if infer_references else 'named_ground_and_saved_filled_geometry'
                section['electrical_return_continuity'] = 'unverified'
                used_layers = section.get('reference_layer', '').split(' + ')
                section['selected_reference_candidates'] = [candidate for candidate in candidates if candidate['layer'] in used_layers]
                # A plane with an arbitrary name may be a valid geometric
                # reference but is not proof of an AC-ground connection.
                if any(not candidate['named_ground'] for candidate in section['selected_reference_candidates']):
                    section['status'] = 'partial'
                    section.setdefault('blockers', []).append({'code': 'REFERENCE_ELECTRICAL_ROLE_UNVERIFIED',
                        'message': 'Filled geometric reference candidate is not a verified return connection.'})
                row['sections'].append(section)
                section_count += 1; item_sections += 1
        if reason:
            omitted.extend(_uuid(other) for other in items[index:]); break
        row['physical_item_count'] += 1
        if not item_sections:
            row.setdefault('unsupported_items', []).append(uid)
        completed += 1
        if progress is not None:
            progress(completed, len(items))
    omitted_set = set(omitted)
    omitted_nets = {str(item.GetNetname()) for item in items if _uuid(item) in omitted_set}
    for island in geometry.islands:
        if island['net'] in rows:
            rows[island['net']]['zones'].append({'id': island['id'], 'layer': engine._layer_name(island['layer']),
                'area_mm2': island['area_mm2'], 'status': 'unknown',
                'reason': 'Filled island retained; R/L needs reviewed terminals and corridor, not an aggregate-net fallback.'})
    for zone in engine.board.Zones():
        net = str(zone.GetNetname())
        if net not in rows or getattr(zone, 'GetIsRuleArea', lambda: False)():
            continue
        for layer in geometry.layers:
            if zone.IsOnLayer(layer) and not zone.HasFilledPolysForLayer(layer):
                rows[net]['zones'].append({'id': _uuid(zone), 'layer': engine._layer_name(layer),
                    'area_mm2': None, 'status': 'unknown',
                    'reason': 'Zone is unfilled on this layer; refill in KiCad and rerun.'})
    for row in rows.values():
        statuses = [section.get('status') for section in row['sections']]
        row['status'] = ('ok' if row['net'] and statuses and all(status == 'ok' for status in statuses) and
                         not row['zones'] and not row.get('unsupported_items') else 'partial')
        row['coverage'] = {'extracted_sections': len(row['sections']),
                           'modeled_z0_sections': sum(section.get('impedance_ohm') is not None for section in row['sections']),
                           'filled_islands_requiring_terminals': len(row['zones'])}
        if row['net'] in omitted_nets:
            row['status'] = reason or 'partial'
    for definition in definitions:
        definition.update(status='ok' if all(rows[net]['status'] == 'ok' for net in definition['nets']) else 'partial',
                          coupled_impedance_ohm=None, mutual_inductance_nh=None,
                          notice='Explicit net grouping only; each member retains independent section results. Coupled fields are unresolved.')
    return {'schema': 'wayricad.rlc-bulk/v1', 'operation': 'bulk',
            'status': reason or ('ok' if rows and all(row['status'] == 'ok' for row in rows.values()) else 'partial'),
            'frequency_mhz': frequency_mhz, 'infer_references': bool(infer_references),
            'nets': list(rows.values()), 'bundles': definitions,
            'coverage': {'selected_nets': len(rows), 'physical_items': len(items), 'completed_items': completed,
                         'extracted_sections': section_count, 'max_sections': max_sections,
                         'omitted_item_uuids': sorted(set(omitted)), 'complete': reason is None},
            'limitations': ['Per-section quasi-static estimates, not whole-board FEM/full-wave extraction.',
                'No net-equivalent impedance is inferred for branched or mixed paths; select terminals in Path mode.',
                'A filled reference corridor is geometric evidence; AC return connectivity remains unverified.',
                'Bundle membership does not solve coupling, crosstalk, differential impedance or terminations.',
                'Zones require terminal corridors; unfilled zones and unsupported geometry cannot establish a passing extraction.']}
