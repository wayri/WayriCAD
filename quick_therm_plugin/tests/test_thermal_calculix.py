"""Focused mesh/deck checks without optional native executables."""
from __future__ import annotations

import math
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quick_therm_plugin.thermal_calculix import (
    calculix_deck, find_calculix, gmsh_geo, prepare_calculix, read_msh2,
    run_calculix,
)
from quick_therm_plugin.thermal_calculix_result import (
    import_calculix_field, read_frd_temperatures,
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
    def test_worker_prepares_gmsh_only_for_calculix(self):
        from quick_therm_plugin.service import run_job

        class Checked(Exception):
            pass

        with patch("wayricad_runtime.runtime_setup.ensure_runtime", side_effect=Checked) as ensure:
            with patch("shutil.which", return_value=None):
                with self.assertRaises(Checked):
                    run_job({"thermal_model_kind": "calculix"})
            self.assertIn("gmsh", ensure.call_args.args[0])
            with self.assertRaises(Checked):
                run_job({"thermal_model_kind": "multilayer"})
            self.assertNotIn("gmsh", ensure.call_args.args[0])

    def test_solver_discovery_prefers_explicit_then_environment(self):
        with tempfile.TemporaryDirectory() as root:
            executable = Path(root) / "ccx.exe"
            executable.write_bytes(b"test")
            with patch("quick_therm_plugin.thermal_calculix.os.access", return_value=True):
                with patch.dict(os.environ, {"WAYRICAD_CCX": str(executable)}):
                    self.assertEqual(find_calculix(), str(executable.resolve()))
                    self.assertEqual(find_calculix(executable), str(executable.resolve()))
            with self.assertRaisesRegex(ValueError, "unavailable"):
                find_calculix(Path(root) / "missing-ccx.exe")

    @unittest.skipUnless(importlib.util.find_spec("gmsh") and os.environ.get("WAYRICAD_TEST_CCX"),
                         "Needs Gmsh and WAYRICAD_TEST_CCX")
    def test_real_calculix_uniform_plate(self):
        geometry, view, result, settings, *_ = fixture()
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)/"candidate"
            prepared = prepare_calculix(geometry, view, result, settings, directory)
            self.assertEqual(prepared["status"], "deck_ready", prepared.get("diagnostic"))
            solved = run_calculix(directory, ccx=os.environ["WAYRICAD_TEST_CCX"])
            self.assertEqual(solved["status"], "solved", solved.get("diagnostic"))
            self.assertLess(abs(solved["heat_balance"]["residual_w"]), .05*1.25)
            field = json.loads((directory/"board_field.json").read_text(encoding="utf-8"))
            expected_top = 20 + 1.25*(.000035/385 + .00153/.3 + .000035/385)/(.01*.01)
            self.assertAlmostEqual(field["layers"][0]["sampled_min_c"], expected_top,
                                   delta=.05*(expected_top-20))
            self.assertAlmostEqual(field["layers"][-1]["sampled_max_c"], 20, places=2)

    @unittest.skipUnless(importlib.util.find_spec("pcbnew") and importlib.util.find_spec("gmsh")
                         and os.environ.get("WAYRICAD_TEST_CCX"),
                         "Needs native KiCad, Gmsh and WAYRICAD_TEST_CCX")
    def test_saved_board_service_returns_imported_thermal_field(self):
        import pcbnew as pcb
        from quick_therm_plugin.service import execute

        board = pcb.BOARD()
        footprint = pcb.FOOTPRINT(board)
        footprint.SetReference("U1")
        footprint.SetValue("LOAD")
        footprint.SetPosition(pcb.VECTOR2I(pcb.FromMM(5), pcb.FromMM(5)))
        pad = pcb.PAD(footprint)
        pad.SetNumber("1")
        pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
        pad.SetShape(pcb.PAD_SHAPE_RECT)
        pad.SetSize(pcb.VECTOR2I(pcb.FromMM(2), pcb.FromMM(2)))
        pad.SetPosition(footprint.GetPosition())
        layers = pcb.LSET()
        for layer in (pcb.F_Cu, pcb.F_Paste, pcb.F_Mask):
            layers.AddLayer(layer)
        pad.SetLayerSet(layers)
        footprint.Add(pad)
        board.Add(footprint)
        corners = ((0, 0), (10, 0), (10, 10), (0, 10))
        for first, second in zip(corners, corners[1:] + corners[:1]):
            line = pcb.PCB_SHAPE(board)
            line.SetShape(pcb.SHAPE_T_SEGMENT)
            line.SetLayer(pcb.Edge_Cuts)
            line.SetStart(pcb.VECTOR2I(*(pcb.FromMM(value) for value in first)))
            line.SetEnd(pcb.VECTOR2I(*(pcb.FromMM(value) for value in second)))
            board.Add(line)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"board.kicad_pcb"
            pcb.SaveBoard(str(path), board)
            source = path.read_text(encoding="utf-8")
            stackup = ('(stackup (layer "F.Cu" (type "copper") (thickness 0.035)) '
                       '(layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4")) '
                       '(layer "B.Cu" (type "copper") (thickness 0.035)))')
            self.assertIn("(setup\n", source)
            path.write_text(source.replace("(setup\n", "(setup\n"+stackup+"\n", 1), encoding="utf-8")
            before = path.read_bytes()
            request = {"action": "quick_therm", "board_path": str(path),
                       "input_mode": "manual", "manual_values": {
                           "U1": {"power_w": "1 W"}},
                       "environment": "air", "ambient_c": 20, "references": ["U1"],
                       "thermal_model_kind": "calculix", "thermal_network_settings": {
                           "board_k_w_mk": .3, "board_emissivity": 0,
                           "grid_cells_long_axis": 20},
                       "calculix_settings": {"gmsh_mesh_size_mm": 1.,
                                             "dielectric_k_w_mk": .3,
                                             "copper_k_w_mk": 385,
                                             "bottom_temperature_c": 20},
                       "calculix_executable": os.environ["WAYRICAD_TEST_CCX"]}
            response = execute(request)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(response["calculix"]["status"], "solved")
            self.assertFalse(response["calculix"]["artifacts_retained"])
            self.assertEqual(response["thermal_network"]["model"], "CalculiX 3D steady conduction")
            self.assertGreater(response["thermal_network"]["layers"][0]["sampled_max_c"], 20)
            self.assertIsNone(response["quick_therm"]["components"][0]["junction_c"])
            self.assertEqual(response["temperature_limits"]["status"], "UNKNOWN")
            request["manual_values"]["U1"]["theta_jb_k_per_w"] = "2 K/W"
            with_junction = execute(request)
            self.assertGreater(with_junction["quick_therm"]["components"][0]["junction_c"],
                               with_junction["thermal_network"]["components"][0]["board_site_c"])
            self.assertEqual(path.read_bytes(), before)

    def test_completed_result_imports_surfaces_and_conserves_heat(self):
        geometry, view, result, settings, nodes, triangles = fixture()
        _, audit = calculix_deck(geometry, view, result, settings, nodes, triangles)
        msh = ("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n4\n"
               "1 0 0 0\n2 10 0 0\n3 10 10 0\n4 0 10 0\n$EndNodes\n"
               "$Elements\n2\n1 2 2 1 1 1 2 3\n2 2 2 1 1 1 3 4\n$EndElements\n")
        z = audit["z_interfaces_mm"]
        power, area = 1.25, .01*.01
        temperatures = [20 + power*(.000035/385 + .00153/.3 + .000035/385)/area,
                        20 + power*(.000035/385 + .00153/.3)/area,
                        20 + power*.000035/(385*area), 20]
        frd = " 100CL\n -4  NDTEMP\n -5  T\n"
        for level, value in enumerate(temperatures):
            for node in range(1, 5):
                frd += f" -1{level*4+node:10d}{value:12.5E}\n"
        frd += " -3\n"
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory/"board.msh").write_text(msh, encoding="utf-8")
            (directory/"board.frd").write_text(frd, encoding="ascii")
            manifest = {**audit, "mesh_file": "board.msh", "result_file": "board.frd",
                        "gmsh_mesh_size_mm": 2, "calculix_deck": "board.inp", "status": "deck_ready"}
            (directory/"manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch("quick_therm_plugin.thermal_calculix.find_calculix", return_value="example-ccx"), \
                 patch("quick_therm_plugin.thermal_calculix.subprocess.run") as process:
                process.return_value.returncode = 0
                outcome = run_calculix(directory, ccx="example-ccx")
            self.assertEqual(outcome["status"], "solved")
            self.assertEqual(outcome["result_status"], "field_validated")
            self.assertLess(abs(outcome["heat_balance"]["bottom_outflow_w"]-power), .05*power)
            field = json.loads((directory/"board_field.json").read_text(encoding="utf-8"))
            self.assertEqual([layer["name"] for layer in field["layers"]], ["F.Cu", "B.Cu"])
            self.assertGreater(field["layers"][0]["sampled_min_c"], 80)
            self.assertAlmostEqual(field["layers"][1]["sampled_max_c"], 20, places=2)

    def test_rejects_partial_or_wrong_boundary_temperature(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"board.frd"
            path.write_text(" 100CL\n -4  NDTEMP\n -5  T\n -1         1 2.00000E+01\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "incomplete"):
                read_frd_temperatures(path)
            path.write_text(" 100CL\n -4  NDTEMP\n -5  T\n -1         1 1.00000E+01\n -3\n", encoding="ascii")
            (Path(root)/"board.msh").write_text(
                "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$Nodes\n3\n"
                "1 0 0 0\n2 1 0 0\n3 0 1 0\n$EndNodes\n"
                "$Elements\n1\n1 2 2 1 1 1 2 3\n$EndElements\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "do not match"):
                import_calculix_field(root, {"mesh_file": "board.msh", "result_file": "board.frd",
                                             "z_interfaces_mm": [0, 1], "gmsh_mesh_size_mm": 1,
                                             "bottom_temperature_c": 20, "power_w": 1,
                                             "copper_k_w_mk": 385, "dielectric_k_w_mk": .3})

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
