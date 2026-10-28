"""Lazy return geometry must preserve sampled coverage and hole boundaries."""
import copy
import random
import unittest

from wayricad_runtime.return_path import audit_return_path, _in_region


def fixture(points):
    return {'signal_net': 'SIG', 'return_nets': ['GND'], 'layer_order': ['F.Cu', 'B.Cu'],
            'segments': [{'layer': 'F.Cu', 'start': list(p), 'end': list(p), 'width_mm': .2} for p in points],
            'signal_vias': [], 'return_vias': [], 'reference_regions': [{
                'net': 'GND', 'layer': 'B.Cu',
                'outer': [[0, 0], [20, 0], [20, 20], [12, 20], [12, 8], [8, 8], [8, 20], [0, 20]],
                'holes': [[[2, 2], [6, 2], [6, 6], [2, 6]],
                          [[14, 2], [18, 2], [16, 6]], []]}],
            'unfilled_reference_layers': [], 'unsupported_geometry': []}


class LazyReturnGeometryTests(unittest.TestCase):
    def test_sampled_concavity_holes_and_boundaries_match_direct_reference(self):
        rng = random.Random(713)
        points = [(rng.uniform(-1, 21), rng.uniform(-1, 21)) for _ in range(350)]
        points += [(0, 0), (20, 20), (8, 12), (2, 4), (4, 2), (16, 2), (16, 6), (4, 4)]
        data = fixture(points);before = copy.deepcopy(data)
        result = audit_return_path(data)
        region = data['reference_regions'][0]
        for point, row in zip(points, result['coverage']):
            expected = _in_region(point, region)
            self.assertEqual(row['covered_sample_count'], 2 if expected else 0, point)
            self.assertEqual(row['status'], 'SAMPLED_COVERED' if expected else 'GAP_SAMPLED', point)
        self.assertEqual(data, before)

    def test_unvisited_regions_do_not_change_evidence(self):
        data = fixture([(1, 1), (7, 7)])
        expected = audit_return_path(data)
        for i in range(1000):
            x = 100 + i * 2
            data['reference_regions'].append({'net': 'GND', 'layer': 'B.Cu',
                'outer': [[x, 100], [x + 1, 100], [x + 1, 101], [x, 101]],
                'holes': [[[x + .2, 100.2], [x + .8, 100.2], [x + .5, 100.8]]]})
        self.assertEqual(audit_return_path(data), expected)

    def test_changed_input_is_not_hidden_by_a_previous_audit(self):
        data = fixture([(1, 1)])
        self.assertEqual(audit_return_path(data)['coverage'][0]['covered_sample_count'], 2)
        data['reference_regions'][0]['holes'].append([[.5, .5], [1.5, .5], [1.5, 1.5], [.5, 1.5]])
        self.assertEqual(audit_return_path(data)['coverage'][0]['covered_sample_count'], 0)

    def test_dense_holes_and_large_hole_preserve_exact_sample_membership(self):
        points=[(x/2,y/2) for x in range(0,41,3) for y in range(0,41,3)]
        data=fixture(points);region=data['reference_regions'][0]
        region['outer']=[[0,0],[20,0],[20,20],[0,20]]
        region['holes']=[[[x+.1,y+.1],[x+.4,y+.1],[x+.4,y+.4],[x+.1,y+.4]]
                         for x in range(20) for y in range(20)]
        region['holes'].append([[2,2],[18,2],[18,18],[2,18]])
        result=audit_return_path(data)
        for point,row in zip(points,result['coverage']):
            self.assertEqual(row['covered_sample_count'],2 if _in_region(point,region) else 0,point)


if __name__ == '__main__':unittest.main()
