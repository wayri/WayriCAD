import json
import unittest
from manufacturing_readiness_plugin.analysis import saved_metrics,audit_metrics,FabricatorProfile

class PadDrillTests(unittest.TestCase):
    def metrics(self,pad):
        board='(kicad_pcb (general (thickness 1.6)) (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (footprint "X" '+pad+'))'
        project={'board':{'design_settings':{'rules':{'min_clearance':.2}}}}
        return saved_metrics(board.encode(),json.dumps(project).encode())

    def test_small_plated_pad_drill_is_not_hidden_by_missing_vias(self):
        metrics=self.metrics('(pad "1" thru_hole circle (size .3 .3) (drill .15))')
        self.assertEqual(metrics.minimum_drill_mm,.15)
        self.assertAlmostEqual(metrics.minimum_annular_ring_mm,.075)
        checks=audit_metrics(metrics,FabricatorProfile())
        self.assertEqual(sum(c.status=='FAIL' for c in checks),2)
        self.assertEqual(checks[0].status,'N/A')

    def test_slot_and_offset_use_conservative_annulus(self):
        metrics=self.metrics('(pad "1" thru_hole oval (size 2 1) (drill oval 1.2 .4 (offset .1 .1)))')
        self.assertEqual(metrics.minimum_drill_mm,.4)
        self.assertAlmostEqual(metrics.minimum_annular_ring_mm,.3-2**.5*.1)

    def test_nonplated_hole_has_no_ring_requirement(self):
        metrics=self.metrics('(pad "" np_thru_hole circle (size .1 .1) (drill .1))')
        self.assertEqual(metrics.minimum_annular_ring_mm,float('inf'))
        self.assertEqual(audit_metrics(metrics,FabricatorProfile())[3].status,'N/A')

    def test_unresolved_shapes_and_malformed_holes_refused(self):
        for pad in ('(pad "1" thru_hole custom (size 1 1) (drill .4))',
                    '(pad "1" thru_hole circle (size 1 1) (drill nan))',
                    '(pad "1" thru_hole circle (size 1 1))'):
            with self.subTest(pad=pad),self.assertRaises(ValueError):self.metrics(pad)
