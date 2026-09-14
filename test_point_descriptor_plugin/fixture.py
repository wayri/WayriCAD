"""Generate a separate, reviewable bed-of-nails fixture PCB."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, List


@dataclass
class FixturePoint:
    reference: str
    pad: str
    net: str
    x_mm: float
    y_mm: float


def collect_fixture_points(board: Any, rows: Iterable[dict[str, str]]) -> List[FixturePoint]:
    wanted = {(row.get("TP Reference", ""), row.get("Pad", ""), row.get("Net Name", "")) for row in rows}
    points = []
    for footprint in board.GetFootprints():
        reference = str(footprint.GetReference())
        for pad in footprint.Pads():
            key = (reference, str(pad.GetNumber()), str(getattr(pad, "GetNetname", lambda: "")()))
            if key not in wanted:
                continue
            position = pad.GetPosition()
            points.append(FixturePoint(*key, float(position.x) / 1_000_000.0, float(position.y) / 1_000_000.0))
    return sorted(points, key=lambda point: (point.y_mm, point.x_mm, point.reference, point.pad))


def generate_fixture_board(points: Iterable[FixturePoint], probe_type: str, connector_pitch_mm: float = 2.54, margin_mm: float = 10.0) -> str:
    points = list(points)
    if not points:
        raise ValueError("No extracted test-point pad coordinates are available for a fixture.")
    min_x = min(point.x_mm for point in points); min_y = min(point.y_mm for point in points)
    normalized = [(point, point.x_mm-min_x+margin_mm, point.y_mm-min_y+margin_mm) for point in points]
    max_x = max(x for _point,x,_y in normalized); max_y = max(y for _point,_x,y in normalized)
    connector_x = max_x + 20.0
    connector_height = max((len(points)-1)*connector_pitch_mm, max_y-margin_mm)
    board_height = max(max_y + margin_mm, connector_height + 2*margin_mm)
    board_width = connector_x + margin_mm
    def quote(value: str) -> str:
        return '"' + str(value).replace('\\','\\\\').replace('"','\\"') + '"'
    nets = [f'  (net {index} {quote(point.net or f"UNCONNECTED_{point.reference}_{point.pad}")})' for index, point in enumerate(points,1)]
    footprints=[]; segments=[]
    drill = 1.0 if "P75" in probe_type else 1.3 if "P100" in probe_type else 1.7 if "P160" in probe_type else 1.0
    diameter = drill + 0.8
    for index,(point,x,y) in enumerate(normalized,1):
        net_name=point.net or f"UNCONNECTED_{point.reference}_{point.pad}"; connector_y=margin_mm+(index-1)*connector_pitch_mm
        ref=re.sub(r"[^A-Za-z0-9_]+","_",point.reference)
        footprints.append(f'''  (footprint "WayriCAD:Probe_{ref}" (layer "F.Cu") (at {x:.4f} {y:.4f})
    (property "Reference" {quote(ref)} (at 0 -2 0) (layer "F.SilkS"))
    (property "Value" {quote(probe_type)} (at 0 2 0) (layer "F.Fab") hide)
    (pad "1" thru_hole circle (at 0 0) (size {diameter:.3f} {diameter:.3f}) (drill {drill:.3f}) (layers "*.Cu" "*.Mask") (net {index} {quote(net_name)})))''')
        footprints.append(f'''  (footprint "WayriCAD:Edge_Channel_{index}" (layer "F.Cu") (at {connector_x:.4f} {connector_y:.4f})
    (property "Reference" {quote(f"J1.{index}")} (at 0 -2 0) (layer "F.SilkS"))
    (property "Value" "Fixture edge channel" (at 0 2 0) (layer "F.Fab") hide)
    (pad {quote(str(index))} thru_hole circle (at 0 0) (size 1.8 1.8) (drill 1.0) (layers "*.Cu" "*.Mask") (net {index} {quote(net_name)})))''')
        lane_x=max_x+5.0+index*0.15
        segments.extend((f'  (segment (start {x:.4f} {y:.4f}) (end {lane_x:.4f} {y:.4f}) (width 0.25) (layer "F.Cu") (net {index}))',f'  (segment (start {lane_x:.4f} {y:.4f}) (end {lane_x:.4f} {connector_y:.4f}) (width 0.25) (layer "F.Cu") (net {index}))',f'  (segment (start {lane_x:.4f} {connector_y:.4f}) (end {connector_x:.4f} {connector_y:.4f}) (width 0.25) (layer "F.Cu") (net {index}))'))
    edge=(f'  (gr_rect (start 0 0) (end {board_width:.4f} {board_height:.4f}) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))')
    return '\n'.join(['(kicad_pcb (version 20240108) (generator "wayricad-test-fixture")','  (general (thickness 1.6))','  (paper "A4")','  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))','  (setup (pad_to_mask_clearance 0))','  (net 0 "")',*nets,*footprints,*segments,edge,')',''])
