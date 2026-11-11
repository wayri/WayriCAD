"""Pure reconstruction checks and native CAD commit, never a mesh or RF solve."""
import importlib.util
import json
import math
import subprocess
import sys
import unittest
from unittest.mock import patch

from quick_emerge_plugin.siw_horn_geometry import build, geometry_spec


def area(vertices):
    return abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(vertices, vertices[1:] + vertices[:1]))) / 2


class PureGeometryTests(unittest.TestCase):
    def test_import_and_spec_are_solver_independent(self):
        code = (
            'import sys; from quick_emerge_plugin.siw_horn_geometry import geometry_spec; '
            'geometry_spec(); '
            'assert not any(m.split(".")[0] in {"emerge", "vtk", "numpy"} for m in sys.modules)'
        )
        subprocess.run([sys.executable, '-B', '-c', code], check=True,
                       capture_output=True, text=True)
        spec = geometry_spec()
        self.assertEqual(json.loads(json.dumps(spec)), spec)
        spec['vias'][0]['x_mm'] = 1000
        spec['source_parameters_mm']['W'] = 1000
        self.assertNotEqual(geometry_spec()['vias'][0]['x_mm'], 1000)
        self.assertEqual(geometry_spec()['source_parameters_mm']['W'], 11.8)

    def test_table_2_and_material_audit(self):
        spec = geometry_spec()
        self.assertEqual(spec['source_parameters_mm'], dict(
            W=11.8, Wo=13, L1=6.705, L2=21.795, L3=3.980, Wi=1.575,
            Li=3.5, Wt=3.383, Lt=8.405, Wm=2.835, Lm=1.064,
            Wf=1.15, Lf=12, P=.15, Wc=.192, Lc=5.9, d=.3, S=.6))
        self.assertEqual(spec['board_mm'], [32.48, 13])
        self.assertEqual(spec['long_axis'], 'X')
        self.assertEqual(spec['bounds_mm'], [-16.24, -6.5, -.508, 16.24, 6.5, 0])
        self.assertEqual(spec['copper_thickness_um'], 17.5)
        self.assertEqual(spec['copper_conductivity_s_m'], 5.8e7)
        self.assertEqual(spec['kind'], 'research_solids')
        self.assertEqual(spec['source_geometry_kind'], 'paper_siw_horn')
        for slab in spec['dielectrics']:
            self.assertEqual(slab['er'], 2.55)
            self.assertEqual(slab['loss_tangent'], .0014)
        self.assertEqual(spec['dielectrics'][0]['bounds_mm'][3],
                         spec['dielectrics'][1]['bounds_mm'][0])
        assumptions = ' '.join(spec['assumptions'])
        for required in ('32.48', '32 mm', 'not W or Wo', 'not tabulated',
                         'parallel-strip', 'zero-thickness PEC', 'no rescaling'):
            self.assertIn(required, assumptions)

    def test_separate_posts_symmetric_rows_and_source_pitch(self):
        spec = geometry_spec()
        vias = spec['vias']
        self.assertEqual(len(vias), 82)
        row = vias[1::2]
        origin = spec['bounds_mm'][0]
        for low, high in zip(vias[::2], row):
            self.assertEqual(low['x_mm'], high['x_mm'])
            self.assertEqual(low['y_mm'], -high['y_mm'])
            self.assertEqual(high['radius_mm'], .15)
            self.assertEqual((high['z0_mm'], high['z1_mm']), (-.508, 0))
            x, y, r = high['x_mm'], high['y_mm'], high['radius_mm']
            self.assertGreaterEqual(x - r, origin)
            self.assertLessEqual(x + r, origin + 28.5)
            self.assertLessEqual(y + r, 11.8 / 2)
        self.assertAlmostEqual(row[0]['x_mm'] - origin, 4.564)
        self.assertEqual(row[0]['y_mm'], 3.383 / 2)
        flare = origin + 12.969
        for a, b in zip(row, row[1:]):
            distance = math.hypot(b['x_mm'] - a['x_mm'], b['y_mm'] - a['y_mm'])
            if a['x_mm'] < flare < b['x_mm']:
                distance = flare - a['x_mm'] + (b['x_mm'] - flare) / math.cos(math.radians(15))
            self.assertAlmostEqual(distance, .6)
            self.assertGreater(distance, .3)
        self.assertAlmostEqual((row[-1]['y_mm'] - row[-2]['y_mm']) /
                               (row[-1]['x_mm'] - row[-2]['x_mm']), math.tan(math.radians(15)))

    def test_slots_belts_and_port(self):
        spec = geometry_spec()
        self.assertEqual(len(spec['sheets']), 8)
        for sheet_index in (0, 4):
            sheet = spec['sheets'][sheet_index]
            self.assertEqual(len(sheet['holes_mm']), 2)
            for hole in sheet['holes_mm']:
                self.assertAlmostEqual(area(hole), 5.9 * .192)
                self.assertEqual({v[2] for v in hole}, {sheet['vertices_mm'][0][2]})
            belts = spec['sheets'][sheet_index + 1:sheet_index + 4]
            for belt in belts:
                self.assertAlmostEqual(area(belt['vertices_mm']), 1.15 * 12)
                self.assertNotIn('holes_mm', belt)
            for a, b in zip(belts, belts[1:]):
                self.assertAlmostEqual(b['vertices_mm'][0][0] - a['vertices_mm'][1][0], .15)
        self.assertEqual(spec['ports'], [[[-16.24, 0, -.508], [-16.24, 0, 0]]])
        self.assertEqual(spec['port_width_mm'], 1.575)

    def test_finite_conductor_is_rejected_before_model_creation(self):
        with self.assertRaisesRegex(ValueError, 'PEC'):
            build(None, None, {'advanced': {'conductor': 'finite'}}, {})


@unittest.skipUnless(importlib.util.find_spec('emerge'), 'Actual EMerge runtime required')
class NativeGeometryTests(unittest.TestCase):
    def test_actual_emerge_commit_and_boolean_slot_areas(self):
        import emerge as em
        import gmsh
        import numpy as np
        from quick_emerge_plugin.advanced import ADVANCED_DEFAULTS
        from quick_emerge_plugin.model import DEFAULT_CONFIG

        config = {**DEFAULT_CONFIG, 'f_start_hz': 54e9, 'f_stop_hz': 70e9,
                  'points': 3, 'air_margin_mm': 5, 'mesh_edge_mm': .12,
                  'resolution': .3, 'advanced': dict(ADVANCED_DEFAULTS)}
        with patch.object(em.Simulation, 'generate_mesh', side_effect=AssertionError('No mesh')):
            result = build(em, np, config, {'model_scope': 'Native CAD commit acceptance only.'})
        model, air, ports, widths, height, bounds = result
        self.assertTrue(model.state._geometry_committed)
        self.assertEqual(len(ports), 1)
        self.assertAlmostEqual(widths[0], .001575)
        self.assertAlmostEqual(height, .000508)
        self.assertEqual(bounds, [-16.24, -6.5, 16.24, 6.5])
        for dim, tag in ports[0].dimtags:
            self.assertEqual(dim,2)
            center=gmsh.model.occ.getCenterOfMass(dim,tag)
            self.assertAlmostEqual(center[0],-.01624,places=10)
            self.assertAlmostEqual(center[1],0,places=10)
            self.assertAlmostEqual(center[2],-.000254,places=10)
            normal=gmsh.model.getNormal(tag,[0.,0.])
            self.assertGreater(abs(normal[0]),.99)
            self.assertLess(abs(normal[1]),1e-8)
            self.assertLess(abs(normal[2]),1e-8)
        spec = geometry_spec()
        self.assertEqual(model._quick_scene_geometry, spec)
        self.assertIn('Native CAD commit acceptance only.', model._quick_research_assumptions)
        self.assertEqual(len(model._quick_conductors), 8 + len(spec['vias']))
        # Actual OCC areas prove slots were subtracted, not merely drawn in a viewer.
        for sheet, obj in zip(spec['sheets'], model._quick_conductors[:8]):
            expected = area(sheet['vertices_mm']) - sum(map(area, sheet.get('holes_mm', [])))
            self.assertTrue(all(dim == 2 for dim, _ in obj.dimtags))
            actual = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in obj.dimtags)
            self.assertAlmostEqual(actual / 1e-6, expected, delta=1e-6)
        for obj in model._quick_conductors[8:]:
            self.assertTrue(all(dim == 3 for dim, _ in obj.dimtags))
            volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in obj.dimtags)
            self.assertAlmostEqual(volume / 1e-9, math.pi * .15 ** 2 * .508, delta=1e-7)
            self.assertIsNotNone(obj.properties.get(em.VoidAttribute))
            self.assertTrue(set(obj.tags).issubset(model.mw.bc.assigned(3)))
            self.assertTrue(set(obj.boundary().tags).issubset(model.mw.bc.assigned(2)))
        self.assertEqual(len(gmsh.model.mesh.getNodes()[0]), 0)


if __name__ == '__main__':
    unittest.main()
