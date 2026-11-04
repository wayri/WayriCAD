import unittest
from unittest.mock import patch

from review_comments_plugin.saved_positions import saved_positions


class SavedPositionsTests(unittest.TestCase):
    def test_rotated_front_and_back_pads(self):
        source = '''(kicad_pcb (version 20240108)
          (footprint "front" (layer "F.Cu") (at 10 20 90) (uuid "front")
            (pad "1" smd rect (at 2 3) (uuid "front-pad")))
          (footprint "back" (layer "B.Cu") (at 40 50 90) (uuid "back")
            (pad "1" smd rect (at 2 3) (uuid "back-pad"))))'''
        points = saved_positions(source)
        self.assertEqual(points['front'], {'x': 10., 'y': 20.})
        self.assertAlmostEqual(points['front-pad']['x'], 13.)
        self.assertAlmostEqual(points['front-pad']['y'], 18.)
        self.assertAlmostEqual(points['back-pad']['x'], 43.)
        self.assertAlmostEqual(points['back-pad']['y'], 48.)

    def test_board_track_via_and_graphics(self):
        source = '''(kicad_pcb
          (segment (start 1 2) (end 3 6) (uuid "track"))
          (via (at 8 9) (uuid "via"))
          (gr_line (start 2 4) (end 6 8) (uuid "line"))
          (gr_circle (center 7 8) (end 9 8) (uuid "circle"))
          (gr_arc (start 0 0) (mid 1 1) (end 2 0) (uuid "arc")))'''
        self.assertEqual(saved_positions(source), {
            'track': {'x': 2., 'y': 4.}, 'via': {'x': 8., 'y': 9.},
            'line': {'x': 4., 'y': 6.}, 'circle': {'x': 7., 'y': 8.}})

    def test_schematic_uses_only_selected_file(self):
        source = '''(kicad_sch
          (symbol (at 10 20 90) (uuid "symbol"))
          (sheet (at 30 40) (property "Sheetfile" "child.kicad_sch") (uuid "sheet"))
          (label "NET" (at 50 60 0) (uuid "label"))
          (wire (pts (xy 1 3) (xy 5 7)) (uuid "wire"))
          (lib_symbols (symbol "Library:Part" (uuid "library"))))'''
        self.assertEqual(saved_positions(source), {
            'symbol': {'x': 10., 'y': 20.}, 'sheet': {'x': 30., 'y': 40.},
            'label': {'x': 50., 'y': 60.}, 'wire': {'x': 3., 'y': 5.}})

    def test_duplicate_and_unsupported_are_omitted(self):
        source = '''(kicad_pcb
          (via (at 1 2) (uuid "same")) (via (at 1 2) (uuid "same"))
          (footprint "affine" (layer "F.Cu") (at 10 20) (transform (flip yes))
            (uuid "new") (pad "1" smd rect (at 1 1) (uuid "new-pad")))
          (zone (uuid "zone")) (via (at nan 2) (uuid "invalid")))'''
        self.assertEqual(saved_positions(source), {})

    def test_limits_and_root(self):
        self.assertEqual(saved_positions('(kicad_pcb (version 20240108))'), {})
        with self.assertRaisesRegex(ValueError, 'Expected a saved'):
            saved_positions('(unknown (at 1 2))')
        with self.assertRaisesRegex(ValueError, 'bounded text'):
            saved_positions(None)
        with patch('review_comments_plugin.saved_positions.MAX_OBJECTS', 2):
            with self.assertRaisesRegex(ValueError, 'object limit'):
                saved_positions('(kicad_pcb (via) (via) (via))')


if __name__ == '__main__':
    unittest.main()
