"""Analytical checks for separate saved-stackup travel-time screening."""
import math
import unittest

from signal_integrity_advisor_plugin.measurement import StackupLayer, TraceMeasurementEngine
from signal_integrity_advisor_plugin import rlc_model


class AutomaticTimingTests(unittest.TestCase):
    def engine(self, er_upper=4.0, er_lower=4.0, upper=.2, lower=.2):
        engine = TraceMeasurementEngine(None)
        engine._stackup_cache = [
            StackupLayer("F.Cu", "copper", .035),
            StackupLayer("dielectric 1", "dielectric", upper, relative_permittivity=er_upper),
            StackupLayer("In1.Cu", "copper", .035),
            StackupLayer("dielectric 2", "dielectric", lower, relative_permittivity=er_lower),
            StackupLayer("B.Cu", "copper", .035),
        ]
        return engine

    def test_embedded_trace_delay_matches_bulk_dielectric_speed(self):
        result = self.engine()._screening_section("track", "In1.Cu", 299.792458, .15, .035)
        self.assertEqual(result["screening_status"], "APPROXIMATE")
        self.assertAlmostEqual(result["screening_delay_ns"], 2.0, places=12)
        self.assertGreater(result["screening_z0_ohm"], 0)
        self.assertIn("ideal", result["screening_model"])

    def test_asymmetric_embedded_trace_keeps_timing_without_inventing_z0(self):
        result = self.engine(lower=.4)._screening_section("track", "In1.Cu", 299.792458, .15, .035)
        self.assertAlmostEqual(result["screening_delay_ns"], 2.0, places=12)
        self.assertIsNone(result["screening_z0_ohm"])

    def test_outer_microstrip_matches_existing_cross_section_solver(self):
        result = self.engine()._screening_section("track", "F.Cu", 100, .15, .035)
        reference = rlc_model.solve(.15, .2, .035, 4, 100, 0, "microstrip")
        self.assertAlmostEqual(result["screening_delay_ns"], reference["propagation_delay_ns"], places=12)
        self.assertAlmostEqual(result["screening_z0_ohm"], reference["z0_ohm"], places=12)
        self.assertIn("assumed continuous", result["screening_model"])

    def test_via_integrates_material_optical_lengths(self):
        # Equal dielectric thicknesses: optical-length average sqrt(4)/2 + sqrt(9)/2.
        result = self.engine(er_lower=9)._screening_section("via", "F.Cu", .47, end_layer="B.Cu")
        self.assertAlmostEqual(result["screening_delay_ns"], .47 * 2.5 / 299.792458, places=12)
        self.assertIsNone(result["screening_z0_ohm"])
        self.assertIn("no discontinuity", result["screening_model"])
        reverse = self.engine(er_lower=9)._screening_section("via", "B.Cu", .47, end_layer="F.Cu")
        self.assertAlmostEqual(result["screening_delay_ns"], reverse["screening_delay_ns"], places=12)

    def test_missing_material_or_stackup_stays_unknown(self):
        for engine in (self.engine(er_lower=0), TraceMeasurementEngine(None)):
            if engine.board is None and engine._stackup_cache is None:
                engine._stackup_cache = []
            result = engine._screening_section("track", "In1.Cu", 100, .15, .035)
            self.assertEqual(result["screening_status"], "UNAVAILABLE")
            self.assertIsNone(result["screening_delay_ns"])

    def test_stratified_embedded_line_is_not_homogeneous(self):
        result = self.engine(er_lower=9)._screening_section("track", "In1.Cu", 100, .15, .035)
        self.assertIsNone(result["screening_delay_ns"])
        self.assertIn("Stratified", result["screening_model"])

    def test_zone_is_not_given_uniform_line_timing(self):
        result = self.engine()._screening_section("zone", "F.Cu", 100, .15, .035)
        self.assertIsNone(result["screening_delay_ns"])
        self.assertIn("spreading", result["screening_model"])
