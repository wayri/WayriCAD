"""Native saved-board thermal geometry: copper, barrels and mounting holes."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pcbnew as p
except ImportError:
    p = None

from quick_therm_plugin.thermal_geometry import collect_thermal_geometry
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal
from quick_therm_plugin.thermal_multilayer import _polygon_contains


FIXTURE = (Path(__file__).resolve().parents[2] / "mechanical_check_plugin" /
           "tests" / "fixtures" / "validation-fixture.kicad_pcb")
STACKUP = '''(stackup
  (layer "F.Cu" (type "copper") (thickness 0.035))
  (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4"))
  (layer "B.Cu" (type "copper") (thickness 0.035)))'''


@unittest.skipIf(p is None, "Requires native KiCad pcbnew polygon geometry")
class ThermalGeometryTests(unittest.TestCase):
    def test_smd_contact_subtracts_separate_thermal_via_drill(self):
        footprint = next(fp for fp in self.board.GetFootprints()
                         if fp.GetReference() == "C1")
        pad = next(item for item in footprint.Pads() if item.IsOnLayer(p.F_Cu))
        self.assertEqual(pad.GetAttribute(), p.PAD_ATTRIB_SMD)
        via = p.PCB_VIA(self.board)
        via.SetPosition(pad.GetPosition())
        via.SetWidth(p.FromMM(.5))
        via.SetDrill(p.FromMM(.3))
        via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu, p.B_Cu)
        self.board.Add(via)
        geometry = collect_thermal_geometry(
            self.board, self.path, contact_pads={"C1": str(pad.GetNumber())})
        contact = next(row for row in geometry["source_contacts"]
                       if row["reference"] == "C1" and row["layer_id"] == p.F_Cu)
        center = [p.ToMM(pad.GetPosition().x), p.ToMM(pad.GetPosition().y)]
        self.assertTrue(contact["polygons_mm"])
        self.assertFalse(any(_polygon_contains(center, polygon)
                             for polygon in contact["polygons_mm"]))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        source = FIXTURE.read_text(encoding="utf-8")
        self.path = Path(self.folder.name) / "thermal-test.kicad_pcb"
        self.path.write_text(source.replace("(setup\n", "(setup\n" + STACKUP + "\n", 1), encoding="utf-8")
        self.board = p.LoadBoard(str(self.path))

    def test_saved_copper_stackup_mounting_holes_and_hash(self):
        geometry = collect_thermal_geometry(self.board, self.path)
        self.assertEqual(geometry["source_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(geometry["bbox_mm"], [0., 0., 60., 40.])
        self.assertEqual([layer["name"] for layer in geometry["layers"]], ["F.Cu", "B.Cu"])
        self.assertEqual([layer["thickness_mm"] for layer in geometry["layers"]], [.035, .035])
        holes = {hole["reference"]: hole for hole in geometry["mounting_holes"]}
        self.assertTrue(holes["H1"]["plated"])
        self.assertEqual(holes["H1"]["contact_evidence"], "flashed_plated_land")
        self.assertFalse(holes["H1"]["plane_connection_verified"])
        self.assertFalse(holes["H2"]["plated"])
        self.assertEqual(holes["H2"]["flashed_copper_layers"], [])
        self.assertTrue(any(barrel["kind"] == "plated_pad" for barrel in geometry["barrels"]))
        self.assertTrue(any(layer["polygons_mm"] for layer in geometry["layers"]))
        json.dumps(geometry, allow_nan=False)

    def test_explicit_stackup_required(self):
        self.path.write_bytes(FIXTURE.read_bytes())
        self.board = p.LoadBoard(str(self.path))
        with self.assertRaisesRegex(ValueError, "stackup"):
            collect_thermal_geometry(self.board, self.path)

    def test_unfilled_zone_rejected(self):
        net = p.NETINFO_ITEM(self.board, "GND")
        self.board.Add(net)
        zone = p.ZONE(self.board)
        zone.SetLayer(p.F_Cu)
        zone.SetNet(net)
        self.board.Add(zone)
        with self.assertRaisesRegex(ValueError, "unfilled"):
            collect_thermal_geometry(self.board, self.path)

    def test_via_span_and_filled_zone_copper(self):
        net = p.NETINFO_ITEM(self.board, "GND")
        self.board.Add(net)
        via = p.PCB_VIA(self.board)
        via.SetPosition(p.VECTOR2I(p.FromMM(28), p.FromMM(22)))
        via.SetWidth(p.FromMM(1.0))
        via.SetDrill(p.FromMM(.4))
        via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu, p.B_Cu)
        via.SetNet(net)
        self.board.Add(via)
        polygon = p.SHAPE_POLY_SET()
        polygon.NewOutline()
        for x, y in ((25, 19), (31, 19), (31, 25), (25, 25)):
            polygon.Append(p.FromMM(x), p.FromMM(y))
        zone = p.ZONE(self.board)
        zone.SetLayer(p.F_Cu)
        zone.SetNet(net)
        zone.Outline().Append(polygon)
        zone.SetFilledPolysList(p.F_Cu, polygon)
        zone.SetIsFilled(True)
        self.board.Add(zone)
        geometry = collect_thermal_geometry(self.board, self.path)
        barrel = next(item for item in geometry["barrels"] if item["id"] == via.m_Uuid.AsString())
        self.assertEqual(barrel["span_layers"], [p.F_Cu, p.B_Cu])
        self.assertEqual(barrel["contact_layers"], [p.F_Cu, p.B_Cu])
        self.assertEqual(barrel["drill_mm"], .4)
        self.assertEqual(geometry["counts"]["zones"], 1)
        self.assertTrue(geometry["layers"][0]["polygons_mm"])

    def test_mismatched_saved_source_rejected(self):
        other = Path(self.folder.name) / "other.kicad_pcb"
        other.write_bytes(self.path.read_bytes())
        with self.assertRaisesRegex(ValueError, "does not match"):
            collect_thermal_geometry(self.board, other)

    def test_native_geometry_solves_with_selected_plated_mount(self):
        geometry = collect_thermal_geometry(self.board, self.path)
        mount = next(row for row in geometry["mounting_holes"] if row["reference"] == "H1")
        from quick_therm_plugin.service import execute
        inventory = execute({"action": "inspect", "board_path": str(self.path)})
        self.assertIn(mount["id"], {row["id"] for row in inventory["mounting_holes"]})
        view = {"components": [{"reference": "U1", "side": "top", "position_mm": [30, 20],
                                 "on_board": True}]}
        result = {"environment": "air", "ambient_c": 20,
                  "components": [{"reference": "U1", "power_w": 1, "heat_path": "board"}]}
        solved = solve_multilayer_thermal(geometry, view, result, {
            "dielectric_k_w_mk": .3, "via_plating_mm": .025,
            "grid_cells_long_axis": 24, "board_emissivity": .9,
            "mount_boundaries": [{"id": mount["id"], "temperature_c": 10,
                                  "contact_r_k_w": 1}],
        })
        self.assertEqual(solved["status"], "converged")
        self.assertEqual(len(solved["layers"]), 2)
        self.assertGreater(solved["heat_balance"]["mount_flux_w"], 0)
        self.assertLess(abs(solved["heat_balance"]["residual_w"]), 1e-4)

    def test_saved_board_quicktherm_service_layered_path(self):
        from quick_therm_plugin.service import execute
        source = next(fp for fp in self.board.GetFootprints() if fp.GetReference() == "C1")
        source.SetField("Power_W", "1")
        source.SetField("Theta_JA", "40")
        p.SaveBoard(str(self.path), self.board)
        inventory = execute({"action": "inspect", "board_path": str(self.path)})
        mount = next(row for row in inventory["mounting_holes"] if row["reference"] == "H1")
        bundle = execute({"action": "quick_therm", "board_path": str(self.path),
            "environment": "air", "ambient_c": 20, "references": ["C1"],
            "field_map": {"power_w": "Power_W", "theta_ja_air_k_per_w": "Theta_JA"},
            "thermal_model_kind": "multilayer", "thermal_network_settings": {
                "dielectric_k_w_mk": .3, "via_plating_mm": .025,
                "grid_cells_long_axis": 24, "mount_boundaries": [{"id": mount["id"],
                    "temperature_c": 10, "contact_r_k_w": 1}]}})
        network = bundle["thermal_network"]
        self.assertEqual(network["status"], "converged")
        self.assertEqual(len(network["layers"]), 2)
        self.assertEqual(bundle["source_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_native_worker_reports_progress_and_preserves_source(self):
        from quick_therm_plugin.service import run_job
        source = next(fp for fp in self.board.GetFootprints() if fp.GetReference() == "C1")
        source.SetField("Power_W", "1")
        source.SetField("Theta_JA", "40")
        p.SaveBoard(str(self.path), self.board)
        before = self.path.read_bytes()
        events = []
        request = {"action": "quick_therm", "board_path": str(self.path),
                   "environment": "air", "ambient_c": 20, "references": ["C1"],
                   "field_map": {"power_w": "Power_W",
                                 "theta_ja_air_k_per_w": "Theta_JA"},
                   "thermal_model_kind": "multilayer", "thermal_network_settings": {
                       "dielectric_k_w_mk": .3, "via_plating_mm": .025,
                       "grid_cells_long_axis": 24}}
        with patch("wayricad_runtime.runtime_setup.ensure_runtime",
                   return_value=sys.executable), patch(
                       "wayricad_runtime.runtime_setup.child_environment",
                       return_value=dict(os.environ)):
            bundle = run_job(request, progress=events.append, timeout=60)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(bundle["thermal_network"]["status"], "converged")
        self.assertTrue(any(event["stage"] == "copper rasterization" for event in events))
        self.assertTrue(all(0 <= event["percent"] <= 100 for event in events))


if __name__ == "__main__":
    unittest.main()
