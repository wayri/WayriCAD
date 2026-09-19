import json, pathlib, sys
import pytest


BOARD='''(kicad_pcb (version 20241229) (generator "pcbnew")
  (general (thickness 1.6)) (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user) (47 "F.CrtYd" user))
  (net 0 "") (net 1 "BGA_D0") (net 2 "BGA_D1")
  (footprint "Package_BGA:Demonstration" (layer "F.Cu")
    (uuid "b95715e1-757f-470c-ac75-60f57d2d94cb") (at 100 100 0)
    (property "Reference" "U1" (at 0 -3) (layer "F.SilkS"))
    (property "Value" "EXAMPLE_ONLY" (at 0 3) (layer "F.Fab"))
    (fp_rect (start -2 -2) (end 2 2) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
    (pad "A1" smd circle (at -0.5 0) (size 0.3 0.3) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "BGA_D0"))
    (pad "A2" smd circle (at 0.5 0) (size 0.3 0.3) (layers "F.Cu" "F.Paste" "F.Mask") (net 2 "BGA_D1"))
  )
  (zone (net 0) (net_name "") (layer "F.Cu") (uuid "90a3bb80-49d8-4366-80bb-ce98454d82c9")
    (name "EXISTING_ESCAPE") (hatch edge 0.5)
    (connect_pads (clearance 0)) (min_thickness 0.01)
    (keepout (tracks allowed) (vias allowed) (pads allowed) (copperpour allowed) (footprints allowed))
    (fill (thermal_gap 0.3) (thermal_bridge_width 0.3))
    (polygon (pts (xy 98 98) (xy 102 98) (xy 102 102) (xy 98 102))))
  (gr_rect (start 90 90) (end 110 110) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))
)
'''
PROJECT={'board':{'design_settings':{'rules':{'min_clearance':.1,'min_track_width':.1,'min_via_diameter':.4,'min_through_hole_diameter':.2,'min_via_annular_width':.1},'rule_severities':{'shorting_items':'error'}}},'net_settings':{'classes':[{'name':'Default','clearance':.2,'track_width':.2,'via_diameter':.6,'via_drill':.3,'custom_preserve_me':'untouched'},{'name':'HighSpeed','clearance':None,'track_width':.15}],'netclass_patterns':[{'netclass':'HighSpeed','pattern':'BGA_*'}]},'unrelated':{'foo':[1,2,{'keep':True}]}}
RULES='''# Original project header; preserve this exactly\n(version 1)\n\n# Working design clearance\n(rule "Board working defaults"\n  (constraint clearance (min 0.2mm))\n  (constraint track_width (min 0.2mm))\n)\n# Trailing project note\n'''

@pytest.fixture
def project(tmp_path):
    board=tmp_path/'demo.kicad_pcb';board.write_text(BOARD)
    board.with_suffix('.kicad_pro').write_text(json.dumps(PROJECT,indent=2)+'\n')
    board.with_suffix('.kicad_dru').write_text(RULES)
    return board
