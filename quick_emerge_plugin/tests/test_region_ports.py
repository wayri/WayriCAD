import copy
import unittest

from quick_emerge_plugin.region_ports import plan_region


def polygon(points, holes=None):
    return {'outer_mm': points, 'holes_mm': holes or []}


def rectangle(x0, y0, x1, y1):
    return polygon([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])


def coupon():
    outline = [rectangle(0, 0, 10, 10)]
    return {'schema': 1, 'source': {'path': 'board.kicad_pcb', 'sha256': 'abc'},
            'area': {'id': 'a', 'name': 'ROI', 'outline': outline},
            'substrate': {'outline': outline, 'thickness_mm': 1.6},
            'copper': [{'layer': 'F.Cu', 'net': 'SIG', 'polygons': [rectangle(0,4,10,6)], 'source_ids': ['s']},
                       {'layer': 'B.Cu', 'net': 'GND', 'polygons': outline, 'source_ids': ['g']}],
            'unsupported': []}


class RegionPortsTests(unittest.TestCase):
    def test_coupon_and_determinism(self):
        snap = coupon()
        before = copy.deepcopy(snap)
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['blockers'], [])
        self.assertEqual([p['width_mm'] for p in plan['ports']], [2, 2])
        self.assertEqual(plan['ports'][0]['z_reference_mm'], -1.6)
        self.assertEqual(snap, before)
        self.assertEqual(plan, plan_region(snap, 'SIG', 'GND'))

    def test_hole_off_center_breaks_ground(self):
        snap = coupon()
        snap['copper'][1]['polygons'] = [polygon(
            [[0,0],[10,0],[10,10],[0,10],[0,4.3],[1,4.3],[1,4.1],[0,4.1]])]
        self.assertTrue(any('entire port span' in x for x in plan_region(snap, 'SIG', 'GND')['blockers']))

    def test_hole_in_reference_span_is_respected(self):
        # A ground void on a substrate-hole edge interrupts the port below.
        from quick_emerge_plugin.region_ports import _polygons, _span_covered
        ground = _polygons([polygon([[0,0],[10,0],[10,10],[0,10]],
            [[[4,4.1],[6,4.1],[6,4.3],[4,4.3]]])])
        self.assertFalse(_span_covered((5,4), (5,6), ground))

    def test_unselected_cut_and_unsupported(self):
        snap = coupon()
        snap['copper'].append({'net': 'OTHER', 'layer': 'F.Cu', 'polygons': [rectangle(0,1,2,2)]})
        snap['unsupported'] = ['via intersects ROI']
        blockers = plan_region(snap, 'SIG', 'GND')['blockers']
        self.assertIn('via intersects ROI', blockers)
        self.assertTrue(any('Unselected' in x for x in blockers))

    def test_interior_feed_is_not_invented(self):
        snap = coupon()
        snap['copper'][0]['polygons'] = [rectangle(2,4,8,6)]
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['ports'], [])
        self.assertTrue(plan['blockers'])

    def test_concave_actual_boundary(self):
        snap = coupon()
        outline = [polygon([[0,0],[10,0],[10,3],[5,3],[5,10],[0,10]])]
        snap['substrate']['outline'] = outline
        snap['area']['outline'] = outline
        snap['copper'][1]['polygons'] = outline
        snap['copper'][0]['polygons'] = [rectangle(0,5,5,7)]
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(plan['ports'][1]['a_mm'], [5,5])

    def test_natural_board_edge_is_not_a_port_or_unselected_cut(self):
        snap = coupon()
        snap['area']['outline'] = [rectangle(-5, -5, 10, 15)]
        snap['copper'].append({'net': 'OTHER', 'layer': 'F.Cu',
            'polygons': [rectangle(0,1,2,2)]})
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(len(plan['ports']), 1)
        self.assertEqual(plan['ports'][0]['a_mm'], [10,4])
        self.assertEqual(plan['ports'][0]['b_mm'], [10,6])

    def test_area_surrounding_board_cannot_invent_ports(self):
        snap = coupon()
        snap['area']['outline'] = [rectangle(-5,-5,15,15)]
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['ports'], [])
        self.assertTrue(any('No signal crossing' in x for x in plan['blockers']))

    def test_board_cutout_is_not_a_port_but_rule_area_hole_can_be(self):
        snap = coupon()
        hole = [[4,4],[6,4],[6,6],[4,6]]
        outline = [polygon([[0,0],[10,0],[10,10],[0,10]], [hole])]
        snap['substrate']['outline'] = outline
        snap['copper'][1]['polygons'] = outline
        snap['copper'][0]['polygons'] = [rectangle(0,4.5,4,5.5)]
        # An existing board hole is not a feed when the rule area has no hole.
        snap['area']['outline'] = [rectangle(-5,-5,15,15)]
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['ports'], [])
        self.assertTrue(plan['blockers'])
        # The same physical span is eligible when it is an actual rule-area cut.
        snap['area']['outline'] = [polygon([[-5,-5],[15,-5],[15,15],[-5,15]], [hole])]
        plan = plan_region(snap, 'SIG', 'GND')
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(len(plan['ports']), 1)
        self.assertEqual(plan['ports'][0]['a_mm'], [4,4.5])
        self.assertEqual(plan['ports'][0]['b_mm'], [4,5.5])

    def test_bad_geometry(self):
        for value in (-1, 0, float('nan'), '1.6'):
            snap = coupon()
            snap['substrate']['thickness_mm'] = value
            with self.assertRaises(ValueError):
                plan_region(snap, 'SIG', 'GND')
        for point in ([0,4], [float('nan'),0], ['bad',0]):
            snap = coupon()
            snap['copper'][0]['polygons'][0]['outer_mm'][1] = point
            with self.assertRaises(ValueError):
                plan_region(snap, 'SIG', 'GND')

    def test_same_net_and_corner_block(self):
        self.assertTrue(plan_region(coupon(), 'GND', 'GND')['blockers'])
        snap = coupon()
        snap['copper'][0]['polygons'] = [rectangle(0,0,2,2)]
        self.assertTrue(any('corner' in x for x in plan_region(snap, 'SIG', 'GND')['blockers']))


if __name__ == '__main__':
    unittest.main()

