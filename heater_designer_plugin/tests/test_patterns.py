"""Topology and physical-envelope checks for the additional heater fills."""
import math
import unittest
from collections import defaultdict

from heater_designer_plugin.patterns import (PATTERNS, circular_envelope,
                                           split_circular_envelope, generate_path)


def _segment_distance(a, b, c, d):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    if cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0:
        return 0.0
    def point_distance(p, q, r):
        dx,dy = r[0]-q[0], r[1]-q[1]
        t = max(0.,min(1.,((p[0]-q[0])*dx+(p[1]-q[1])*dy)/(dx*dx+dy*dy)))
        return math.hypot(p[0]-q[0]-t*dx,p[1]-q[1]-t*dy)
    return min(point_distance(a,c,d),point_distance(b,c,d),
               point_distance(c,a,b),point_distance(d,a,b))


def _minimum_nonlocal_gap(points, width, pitch):
    """Exact segment separation, with 2*pitch of local series joints exempt.

    A spatial bucket only removes pairs farther than twice the pitch; the
    final distance is between the full segments, including terminals.
    """
    cumulative, buckets = [0.], defaultdict(list)
    size = 2*pitch
    for index,(a,b) in enumerate(zip(points,points[1:])):
        cumulative.append(cumulative[-1]+math.dist(a,b))
        for x in range(math.floor((min(a[0],b[0])-pitch)/size),
                       math.floor((max(a[0],b[0])+pitch)/size)+1):
            for y in range(math.floor((min(a[1],b[1])-pitch)/size),
                           math.floor((max(a[1],b[1])+pitch)/size)+1):
                buckets[x,y].append(index)
    pairs = set()
    for indices in buckets.values():
        for position,i in enumerate(indices):
            for j in indices[position+1:]:
                if cumulative[j]-cumulative[i+1] >= 2*pitch-1e-9:
                    pairs.add((i,j))
    return min(_segment_distance(points[i],points[i+1],points[j],points[j+1])
               for i,j in pairs)-width


class PatternTests(unittest.TestCase):
    def test_every_pattern_is_one_finite_envelope_contained_path(self):
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                points = generate_path(pattern, 80, 80, 1, .5)
                self.assertGreater(len(points), 3)
                self.assertEqual(len(set(points)), len(points))
                for x, y in points:
                    self.assertTrue(math.isfinite(x) and math.isfinite(y))
                    self.assertGreaterEqual(x, .5 - 1e-9)
                    self.assertLessEqual(x, 79.5 + 1e-9)
                    self.assertGreaterEqual(y, .5 - 1e-9)
                    self.assertLessEqual(y, 79.5 + 1e-9)

    def test_circular_raster_preserves_disk_and_row_pitch(self):
        points = generate_path("Circular serpentine", 90, 70, 2, .25)
        cx, cy, radius = circular_envelope(90, 70)
        for x, y in points:
            self.assertLessEqual(math.hypot(x-cx, y-cy) + 1, radius + 1e-9)
        rows = points[::2]
        self.assertTrue(all(abs(b[1]-a[1]-2.25) < 1e-9 for a, b in zip(rows, rows[1:])))
        self.assertEqual(points, generate_path("Circular foil", 90, 70, 2, .25))

    def test_annular_polyline_and_leads_respect_inner_opening(self):
        trace, gap, inner, lead = 2, .8, 20, 10
        points = generate_path("Annular arc meander", 80, 80, trace, gap,
                               inner, 55, lead)
        cx, cy, radius = circular_envelope(80, 80, lead)
        self.assertAlmostEqual(points[0][1], trace / 2)
        self.assertAlmostEqual(points[-1][1], trace / 2)
        self.assertLess((points[0][0]-cx)*(points[-1][0]-cx), 0)
        for a, b in zip(points[1:-1], points[2:-1]):
            ax, ay = a[0]-cx, a[1]-cy
            dx, dy = b[0]-a[0], b[1]-a[1]
            t = max(0, min(1, -(ax*dx+ay*dy)/(dx*dx+dy*dy)))
            self.assertGreaterEqual(math.hypot(ax+t*dx, ay+t*dy)-trace/2, inner/2-1e-9)
        for x, y in points[1:-1]:
            self.assertLessEqual(math.hypot(x-cx, y-cy)+trace/2, radius+1e-9)
        # Arc radial spacing includes chord-sag allowance, rather than relying
        # only on distances between vertices.
        radii = sorted({round(math.hypot(x-cx, y-cy), 7) for x, y in points[1:-1]})
        self.assertGreaterEqual(min(b-a for a,b in zip(radii, radii[1:])), trace+gap)

    def test_maze_is_unique_unit_grid_path_and_seeded(self):
        for pattern in ("Seeded maze", "Circular maze"):
            points = generate_path(pattern, 50, 40, 1.5, .5, random_seed=42)
            self.assertEqual(points, generate_path(pattern, 50, 40, 1.5, .5, random_seed=42))
            self.assertNotEqual(points, generate_path(pattern, 50, 40, 1.5, .5, random_seed=43))
            self.assertEqual(len(points), len(set(points)))
            for a,b in zip(points, points[1:]):
                dx,dy = abs(a[0]-b[0]), abs(a[1]-b[1])
                self.assertTrue((abs(dx-2)<1e-9 and dy<1e-9) or
                                (abs(dy-2)<1e-9 and dx<1e-9))
            # Unique vertices and axis-aligned unit grid edges imply no
            # nonlocal intersections, with at least one pitch of separation.
            if pattern == "Circular maze":
                self.assertTrue(all(math.hypot(x-25, y-20)+.75 <= 20+1e-9 for x,y in points))

    def test_maze_covers_all_rectangular_cells(self):
        points = generate_path("Seeded maze", 20, 20, 1, 1)
        # Five by five coarse cells; four distinct path vertices per cell.
        self.assertEqual(len(points), 100)

    def test_full_width_presets_have_no_nonlocal_copper_bypass(self):
        cases = (("Annular arc meander",80,90,1,.3,30,24,10),
                 ("Circular foil",80,80,3,.25,20,30,10),
                 ("Split circular foil",90,80,3,.25,20,30,10),
                 ("Seeded maze",80,80,1.5,.4,20,30,10),
                 ("Circular maze",80,80,1.5,.4,20,30,10))
        for pattern,w,h,trace,gap,inner,slot,lead in cases:
            with self.subTest(pattern=pattern):
                points = generate_path(pattern,w,h,trace,gap,inner,slot,lead,17)
                actual = _minimum_nonlocal_gap(points,trace,trace+gap)
                self.assertGreaterEqual(actual, gap-1e-8)

    def test_split_circular_foil_has_left_midline_terminals_and_disk_banks(self):
        for width,height,trace,gap,lead in ((90,80,3,.25,10),
                                           (80,60,.5,.2,8),
                                           (50,70,2,1,5)):
            with self.subTest(width=width,height=height):
                pitch = trace+gap
                points = generate_path("Split circular foil",width,height,
                                       trace,gap,terminal_length_mm=lead)
                cx,cy,radius = split_circular_envelope(width,height,lead)
                self.assertEqual(points[0],(trace/2,cy-pitch/2))
                self.assertEqual(points[-1],(trace/2,cy+pitch/2))
                self.assertEqual(len(points),len(set(points)))
                for x,y in points[1:-1]:
                    self.assertLessEqual(math.hypot(x-cx,y-cy)+trace/2,radius+1e-9)
                self.assertGreaterEqual(_minimum_nonlocal_gap(points,trace,pitch),gap-1e-8)

    def test_split_terminal_space_cannot_remove_disk(self):
        with self.assertRaisesRegex(ValueError,"too little room"):
            generate_path("Split circular foil",80,80,3,.25,terminal_length_mm=75)

    def test_invalid_geometry_and_excessive_detail_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "too detailed"):
            generate_path("Seeded maze", 100, 100, .01, .01)
        with self.assertRaisesRegex(ValueError, "three arc lanes"):
            generate_path("Annular arc meander", 40, 40, 2, 1, 29, 30, 5)
        with self.assertRaisesRegex(ValueError, "too narrow"):
            generate_path("Annular arc meander", 80, 80, 3, 1, 5, 5, 10)
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                generate_path("Circular foil", value, 80, 1, .5)


if __name__ == "__main__":
    unittest.main()
