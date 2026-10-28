"""Conservative, saved-board return-path evidence for Quick PI and Quick SI.

This is a geometric screening tool, not a return-current or impedance solver.
The pure ``audit_return_path`` function accepts JSON-compatible evidence so the
same findings can be shown in a UI, CLI, or report without a KiCad dependency.
``collect_board_evidence`` reads native, *filled* copper zones from pcbnew.
"""
from __future__ import annotations

import math
from typing import Any


def _xy(point: Any, pcbnew: Any) -> list[float]:
    return [pcbnew.ToMM(point.x), pcbnew.ToMM(point.y)]


def _ring(chain: Any, pcbnew: Any) -> list[list[float]]:
    points = [_xy(chain.CPoint(i), pcbnew) for i in range(chain.PointCount())]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def collect_board_evidence(board: Any, signal_net: str, return_nets: list[str] | tuple[str, ...]) -> dict:
    """Read routed tracks, vias, and actual filled return zones from a board.

    An unfilled return zone is explicitly recorded as missing evidence. This
    function does not refill the board or alter the editor. The caller should
    load a saved board if its results must correspond to a saved revision.
    """
    import pcbnew

    signal_net = str(signal_net).strip()
    returns = {str(name).strip() for name in return_nets if str(name).strip()}
    if not signal_net or not returns or signal_net in returns:
        raise ValueError("Choose a signal net and distinct, explicit return net(s).")
    copper_layers = list(board.GetEnabledLayers().CuStack())
    layer_names = {layer: str(board.GetLayerName(layer)) for layer in copper_layers}
    evidence: dict[str, Any] = {
        "signal_net": signal_net, "return_nets": sorted(returns),
        "layer_order": [layer_names[layer] for layer in copper_layers],
        "segments": [], "signal_vias": [], "return_vias": [],
        "reference_regions": [], "unfilled_reference_layers": [], "unsupported_geometry": [], "terminals": [],
    }
    for item in board.GetTracks():
        net = str(item.GetNetname())
        if net != signal_net and net not in returns:
            continue
        if isinstance(item, pcbnew.PCB_VIA):
            entry = {
                "net": net, "position": _xy(item.GetPosition(), pcbnew),
                "id": str(item.m_Uuid.AsString()), "diameter_mm": pcbnew.ToMM(item.GetWidth(item.TopLayer())),
                "layers": [layer_names[layer] for layer in copper_layers if item.IsOnLayer(layer)],
            }
            evidence["signal_vias" if net == signal_net else "return_vias"].append(entry)
        elif net == signal_net:
            if isinstance(item, pcbnew.PCB_ARC):
                # Chords can jump over a plane slit. Do not claim coverage for them.
                evidence["unsupported_geometry"].append("Arc on " + layer_names[item.GetLayer()])
                continue
            evidence["segments"].append({
                "layer": layer_names[item.GetLayer()],
                "start": _xy(item.GetStart(), pcbnew), "end": _xy(item.GetEnd(), pcbnew),
                "width_mm": pcbnew.ToMM(item.GetWidth()),
            })
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            net=str(pad.GetNetname())
            if net!=signal_net and net not in returns:continue
            evidence['terminals'].append({'id':str(pad.m_Uuid.AsString()),'label':str(footprint.GetReference())+'.'+str(pad.GetNumber()),
                'net':net,'position_mm':_xy(pad.GetPosition(),pcbnew),'layers':[layer_names[layer] for layer in copper_layers if pad.IsOnLayer(layer)]})
    for zone in board.Zones():
        if zone.GetIsRuleArea() or str(zone.GetNetname()) not in returns:
            continue
        for layer in copper_layers:
            if not zone.IsOnLayer(layer):
                continue
            layer_name = layer_names[layer]
            if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                evidence["unfilled_reference_layers"].append(layer_name)
                continue
            filled = zone.GetFilledPolysList(layer)
            for i in range(filled.OutlineCount()):
                evidence["reference_regions"].append({
                    "net": str(zone.GetNetname()), "layer": layer_name,
                    "outer": _ring(filled.COutline(i), pcbnew),
                    "holes": [_ring(filled.CHole(i, h), pcbnew)
                              for h in range(filled.HoleCount(i))],
                })
    return evidence


def _on_segment(point: tuple[float, float], a: list[float], b: list[float]) -> bool:
    cross = (point[0]-a[0])*(b[1]-a[1])-(point[1]-a[1])*(b[0]-a[0])
    return abs(cross) < 1e-9 and min(a[0], b[0])-1e-9 <= point[0] <= max(a[0], b[0])+1e-9 and min(a[1], b[1])-1e-9 <= point[1] <= max(a[1], b[1])+1e-9


def _inside_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if _on_segment(point, a, b):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if point[0] < x:
                inside = not inside
    return inside


def _in_region(point: tuple[float, float], region: dict) -> bool:
    return _inside_ring(point, region["outer"]) and not any(
        _inside_ring(point, hole) for hole in region.get("holes", [])
    )


def _finding(level: str, code: str, detail: str, *, layer: str = "", position: list[float] | None = None) -> dict:
    return {"level": level, "code": code, "detail": detail,
            "layer": layer, "position_mm": position}


def audit_return_path(evidence: dict, *, sample_pitch_mm: float = 0.25,
                      return_via_radius_mm: float = 2.0, return_terminal_ids: list[str] | None = None, return_terminal_roles: dict[str,str] | None = None) -> dict:
    """Screen sampled track reference coverage and selected via transitions.

    A sampled clear route is never labelled a proved continuous return plane:
    gaps narrower than the sample pitch and parallel-plane coupling are unknown.
    Reference nets must be chosen by the user; name guessing is unsafe.
    """
    if not math.isfinite(sample_pitch_mm) or sample_pitch_mm <= 0:
        raise ValueError("Sample pitch must be finite and positive.")
    if not math.isfinite(return_via_radius_mm) or return_via_radius_mm <= 0:
        raise ValueError("Return-via radius must be finite and positive.")
    layers = list(evidence.get("layer_order", []))
    if len(layers) != len(set(layers)) or not layers:
        raise ValueError("Provide an ordered list of enabled copper layers.")
    if not evidence.get("signal_net") or not evidence.get("return_nets"):
        raise ValueError("Signal and explicit return net names are required.")
    if evidence["signal_net"] in evidence["return_nets"]:raise ValueError("Signal net and return nets must differ.")
    positions = {name: index for index, name in enumerate(layers)}
    regions = [item for item in evidence.get("reference_regions", [])
               if item.get("net") in evidence["return_nets"]]
    by_layer: dict[str, list[dict]] = {name: [] for name in layers}
    for region in regions:
        if region["layer"] in by_layer:
            by_layer[region["layer"]].append(region)
    # Cache conservative bounds once per audit. Avoid walking full zone outlines
    # for sampled points outside their bounding boxes on large boards.
    bounds={id(region):(min(p[0] for p in region['outer']),max(p[0] for p in region['outer']),min(p[1] for p in region['outer']),max(p[1] for p in region['outer'])) for region in regions if region.get('outer')}
    ray_cache={}
    hole_indices={}
    def prepare_ring(ring):
        cached=ray_cache.get(id(ring))
        if cached is None:
            low=min(p[1] for p in ring);step=max(.25,(max(p[1] for p in ring)-low)/64)
            bins={}
            for a,b in zip(ring,ring[1:]+ring[:1]):
                for band in range(math.floor((min(a[1],b[1])-low)/step),math.floor((max(a[1],b[1])-low)/step)+1):bins.setdefault(band,[]).append((a,b))
            cached=(low,step,bins)
            ray_cache[id(ring)]=cached
        return cached
    def in_ring(point,ring):
        if not ring:return False
        low,step,bins=prepare_ring(ring);inside=False
        for a,b in bins.get(math.floor((point[1]-low)/step),()):
            if _on_segment(point,a,b):return True
            if (a[1]>point[1])!=(b[1]>point[1]) and point[0]<a[0]+(point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]):inside=not inside
        return inside
    def contains(point,region):
        b=bounds.get(id(region))
        if not (b and b[0]<=point[0]<=b[1] and b[2]<=point[1]<=b[3] and in_ring(point,region['outer'])):
            return False
        # A selected route usually visits a tiny fraction of a filled plane's
        # thousands of holes. Prepare only rings that can contain a queried
        # point. Keep the existing boundary tolerance and ray test unchanged.
        index=hole_indices.get(id(region))
        if index is None:
            holes=[((min(p[0] for p in ring)-1e-9,max(p[0] for p in ring)+1e-9,
                     min(p[1] for p in ring)-1e-9,max(p[1] for p in ring)+1e-9),ring)
                   for ring in region.get('holes',[]) if ring]
            step=max(.25,math.sqrt(max((b[1]-b[0])*(b[3]-b[2]),.0625)/max(1,len(holes))))
            bins={};broad=[]
            for hole in holes:
                box=hole[0]
                x0,x1,y0,y1=(math.floor(value/step) for value in box)
                if (x1-x0+1)*(y1-y0+1)>256:
                    broad.append(hole)
                    continue
                for x in range(x0,x1+1):
                    for y in range(y0,y1+1):bins.setdefault((x,y),[]).append(hole)
            index=(step,bins,broad)
            hole_indices[id(region)]=index
        step,bins,broad=index
        holes=(*bins.get((math.floor(point[0]/step),math.floor(point[1]/step)),()),*broad)
        return not any(b[0]<=point[0]<=b[1] and b[2]<=point[1]<=b[3] and in_ring(point,ring)
                       for b,ring in holes)
    terminals=list(evidence.get('terminals',[]))
    if len(set(return_terminal_ids or []))!=len(return_terminal_ids or []):raise ValueError("Choose distinct return terminals.")
    declared_roles=dict(return_terminal_roles or {})
    if any(role not in ('source','load') for role in declared_roles):raise ValueError('Return pad roles must be source or load.')
    selected_terminals=[]
    for identifier in return_terminal_ids or []:
        matches=[row for row in terminals if row['net'] in evidence['return_nets'] and identifier in (row['id'],row['label'])]
        if len(matches)!=1:raise ValueError('Return terminal must identify one pad on a selected return net: '+str(identifier))
        selected_terminals.append(matches[0])
    resolved_roles={}
    for role,identifier in declared_roles.items():
        matches=[row for row in selected_terminals if identifier in (row['id'],row['label'])]
        if len(matches)!=1:raise ValueError('Declared return pad role must match one selected return terminal.')
        resolved_roles[role]=matches[0]
    endpoint_bins={}
    for segment in evidence.get('segments',[]):
        for xy in (segment['start'],segment['end']):
            endpoint_bins.setdefault((math.floor(xy[0]/.02),math.floor(xy[1]/.02)),[]).append((xy,segment['layer']))
    via_bins={}
    for via in evidence.get('return_vias',[]):
        if via.get('net') in evidence['return_nets']:
            xy=via['position'];via_bins.setdefault((math.floor(xy[0]/return_via_radius_mm),math.floor(xy[1]/return_via_radius_mm)),[]).append(via)
    coverage=[];transitions=[]
    unfilled = set(evidence.get("unfilled_reference_layers", []))
    findings: list[dict] = []
    segments = list(evidence.get("segments", []))
    if not segments:
        findings.append(_finding("unknown", "NO_ROUTED_TRACKS", "No routed straight signal tracks were supplied."))
    for segment in segments:
        layer = segment["layer"]
        if layer not in positions:
            raise ValueError("Signal segment uses an unknown copper layer: " + layer)
        a, b = segment["start"], segment["end"]
        length = math.dist(a, b)
        count = max(1, math.ceil(length / sample_pitch_mm))
        adjacent = [layers[i] for i in (positions[layer]-1, positions[layer]+1) if 0 <= i < len(layers)]
        if not adjacent or not any(by_layer[name] for name in adjacent):
            level = "unknown" if any(name in unfilled for name in adjacent) else "warning"
            findings.append(_finding(level, "NO_ADJACENT_REFERENCE",
                "No filled selected return-net zone was found on an adjacent copper layer; unfilled zones need refill before review."
                if level == "unknown" else "No filled selected return-net zone was found on an adjacent copper layer.",
                layer=layer, position=[(a[0]+b[0])/2, (a[1]+b[1])/2]))
            coverage.append({'signal_layer':layer,'start_mm':list(a),'end_mm':list(b),'length_mm':length,'sample_count':0,'covered_sample_count':0,'status':'NO_REFERENCE_EVIDENCE','references':[]})
            continue
        uncovered = None;covered=0;references=set()
        for i in range(count + 1):
            t = i / count
            point = (a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]))
            matches=[region for name in adjacent for region in by_layer[name] if contains(point,region)]
            if not matches:
                if uncovered is None:uncovered=list(point)
            else:
                covered+=1;references.update((r['net'],r['layer']) for r in matches)
        coverage.append({'signal_layer':layer,'start_mm':list(a),'end_mm':list(b),'length_mm':length,
                         'sample_count':count+1,'covered_sample_count':covered,'status':'SAMPLED_COVERED' if uncovered is None else 'GAP_SAMPLED',
                         'references':[{'net':net,'layer':name} for net,name in sorted(references)]})
        if uncovered is not None:
            findings.append(_finding("warning", "REFERENCE_GAP_SAMPLED",
                f"A sampled point lacks filled return copper on either adjacent layer (sample pitch {sample_pitch_mm:g} mm).",
                layer=layer, position=uncovered))
    for arc in evidence.get("unsupported_geometry", []):
        findings.append(_finding("unknown", "UNSUPPORTED_GEOMETRY",
            "Coverage for " + str(arc) + " was not checked."))
    # Only a via with routed segments on two distinct layers is a known signal
    # transition. A physical through-via may span unused copper layers.
    for via in evidence.get("signal_vias", []):
        xy = via["position"]
        connected=set();ex,ey=math.floor(xy[0]/.02),math.floor(xy[1]/.02)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for point,layer in endpoint_bins.get((ex+dx,ey+dy),()):
                    if math.dist(point,xy)<=.02:connected.add(layer)
        transition={'position_mm':list(xy),'signal_layers':sorted(connected,key=positions.get),'reference_layers':[],
                    'nearby_candidates':[],'status':'UNKNOWN','connectivity':'Not established by geometric review'}
        transitions.append(transition)
        if len(connected) < 2:
            findings.append(_finding("unknown", "TRANSITION_LAYERS_UNKNOWN",
                "Signal via has fewer than two evidenced connected routing layers; its return transfer cannot be assessed.",
                position=xy))
            continue
        # A signal-via center is normally an antipad void in its reference
        # plane. Preserve that void, but look for local reference candidates on
        # a declared annular sampling radius instead of treating it as copper.
        probe_radius=float(via.get('diameter_mm',0))
        probe_points=[tuple(xy)] if probe_radius<=0 else [tuple(xy)]+[(xy[0]+probe_radius*math.cos(i*math.pi/8),xy[1]+probe_radius*math.sin(i*math.pi/8)) for i in range(16)]
        adjacent_layers={layers[i] for layer in connected for i in (positions[layer]-1,positions[layer]+1) if 0<=i<len(layers)}
        local_regions={name:[region for region in by_layer[name] if any(contains(point,region) for point in probe_points)] for name in adjacent_layers}
        reference_layers={name for name in adjacent_layers if local_regions[name]}
        transition['reference_probe_radius_mm']=probe_radius
        transition['reference_basis']='Local annular samples around the signal antipad; no copper is assumed inside its drill/void.'
        transition['reference_layers']=sorted(reference_layers,key=positions.get)
        if len(reference_layers) < 2:
            findings.append(_finding("unknown", "REFERENCE_TRANSFER_UNKNOWN",
                "The selected filled zones do not identify two distinct local reference layers at the recorded annular probe radius.",
                position=xy))
            continue
        transition['reference_layers']=sorted(reference_layers,key=positions.get)
        reference_nets={region['net'] for name in reference_layers for region in local_regions[name]}
        transition['reference_nets']=sorted(reference_nets)
        if len(reference_nets)>1:
            findings.append(_finding('unknown','REFERENCE_NET_CHANGE','Different return nets cover this transition; a nearby via does not establish transfer between them.',position=xy))
        vx,vy=math.floor(xy[0]/return_via_radius_mm),math.floor(xy[1]/return_via_radius_mm)
        candidates=[item for dx in (-1,0,1) for dy in (-1,0,1) for item in via_bins.get((vx+dx,vy+dy),()) if math.dist(xy,item['position'])<=return_via_radius_mm]
        nearby=[]
        for item in sorted(candidates,key=lambda row:math.dist(xy,row['position'])):
            contact_layers=[]
            center=item['position'];radius=float(item.get('diameter_mm',0))/2
            # Sample the outer annulus because a plated drill center is a hole.
            samples=[tuple(center)] if radius<=0 else [(center[0]+(radius+1e-6)*math.cos(i*math.pi/8),center[1]+(radius+1e-6)*math.sin(i*math.pi/8)) for i in range(16)]
            for name in reference_layers:
                if name in item.get('layers',[]) and any(contains(point,region) for region in local_regions[name] if region['net']==item['net'] for point in samples):contact_layers.append(name)
            spans=reference_layers.issubset(set(item.get('layers',[])))
            contact=reference_layers.issubset(set(contact_layers))
            candidate={'id':item.get('id',''),'net':item['net'],'position_mm':list(center),'distance_mm':math.dist(xy,center),
                       'spans_reference_layers':spans,'sampled_contact_layers':sorted(contact_layers,key=positions.get),'contact_status':'SAMPLED_CONTACT' if contact else 'CONTACT_UNRESOLVED'}
            transition['nearby_candidates'].append(candidate)
            if spans:nearby.append(candidate)
        if nearby and len(reference_nets)==1 and any(item['contact_status']=='SAMPLED_CONTACT' for item in nearby):transition['status']='GEOMETRIC_CANDIDATE'
        elif nearby:
            findings.append(_finding('unknown','RETURN_VIA_CONTACT_UNKNOWN','A nearby spanning via was found but sampled contact to every local reference layer on its own net is not established.',position=xy))
        if not nearby:
            findings.append(_finding("warning", "NO_NEARBY_RETURN_VIA",
                f"No selected return-net via spanning the local reference layers lies within {return_via_radius_mm:g} mm.",
                position=xy))
    warnings = sum(item["level"] == "warning" for item in findings)
    unknowns = sum(item["level"] == "unknown" for item in findings)
    return {"signal_net": evidence["signal_net"], "return_nets": list(evidence["return_nets"]),
            "findings": findings, "warning_count": warnings, "unknown_count": unknowns,
            "status":"REVIEW" if warnings else "INCOMPLETE" if unknowns else "GEOMETRY_SCREENED",
            "coverage":coverage,"transitions":transitions,"selected_return_terminals":selected_terminals,"return_terminal_roles":resolved_roles,
            "return_terminal_inventory":[row for row in terminals if row['net'] in evidence['return_nets']],
            "signal_terminals":[row for row in terminals if row['net']==evidence['signal_net']],
            "settings":{"sample_pitch_mm":sample_pitch_mm,"return_via_radius_mm":return_via_radius_mm},
            "terminal_connectivity":"Explicit selected pads are declarations, not a solved closed return-current circuit.",
            "checked_segment_count": len(segments), "checked_signal_via_count": len(evidence.get("signal_vias", [])),
            "basis": "Sampled saved-board geometry; not a proof of return current, plane continuity, loop inductance, or impedance."}


def analyze_return_path(board: Any, signal_net: str, return_nets: list[str] | tuple[str, ...],
                        *, sample_pitch_mm: float = 0.25, return_via_radius_mm: float = 2.0, return_terminal_ids: list[str] | None = None, return_terminal_roles: dict[str,str] | None = None) -> dict:
    """Convenience entry point for a caller holding a native pcbnew BOARD."""
    evidence = collect_board_evidence(board, signal_net, return_nets)
    return audit_return_path(evidence, sample_pitch_mm=sample_pitch_mm,
                             return_via_radius_mm=return_via_radius_mm, return_terminal_ids=return_terminal_ids,
                             return_terminal_roles=return_terminal_roles)


def summary_text(result):
    """Describe declared terminals, sampled references and transition candidates."""
    settings=result.get('settings',{})
    lines=[str(result.get('status','INCOMPLETE'))+' · '+', '.join(result.get('return_nets',[])),
           result.get('scope','Whole signal net; no return-current or loop-impedance solve.'),
           'Pitch '+str(settings.get('sample_pitch_mm','?'))+' mm; stitching search '+str(settings.get('return_via_radius_mm','?'))+' mm.']
    pads=result.get('selected_return_terminals',[])
    lines.append('Declared return pads: '+(', '.join(row['label']+' ('+row['net']+')' for row in pads) if pads else 'Not specified; source/load return closure is unresolved.'))
    for role,pad in result.get('return_terminal_roles',{}).items():lines.append(role.title()+' return: '+pad['label']+' ('+pad['net']+')')
    lines.append('Return pad inventory: '+str(len(result.get('return_terminal_inventory',[])))+' pads on the selected return nets.')
    grouped={}
    for row in result.get('coverage',[]):
        item=grouped.setdefault(row['signal_layer'],{'covered':0,'total':0,'references':set(),'states':set(),'segments':0})
        item['covered']+=row['covered_sample_count'];item['total']+=row['sample_count'];item['segments']+=1
        item['references'].update(v['net']+' / '+v['layer'] for v in row['references']);item['states'].add(row['status'])
    for layer,item in grouped.items():
        refs=', '.join(sorted(item['references'])) or 'None evidenced'
        lines.append(f"{layer}: {item['segments']} segments; {item['covered']}/{item['total']} covered samples; {refs} [{', '.join(sorted(item['states']))}]")
    for row in result.get('transitions',[]):
        point=', '.join(f'{v:.5g}' for v in row['position_mm'])
        lines.append(f"Via at {point} mm: {' / '.join(row['signal_layers'])} -> {' / '.join(row['reference_layers']) or 'reference unresolved'} [{row['status']}]")
        lines.append('  Reference probe radius '+str(row.get('reference_probe_radius_mm',0))+' mm; local annular evidence, not copper inside the antipad.')
        for candidate in row['nearby_candidates'][:3]:
            lines.append(f"  {candidate['net']}: {candidate['distance_mm']:.5g} mm; span={candidate['spans_reference_layers']}; {candidate['contact_status']}; layers {', '.join(candidate['sampled_contact_layers']) or 'unresolved'}")
    if len(result.get('transitions',[]))>20:lines.append('More transitions are retained in the exported evidence tables/JSON.')
    lines.append(result.get('terminal_connectivity',''))
    lines.append(result['basis'])
    return '\n'.join(lines)


def html_details(result):
    """Return escaped, portable evidence tables for PI and SI HTML exports."""
    from html import escape
    def table(headers,rows):
        return '<div style="overflow:auto"><table><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table></div>'
    html='<h2>Explicit return-path review</h2><p>'+escape(result.get('scope','Whole selected signal net'))+'</p><pre>'+escape(summary_text(result))+'</pre>'
    html+=table(['Signal layer','Length mm','Covered / sampled','Reference net / layer','Status'],[
        [row['signal_layer'],f"{row['length_mm']:.6g}",f"{row['covered_sample_count']} / {row['sample_count']}",'; '.join(v['net']+' / '+v['layer'] for v in row['references']),row['status']] for row in result.get('coverage',[])])
    html+=table(['Signal via XY mm','Signal layers','Reference layers','Return candidate net','Distance mm','Spans layers','Sampled contact','Status'],[
        [', '.join(f'{v:.6g}' for v in row['position_mm']),', '.join(row['signal_layers']),', '.join(row['reference_layers']),candidate.get('net','None'),candidate.get('distance_mm','Unknown'),candidate.get('spans_reference_layers','Unknown'),', '.join(candidate.get('sampled_contact_layers',[])),candidate.get('contact_status',row['status'])]
        for row in result.get('transitions',[]) for candidate in row['nearby_candidates'] or [{}]])
    html+=table(['Level','Finding','Layer','XY mm','Detail'],[[row['level'],row['code'],row['layer'],row['position_mm'],row['detail']] for row in result.get('findings',[])])
    return html
