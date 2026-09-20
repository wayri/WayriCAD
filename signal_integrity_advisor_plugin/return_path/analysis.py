"""Geometry-based return-path and discontinuity checks."""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable

try:
    from .diff_pairs import find_mate as _shared_find_mate
except ImportError:  # Direct-file execution (automation) has no package parent.
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("_wayricad_diff_pairs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "diff_pairs.py"))
    _diff_pairs = _ilu.module_from_spec(_spec)
    sys.modules[_spec.name] = _diff_pairs
    _spec.loader.exec_module(_diff_pairs)
    _shared_find_mate = _diff_pairs.find_mate


@dataclass(frozen=True)
class CopperSegment:
    net: str
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float
    length_mm: float | None = None


@dataclass(frozen=True)
class ViaPoint:
    net: str
    position: tuple[float, float]
    layers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceRegion:
    net: str
    layer: str
    bounds: tuple[float, float, float, float]
    outline: tuple[tuple[float,float], ...] = ()
    holes: tuple[tuple[tuple[float,float], ...], ...] = ()
    native_poly: object = field(default=None,repr=False,compare=False)
    _edge_bins: dict = field(default_factory=dict,repr=False,compare=False)

    def __post_init__(self):
        x1,y1,x2,y2=self.bounds
        outline=self.outline or ((x1,y1),(x2,y1),(x2,y2),(x1,y2))
        object.__setattr__(self,'outline',tuple(outline))
        for ring in (outline,)+self.holes:
            for a,b in zip(ring,ring[1:]+ring[:1]):
                for x in range(math.floor(min(a[0],b[0])/5),math.floor(max(a[0],b[0])/5)+1):
                    for y in range(math.floor(min(a[1],b[1])/5),math.floor(max(a[1],b[1])/5)+1):
                        self._edge_bins.setdefault((x,y),[]).append((a,b))

    def contains(self, point: tuple[float, float]) -> bool:
        x1, y1, x2, y2 = self.bounds
        if not (min(x1,x2)<=point[0]<=max(x1,x2) and min(y1,y2)<=point[1]<=max(y1,y2)):
            return False
        if self.native_poly is not None:
            import pcbnew
            return bool(self.native_poly.Contains(pcbnew.VECTOR2I(round(point[0]*1e6),round(point[1]*1e6))))
        return _inside(point,self.outline) and not any(_inside(point,hole) for hole in self.holes)

    def covers(self,segment):
        a,b=segment.start,segment.end;length=math.hypot(b[0]-a[0],b[1]-a[1])
        if length<1e-12:return self.contains(a)
        dx=(b[0]-a[0])*segment.width_mm/(2*length);dy=(b[1]-a[1])*segment.width_mm/(2*length)
        rectangle=((a[0]-dy,a[1]+dx),(b[0]-dy,b[1]+dx),(b[0]+dy,b[1]-dx),(a[0]+dy,a[1]-dx))
        if not all(self.contains(p) for p in rectangle):return False
        x1,y1=min(p[0] for p in rectangle),min(p[1] for p in rectangle)
        x2,y2=max(p[0] for p in rectangle),max(p[1] for p in rectangle)
        seen=set()
        for x in range(math.floor(x1/5),math.floor(x2/5)+1):
            for y in range(math.floor(y1/5),math.floor(y2/5)+1):
                for p,q in self._edge_bins.get((x,y),[]):
                    if (p,q) in seen:continue
                    seen.add((p,q))
                    if max(p[0],q[0])<x1 or min(p[0],q[0])>x2 or max(p[1],q[1])<y1 or min(p[1],q[1])>y2:continue
                    if _inside(p,rectangle) or _inside(q,rectangle):return False
                    if any(_crosses(p,q,u,v) for u,v in zip(rectangle,rectangle[1:]+rectangle[:1])):return False
        return True


def _inside(p,ring):
    inside=False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        cross=(p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])
        if abs(cross)<1e-10 and min(a[0],b[0])-1e-10<=p[0]<=max(a[0],b[0])+1e-10 and min(a[1],b[1])-1e-10<=p[1]<=max(a[1],b[1])+1e-10:return True
        if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:inside=not inside
    return inside


def _crosses(a,b,c,d):
    cross=lambda p,q,r:(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return cross(a,b,c)*cross(a,b,d)<-1e-16 and cross(c,d,a)*cross(c,d,b)<-1e-16


def _point_segment_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
    t=max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0.
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


def collect_board_geometry(board):
    """Read native filled polygons, arc geometry and complete via layer spans."""
    import pcbnew
    layers=list(board.GetEnabledLayers().CuStack())
    names={layer:str(board.GetLayerName(layer)) for layer in layers}
    segments=[];vias=[];regions=[]
    xy=lambda p:(p.x/1e6,p.y/1e6)
    for item in board.GetTracks():
        net=str(item.GetNetname())
        if isinstance(item,pcbnew.PCB_VIA):
            vias.append(ViaPoint(net,xy(item.GetPosition()),tuple(names[l] for l in layers if item.IsOnLayer(l))))
        elif isinstance(item,pcbnew.PCB_ARC):
            a,m,b,c=map(xy,(item.GetStart(),item.GetMid(),item.GetEnd(),item.GetCenter()))
            radius=math.hypot(a[0]-c[0],a[1]-c[1]);angles=[math.atan2(p[1]-c[1],p[0]-c[0]) for p in (a,m,b)]
            sweep=(angles[2]-angles[0])%(2*math.pi)
            if (angles[1]-angles[0])%(2*math.pi)>sweep:sweep-=2*math.pi
            angle=2*math.acos(max(-1.,min(1.,1-.001/max(radius,1e-9))))
            count=max(2,math.ceil(abs(sweep)/max(angle,1e-6)))
            points=[a]+[(c[0]+radius*math.cos(angles[0]+sweep*i/count),c[1]+radius*math.sin(angles[0]+sweep*i/count)) for i in range(1,count)]+[b]
            for p,q in zip(points,points[1:]):
                segments.append(CopperSegment(net,names[item.GetLayer()],p,q,item.GetWidth()/1e6+.002,item.GetLength()/1e6/count))
        else:
            segments.append(CopperSegment(net,names[item.GetLayer()],xy(item.GetStart()),xy(item.GetEnd()),item.GetWidth()/1e6))
    grouped={}
    for zone in board.Zones():
        if zone.GetIsRuleArea():continue
        for layer in layers:
            if not zone.IsOnLayer(layer) or not zone.HasFilledPolysForLayer(layer):continue
            key=(str(zone.GetNetname()),names[layer])
            grouped.setdefault(key,pcbnew.SHAPE_POLY_SET()).BooleanAdd(zone.GetFilledPolysList(layer))
    for (net,layer),filled in grouped.items():
        for index in range(filled.OutlineCount()):
            poly=pcbnew.SHAPE_POLY_SET();poly.AddOutline(filled.COutline(index))
            for h in range(filled.HoleCount(index)):poly.AddHole(filled.CHole(index,h),0)
            ring=lambda chain:tuple(xy(chain.CPoint(i)) for i in range(chain.PointCount()))
            outline=ring(poly.COutline(0));holes=tuple(ring(poly.CHole(0,h)) for h in range(poly.HoleCount(0)))
            bounds=(min(p[0] for p in outline),min(p[1] for p in outline),max(p[0] for p in outline),max(p[1] for p in outline))
            regions.append(ReferenceRegion(net,layer,bounds,outline,holes,poly))
    return segments,vias,regions


@dataclass
class Finding:
    severity: str
    check: str
    net: str
    layer: str
    x_mm: float
    y_mm: float
    detail: str
    remedy: str


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    segments: list[CopperSegment] = field(default_factory=list)
    vias: list[ViaPoint] = field(default_factory=list)


class ReturnPathAnalyzer:
    def __init__(self, ground_patterns: Iterable[str] = ("GND", "AGND", "DGND", "PGND", "VSS")) -> None:
        self.ground_patterns = tuple(value.upper() for value in ground_patterns if value)

    def is_return_net(self, net: str) -> bool:
        upper = net.upper().strip("/ ")
        return any(re.search(r'(?:^|[/_+\-])'+re.escape(token.strip())+r'(?:$|[_\-\d])',upper) for token in self.ground_patterns)

    @staticmethod
    def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _key(point: tuple[float, float], tolerance_mm: float = 0.02) -> tuple[int, int]:
        return round(point[0] / tolerance_mm), round(point[1] / tolerance_mm)

    def audit(self, segments: Iterable[CopperSegment], vias: Iterable[ViaPoint],
              references: Iterable[ReferenceRegion], return_via_radius_mm: float = 2.0,
              stub_limit_mm: float = 5.0, differential_gap_limit_mm: float = 1.0,
              differential_skew_limit_mm: float = 0.5, layer_order: Iterable[str] = ()) -> AuditResult:
        signal_segments = [segment for segment in segments if segment.net and not self.is_return_net(segment.net)]
        all_vias = list(vias); regions = list(references); findings: list[Finding] = []
        return_vias = [via for via in all_vias if self.is_return_net(via.net)]
        order={layer:i for i,layer in enumerate(layer_order)}

        for via in (item for item in all_vias if item.net and not self.is_return_net(item.net)):
            nearest = min((self._distance(via.position, ground.position) for ground in return_vias
                           if via.layers and set(via.layers).issubset(ground.layers)), default=math.inf)
            if nearest > return_via_radius_mm:
                findings.append(Finding(
                    "warning", "Layer transition return via", via.net, "/".join(via.layers), *via.position,
                    f"No configured return-net via covering these layers within {return_via_radius_mm:g} mm; nearest is " +
                    ("unavailable." if math.isinf(nearest) else f"{nearest:.2f} mm."),
                    "Add a return via beside the signal transition or verify an uninterrupted plane transition.",
                ))

        for segment in signal_segments:
            midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
            candidates = [region for region in regions if self.is_return_net(region.net) and region.layer != segment.layer
                          and (not order or segment.layer in order and region.layer in order and abs(order[segment.layer]-order[region.layer])==1)]
            if not any(region.covers(segment) for region in candidates):
                findings.append(Finding(
                    "warning", "Reference-plane coverage", segment.net, segment.layer, *midpoint,
                    "The full trace-width corridor lacks continuous filled return copper on an adjacent layer." if order else "The full trace-width corridor lacks continuous supplied return-plane coverage; stackup adjacency was not provided.",
                    "Inspect plane splits/voids and reroute over continuous reference copper.",
                ))

        by_net: dict[str, list[CopperSegment]] = {}
        for segment in signal_segments:
            by_net.setdefault(segment.net, []).append(segment)
        for net, net_segments in by_net.items():
            degree: dict[tuple[int, int], int] = {}
            for segment in net_segments:
                for point in (segment.start, segment.end):
                    key = (segment.layer,*self._key(point)); degree[key] = degree.get(key, 0) + 1
            branch_keys = {key for key, count in degree.items() if count > 2}
            for segment in net_segments:
                length = segment.length_mm if segment.length_mm is not None else self._distance(segment.start, segment.end)
                if length >= stub_limit_mm and any((segment.layer,*self._key(point)) in branch_keys for point in (segment.start, segment.end)):
                    midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
                    findings.append(Finding(
                        "warning", "Possible routed stub", net, segment.layer, *midpoint,
                        f"A {length:.2f} mm branch leaves a node with more than two routed connections.",
                        "Confirm intended topology; shorten/remove the branch or validate it with SI simulation.",
                    ))
        checked_pairs = set()
        for net, net_segments in by_net.items():
            mate = differential_mate(net, by_net)
            pair_key = tuple(sorted((net, mate))) if mate else ()
            if not mate or pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            mate_segments = by_net[mate]
            length = sum(item.length_mm if item.length_mm is not None else self._distance(item.start,item.end) for item in net_segments)
            mate_length = sum(item.length_mm if item.length_mm is not None else self._distance(item.start,item.end) for item in mate_segments)
            skew = abs(length - mate_length)
            anchor = net_segments[0].start
            layers = ",".join(sorted({item.layer for item in net_segments + mate_segments}))
            if skew > differential_skew_limit_mm:
                findings.append(Finding(
                    "warning", "Differential-pair skew", f"{net} / {mate}", layers, *anchor,
                    f"Routed-length difference is {skew:.2f} mm (limit {differential_skew_limit_mm:g} mm).",
                    "Length-match the pair using the protocol timing budget and KiCad constraints.",
                ))
            uncoupled = 0
            for segment in net_segments:
                midpoint = ((segment.start[0] + segment.end[0]) / 2, (segment.start[1] + segment.end[1]) / 2)
                same_layer = [item for item in mate_segments if item.layer == segment.layer]
                nearest = min((max(0.,_point_segment_distance(midpoint,item.start,item.end)-(segment.width_mm+item.width_mm)/2)
                               for item in same_layer), default=math.inf)
                if nearest > differential_gap_limit_mm:
                    uncoupled += 1
            if uncoupled:
                findings.append(Finding(
                    "warning", "Differential-pair uncoupling", f"{net} / {mate}", layers, *anchor,
                    f"{uncoupled} primary segment(s) have no mate copper within {differential_gap_limit_mm:g} mm on the same layer at their midpoint.",
                    "Inspect coupling, layer transitions, neck-downs, and reference continuity.",
                ))
        return AuditResult(findings, signal_segments, all_vias)


def differential_mate(net: str, available: Iterable[str]) -> str:
    """Shared pattern detector with the legacy suffix fallbacks."""
    names = list(available)
    mate = _shared_find_mate(net, names)
    if mate:
        return mate
    candidates = []
    if net.endswith("_P"): candidates.append(net[:-2] + "_N")
    if net.endswith("_N"): candidates.append(net[:-2] + "_P")
    if net.endswith("+"): candidates.append(net[:-1] + "-")
    if net.endswith("-"): candidates.append(net[:-1] + "+")
    lookup = {value.casefold(): value for value in names}
    return next((lookup[value.casefold()] for value in candidates if value.casefold() in lookup), "")
