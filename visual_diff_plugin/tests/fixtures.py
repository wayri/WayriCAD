"""Small original designs, including real KiCad page and title-block metadata."""

from uuid import NAMESPACE_URL, uuid5


def uid(name):
    return str(uuid5(NAMESPACE_URL, 'kicad-vizdiff-test/' + name))


def schematic(changed=False):
    value = '4.7k' if changed else '10k'
    return f'''(kicad_sch (version 20250114) (generator "eeschema")
      (uuid "{uid('root')}") (paper "A4")
      (title_block (title "Sensor interface") (date "2026-09-14")
        (rev "{'B' if changed else 'A'}") (company "KiCad Visual Review")
        (comment 1 "Native schematic - page and title block preserved"))
      (lib_symbols
        (symbol "Demo:R" (pin_names (offset 0)) (in_bom yes) (on_board yes)
          (property "Reference" "R" (at 2.54 0 90) (effects (font (size 1.27 1.27))))
          (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
          (symbol "R_0_1"
            (rectangle (start -1.016 -2.54) (end 1.016 2.54)
              (stroke (width 0.254) (type default)) (fill (type none))))
          (symbol "R_1_1"
            (pin passive line (at 0 3.81 270) (length 1.27)
              (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
            (pin passive line (at 0 -3.81 90) (length 1.27)
              (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27))))))))
      (wire (pts (xy 100 70) (xy 100 86.19)) (stroke (width 0) (type default)) (uuid "{uid('wire1')}"))
      (wire (pts (xy 100 93.81) (xy 100 110)) (stroke (width 0) (type default)) (uuid "{uid('wire2')}"))
      (label "SIGNAL_IN" (at 100 70 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{uid('label1')}"))
      (label "SENSE" (at 100 110 0) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{uid('label2')}"))
      (text "Analog sensor input" (at 100 60 0) (effects (font (size 2 2))) (uuid "{uid('text')}"))
      (symbol (lib_id "Demo:R") (at 100 90 0) (unit 1) (in_bom yes) (on_board yes) (dnp no)
        (uuid "{uid('resistor')}")
        (property "Reference" "R1" (at 105 88 0) (effects (font (size 1.27 1.27))))
        (property "Value" "{value}" (at 105 91 0) (effects (font (size 1.27 1.27))))
        (pin "1" (uuid "{uid('pin1')}")) (pin "2" (uuid "{uid('pin2')}"))
        (instances (project "sensor" (path "/{uid('root')}" (reference "R1") (unit 1)))))
      (sheet_instances (path "/" (page "1"))))'''


def board(changed=False):
    y = 84 if changed else 80
    return f'''(kicad_pcb (version 20241229) (generator "pcbnew")
      (general (thickness 1.6)) (paper "A4")
      (title_block (title "Sensor interface PCB") (date "2026-09-14")
        (rev "{'B' if changed else 'A'}") (company "KiCad Visual Review"))
      (layers (0 "F.Cu" signal) (31 "B.Cu" signal)
        (36 "B.SilkS" user "b.silkscreen") (37 "F.SilkS" user "f.silkscreen") (44 "Edge.Cuts" user))
      (setup (pad_to_mask_clearance 0))
      (net 0 "") (net 1 "SENSE")
      (gr_rect (start 80 65) (end 150 115) (stroke (width 0.1) (type default))
        (fill none) (layer "Edge.Cuts") (uuid "{uid('edge')}"))
      (gr_text "SENSOR / R{'2' if changed else '1'}" (at 115 72) (layer "F.SilkS")
        (uuid "{uid('silk')}") (effects (font (size 1.5 1.5) (thickness 0.25))))
      (footprint "Demo:TwoPads" (layer "F.Cu") (at 95 {y})
        (uuid "{uid('fp')}")
        (property "Reference" "R1" (at 0 -3) (layer "F.SilkS") (uuid "{uid('fpref')}")
          (effects (font (size 1 1) (thickness 0.15))))
        (pad "1" thru_hole circle (at 0 0) (size 2.4 2.4) (drill 1) (layers "*.Cu" "*.Mask") (net 1 "SENSE") (uuid "{uid('pad1')}"))
        (pad "2" thru_hole circle (at 10 0) (size 2.4 2.4) (drill 1) (layers "*.Cu" "*.Mask") (net 1 "SENSE") (uuid "{uid('pad2')}")))
      (segment (start 95 {y}) (end 95 100) (width 0.6) (layer "F.Cu") (net 1) (uuid "{uid('track1')}"))
      (segment (start 95 100) (end 135 100) (width 0.6) (layer "F.Cu") (net 1) (uuid "{uid('track2')}"))
      (via (at 135 100) (size 1.5) (drill 0.7) (layers "F.Cu" "B.Cu") (net 1) (uuid "{uid('via')}")))'''
