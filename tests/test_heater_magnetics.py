import json
import tempfile
import unittest
from pathlib import Path

from heater_designer_plugin.analysis import HeatZone, HeaterEngine, HeaterSpec, ThermalSpec
from planar_magnetics_plugin.analysis import CoilSpec, MagneticsEngine, MotionSpec, load_core_catalog, save_core_catalog, CORE_CATALOG


class HeaterAndMagneticsTests(unittest.TestCase):
    def test_packages_have_guided_help_icons_and_guarded_commit(self):
        root = Path(__file__).resolve().parents[1]
        for package, module in (
            ("heater_designer_plugin", "heater_designer_plugin.py"),
            ("planar_magnetics_plugin", "planar_magnetics_plugin.py"),
        ):
            source = (root / package / module).read_text(encoding="utf-8")
            metadata = json.loads((root / package / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("add_workflow", source)
            self.assertIn("dark_icon_file_name", source)
            self.assertIn("PCB preview required", source)
            self.assertEqual("swig", metadata["versions"][0]["runtime"])
            self.assertTrue((root / package / "help.html").is_file())
            self.assertTrue((root / package / "help-workflow.png").is_file())
            self.assertTrue((root / package / "icon.png").is_file())

    def test_zoned_multilayer_heater_changes_width_and_power(self):
        result = HeaterEngine.generate(HeaterSpec(
            layers=3,
            zones=(HeatZone("Hot", 50, 50, 30, 2.0), HeatZone("Cold", 8, 50, 15, 0.5)),
        ))
        widths = {round(segment.width_mm, 3) for segment in result.segments}
        self.assertGreaterEqual(len(widths), 2)
        self.assertEqual(2, len(result.vias))
        self.assertAlmostEqual(result.spec.voltage_v, result.current_a * result.resistance_ohm, places=6)
        self.assertIn("Hot", result.zone_power_w)

    def test_thermal_solver_produces_nonuniform_temperature_map(self):
        heater = HeaterEngine.generate(HeaterSpec(
            voltage_v=5.0,
            zones=(HeatZone("Hot", 50, 50, 20, 2.5),),
        ))
        result = HeaterEngine.simulate(heater, ThermalSpec(grid_x=20, grid_y=14, iterations=100))
        self.assertGreater(result.maximum_c, result.average_c)
        self.assertGreater(result.average_c, 25.0)
        self.assertEqual(14, len(result.temperatures_c))
        self.assertEqual(20, len(result.temperatures_c[0]))

    def test_planar_transformer_reports_lcr_coupling_and_vias(self):
        result = MagneticsEngine.analyze(CoilSpec(layers=4, turns=6, secondary_turns=18, coupling=0.93))
        self.assertEqual(3, len(result.vias))
        self.assertGreater(result.inductance_uh, 0)
        self.assertGreater(result.resistance_ac_ohm, result.resistance_dc_ohm)
        self.assertGreater(result.capacitance_pf, 0)
        self.assertGreater(result.mutual_inductance_uh, 0)
        self.assertAlmostEqual(18 / 24, result.turns_ratio, places=6)
        self.assertTrue(any(segment.winding == "Secondary" for segment in result.segments))

    def test_gapped_core_increases_inductance_and_catalog_roundtrips(self):
        air = MagneticsEngine.analyze(CoilSpec(layers=1, turns=6))
        core = MagneticsEngine.analyze(CoilSpec(layers=1, turns=6, core_name="Planar E 18 - N87"))
        self.assertGreater(core.inductance_uh, air.inductance_uh)
        self.assertGreater(core.saturation_current_a, 0)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cores.json"
            save_core_catalog(path, CORE_CATALOG)
            loaded = load_core_catalog(path)
            self.assertEqual(set(CORE_CATALOG), set(loaded))
            self.assertIn("cores", json.loads(path.read_text(encoding="utf-8")))

    def test_coupled_actuator_reports_force_acceleration_speed_and_resonance(self):
        magnetic = MagneticsEngine.analyze(CoilSpec(current_a=0.2, voltage_v=3.3))
        dynamics = MagneticsEngine.simulate_dynamics(
            magnetic,
            MotionSpec(moving_mass_kg=1e-6, spring_n_m=1.0,
                       drive_mode="Current step", duration_s=0.005,
                       time_step_s=2e-6),
            "Voice coil",
        )
        self.assertGreater(dynamics.peak_force_n, 0)
        self.assertGreater(dynamics.peak_acceleration_m_s2, 0)
        self.assertGreater(dynamics.peak_speed_m_s, 0)
        self.assertGreater(dynamics.peak_displacement_m, 0)
        self.assertAlmostEqual((1.0 / 1e-6) ** 0.5 / (2 * 3.141592653589793),
                               dynamics.natural_frequency_hz, places=5)
        self.assertGreater(dynamics.thermal_force_noise_n_sqrt_hz, 0)
        self.assertGreater(dynamics.brownian_displacement_rms_m, 0)

    def test_static_friction_can_hold_mover(self):
        magnetic = MagneticsEngine.analyze(CoilSpec(current_a=0.01))
        dynamics = MagneticsEngine.simulate_dynamics(
            magnetic,
            MotionSpec(drive_mode="Current step", static_friction_n=1.0,
                       duration_s=0.001, time_step_s=1e-6),
            "Voice coil",
        )
        self.assertEqual(0.0, dynamics.peak_speed_m_s)
        self.assertEqual(0.0, dynamics.peak_displacement_m)

    def test_nanoscale_mode_is_explicitly_screening_only(self):
        magnetic = MagneticsEngine.analyze(CoilSpec(current_a=0.01))
        dynamics = MagneticsEngine.simulate_dynamics(
            magnetic,
            MotionSpec(moving_mass_kg=1e-12, spring_n_m=0.1,
                       initial_gap_m=500e-9, stroke_limit_m=200e-9,
                       drive_mode="Current step", duration_s=5e-6,
                       time_step_s=1e-9),
            "Linear solenoid",
        )
        self.assertEqual("NANOSCALE SCREENING ONLY", dynamics.validity)
        self.assertTrue(any("squeeze-film" in warning for warning in dynamics.warnings))
        self.assertGreater(dynamics.force_gradient_n_m, 0)


if __name__ == "__main__":
    unittest.main()
