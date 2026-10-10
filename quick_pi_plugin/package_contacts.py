"""Explicit axial package paths attached to one saved pad copper face.

Virtual endpoint nodes are circuit terminals, not meshed package geometry.
The ordinary FEM resistor stamp solves current sharing through all paths.
"""
import copy
import math


def guard_request(request):
    """Reject modes which cannot preserve contact losses and port voltages."""
    raw = request.get('package_conduction')
    if raw is None or raw == []:
        return
    from wayricad_runtime.package_conduction import normalize_paths
    normalize_paths(raw, physics='electrical')
    if (request.get('model_dimension', '2.5d') != '2.5d' or request.get('series') or
            request.get('load_resistance_ohm') is not None or
            request.get('action', 'solve') not in ('geometry', 'mesh', 'solve', 'converge')):
        raise ValueError('Explicit package contacts require 2.5D constant-current DC; '
                         '3D, series, resistive-load, sweep, transient and electrothermal modes are unsupported.')


def attach(mesh, geometry, raw, source_id, sinks):
    """Return a copied network, source nodes and sinks with package endpoints.

    sink ports are sink:<resolved pad UUID>. Request terminal labels are accepted
    as aliases and canonicalized; paths of a port may attach to multiple pads.
    """
    from wayricad_runtime.package_conduction import normalize_paths
    paths = normalize_paths(raw, physics='electrical')
    if not paths:
        return mesh, mesh['terminal_nodes'][source_id], sinks
    if mesh.get('lumped_branches'):
        raise ValueError('Package contacts cannot be combined with series branches.')
    aliases = {'source': 'source'}
    for sink in sinks:
        canonical = 'sink:' + sink['id']
        aliases[canonical] = canonical
        aliases['sink:' + sink['terminal']] = canonical
    catalog = geometry.get('pad_catalog', geometry['terminals'])
    records=[];owned={};pad_owners={}
    for path in paths:
        definition=copy.deepcopy(path['definition'])
        port=aliases.get(definition.get('port'))
        if port is None:
            raise ValueError('Unknown package port; use source or sink:<selected sink pad UUID/label>.')
        matches=[p for p in catalog if p.get('reference')==definition['reference'] and
                 p.get('pad_number')==definition['pad_number'] and
                 (not definition.get('pad_uuid') or p['id']==definition['pad_uuid'])]
        if len(matches)!=1:
            raise ValueError('Package contact pad binding is missing or ambiguous: '+definition['id'])
        pad=matches[0];pad_id=pad['id'];layer=str(definition['layer_id'])
        if pad.get('net')!=geometry['net']:
            raise ValueError('Package contact pad belongs to a different net: '+definition['id'])
        face=mesh.get('terminal_nodes_by_layer',{}).get(pad_id,{}).get(layer)
        if not face:
            raise ValueError('Package contact has no copper mesh on the declared pad face: '+definition['id'])
        terminal=next((row for row in geometry['terminals'] if row['id']==pad_id),{})
        polygons=terminal.get('polygons',{}).get(layer,[])
        def ring_area(ring):
            return abs(math.fsum(a[0]*b[1]-b[0]*a[1]
                for a,b in zip(ring,ring[1:]+ring[:1])))/2 if len(ring)>=3 else 0.
        area=math.fsum(ring_area(poly['outer'])-math.fsum(ring_area(hole) for hole in poly.get('holes',[]))
                      for poly in polygons)
        if not math.isfinite(area) or area<=0:
            raise ValueError('Package contact has no reviewed saved pad copper area: '+definition['id'])
        if path['segments'][-1]['minimum_area_mm2']>area*(1+1e-6):
            raise ValueError('Package contact end neck exceeds saved pad copper area: '+definition['id'])
        key=(pad_id,layer)
        if key in owned or pad_owners.get(pad_id,port)!=port:
            raise ValueError('Duplicate or conflicting package contact pad ownership: '+definition['id'])
        owned[key]=port;pad_owners[pad_id]=port
        definition.update(port=port,pad_uuid=pad_id)
        records.append({**path,'definition':definition,'board_nodes':list(face),'pad_copper_area_mm2':area})
    configured={r['definition']['port'] for r in records}
    legacy=[]
    if 'source' not in configured:legacy.append(('source',mesh['terminal_nodes'][source_id]))
    for sink in sinks:
        port='sink:'+sink['id']
        if port not in configured:legacy.append((port,sink['nodes']))
    seen_nodes={}
    for record in records:
        port=record['definition']['port']
        for node in record['board_nodes']:
            if node in seen_nodes:
                raise ValueError('Package contact faces overlap in the copper mesh.')
            if any(node in indices for _,indices in legacy):
                raise ValueError('Package contact overlaps a legacy ideal terminal.')
            seen_nodes[node]=port
    network=copy.deepcopy(mesh);endpoints={}
    for port in sorted(configured):
        sample=next(r for r in records if r['definition']['port']==port)['board_nodes'][0]
        endpoints[port]=len(network['points_mm'])
        network['points_mm'].append(list(network['points_mm'][sample]))
    branches=[]
    for record in records:
        endpoint=endpoints[record['definition']['port']]
        record['package_node']=endpoint
        branches.append({'id':record['definition']['id'],'top_nodes':[endpoint],
                         'bottom_nodes':record['board_nodes'],
                         'resistance_ohm':record['electrical_resistance_ohm'],'inductance_h':0.})
    network['lumped_branches']=branches
    network['package_contacts']=records
    network['package_endpoint_nodes']=endpoints
    source_nodes=[endpoints['source']] if 'source' in endpoints else mesh['terminal_nodes'][source_id]
    loads=[{**s,'nodes':[endpoints['sink:'+s['id']]] if 'sink:'+s['id'] in endpoints else s['nodes']} for s in sinks]
    return network,source_nodes,loads


def ledger(mesh, result):
    """Separate contact loss and retain solved board/package voltage evidence."""
    if not mesh.get('package_contacts'):
        return
    rows=[]
    for path,branch in zip(mesh['package_contacts'],result['components']):
        row={**copy.deepcopy(path),**branch}
        row['port']=path['definition']['port']
        row['package_voltage_V']=branch['voltage_before_V']
        row['board_voltage_V']=branch['voltage_after_V']
        row['direction']='package_to_board_positive'
        current=branch['current_A']
        row['segments']=[{**copy.deepcopy(segment),'power_W':
                          None if current is None else current*current*segment['electrical_resistance_ohm']}
                         for segment in path['segments']]
        extra=path['definition'].get('additional_electrical_ohm',0.)
        row['additional_electrical_power_W']=None if current is None else current*current*extra
        row['additional_electrical_heat_location']=None
        rows.append(row)
    result['package_contacts']=rows
    result['package_power_W']=math.fsum(row['power_W'] or 0 for row in rows)
    result['package_port_currents_A']={}
    for port in mesh['package_endpoint_nodes']:
        values=[row['current_A'] for row in rows if row['port']==port]
        result['package_port_currents_A'][port]=None if any(value is None for value in values) else math.fsum(values)
    result['components']=[]
    result['component_power_W']=0.
    result['package_port_voltages_V']={port:result['potential_V'][node] for port,node in mesh['package_endpoint_nodes'].items()}
    from .analytics import summarize
    result['analytics']=summarize(mesh,result)


def details_text(result):
    lines=['PACKAGE CONTACTS — axial finite-resistance paths; package-to-board current positive']
    def value(number):
        return 'unknown' if number is None else f'{number:.9g}'
    for row in result.get('package_contacts',[]):
        lines.append(f"{row['id']} [{row['port']}] {value(row['current_A'])} A; "
                     f"R {value(row['resistance_ohm'])} ohm; drop {value(row['voltage_drop_V'])} V; "
                     f"I²R {value(row['power_W'])} W; package {value(row['package_voltage_V'])} V; "
                     f"board {value(row['board_voltage_V'])} V")
    return '\n'.join(lines)
