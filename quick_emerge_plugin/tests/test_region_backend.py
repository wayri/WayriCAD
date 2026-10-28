import copy
from types import SimpleNamespace
import unittest

import numpy as np

from quick_emerge_plugin import region_backend as rb
from quick_emerge_plugin.region_ports import plan_region


def polygon(points, holes=None):
    return dict(outer_mm=points, holes_mm=holes or [])


def reviewed():
    outline = polygon([[0, 0], [10, 0], [10, 10], [0, 10]])
    signal = polygon([[0, 4], [10, 4], [10, 6], [0, 6]])
    ground = polygon(outline['outer_mm'], [[[4, 1], [6, 1], [6, 2], [4, 2]]])
    snapshot = dict(schema=1, source={'sha256': 'fixture'}, area=dict(id='roi', outline=[outline]),
                    substrate=dict(thickness_mm=1, outline=[outline]),
                    copper=[dict(net='SIG', layer='F.Cu', polygons=[signal]),
                            dict(net='GND', layer='B.Cu', polygons=[ground])])
    return plan_region(snapshot, 'SIG', 'GND')


CONFIG = dict(rule_area_id='roi', signal_net='SIG', reference_net='GND', solver='SUPERLU',
              er=4, air_margin_mm=5, resolution=.5, f_start_hz=1e9, f_stop_hz=2e9,
              points=3, mesh_edge_mm=2)


class Surface:
    def __init__(self, points=None, z=0):
        self.points, self.z, self.material = points, z, None
    def set_material(self, material):
        self.material = material
        return self
    def background(self):
        return self


class RecordingEM:
    def __init__(self):
        self.geo = self
        self.GCS = SimpleNamespace(displace=lambda x, y, z: z)
        self.lib = SimpleNamespace(PEC='PEC')
        self.EMSolver = {'SUPERLU': 'SUPERLU'}
        self.polygons, self.removals, self.extrusions, self.plates, self.boxes = [], [], [], [], []
        self.mw = SimpleNamespace(set_resolution=lambda *args: None, set_frequency_range=lambda *args: None)
        self.mesher = SimpleNamespace(set_boundary_size=lambda *args: None, set_face_size=lambda *args: None)
    def Simulation(self, name): return self
    def set_solver(self, solver): return self
    def set_nthreads(self, threads): self.threads = threads
    def Material(self, **kwargs): return kwargs
    def commit_geometry(self): pass
    def XYPolygon(self, xs, ys, **kwargs):
        points = list(zip(xs, ys))
        def geo(cs):
            surface = Surface(points, cs)
            self.polygons.append(surface)
            return surface
        return SimpleNamespace(geo=geo)
    def remove(self, surface, hole):
        self.removals.append((surface, hole))
        return surface
    def extrude(self, surface, **kwargs):
        self.extrusions.append((surface, kwargs))
        return surface
    def Plate(self, *args):
        self.plates.append(args)
        return Surface()
    def Box(self, *args, **kwargs):
        self.boxes.append((args, kwargs))
        return Surface()


class RegionBackendTests(unittest.TestCase):
    def test_digest_tracks_exact_review_content_and_is_key_order_independent(self):
        region = reviewed()
        self.assertEqual(rb.region_digest(region), rb.region_digest(dict(reversed(list(region.items())))))
        changed = copy.deepcopy(region)
        changed['ports'][0]['width_mm'] += .01
        self.assertNotEqual(rb.region_digest(region), rb.region_digest(changed))
        changed['ports'][0]['width_mm'] = float('nan')
        with self.assertRaises(ValueError):
            rb.region_digest(changed)

    def test_valid_region_returns_actual_substrate_bounds(self):
        checked, bounds = rb.validate_region(reviewed(), CONFIG)
        self.assertEqual(bounds, [0, 0, 10, 10])
        self.assertEqual(len(checked['ports']), 2)

    def test_blocked_wrong_area_changed_ports_and_bad_numeric_geometry_rejected(self):
        mutations = [lambda r: r.update(blockers=['unsupported via']),
                     lambda r: r['area'].update(id='other'),
                     lambda r: r['ports'][0].update(width_mm=99),
                     lambda r: r['substrate'].update(thickness_mm='1'),
                     lambda r: r['copper'][0]['polygons'][0]['outer_mm'][0].__setitem__(0, float('nan')),
                     lambda r: r['substrate']['outline'][0]['outer_mm'][0].__setitem__(0, 'bad')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                region = copy.deepcopy(reviewed())
                mutation(region)
                with self.assertRaises(ValueError):
                    rb.validate_region(region, CONFIG)

    def test_geometry_uses_only_reviewed_clipped_polygons_and_preserves_holes(self):
        region = reviewed()
        em = RecordingEM()
        _, _, ports, widths, thickness, bbox = rb.build_region(em, np, CONFIG, region)
        # Substrate, signal, reference and reference hole: no synthetic full-board copper.
        expected = [region['substrate']['outline'][0]['outer_mm'],
                    region['copper'][0]['polygons'][0]['outer_mm'],
                    region['copper'][1]['polygons'][0]['outer_mm'],
                    region['copper'][1]['polygons'][0]['holes_mm'][0]]
        self.assertEqual([surface.points for surface in em.polygons],
                         [[(x*.001, y*.001) for x, y in ring] for ring in expected])
        self.assertEqual([surface.z for surface in em.polygons], [0, 0, -.001, -.001])
        self.assertEqual(len(em.removals), 1)
        self.assertEqual(em.extrusions[0][1], {'dz': -.001})
        self.assertEqual(len(ports), 2)
        self.assertEqual(widths, [.002, .002])
        self.assertEqual(thickness, .001)
        self.assertEqual(bbox, [0, 0, 10, 10])
        self.assertEqual(em.boxes[0][0], (.02, .02, .011))
        self.assertEqual(em.boxes[0][1]['position'], (-.005, -.005, -.006))


if __name__ == '__main__':
    unittest.main()
