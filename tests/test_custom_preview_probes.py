"""Native custom-preview probes preserve exact cells and model samples."""
import unittest
from types import SimpleNamespace
try:
 import wx,pcbnew
except ImportError:
 wx=None

@unittest.skipIf(wx is None,'Native KiCad wxPython is required')
class CustomProbeTests(unittest.TestCase):
 def test_heater_exact_cell_and_outside(self):
  from heater_designer_plugin.heater_designer_plugin import HeaterPreview
  spec=SimpleNamespace(width_mm=20,height_mm=10)
  preview=SimpleNamespace(heater=None,canvas_spec=spec,mode='thermal',thermal=SimpleNamespace(temperatures_c=[[10,20],[30,40]]),_transform=lambda w,h:(10,5,5))
  self.assertEqual(HeaterPreview.probe_at(preview,wx.Point(55,80),300,200),(5.,2.5,10,(0,0)))
  self.assertEqual(HeaterPreview.probe_at(preview,wx.Point(155,30),300,200),(15.,7.5,40,(1,1)))
  self.assertIsNone(HeaterPreview.probe_at(preview,wx.Point(250,30),300,200))
  preview.mode='pattern'
  self.assertIsNone(HeaterPreview.probe_at(preview,wx.Point(55,80),300,200)[2])
 def test_coil_coordinates_not_field(self):
  from planar_magnetics_plugin.planar_magnetics_plugin import MagneticPreview
  preview=SimpleNamespace(result=SimpleNamespace(spec=SimpleNamespace(outer_width_mm=20,outer_height_mm=10)),zoom=1,pan=(0,0),GetClientSize=lambda:(270,170))
  self.assertEqual(MagneticPreview.world_point(preview,wx.Point(135,85)),(10.,5.))
  self.assertIsNone(MagneticPreview.world_point(preview,wx.Point(0,0)))
 def test_motion_pins_exact_sample_requires_modifier(self):
  from planar_magnetics_plugin.planar_magnetics_plugin import MotionPlot
  preview=SimpleNamespace(hover=(120,70,1,.02,.125,'Speed','m/s'),probes=[],Refresh=lambda:None)
  MotionPlot.pin(preview,SimpleNamespace(ControlDown=lambda:False));self.assertEqual(preview.probes,[])
  MotionPlot.pin(preview,SimpleNamespace(ControlDown=lambda:True));self.assertEqual(preview.probes,[(1,.02,.125,'Speed','m/s')])
if __name__=='__main__':unittest.main()
