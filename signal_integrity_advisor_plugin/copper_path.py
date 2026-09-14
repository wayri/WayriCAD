"""Layer-aware, conservative copper paths using KiCad's filled polygons.

This is a geometry model, not a current-distribution/field solver. Zone hops
are allowed only when a finite-width straight corridor fits inside one filled
island. Missing or unsupported geometry never falls back to aggregate nets.
"""
from __future__ import annotations

import heapq
import math
import re

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

    def fits(self, island, a, b, width_mm):
        if not self.contains(island, a) or not self.contains(island, b):
            return False
        missing = self.corridor(a, b, width_mm)
        missing.BooleanSubtract(island['poly'])
        return missing.Area() <= 4  # four square internal units, rounding only

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
        if all_matches:
            return candidates
        return min(candidates, key=lambda x: x[0]) if candidates else None

    def overlap(self, polygon, reference):
        clipped = self.pcb.SHAPE_POLY_SET(polygon)
        clipped.BooleanIntersection(reference['poly'])
        return max(0., clipped.Area() / IU ** 2)

    def pads(self, net):
        out = {}
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if str(pad.GetNetname()) == net:
                    out.setdefault(f'{fp.GetReference()}.{pad.GetNumber()}', []).append(pad)
        return out

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
        nodes = set()
        tracks = []
        vias = []
        for item in self.board.GetTracks():
            if str(item.GetNetname()) != net:
                continue
            if isinstance(item, self.pcb.PCB_VIA):
                vias.append(item)
                for layer in self.layers:
                    if item.IsOnLayer(layer):
                        nodes.add((*point(item.GetPosition()), layer))
            elif isinstance(item, self.pcb.PCB_ARC):
                self.notes.append('Arc copper is not traversed; a path needing it remains unresolved.')
            else:
                a, b, layer = point(item.GetStart()), point(item.GetEnd()), item.GetLayer()
                tracks.append((a, b, layer, item))
                nodes.update([(*a, layer), (*b, layer)])
        for key, values in pads.items():
            for pad in values:
                p = point(pad.GetPosition())
                for layer in self.layers:
                    if pad.IsOnLayer(layer):
                        nodes.add((*p, layer))
        # Endpoints on a same-layer centreline split that track. Endpoints on
        # different layers remain separate, even at identical coordinates.
        for a, b, layer, item in tracks:
            split = [(t, n) for n in nodes if n[2] == layer and (t := on_segment(n[:2], a, b)) is not None]
            split.sort()
            for (_, na), (_, nb) in zip(split, split[1:]):
                if na != nb:
                    add(na, nb, kind='track', layer=layer, a=na[:2], b=nb[:2], item=item,
                        length_mm=distance(na, nb), width_mm=item.GetWidth() / IU)
        for key, values in pads.items():
            for pad in values:
                # Only geometrically contained, layer-correct contacts; no
                # nearest-node jump, and NPTH pads cannot bridge copper layers.
                contacts = [n for n in nodes if pad.IsOnLayer(n[2]) and pad.HitTest(self.pcb.VECTOR2I(*n[:2]), 0, n[2])]
                is_plated = pad.GetAttribute() == self.pcb.PAD_ATTRIB_PTH
                for n in contacts:
                    terminal = ('pad', key) if is_plated else ('pad', key, n[2])
                    add(terminal, n, kind='pad', item=pad, layer=n[2])
                for n in contacts:
                    if key in (start, end):
                        add(key, ('pad', key) if is_plated else ('pad', key, n[2]), kind='terminal')
        for via in vias:
            position = point(via.GetPosition())
            span = [layer for layer in self.layers if via.IsOnLayer(layer)]
            for la, lb in zip(span, span[1:]):
                length = self.engine.via_span_mm(la,lb)
                add((*position, la), (*position, lb), kind='via', item=via, layer=la, end_layer=lb,
                    a=position, b=position, length_mm=length, drill_mm=via.GetDrillValue()/IU)
        for island in self.islands:
            if island['net'] != net:
                continue
            contacts = [n for n in nodes if n[2] == island['layer'] and self.contains(island, n[:2])]
            if len(contacts) > 128:
                self.notes.append('A filled island has more than 128 contacts; automatic corridor search omitted it. Use a terminal-defined zone measurement.')
                continue
            for i, a in enumerate(contacts):
                for b in contacts[i+1:]:
                    if self.fits(island, a[:2], b[:2], corridor_width_mm):
                        add(a,b,kind='zone',layer=island['layer'],a=a[:2],b=b[:2],
                            item=island['item'],island=island,length_mm=distance(a,b),width_mm=corridor_width_mm)
        return shortest_path(graph, start, end), list(dict.fromkeys(self.notes))
