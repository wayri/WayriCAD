"""Geometry and thermal feedback checks for the organic heater workflow."""
from dataclasses import replace
import math
import unittest

from heater_designer_plugin.analysis import HeatZone, HeaterEngine, HeaterSpec, ThermalSpec


class OrganicGradientTests(unittest.TestCase):
    def test_organic_path_is_continuous_inside_board_and_connects_layers(self):
        spec = HeaterSpec(pattern="Organic path", layers=2, voltage_v=1.5)
        result = HeaterEngine.generate(spec)
        self.assertGreater(len(result.segments), 100)
        self.assertEqual(len(result.vias), 1)
        half = len(result.segments)//2
        for a, b in zip(result.segments[:half-1], result.segments[1:half]):
            self.assertAlmostEqual(a.x2_mm, b.x1_mm)
            self.assertAlmostEqual(a.y2_mm, b.y1_mm)
        via = result.vias[0]
        self.assertAlmostEqual(via.x_mm, result.segments[half-1].x2_mm)
        self.assertAlmostEqual(via.y_mm, result.segments[half-1].y2_mm)
        self.assertAlmostEqual(via.x_mm, result.segments[half].x1_mm)
        self.assertAlmostEqual(via.y_mm, result.segments[half].y1_mm)
        for segment in result.segments:
            for x, y in ((segment.x1_mm, segment.y1_mm), (segment.x2_mm, segment.y2_mm)):
                self.assertGreaterEqual(x, segment.width_mm/2)
                self.assertLessEqual(x, spec.width_mm-segment.width_mm/2)
                self.assertGreaterEqual(y, segment.width_mm/2)
                self.assertLessEqual(y, spec.height_mm-segment.width_mm/2)

    def test_organic_path_rejects_a_close_return_and_bad_coordinates(self):
        close = ((10, 10), (90, 10), (90, 12), (10, 12))
        with self.assertRaisesRegex(ValueError, "doubles back"):
            HeaterEngine.generate(HeaterSpec(pattern="Organic path", organic_points_percent=close))
        with self.assertRaisesRegex(ValueError, "0 to 100"):
            HeaterEngine.generate(HeaterSpec(pattern="Organic path",
                                             organic_points_percent=((10, 10), (50, math.nan), (90, 90))))

    def test_gradient_tuning_and_sensor_markers_use_actual_thermal_cells(self):
        spec = HeaterSpec(pattern="Organic path", voltage_v=1.5,
                          gradient_axis="Left to right", gradient_ratio=1.0)
        thermal = ThermalSpec(grid_x=20, grid_y=14, iterations=100, sensor_clearance_mm=0.1)
        result = HeaterEngine.tune_gradient(spec, thermal, target_delta_c=2.0)
        self.assertLess(abs(result.gradient_delta_c-2.0), 0.5)
        self.assertGreater(result.heater.spec.gradient_ratio, 1.0)
        self.assertLess(result.heater.spec.gradient_ratio, 4.0)
        self.assertEqual({marker.kind for marker in result.sensors}, {"PTC", "NTC"})
        for marker in result.sensors:
            self.assertGreaterEqual(marker.copper_clearance_mm, thermal.sensor_clearance_mm)
            self.assertGreater(marker.x_mm, 0)
            self.assertLess(marker.x_mm, spec.width_mm)
            self.assertGreater(marker.y_mm, 0)
            self.assertLess(marker.y_mm, spec.height_mm)
        no_room = HeaterEngine.simulate(result.heater,
                                        replace(thermal, sensor_clearance_mm=30.0))
        self.assertEqual(no_room.sensors, [])
        self.assertTrue(any("No sensor marker" in note for note in no_room.notes))

    def test_tuning_can_bias_opposite_end_when_regions_already_overshoot_target(self):
        spec = HeaterSpec(pattern="Organic path", voltage_v=1.5,
                          gradient_axis="Left to right",
                          zones=(HeatZone("Hotspot", 50, 50, 18, 1.8),
                                 HeatZone("Cold edge", 10, 50, 12, 0.65)))
        result = HeaterEngine.tune_gradient(spec, ThermalSpec(grid_x=20, grid_y=14,
                                                               iterations=100), 2.0)
        self.assertLess(result.heater.spec.gradient_ratio, 1.0)
        self.assertLess(abs(result.gradient_delta_c-2.0), 0.5)


if __name__ == "__main__":
    unittest.main()
