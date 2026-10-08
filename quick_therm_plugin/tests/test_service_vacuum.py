"""Spatial radiation boundaries do not require a legacy lumped board resistance."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from quick_therm_plugin.service import execute
from quick_therm_plugin.tests.test_quick_therm import Board, Footprint
from quick_therm_plugin.tests.test_thermal_multilayer import inputs

class VacuumServiceTests(unittest.TestCase):
    def test_multilayer_vacuum_radiation_without_lumped_resistance(self):
        geometry, view, _, settings = inputs("vacuum")
        board = Board([Footprint("U1", {"Dissipation": "1 W", "Theta JB": "4 K/W"})])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"board.kicad_pcb"
            path.write_text("fixture",encoding="utf-8")
            request={"action":"quick_therm","board_path":str(path),"environment":"vacuum",
                     "ambient_c":20,"references":["U1"],"field_map":{"power_w":"Dissipation"},
                     "thermal_model_kind":"multilayer","thermal_network_settings":settings,
                     "thermal_network_component_field":"Theta JB"}
            with patch.dict(sys.modules, {"pcbnew":SimpleNamespace(LoadBoard=lambda _:board)}), \
                 patch("quick_therm_plugin.thermal_board_view.build_board_thermal_view",return_value=view), \
                 patch("quick_therm_plugin.thermal_geometry.collect_thermal_geometry",return_value=geometry), \
                 patch("quick_therm_plugin.thermal_review.evaluate_limits",return_value={}), \
                 patch("quick_therm_plugin.thermal_review.sample_probes",return_value=[]):
                output=execute(request)
            field=output["thermal_network"]
            self.assertEqual(field["status"],"converged")
            self.assertEqual(field["heat_balance"]["convection_w"],0)
            self.assertAlmostEqual(field["heat_balance"]["radiation_w"],1,places=7)
            part=field["components"][0]
            self.assertAlmostEqual(part["junction_c"]-part["board_site_c"],4)
            self.assertIsNone(output["quick_therm"]["vacuum_board_to_environment_k_per_w"])
    def test_legacy_lumped_vacuum_still_requires_board_resistance(self):
        board=Board([Footprint("U1",{"Dissipation":"1 W","Theta JB":"4 K/W"})])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"board.kicad_pcb"
            path.write_text("fixture",encoding="utf-8")
            request={"action":"quick_therm","board_path":str(path),"environment":"vacuum",
                     "references":["U1"],"field_map":{"power_w":"Dissipation","theta_jb_k_per_w":"Theta JB"}}
            with patch.dict(sys.modules,{"pcbnew":SimpleNamespace(LoadBoard=lambda _:board)}):
                with self.assertRaises(ValueError):execute(request)
