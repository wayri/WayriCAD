"""Behaviour checks for the native-API-independent centreline generator."""

import importlib.util
from math import hypot
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("trace_refiner_geometry", Path(__file__).parents[1] / "geometry.py")
geometry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(geometry)
simplify = geometry.simplify


class GeometryTests(unittest.TestCase):
    def test_exact_collinear_subdivisions_collapse_at_zero_tolerance(self):
        for points in ([(0, 0), (1, 0), (3, 0)], [(0, 0), (1, 1), (3, 3)]):
            self.assertEqual(simplify(points, 0, 0), [points[0], points[-1]])

    def test_small_horizontal_excursion_flattens(self):
        points = [(0, 0), (1, 0), (1.02, .02), (2, .02), (2.02, 0), (3, 0)]
        self.assertEqual(simplify(points, .025, .1), [(0, 0), (3, 0)])
        self.assertIsNone(simplify(points, .005, .1))
        self.assertIsNone(simplify(points, .025, .001))

    def test_oblique_excursion_flattens(self):
        points = [(0, 0), (1, 1), (1.02, 1), (2.02, 2), (2.02, 2.02), (3, 3)]
        self.assertEqual(simplify(points, .025, .1), [(0, 0), (3, 3)])

    def test_valid_bend_is_retained(self):
        self.assertIsNone(simplify([(0, 0), (1, 0), (2, 1)], .05, .1))
        self.assertEqual(simplify([(0, 0), (.5, 0), (1, 0), (2, 1)], 0, 0),
                         [(0, 0), (1, 0), (2, 1)])

    def test_endpoint_and_length_contract_for_single_bend(self):
        points = [(0, 0), (1, 0), (1.01, .01), (2, .01), (3, 1.01)]
        result = simplify(points, .025, .1)
        self.assertIsNotNone(result)
        self.assertEqual((result[0], result[-1]), (points[0], points[-1]))
        length = lambda path: sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
        self.assertLessEqual(length(result), length(points))
        self.assertLessEqual(length(points) - length(result), .1)
        self.assertLessEqual(len(result), 3)
        self.assertTrue(all(geometry._octilinear(a, b) for a, b in zip(result, result[1:])))
        self.assertEqual(result, simplify(points, .025, .1))

    def test_backtrack_repetition_intersection_and_tuning_are_rejected(self):
        invalid = [
            [(0, 0), (2, 0), (1, 0), (3, 0)],
            [(0, 0), (1, 0), (1, 1), (1, 0), (3, 0)],
            [(0, 0), (2, 2), (0, 2), (2, 0), (3, 0)],
            [(0, 0), (1, .01), (2, 0), (3, .01), (4, 0)],
        ]
        for points in invalid:
            with self.subTest(points=points):
                self.assertIsNone(simplify(points, 10, 100))

    def test_invalid_bounds_and_coordinates(self):
        points = [(0, 0), (1, 0), (2, 0)]
        for deviation, shortening in [(-1, .1), (.1, -1), (float("nan"), .1), (.1, float("inf"))]:
            self.assertIsNone(simplify(points, deviation, shortening))
        self.assertIsNone(simplify([(0, 0), (float("nan"), 0), (2, 0)]))
        self.assertIsNone(simplify([(0, 0), (1, 0, 0), (2, 0)]))

    def test_capsule_coverage_checks_interiors_not_only_vertices(self):
        # Both ends of the shortcut are on the target, but its centre is far
        # from the original L. The directed certificate must reject it.
        self.assertFalse(geometry._covered([(0, 0), (1, 1)], [(0, 0), (0, 1), (1, 1)], .1))
        # A segment crossing several collinear capsules can be proved by
        # subdivision; checking only whether one capsule contains it fails.
        self.assertTrue(geometry._covered([(0, 0), (3, 0)], [(0, 0), (1, 0), (3, 0)], .01))

    def test_translated_native_precision_jog(self):
        points = [(1, 2), (3, 2), (3.03, 2.03), (5, 2.03), (7, 2.03)]
        result = simplify(points, .05, .1)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], points[0])
        self.assertEqual(result[-1], points[-1])
        self.assertTrue(geometry._covered(points, result, .05))
        self.assertTrue(geometry._covered(result, points, .05))
        self.assertFalse(geometry._octilinear((0, 0), (1, 1.000001)))
        self.assertFalse(geometry._covered([(0, .0000000001), (1, .0000000001)],
                                           [(0, 0), (1, 0)], 0))

    def test_local_cleanup_retains_large_route_turns(self):
        points = [(0, 0), (1, 0), (1.02, .02), (2, .02), (2.02, 0),
                  (3, 0), (4, 0), (5, 1), (5, 3), (4, 4), (4, 5)]
        self.assertIsNone(simplify(points, .025, .1))
        result = geometry.simplify_local(points, .025, .1)
        self.assertIsNotNone(result)
        self.assertLess(len(result), len(points))
        self.assertEqual((result[0], result[-1]), (points[0], points[-1]))
        self.assertIn((5, 3), result)
        self.assertIn((4, 4), result)
        self.assertTrue(geometry._covered(points, result, .025))
        self.assertTrue(geometry._covered(result, points, .025))
        self.assertLessEqual(geometry._length(points) - geometry._length(result), .1 + 1e-9)

    def test_local_cleanup_preserves_repeated_tuning_and_valid_corner(self):
        tuning = [(0, 0), (1, .01), (2, 0), (3, .01), (4, 0), (5, 1), (5, 3)]
        self.assertIsNone(geometry.simplify_local(tuning, .1, .1))
        self.assertIsNone(geometry.simplify_local([(0, 0), (1, 0), (2, 1)], .05, .1))


if __name__ == "__main__":
    unittest.main()
