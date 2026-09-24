"""Offscreen native rendering checks for the heater preview canvas."""

import unittest
from collections import Counter
from types import SimpleNamespace

try:
    import pcbnew  # noqa: F401 - native KiCad interpreter availability
    import wx
    import heater_designer_plugin.analysis  # Import before wx.App to avoid standalone ActionPlugin registration.
except ImportError:
    wx = None


@unittest.skipIf(wx is None, "Requires native KiCad Python and wxPython")
class HeaterPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def render(self, spec, *, thermal=False):
        from heater_designer_plugin.analysis import HeaterEngine, ThermalSpec
        from heater_designer_plugin.heater_designer_plugin import HeaterPreview

        heater = HeaterEngine.generate(spec)
        bitmap = wx.Bitmap(800, 600)
        dc = wx.MemoryDC(bitmap)
        thermal_result = HeaterEngine.simulate(heater, ThermalSpec(grid_x=20, grid_y=14, iterations=100)) if thermal else None
        preview = SimpleNamespace(heater=heater, thermal=thermal_result, mode="thermal" if thermal else "pattern", zoom=1.0, pan=(0, 0), zone_drag=None)
        preview._transform = lambda w, h: HeaterPreview._transform(preview, w, h)
        HeaterPreview.draw(preview, dc, 800, 600)
        dc.SelectObject(wx.NullBitmap)
        data = bitmap.ConvertToImage().GetData()
        return Counter(tuple(data[i:i + 3]) for i in range(0, len(data), 3))

    def test_serpentine_and_heating_region_are_visible(self):
        from heater_designer_plugin.analysis import HeatZone, HeaterSpec

        pixels = self.render(HeaterSpec(zones=(HeatZone("Hotspot", 50, 50, 18, 1.8),)))
        self.assertGreater(pixels[(21, 127, 116)], 1000)  # uniform copper
        self.assertGreater(pixels[(209, 73, 91)], 100)  # region copper and outline

    def test_spiral_is_visible(self):
        from heater_designer_plugin.analysis import HeaterSpec

        pixels = self.render(HeaterSpec(pattern="Concentric spiral"))
        self.assertGreater(pixels[(21, 127, 116)], 1000)

    def test_drawn_region_maps_to_board_coordinates(self):
        from heater_designer_plugin.analysis import HeaterEngine, HeaterSpec
        from heater_designer_plugin.heater_designer_plugin import HeaterPreview

        heater = HeaterEngine.generate(HeaterSpec())
        preview = SimpleNamespace(heater=heater, zoom=1.0, pan=(0, 0))
        preview._transform = lambda w, h: HeaterPreview._transform(preview, w, h)
        centre = wx.Point(400, 300)
        zone = HeaterPreview.zone_from_drag(preview, centre, wx.Point(446, 300), 800, 600)
        self.assertAlmostEqual(zone.x_percent, 50.0)
        self.assertAlmostEqual(zone.y_percent, 50.0)
        self.assertAlmostEqual(zone.radius_percent, 10.0)
        self.assertIsNone(HeaterPreview.zone_from_drag(preview, centre, wx.Point(405, 300), 800, 600))

    def test_organic_control_point_maps_from_click(self):
        from heater_designer_plugin.analysis import HeaterSpec
        from heater_designer_plugin.heater_designer_plugin import HeaterPreview

        preview = SimpleNamespace(heater=None, canvas_spec=HeaterSpec(pattern="Organic path"),
                                  zoom=1.0, pan=(0, 0))
        preview._transform = lambda w, h: HeaterPreview._transform(preview, w, h)
        self.assertEqual(HeaterPreview.path_point_from_click(preview, wx.Point(400, 300), 800, 600),
                         (50.0, 50.0))
        self.assertIsNone(HeaterPreview.path_point_from_click(preview, wx.Point(5, 5), 800, 600))

    def test_organic_gradient_renders_control_points_and_both_sensor_markers(self):
        from heater_designer_plugin.analysis import HeaterSpec

        pixels = self.render(HeaterSpec(pattern="Organic path", voltage_v=1.5,
                                        gradient_axis="Left to right", gradient_ratio=1.4), thermal=True)
        self.assertGreater(pixels[(255, 242, 216)], 10)  # filled control-point markers
        self.assertGreater(pixels[(175, 46, 69)], 10)  # PTC safety marker
        self.assertGreater(pixels[(40, 101, 176)], 10)  # NTC control marker


if __name__ == "__main__":
    unittest.main()
