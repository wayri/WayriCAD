"""Synthetic union, fill, hole and layer-span evidence for board analytics."""
import math
import unittest
from bomstudio.board_analytics import analyze_tree
from bomstudio.sexpr import parse


class BoardAnalyticsTests(unittest.TestCase):
    def run_board(self, content):
        return analyze_tree(parse('(kicad_pcb (layers (0 "F.Cu" signal) (2 "In1.Cu" signal) (31 "B.Cu" signal))'
                                  '(net 1 "GND") (net 2 "VCC")'
                                  '(gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))'+content+')'))

    def zone(self, x0, x1, net=1, layer='F.Cu', filled=True):
        pts=f'(pts (xy {x0} 0) (xy {x1} 0) (xy {x1} 4) (xy {x0} 4))'
        return f'(zone (net {net}) (layer "{layer}") (polygon {pts})'+(f'(filled_polygon (layer "{layer}") {pts})' if filled else '')+')'

    def test_overlapping_zone_and_layer_union(self):
        r=self.run_board(self.zone(0,4)+self.zone(2,6)+self.zone(0,2,2))
        layer=r['layers'][0]
        self.assertAlmostEqual(layer['filled_zone_area_mm2'],24)
        self.assertAlmostEqual(layer['copper_area_mm2'],24)
        self.assertAlmostEqual(layer['coverage_percent'],24)
        self.assertEqual([z['filled_zone_area_mm2'] for z in r['zones']],[16,16,8])
        self.assertAlmostEqual(next(n for n in r['nets'] if n['net']=='GND')['filled_zone_area_mm2'],24)
        # Different nets are separately inventoried; their overlapping areas are not summed for layer occupancy.
        self.assertAlmostEqual(next(n for n in r['nets'] if n['net']=='VCC')['filled_zone_area_mm2'],8)

    def test_unfilled_zone_is_unknown_not_boundary(self):
        r=self.run_board(self.zone(0,4,filled=False))
        self.assertIsNone(r['layers'][0]['filled_zone_area_mm2'])
        self.assertIsNone(r['layers'][0]['copper_area_mm2'])
        self.assertEqual(r['layers'][0]['zone_boundary_area_mm2'],16)
        self.assertEqual(r['status'],'partial')
        self.assertEqual(r['summary']['unknown_fill_layers'],1)
        self.assertEqual(r['layers'][0]['pad_area_mm2'],0)

    def test_holes_contact_and_through_via_not_multiplied(self):
        r=self.run_board('(footprint "X" (at 5 5) (layer "F.Cu") (property "Reference" "U1")'
                         '(pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net 1 "GND")))'
                         '(via (at 8 8) (size 1) (drill .5) (layers "F.Cu" "B.Cu") (net 1))')
        self.assertAlmostEqual(r['components'][0]['pad_area_mm2'],math.pi*.75,delta=.002)
        self.assertEqual(r['summary']['via_count'],1)
        self.assertEqual(r['summary']['transition_count'],1)
        self.assertEqual(r['nets'][0]['via_count'],1)
        self.assertEqual(r['nets'][0]['pad_count'],1)
        self.assertEqual([x['via_count'] for x in r['layers']],[1,1,1])
        self.assertAlmostEqual(r['summary']['board_area_mm2'],100-math.pi*(.25+.0625),delta=.002)

    def test_blind_via_does_not_cut_bottom_layer_or_through_board(self):
        r=self.run_board(self.zone(0,10,layer='B.Cu')+
                         '(via blind (at 5 2) (size 1) (drill .5) (layers "F.Cu" "In1.Cu") (net 1))')
        self.assertEqual(r['layers'][-1]['via_count'],0)
        self.assertEqual(r['layers'][-1]['copper_area_mm2'],40)
        self.assertEqual(r['summary']['board_area_mm2'],100)

    def test_track_pad_overlap_union_and_lengths(self):
        r=self.run_board('(segment (start 1 2) (end 5 2) (width 1) (layer "F.Cu") (net 1))'
                         '(footprint "X" (at 1 2) (layer "F.Cu") (property "Reference" "J1")'
                         '(pad "1" smd circle (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "GND")))')
        self.assertAlmostEqual(r['summary']['track_length_mm'],4)
        self.assertAlmostEqual(r['layers'][0]['copper_area_mm2'],4+math.pi/4,delta=.002)

    def test_unsupported_custom_pad_preserves_counts_and_marks_area(self):
        r=self.run_board('(footprint "X" (at 1 2) (layer "F.Cu") (property "Reference" "U1")'
                         '(pad "1" smd custom (at 0 0) (size 1 1) (layers "F.Cu") (net 1)))')
        self.assertEqual(r['summary']['pad_count'],1)
        self.assertIsNone(r['layers'][0]['copper_area_mm2'])
        self.assertIsNone(r['components'][0]['placement_pad_area_mm2'])
        self.assertTrue(r['components'][0]['issues'])

    def test_keepouts_not_copper_and_empty_board_has_zero_counts(self):
        r=self.run_board('(zone (net 1) (layer "F.Cu") (keepout (tracks not_allowed)))')
        self.assertEqual(r['summary']['zone_count'],0)
        self.assertEqual(r['summary']['copper_area_mm2'],0)

    def test_nested_edge_cutout_and_open_edge_rejection(self):
        r=self.run_board('(gr_rect (start 2 2) (end 4 4) (layer "Edge.Cuts"))')
        self.assertEqual(r['summary']['board_area_mm2'],96)
        r=self.run_board('(gr_line (start 20 20) (end 21 20) (layer "Edge.Cuts"))')
        self.assertIsNone(r['summary']['board_area_mm2'])

    def test_net_layer_rows_and_named_net_format(self):
        r=self.run_board('(segment (start 1 1) (end 4 5) (width .2) (layer "B.Cu") (net "SIGNAL"))')
        row=r['net_layers'][0]
        self.assertEqual((row['net'],row['layer']),('SIGNAL','B.Cu'))
        self.assertEqual(row['track_length_mm'],5)

    def test_saved_zone_bridges_preserve_hole_area(self):
        # Outer 4x4 square and clockwise 2x2 hole joined by a repeated bridge.
        pts='(pts (xy 0 0) (xy 4 0) (xy 4 4) (xy 0 4) (xy 0 0) (xy 1 1) (xy 1 3) (xy 3 3) (xy 3 1) (xy 1 1) (xy 0 0))'
        r=self.run_board('(zone (net 1) (layer "F.Cu") (polygon '+pts+') (filled_polygon (layer "F.Cu") '+pts+'))')
        self.assertEqual(r['layers'][0]['filled_zone_area_mm2'],12)

    def test_crossed_polygon_not_repaired_into_false_area(self):
        pts='(pts (xy 0 0) (xy 4 4) (xy 0 4) (xy 4 0))'
        r=self.run_board('(zone (net 1) (layer "F.Cu") (polygon '+pts+') (filled_polygon (layer "F.Cu") '+pts+'))')
        self.assertIsNone(r['layers'][0]['filled_zone_area_mm2'])

    def test_graphical_copper_is_not_silently_omitted(self):
        r=self.run_board('(gr_text "COPPER" (at 5 5) (layer "F.Cu"))')
        self.assertIsNone(r['layers'][0]['copper_area_mm2'])
        self.assertEqual(r['layers'][1]['copper_area_mm2'],0)

    def test_snapshot_cache_clones_and_invalidates_on_content(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from bomstudio.board_analytics import board_analysis, _CACHE
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'demo.kicad_pcb'
            path.write_text('(kicad_pcb (gr_rect (start 0 0) (end 2 2) (layer "Edge.Cuts")))')
            workspace=SimpleNamespace(state={},project=SimpleNamespace(pro_path=path.with_suffix('.kicad_pro')))
            _CACHE.clear()
            with patch('bomstudio.board_analytics.analyze_tree',wraps=analyze_tree) as analyze:
                one=board_analysis(workspace); one['summary']['board_area_mm2']=999
                two=board_analysis(workspace)
                self.assertEqual(two['summary']['board_area_mm2'],4)
                self.assertEqual(analyze.call_count,1)
                path.write_text('(kicad_pcb (gr_rect (start 0 0) (end 3 2) (layer "Edge.Cuts")))')
                three=board_analysis(workspace)
                self.assertEqual(three['summary']['board_area_mm2'],6)
                self.assertNotEqual(two['source']['sha256'],three['source']['sha256'])
                self.assertEqual(analyze.call_count,2)


if __name__=='__main__': unittest.main()
