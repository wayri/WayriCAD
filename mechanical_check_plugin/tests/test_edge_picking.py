import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from wayricad_mechanical.edge_picking import nearest_edge


def edge(index, points, reference='U1'):
    return dict(reference=reference, edge_index=index, points=points)


def horizontal(index, y=0, depth=.5, reference='U1'):
    return edge(index, [[0, y, depth, 0, 0, 3], [100, y, depth, 10, 0, 3]], reference)


class EdgePickingTests(unittest.TestCase):
    def test_straight_segment_projects_nearest_point_with_units_preserved(self):
        picked = nearest_edge((25, 4), [horizontal(7)])
        self.assertEqual(picked['reference'], 'U1')
        self.assertEqual(picked['edge_index'], 7)
        self.assertEqual(picked['screen_position'], [25, 0])
        self.assertEqual(picked['position'], [2.5, 0, 3])
        self.assertEqual(picked['screen_distance'], 4)
        self.assertEqual(picked['depth'], .5)

    def test_sampled_curve_uses_nearest_segment_not_endpoint_or_whole_chord(self):
        curve = edge(2, [[0, 0, .3, 0, 0, 0], [10, 10, .3, 1, 1, 0],
                         [20, 0, .3, 2, 0, 0]])
        picked = nearest_edge((14, 8), [curve])
        self.assertEqual(picked['screen_position'], [13, 7])
        for actual, expected in zip(picked['position'], [1.3, .7, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(picked['screen_distance'], math.sqrt(2))

    def test_endpoint_selection_clamps_segment_parameter(self):
        picked = nearest_edge((104, 3), [horizontal(1)])
        self.assertEqual(picked['screen_position'], [100, 0])
        self.assertEqual(picked['position'], [10, 0, 3])
        self.assertEqual(picked['screen_distance'], 5)

    def test_closest_pixels_win_before_depth_then_depth_breaks_tie(self):
        picked = nearest_edge((50, 4), [horizontal(0, y=0, depth=.1), horizontal(1, y=5, depth=.8)])
        self.assertEqual(picked['edge_index'], 1)
        picked = nearest_edge((50, 0), [horizontal(0, depth=.9), horizontal(1, depth=.2)])
        self.assertEqual(picked['edge_index'], 1)
        picked = nearest_edge((50, 0), [horizontal(3, depth=.2), horizontal(1, depth=.2)])
        self.assertEqual(picked['edge_index'], 3)

    def test_different_edges_on_same_body_retain_edge_identity(self):
        picked = nearest_edge((50, 5), [horizontal(10, y=0), horizontal(11, y=6)])
        self.assertEqual((picked['reference'], picked['edge_index']), ('U1', 11))

    def test_accept_rejection_falls_back_to_another_edge_or_segment(self):
        picked = nearest_edge((50, 1), [horizontal(1, y=0), horizontal(2, y=4)],
                              accept=lambda candidate: candidate['edge_index'] != 1)
        self.assertEqual(picked['edge_index'], 2)
        polyline = edge(3, [[0, 0, .1, 0, 0, 0], [100, 0, .1, 10, 0, 0],
                            [100, 5, .5, 10, 5, 0], [0, 5, .5, 0, 5, 0]])
        picked = nearest_edge((50, 1), [polyline], accept=lambda candidate: candidate['depth'] >= .3)
        self.assertEqual(picked['screen_position'], [50, 5])
        self.assertIsNone(nearest_edge((50, 1), [polyline], accept=lambda candidate: False))

    def test_clipped_missing_and_nonfinite_samples_break_continuity(self):
        for bad in (None, [50, 0, -.1, 5, 0, 0], [50, 0, 1.1, 5, 0, 0],
                    [50, 0, float('nan'), 5, 0, 0], [50, 0, .5, float('inf'), 0, 0]):
            with self.subTest(bad=bad):
                curve = edge(1, [[0, 0, .5, 0, 0, 0], bad, [100, 0, .5, 10, 0, 0]])
                self.assertIsNone(nearest_edge((50, 0), [curve]))
        clipped = edge(2, [[0, 0, -1, 0, 0, 0], [100, 0, 2, 10, 0, 0]])
        self.assertIsNone(nearest_edge((50, 0), [clipped]))

    def test_depth_and_world_use_same_projected_parameter_with_explicit_perspective_approximation(self):
        # The input has no clip W: world XYZ is a sampled-polyline witness,
        # not perspective-correct unprojection or a kernel distance result.
        curve = edge(1, [[0, 0, .2, 2, 4, 10], [100, 0, .8, 12, 8, 20]])
        picked = nearest_edge((25, 0), [curve])
        self.assertEqual(picked['position'], [4.5, 5, 12.5])
        self.assertAlmostEqual(picked['depth'], .35)

    def test_degenerate_malformed_and_out_of_tolerance_edges_are_ignored(self):
        invalid = [None, {}, edge(-1, []), edge(True, []), dict(reference='', edge_index=0, points=[]),
                   edge(1, None), edge(2, [[0, 0, .5, 0, 0, 0]]),
                   edge(3, [[10, 10, .5, 0, 0, 0], [10, 10, .2, 0, 0, 5]])]
        self.assertIsNone(nearest_edge((10, 10), invalid))
        self.assertIsNone(nearest_edge((50, 8.001), [horizontal(1)]))
        self.assertIsNotNone(nearest_edge((50, 8), [horizontal(1)]))
        self.assertIsNone(nearest_edge((50, 2), [horizontal(1)], tolerance=1))
        self.assertIsNone(nearest_edge((float('nan'), 0), [horizontal(1)]))
        self.assertIsNone(nearest_edge(None, [horizontal(1)]))
        for tolerance in (-1, 8.1, float('inf'), True):
            with self.subTest(tolerance=tolerance), self.assertRaisesRegex(ValueError, '0 and 8'):
                nearest_edge((50, 0), [horizontal(1)], tolerance=tolerance)


if __name__ == '__main__':
    unittest.main()
