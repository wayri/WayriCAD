"""Focused mesh/deck checks without optional native executables."""
from __future__ import annotations

import math
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quick_therm_plugin.thermal_calculix import (
    calculix_deck, gmsh_geo, prepare_calculix, read_msh2, run_calculix,
)


def fixture():
    polygon = {"outer": [[0, 0], [10, 0], [10, 10], [0, 10]], "holes": []}
    geometry = {"outline_status": "valid", "outline": [{"outer_mm": polygon["outer"], "holes_mm": []}],
                "layers": [{"id": 0, "z_mm": .0175, "thickness_mm": .035, "polygons_mm": [polygon]},
                           {"id": 31, "z_mm": 1.5825, "thickness_mm": .035, "polygons_mm": [polygon]}],
                "barrels": [], "mounting_holes": []}
    view = {"components": [{"reference": "U1", "on_board": True, "side": "top",
                            "bbox_mm": [0, 0, 10, 10]}]}
    result = {"components": [{"reference": "U1", "heat_path": "board", "power_w": 1.25}]}
    settings = {"gmsh_mesh_size_mm": 2, "dielectric_k_w_mk": .3,
                "copper_k_w_mk": 385, "bottom_temperature_c": 20}
    nodes = {1: (0, 0), 2: (10, 0), 3: (10, 10), 4: (0, 10)}
    triangles = [(1, 2, 3), (1, 3, 4)]
    return geometry, view, result, settings, nodes, triangles


class CalculixBridgeTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("gmsh"), "Needs Gmsh Python runtime")
    def test_native_gmsh_python_generates_deck(self):
        geometry, view, result, settings, *_ = fixture()
        with tempfile.TemporaryDirectory() as root, patch(
                "quick_therm_plugin.thermal_calculix.shutil.which", return_value=None):
            out = Path(root)/"candidate"
            manifest = prepare_calculix(geometry, view, result, settings, out)
            self.assertEqual(manifest["status"], "deck_ready", manifest.get("diagnostic"))
            self.assertEqual(manifest["mesh_backend"], "gmsh_python")
            self.assertAlmostEqual(manifest["power_w"], 1.25)
            self.assertTrue((out/"board.msh").is_file())
            self.assertTrue((out/"board.inp").is_file())

    def test_geo_keeps_outline_hole(self):
        geometry, *_ = fixture()
        geometry["outline"][0]["holes_mm"] = [[[4, 4], [6, 4], [6, 6], [4, 6]]]
        script = gmsh_geo(geometry, 1)
        self.assertIn("Plane Surface(1) = {1, 2};", script)
        self.assertIn("Physical Surface(1) = {1};", script)

    def test_wedge_deck_keeps_power_and_stackup_units(self):
        geometry, view, result, settings, nodes, triangles = fixture()
        deck, audit = calculix_deck(geometry, view, result, settings, nodes, triangles)
        self.assertEqual(audit["element_groups"], {"DIEL": 2, "CU0": 2, "DI0": 0, "CU1": 2, "DI1": 0})
        self.assertEqual(audit["wedge_elements"], 6)
        self.assertAlmostEqual(audit["power_w"], 1.25)
        self.assertEqual(audit["z_interfaces_mm"], [0, .035, 1.565, 1.6])
        self.assertIn("*ELEMENT, TYPE=DC3D6", deck)
        self.assertIn("0.0016", deck)
        self.assertIn("BOTTOM, 11, 11, 20", deck)
        self.assertIn("*HEAT TRANSFER, STEADY STATE", deck)

    def test_rejects_unmodelled_barrel_and_unresolved_source(self):
        geometry, view, result, settings, nodes, triangles = fixture()
        geometry["barrels"] = [{"id": "via-1"}]
        with self.assertRaisesRegex(ValueError, "vias"):
            calculix_deck(geometry, view, result, settings, nodes, triangles)
        geometry["barrels"] = []
        view["components"][0]["bbox_mm"] = [4.9, 4.9, 5.1, 5.1]
        with self.assertRaisesRegex(ValueError, "refine Gmsh"):
            calculix_deck(geometry, view, result, settings, nodes, triangles)

    def test_missing_gmsh_emits_inspectable_geometry_and_status(self):
        geometry, view, result, settings, *_ = fixture()
        with tempfile.TemporaryDirectory() as root, patch(
                "quick_therm_plugin.thermal_calculix.shutil.which", return_value=None), patch(
                "quick_therm_plugin.thermal_calculix.importlib.util.find_spec", return_value=None):
            out = Path(root)/"candidate"
            manifest = prepare_calculix(geometry, view, result, settings, out)
            self.assertEqual(manifest["status"], "needs_gmsh")
            self.assertEqual(manifest["result_status"], "not_solved")
            self.assertTrue((out/"board.geo").is_file())
            self.assertTrue((out/"manifest.json").is_file())
            self.assertFalse((out/"board.inp").exists())

    def test_msh2_reader_linear_triangles(self):
        data = "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n3\n1 0 0 0\n2 1 0 0\n3 0 1 0\n$EndNodes\n$Elements\n1\n1 2 2 1 1 1 2 3\n$EndElements\n"
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"tiny.msh"
            path.write_text(data, encoding="utf-8")
            nodes, triangles = read_msh2(path)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(triangles, [(1, 2, 3)])

    def test_solver_absence_is_reported_without_temperature_claim(self):
        geometry, view, result, settings, *_ = fixture()
        with tempfile.TemporaryDirectory() as root:
            out = Path(root)/"candidate"
            with patch("quick_therm_plugin.thermal_calculix.shutil.which", return_value=None):
                prepare_calculix(geometry, view, result, settings, out)
            # Pretend the deck was prepared; the missing-solver path is independent.
            import json
            path = out/"manifest.json"
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata.update(status="deck_ready", calculix_deck="board.inp")
            path.write_text(json.dumps(metadata), encoding="utf-8")
            with patch("quick_therm_plugin.thermal_calculix.shutil.which", return_value=None):
                outcome = run_calculix(out)
            self.assertEqual(outcome["status"], "needs_calculix")
            self.assertEqual(outcome["result_status"], "not_solved")


if __name__ == "__main__":
    unittest.main()
