"""Audit reproducer: run with KiCad Python; no GUI or board files are opened.

Prints current behavior, including defects; this is not a passing regression test.
"""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pcbnew
from fanout_generator_plugin.fanout_generator_plugin import FanoutFrame
from via_stitching_plugin.via_stitching_plugin import ViaFrame
from extract_pins_plugin.automation import execute


def control(value):
    return NS(GetValue=lambda: value)


board = pcbnew.BOARD()
ground = pcbnew.NETINFO_ITEM(board, "GND")
board.Add(ground)
stitch = NS(
    board=board, spacing=control("2"), edge=control("0.5"),
    drill=control("0.3"), diameter=control("0.6"), density=control("Uniform"),
    require_target_zone=control(True), _selected_net=lambda: ("GND", ground.GetNetCode()),
    _bounds=lambda: tuple(pcbnew.FromMM(v) for v in (0, 0, 5, 5)),
    _target_zones=lambda code: [], _blocked_reason=lambda pos, code: "",
)
plan = ViaFrame._plan(stitch)
print(json.dumps({"probe": "required_target_zone_missing", "accepted": len(plan),
                  "rejections": stitch.plan_rejections}))

obstacles = NS(
    board=NS(GetFootprints=lambda: [NS(GetReference=lambda: "U1")]),
    skip_parts=control(True), _excluded_refs=lambda: {"U1"},
    _contains=lambda item, pos: False,
)
print(json.dumps({"probe": "skip_ref_far_from_candidate", "reason":
    ViaFrame._blocked_reason(obstacles, pcbnew.VECTOR2I(100000000, 100000000), 1)}))

footprint = NS(GetPosition=lambda: pcbnew.VECTOR2I(0, 0))
pad = NS(GetPosition=lambda: pcbnew.VECTOR2I(1000000, 2000000), GetNetCode=lambda: 1)
fanout = NS(width=control("-0.2"), length=control("-1.5"),
            via_diameter=control("0.3"), via_drill=control("0.6"),
            pattern=control("Dogbone outward"), add_vias=control(False),
            _eligible_pads=lambda: [(footprint, pad)])
fanout._escape_angle = lambda pattern, fp, p: FanoutFrame._escape_angle(fanout, pattern, fp, p)
plan = FanoutFrame._plan(fanout)
print(json.dumps({"probe": "invalid_fanout_dimensions", "accepted": len(plan),
                  "width_mm": pcbnew.ToMM(plan[0].width),
                  "via_diameter_mm": pcbnew.ToMM(plan[0].via_diameter),
                  "via_drill_mm": pcbnew.ToMM(plan[0].via_drill)}))
angles = {name: round(math.degrees(fanout._escape_angle(name, footprint, pad)), 6)
          for name in ("Dogbone outward", "Radial outward", "BGA/LGA grid outward", "Perimeter outward")}
print(json.dumps({"probe": "pattern_angles", "degrees": angles}))

pth_pad = NS(GetAttribute=lambda: pcbnew.PAD_ATTRIB_PTH)
pth_fp = NS(GetReference=lambda: "J1", Pads=lambda: [pth_pad])
scope = NS(board=NS(GetFootprints=lambda: [pth_fp]), scope=control("All SMD pads"),
           ref=control(""), _selected_pad_keys=lambda: set(),
           _selected_footprint_refs=lambda: set())
print(json.dumps({"probe": "pth_in_smd_scope", "accepted": len(FanoutFrame._eligible_pads(scope)),
                  "native_smd_enum": pcbnew.PAD_ATTRIB_SMD, "native_pth_enum": pcbnew.PAD_ATTRIB_PTH}))

item = pcbnew.PCB_TRACK(board)
try:
    item.SetSelected(True)
except TypeError as exc:
    print(json.dumps({"probe": "preview_kit_selection_signature", "error": str(exc)}))

for method in ("fanout-generator.plan", "via-stitching.plan"):
    print(json.dumps({"probe": "rpc", "method": method,
                      "response": execute({"id": 1, "method": method, "params": {}})}))

print(json.dumps({"native_board_tracks_added": len(list(board.GetTracks()))}))
