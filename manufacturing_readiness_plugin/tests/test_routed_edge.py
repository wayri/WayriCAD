"""Saved-board copper-edge checks never promote incomplete geometry to PASS."""
import json
import tempfile
import unittest
from pathlib import Path

from manufacturing_readiness_plugin.analysis import (FabricatorProfile, audit_metrics,
                                                     load_profile, save_profile, saved_metrics)


PROJECT=json.dumps({'board':{'design_settings':{'rules':{'min_clearance':0.2}}}}).encode()
RECT='(gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))'


def board(outline=RECT, routing=''):
    return (f'(kicad_pcb (general (thickness 1.6)) '
            f'(layers (0 "F.Cu" signal) (31 "B.Cu" signal)) {outline} {routing})').encode()


def edge_check(outline=RECT, routing='', profile=None):
    metrics=saved_metrics(board(outline,routing),PROJECT)
    return metrics,audit_metrics(metrics,profile or FabricatorProfile())[-1]


class RoutedEdgeTests(unittest.TestCase):
    def test_straight_track_and_via_use_outer_copper_radius(self):
        track='(segment (start 1 1) (end 9 1) (width .2) (layer "F.Cu"))'
        via='(via (at 5 .4) (size .6) (drill .3))'
        metrics,check=edge_check(routing=track)
        self.assertAlmostEqual(metrics.minimum_routed_edge_mm,.9)
        self.assertEqual(check.status,'PASS')
        metrics,check=edge_check(routing=track+via)
        self.assertAlmostEqual(metrics.minimum_routed_edge_mm,.1)
        self.assertEqual(check.status,'FAIL')

    def test_unordered_straight_outline_and_diagonal_routing(self):
        outline=''.join(f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))'
                        for a,b in [((10,0),(10,10)),((0,10),(0,0)),((10,10),(0,10)),((0,0),(10,0))])
        track='(segment (start 1 1) (end 9 9) (width .2))'
        metrics,check=edge_check(outline,track)
        self.assertAlmostEqual(metrics.minimum_routed_edge_mm,.9)
        self.assertEqual(check.status,'PASS')

    def test_missing_outline_or_routing_coordinates_are_unknown(self):
        for outline,routing in [('', '(segment (start 1 1) (end 2 2) (width .2))'),
                                (RECT, '(segment (width .2))'),
                                ('(gr_line (start 0 0) (end 10 0) (layer "Edge.Cuts"))',
                                 '(via (at 5 5) (size .6) (drill .3))'),
                                ('(gr_circle (center 5 5) (end 10 5) (layer "Edge.Cuts"))',
                                 '(via (at 5 5) (size .6) (drill .3))')]:
            with self.subTest(outline=outline,routing=routing):
                _,check=edge_check(outline,routing)
                self.assertEqual(check.status,'UNKNOWN')
        with self.assertRaisesRegex(ValueError,'unambiguous width'):
            edge_check(RECT,'(segment (start 1 1) (end 2 2) (width .2) (width .1))')

    def test_arc_unknown_does_not_hide_exact_track_failure(self):
        arc='(arc (start 2 2) (mid 3 3) (end 4 2) (width .2))'
        track='(segment (start .2 1) (end 2 1) (width .2))'
        _,check=edge_check(routing=arc+track)
        self.assertEqual(check.status,'FAIL')
        _,check=edge_check(routing=arc+'(segment (start 1 1) (end 2 1) (width .2))')
        self.assertEqual(check.status,'UNKNOWN')

    def test_outside_routing_fails_and_no_routing_is_not_applicable(self):
        _,check=edge_check(routing='(via (at 15 5) (size .6) (drill .3))')
        self.assertEqual(check.status,'FAIL')
        _,check=edge_check(outline='',routing='')
        self.assertEqual(check.status,'N/A')

    def test_profile_roundtrip_keeps_edge_requirement(self):
        profile=FabricatorProfile(minimum_routed_edge_mm=.35)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fabricator.json'
            save_profile(path,profile)
            self.assertEqual(load_profile(path).minimum_routed_edge_mm,.35)
