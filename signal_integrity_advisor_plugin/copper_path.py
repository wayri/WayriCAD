"""Layer-aware, conservative copper paths using KiCad's filled polygons.

This is a geometry model, not a current-distribution/field solver. Zone hops
require finite-width connected corridors through filled copper, including
navigation around holes. Missing geometry never falls back to aggregate nets.
"""
from __future__ import annotations

import heapq
import math
import re
import importlib.util
import os

IU = 1_000_000


def point(value):
    return (int(value.x), int(value.y))


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1]) / IU


def on_segment(p, a, b, tolerance=2):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    if not den:
        return None
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den
    if -1e-10 <= t <= 1 + 1e-10 and math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy) <= tolerance:
        return max(0., min(1., t))
    return None


def ground_name(name):
    """Conservative name heuristic; coverage is checked independently."""
    return bool(re.search(r"(?:^|[/_+\-])(GND|AGND|DGND|PGND|SGND|VSS|GROUND)(?:$|[_\-\d])", str(name), re.I))


def via_layers(via, layers):
    """Physical drilled span, independent of which unused annuli are flashed."""
    for name in ('GetSecondaryDrillSize', 'GetTertiaryDrillSize'):
        if getattr(via, name, lambda: None)() is not None:
            raise ValueError('Backdrilled/stepped vias need an explicit barrel model; not supported.')
    if not hasattr(via, 'TopLayer') or not hasattr(via, 'BottomLayer'):
        raise ValueError('Via physical start/end layers are unavailable.')
    a, b = via.TopLayer(), via.BottomLayer()
    if a not in layers or b not in layers or layers.index(a) >= layers.index(b):
        raise ValueError('Via physical span does not match the saved copper stack.')
    return layers[layers.index(a):layers.index(b)+1]


def routing_ambiguity(graph, start):
    """Conservative branch/cycle evidence after ideal contact nodes collapse."""
    seen, pending, parent = set(), [start], {}
    while pending:
        node = pending.pop()
        if node in seen:continue
        seen.add(node);parent[node] = node
        pending.extend(target for target, _ in graph.get(node, ()))
    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]];node = parent[node]
        return node
    for node in seen:
        for target, edge in graph.get(node, ()):
            if edge.get('kind') not in ('track', 'via'):
                parent[root(node)] = root(target)
    links, identities, degree = [], set(), {}
    for node in seen:
        for target, edge in graph.get(node, ()):
            if edge.get('kind') not in ('track', 'via') or id(edge) in identities:continue
            identities.add(id(edge))
            a, b = root(node), root(target)
            if a == b:continue
            links.append((a,b));degree[a] = degree.get(a,0)+1;degree[b] = degree.get(b,0)+1
    # The remaining connected multigraph has a cycle iff E >= V.
    return {'branched': any(value > 2 for value in degree.values()),
            'alternate_paths': bool(degree) and len(links) >= len(degree),
            'basis': 'Shortest geometric candidate; not solved current distribution'}


def shortest_path(graph, start, end):
    queue = [(0., 0, start)]
    distances = {start: 0.}
    parents = {}
    serial = 0
    while queue:
        cost, _, node = heapq.heappop(queue)
        if cost != distances[node]:
            continue
        if node == end:
            edges = []
            while node != start:
                previous, edge = parents[node]
                if edge.get('kind') == 'via' and edge.get('_node_a') != previous:
                    edge = dict(edge, layer=edge['end_layer'], end_layer=edge['layer'])
                edges.append(edge)
                node = previous
            return list(reversed(edges))
        for target, edge in graph.get(node, []):
            value = cost + max(float(edge.get('length_mm', 0)), 1e-12)
            if value < distances.get(target, math.inf):
                distances[target] = value
                parents[target] = (node, edge)
                serial += 1
                heapq.heappush(queue, (value, serial, target))
    return None


class CopperGeometry:
    def __init__(self, engine):
        import pcbnew
        self.pcb = pcbnew
        self.engine = engine
        self.board = engine.board
        self.layers = list(self.board.GetEnabledLayers().CuStack())
        self.islands = []
        self.notes = []
        self._navigation_cache = {}
        self._routing_prepared = set()
        self._lateral_drawings = {}
        self._fit_cache = {}
        self._reference_tiles = {}
        for shape in self.board.GetDrawings():
            layer = shape.GetLayer()
            if layer in self.layers and hasattr(shape, 'TransformShapeToPolygon'):
                self._lateral_drawings.setdefault(layer, []).append(shape)
        for zone in self.board.Zones():
            if getattr(zone, 'GetIsRuleArea', lambda: False)():
                continue
            for layer in self.layers:
                if not zone.IsOnLayer(layer) or not zone.HasFilledPolysForLayer(layer):
                    continue
                filled = zone.GetFilledPolysList(layer)
                for index in range(filled.OutlineCount()):
                    poly = pcbnew.SHAPE_POLY_SET()
                    poly.AddOutline(filled.COutline(index))
                    for hole in range(filled.HoleCount(index)):
                        poly.AddHole(filled.CHole(index, hole), 0)
                    uuid = zone.m_Uuid.AsString()
                    self.islands.append(dict(id=f'{uuid}:{layer}:{index}', net=str(zone.GetNetname()),
                        layer=layer, island=index, poly=poly, item=zone, area_mm2=poly.Area() / IU ** 2))

    def polygon(self, points):
        poly = self.pcb.SHAPE_POLY_SET()
        chain = self.pcb.SHAPE_LINE_CHAIN()
        for x, y in points:
            chain.Append(int(round(x)), int(round(y)))
        chain.SetClosed(True)
        poly.AddOutline(chain)
        return poly

    def corridor(self, a, b, width_mm):
        length = distance(a, b) * IU
        if length < 1:
            # A small finite terminal square keeps area calculations defined.
            r = max(1, width_mm * IU / 2)
            return self.polygon([(a[0]-r,a[1]-r),(a[0]+r,a[1]-r),(a[0]+r,a[1]+r),(a[0]-r,a[1]+r)])
        scale = width_mm * IU / (2 * length)
        dx, dy = (b[0] - a[0]) * scale, (b[1] - a[1]) * scale
        return self.polygon([(a[0]-dy,a[1]+dx),(b[0]-dy,b[1]+dx),(b[0]+dy,b[1]-dx),(a[0]+dy,a[1]-dx)])

    def contains(self, island, p):
        return island['poly'].Contains(self.pcb.VECTOR2I(*p))

    def fits(self, island, a, b, width_mm, routing=False):
        poly = island.get('routing_poly',island['poly']) if routing else island['poly']
        key = (id(poly), tuple(a), tuple(b), float(width_mm))
        if key in self._fit_cache:
            return self._fit_cache[key]
        if not poly.Contains(self.pcb.VECTOR2I(*a)) or not poly.Contains(self.pcb.VECTOR2I(*b)):
            if len(self._fit_cache) < 8192:self._fit_cache[key] = False
            return False
        missing = self.corridor(a, b, width_mm)
        # The complete corridor lies inside this integer-aligned rectangle.
        # Subtracting (plane intersect rectangle) is therefore the same set
        # operation within the corridor, without revisiting remote plane holes.
        # Cache only this measure's native geometry; measure() creates a new
        # CopperGeometry after board edits. Bound retained clipped polygons.
        box = missing.BBox()
        pitch = 25 * IU
        bounds = (math.floor(box.GetLeft()/pitch)*pitch-1000,
                  math.floor(box.GetTop()/pitch)*pitch-1000,
                  math.ceil(box.GetRight()/pitch)*pitch+1000,
                  math.ceil(box.GetBottom()/pitch)*pitch+1000)
        tile_key = (id(poly), bounds)
        local = self._reference_tiles.get(tile_key)
        if local is None and len(self._reference_tiles) < 128:
            left, top, right, bottom = bounds
            region = self.polygon([(left,top),(right,top),(right,bottom),(left,bottom)])
            local = self.pcb.SHAPE_POLY_SET(poly)
            local.BooleanIntersection(region)
            self._reference_tiles[tile_key] = local
        missing.BooleanSubtract(poly if local is None else local)
        answer = missing.Area() <= 4  # four square internal units, rounding only
        if len(self._fit_cache) < 8192:self._fit_cache[key] = answer
        return answer

    def prepare_routing(self,net):
        """Union actual pad copper into touching fill, preserving thermal voids.

        Disjoint pads remain separate outlines and are discarded. This gives
        thermal spokes a real path from the terminal instead of jumping a gap.
        Original filled geometry/area stays intact for reference and C reports.
        """
        if net in self._routing_prepared:return
        self._routing_prepared.add(net)
        pads=[pad for group in self.pads(net).values() for pad in group]
        for island in self.islands:
            if island['net']!=net:continue
            combined=self.pcb.SHAPE_POLY_SET(island['poly'])
            for pad in pads:
                if not pad.IsOnLayer(island['layer']):continue
                if not pad.GetBoundingBox().Intersects(island['poly'].BBox()):continue
                copper=self.pcb.SHAPE_POLY_SET()
                pad.TransformShapeToPolygon(copper,island['layer'],0,1000,self.pcb.ERROR_INSIDE)
                combined.BooleanAdd(copper)
            # Extract only components containing original fill. An isolated pad
            # placed inside a clearance hole must not become a connected terminal.
            kept=self.pcb.SHAPE_POLY_SET()
            for i in range(combined.OutlineCount()):
                part=self.pcb.SHAPE_POLY_SET();part.AddOutline(combined.COutline(i))
                for h in range(combined.HoleCount(i)):part.AddHole(combined.CHole(i,h),0)
                overlap=self.pcb.SHAPE_POLY_SET(part);overlap.BooleanIntersection(island['poly'])
                if overlap.Area()>0:kept.BooleanAdd(part)
            island['routing_poly']=kept

    def navigation(self,island,width_mm):
        key=(island['id'],width_mm)
        if key not in self._navigation_cache:
            try:
                from .zone_navigation import ZoneNavigation
            except ImportError:
                spec=importlib.util.spec_from_file_location('_wayricad_zone_navigation',os.path.join(os.path.dirname(__file__),'zone_navigation.py'))
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                ZoneNavigation=module.ZoneNavigation
            self._navigation_cache[key]=ZoneNavigation(self,island,width_mm)
        return self._navigation_cache[key]

    def arc_pieces(self,item):
        """Chords for coverage/contact checks; retain exact circular arc length."""
        a,m,b=point(item.GetStart()),point(item.GetMid()),point(item.GetEnd())
        c=point(item.GetCenter());radius=distance(a,c)*IU
        if radius<=0:raise ValueError('Arc has zero radius.')
        angles=[math.atan2(p[1]-c[1],p[0]-c[0]) for p in (a,m,b)]
        sweep=(angles[2]-angles[0])%(2*math.pi)
        if (angles[1]-angles[0])%(2*math.pi)>sweep:sweep-=2*math.pi
        maximum=2*math.acos(max(-1.,min(1.,1-1000/radius)))
        count=max(2,math.ceil(abs(sweep)/max(maximum,1e-6)))
        points=[a]+[(round(c[0]+radius*math.cos(angles[0]+sweep*i/count)),
                     round(c[1]+radius*math.sin(angles[0]+sweep*i/count))) for i in range(1,count)]+[b]
        exact=item.GetLength()/IU/count
        return [(p,q,exact/max(distance(p,q),1e-15)) for p,q in zip(points,points[1:])]

    def reference(self, signal_layer, a, b, width_mm, reference_layer='Auto', net='', all_matches=False):
        """Nearest named-ground filled island covering the entire corridor.

        Explicit layer selection still requires ground copper coverage. An
        intermediate copper layer blocks claiming a simple single-plane model.
        """
        candidates = []
        order = {layer: i for i, layer in enumerate(self.layers)}
        for island in self.islands:
            layer = island['layer']
            if layer == signal_layer or island['net'] == net:
                continue
            if reference_layer in ('Auto', '', None) and not ground_name(island['net']):
                continue
            name = self.engine._layer_name(layer)
            if reference_layer not in ('Auto', '', None) and name != reference_layer:
                continue
            if not self.fits(island, a, b, width_mm):
                continue
            if abs(order[layer] - order[signal_layer]) != 1:
                continue
            h, er = self.engine.dielectric_to_reference(self.engine._layer_name(signal_layer), name)
            candidates.append((h, name, er, island))
        counts = {}
        for row in candidates:counts[row[1]] = counts.get(row[1],0)+1
        if any(count > 1 for count in counts.values()):
            self.notes.append('Overlapping reference candidates on one layer are ambiguous; no candidate is chosen on that layer.')
        candidates = [row for row in candidates if counts[row[1]] == 1]
        if all_matches:
            return candidates
        return min(candidates, key=lambda x: x[0]) if candidates else None

    def overlap(self, polygon, reference):
        clipped = self.pcb.SHAPE_POLY_SET(polygon)
        clipped.BooleanIntersection(reference['poly'])
        return max(0., clipped.Area() / IU ** 2)

    def lateral_copper_near(self, layer, a, b, width_mm):
        """Detect same-layer copper close enough to invalidate plain microstrip.

        This is a conservative topology guard, not a CPW gap measurement or
        a coupled-line solver. Filled zones and copper graphics are included.
        """
        probe = self.corridor(a, b, width_mm + 2 * max(.5, width_mm))
        probe.BooleanSubtract(self.corridor(a, b, width_mm))
        box = probe.BBox()
        candidates = (island['poly'] for island in self.islands if island['layer'] == layer)
        for poly in candidates:
            if not box.Intersects(poly.BBox()):
                continue
            overlap = self.pcb.SHAPE_POLY_SET(poly)
            overlap.BooleanIntersection(probe)
            if overlap.Area() > 4:
                return True
        for shape in self._lateral_drawings.get(layer, ()):
            if not box.Intersects(shape.GetBoundingBox()):
                continue
            poly = self.pcb.SHAPE_POLY_SET()
            try:
                shape.TransformShapeToPolygon(poly, layer, 0, 1000, self.pcb.ERROR_INSIDE)
            except (TypeError, RuntimeError):
                continue
            poly.BooleanIntersection(probe)
            if poly.Area() > 4:
                return True
        return False

    def pads(self, net):
        out = {}
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if str(pad.GetNetname()) == net:
                    out.setdefault(f'{fp.GetReference()}.{pad.GetNumber()}', []).append(pad)
        return out

    def via_evidence(self, edge):
        via = edge['item']
        span = via_layers(via, self.layers)
        names = [self.engine._layer_name(layer) for layer in span]
        kind = ('through' if span[0] == self.layers[0] and span[-1] == self.layers[-1]
                else 'blind' if span[0] == self.layers[0] or span[-1] == self.layers[-1] else 'buried')
        if via.GetViaType() == getattr(self.pcb, 'VIATYPE_MICROVIA', None):kind = 'microvia'
        evidence = dict(via_type=kind, physical_layers=names,
                        physical_length_mm=self.engine.via_span_mm(span[0],span[-1]),
                        length_basis='Saved stackup copper midplanes; end-face overhang not included',
                        barrel_model='Constant circular drill and assumed plating; microvia taper is not extracted')
        if edge.get('scope') == 'bulk_barrel_slice':
            evidence.update(stub_status='not_evaluated_without_terminal_path',
                            connected_path_span=None, remaining_barrel=None)
            return evidence
        a, b = sorted((span.index(edge['layer']),span.index(edge['end_layer'])))
        remaining = []
        for first, last in ((0,a),(b,len(span)-1)):
            if first != last:
                remaining.append(dict(start_layer=names[first],end_layer=names[last],
                    length_mm=self.engine.via_span_mm(span[first],span[last]),
                    termination='unverified_open_stub_or_connected_branch',
                    capacitance_pf=None,input_impedance_ohm=None,resonance_hz=None))
        evidence.update(connected_path_span=dict(start_layer=self.engine._layer_name(edge['layer']),
                        end_layer=self.engine._layer_name(edge['end_layer']),length_mm=edge['length_mm']),
                        remaining_barrel=remaining,
                        stub_status='candidate_extensions_unmodeled' if remaining else 'no_extension_beyond_selected_span')
        return evidence

    def path(self, net, start, end, corridor_width_mm=.2):
        graph = {}
        def add(node_a, node_b, **edge):
            edge.setdefault('length_mm', 0.)
            edge['_node_a'] = node_a
            graph.setdefault(node_a, []).append((node_b, edge))
            graph.setdefault(node_b, []).append((node_a, edge))
        pads = self.pads(net)
        if start not in pads or end not in pads or start == end:
            return None, ['Select two distinct pads on the selected net.']
        if len(pads[start]) != 1 or len(pads[end]) != 1:
            return None, ['Endpoint pad label is ambiguous; duplicate pad numbers need explicit physical-pad selection.']
        self.prepare_routing(net)
        nodes = set()
        tracks = []
        vias = []
        for item in self.board.GetTracks():
            if str(item.GetNetname()) != net:
                continue
            if isinstance(item, self.pcb.PCB_VIA):
                vias.append(item)
                for layer in via_layers(item, self.layers):
                    nodes.add((*point(item.GetPosition()), layer))
            elif isinstance(item, self.pcb.PCB_ARC):
                for a,b,scale in self.arc_pieces(item):
                    layer=item.GetLayer()
                    tracks.append((a,b,layer,item,scale))
                    nodes.update([(*a,layer),(*b,layer)])
            else:
                a, b, layer = point(item.GetStart()), point(item.GetEnd()), item.GetLayer()
                tracks.append((a, b, layer, item,1.))
                nodes.update([(*a, layer), (*b, layer)])
        for key, values in pads.items():
            for pad in values:
                p = point(pad.GetPosition())
                for layer in self.layers:
                    if pad.IsOnLayer(layer):
                        nodes.add((*p, layer))
        # Endpoints on a same-layer centreline split that track. Endpoints on
        # different layers remain separate, even at identical coordinates.
        for a, b, layer, item,length_scale in tracks:
            split = [(t, n) for n in nodes if n[2] == layer and (t := on_segment(n[:2], a, b)) is not None]
            split.sort()
            for (_, na), (_, nb) in zip(split, split[1:]):
                if na != nb:
                    add(na, nb, kind='track', layer=layer, a=na[:2], b=nb[:2], item=item,
                        length_mm=distance(na, nb)*length_scale, width_mm=item.GetWidth() / IU,
                        geometry='arc (exact length, 1 um chord approximation)' if isinstance(item,self.pcb.PCB_ARC) else 'straight')
        for key, values in pads.items():
            for pad in values:
                # Only geometrically contained, layer-correct contacts; no
                # nearest-node jump, and NPTH pads cannot bridge copper layers.
                contacts = [n for n in nodes if pad.IsOnLayer(n[2]) and pad.HitTest(self.pcb.VECTOR2I(*n[:2]), 0, n[2])]
                is_plated = pad.GetAttribute() == self.pcb.PAD_ATTRIB_PTH
                identity = pad.m_Uuid.AsString()
                for n in contacts:
                    terminal = ('pad', identity) if is_plated else ('pad', identity, n[2])
                    add(terminal, n, kind='pad', item=pad, layer=n[2])
                for n in contacts:
                    if key in (start, end):
                        add(key, ('pad', identity) if is_plated else ('pad', identity, n[2]), kind='terminal')
        for via in vias:
            position = point(via.GetPosition())
            span = via_layers(via, self.layers)
            for la, lb in zip(span, span[1:]):
                length = self.engine.via_span_mm(la,lb)
                add((*position, la), (*position, lb), kind='via', item=via, layer=la, end_layer=lb,
                    a=position, b=position, length_mm=length, drill_mm=via.GetDrillValue()/IU)
        for island in self.islands:
            if island['net'] != net:
                continue
            navigation=self.navigation(island,corridor_width_mm)
            for n in nodes:
                if n[2]!=island['layer']:continue
                component=navigation.component(n[:2])
                if component is not None:
                    add(n,('island',island['id'],component),kind='zone_contact',contact=n,
                        island=island,navigation=navigation,component=component)
        edges=shortest_path(graph,start,end)
        if edges is None:return None,list(dict.fromkeys(self.notes))
        self.path_evidence = routing_ambiguity(graph, start)
        resolved=[];index=0
        while index<len(edges):
            edge=edges[index]
            if edge['kind']!='zone_contact':resolved.append(edge);index+=1;continue
            if index+1>=len(edges) or edges[index+1]['kind']!='zone_contact':
                return None,['Internal zone path could not be paired.']
            other=edges[index+1];island=edge['island']
            route=edge['navigation'].route(edge['contact'][:2],other['contact'][:2],edge['component'])
            if route is None:return None,['Finite-width copper navigation could not resolve this island path.']
            for a,b in zip(route,route[1:]):
                resolved.append(dict(kind='zone',layer=island['layer'],a=a,b=b,item=island['item'],island=island,
                    length_mm=distance(a,b),width_mm=corridor_width_mm,geometry='filled-copper corridor'))
            index+=2
        if any(edge['kind']=='zone' for edge in resolved):
            self.notes.append('Zone topology is resolved through filled islands; reported corridor is visibility-shortened, not a globally shortest current-distribution solution.')
        return resolved,list(dict.fromkeys(self.notes))
