"""Coordinate contracts and optional real EMerge commit; never mesh or solve."""
import importlib.util
import json
import math
import subprocess
import sys
import unittest
from unittest import mock

from quick_emerge_plugin.siw_dra_geometry import build, geometry_spec


class GeometrySpecTests(unittest.TestCase):
    def test_preview_import_does_not_load_solver_or_vtk(self):
        result = subprocess.run([
            sys.executable, "-B", "-c",
            "import sys; from quick_emerge_plugin.siw_dra_geometry import geometry_spec; "
            "geometry_spec(); assert not any(n.split('.')[0] in ('emerge','vtk','numpy') "
            "for n in sys.modules)",
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pure_fresh_json_descriptor_and_origin(self):
        spec = geometry_spec()
        self.assertEqual(spec["kind"], "research_solids")
        self.assertEqual(spec["audit_to_model_shift_mm"], [0, 14.5, 0])
        self.assertEqual(spec["bbox_mm"], [-32, -42.5, 32, 42.5])
        self.assertEqual(json.loads(json.dumps(spec)), spec)
        spec["dielectrics"][0]["er"] = 100
        spec["assumptions"][0]["detail"] = "changed"
        self.assertEqual(geometry_spec()["dielectrics"][0]["er"], 4.6)
        self.assertNotEqual(geometry_spec()["assumptions"][0]["detail"], "changed")

    def test_dra_bounds_and_drawing_margins(self):
        substrate, dra = geometry_spec()["dielectrics"]
        self.assertEqual(substrate["bounds_mm"], [-32, -42.5, -1.6, 32, 42.5, 0])
        self.assertEqual(dra["bounds_mm"], [-20, -7.5, 0, 20, 32.5, 21])
        self.assertEqual(dra["bounds_mm"][1] - (-13.5), 6)
        self.assertEqual(42.5 - dra["bounds_mm"][4], 10)
        self.assertEqual(substrate["loss_tangent"], 0.019)
        self.assertEqual(dra["loss_tangent"], 0.0019)

    def test_conditional_lattice_is_twenty_cylinders_not_walls(self):
        vias = geometry_spec()["vias"]
        centers = {(v["x_mm"], v["y_mm"]) for v in vias}
        self.assertEqual(len(centers), 20)
        self.assertEqual(len(vias), 20)
        self.assertEqual(centers, {(x, -9.5 + 8*n) for x in (-28, 28) for n in range(7)}
                         | {(-28 + 8*n, 38.5) for n in range(8)})
        for v in vias:
            self.assertEqual((v["z0_mm"], v["z1_mm"], v["radius_mm"]), (-1.6, 0, 2))

    def test_slot_is_open_toward_feed_and_absent_from_preview_copper(self):
        spec = geometry_spec()
        self.assertEqual(spec["slot_rectangles_mm"], [
            [-11.5, 9, 11.5, 16], [-11.5, -11, -5.5, 9], [5.5, -11, 11.5, 9]])
        top = [s for s in spec["sheets"] if s["role"] == "top"]
        area = 0
        for s in top:
            (x0, y0, z), _, (x1, y1, _), _ = s["vertices_mm"]
            self.assertEqual(z, 0)
            area += (x1-x0)*(y1-y0)
            for a, b, c, d in spec["slot_rectangles_mm"]:
                self.assertFalse(max(x0, a) < min(x1, c) and max(y0, b) < min(y1, d))
        self.assertAlmostEqual(area, 64*56 - 23*7 - 2*20*6)
        self.assertEqual(spec["ports"], [[[0, -42.5, -1.6], [0, -42.5, 0]]])

    def test_assumptions_preserve_conflict_and_idealizations(self):
        assumptions = {a["id"]: a for a in geometry_spec()["assumptions"]}
        self.assertEqual(assumptions["width_conflict"]["status"], "unresolved")
        self.assertIn("49.870769", assumptions["width_conflict"]["detail"])
        self.assertIn("solid PEC cylinders", assumptions["posts"]["detail"])
        self.assertIn("unknown", assumptions["posts"]["detail"])
        self.assertIn("zero-thickness", assumptions["copper"]["detail"])

    def test_rejects_unsupported_settings_before_geometry(self):
        for advanced, margin, message in [
            ({"conductor": "finite", "boundary": "absorbing"}, 30, "PEC"),
            ({"conductor": "pec", "boundary": "pml"}, 30, "PML"),
            ({"conductor": "pec", "boundary": "absorbing"}, 21, "clearance"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                build(None, None, {"advanced": advanced, "air_margin_mm": margin}, {})


@unittest.skipUnless(importlib.util.find_spec("emerge"), "EMerge runtime required")
class EMergeCommitTests(unittest.TestCase):
    def test_actual_commit_without_meshing_or_solving(self):
        import emerge as em
        import gmsh
        import numpy as np
        from quick_emerge_plugin.model import validate_config

        config = validate_config({"air_margin_mm": 50, "points": 3, "field_grid": 61,
                                  "field_z_mm": 20, "advanced": {
                                      "field_layers": 3, "field_z_min_mm": 0.8}})
        with mock.patch.object(em.Simulation, "generate_mesh",
                               side_effect=AssertionError("No meshing allowed")):
            model, air, ports, widths, h, bbox = build(em, np, config, {})
        self.assertTrue(model.state._geometry_committed)
        self.assertEqual(len(model._quick_conductors), 22)
        self.assertEqual(len(ports), 1)
        self.assertEqual(len(widths), 1)
        self.assertAlmostEqual(widths[0], 0.00295)
        self.assertAlmostEqual(h, 0.0016)
        self.assertEqual(bbox, [-32, -42.5, 32, 42.5])
        self.assertEqual(model._quick_scene_geometry, geometry_spec())
        top_area, ground_area = [sum(gmsh.model.occ.getMass(d, t) for d, t in g.dimtags)
                                 for g in model._quick_conductors[:2]]
        self.assertAlmostEqual(top_area, (64*56 - 23*7 - 2*20*6 + 2.95*10
                                          + (2.95+20)*19/2) * 1e-6, places=12)
        self.assertAlmostEqual(ground_area, 64*85*1e-6, places=12)
        self.assertAlmostEqual(sum(gmsh.model.occ.getMass(d, t) for d, t in ports[0].dimtags),
                               2.95*1.6*1e-6, places=12)
        # Verify real OCC cylinder volume and dielectric removal, not just objects.
        for post in model._quick_conductors[2:]:
            volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in post.dimtags)
            self.assertAlmostEqual(volume, math.pi * .002**2 * .0016, places=13)
            self.assertIsNotNone(post.properties.get(em.VoidAttribute))
            self.assertTrue(set(post.tags).issubset(model.mw.bc.assigned(3)))
            self.assertTrue(set(post.boundary().tags).issubset(model.mw.bc.assigned(2)))
        substrate = next(g for g in model.all_geos()
                         if g.material is not None and g.material.er.value == 4.6)
        volume = sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in substrate.dimtags)
        self.assertAlmostEqual(volume, .064*.085*.0016 - 20*math.pi*.002**2*.0016, places=13)
        dra = next(g for g in model.all_geos()
                   if g.material is not None and g.material.er.value == 10)
        self.assertAlmostEqual(sum(gmsh.model.occ.getMass(d, t) for d, t in dra.dimtags),
                               .040*.040*.021, places=13)
        self.assertIsNotNone(air)


if __name__ == "__main__":
    unittest.main()
