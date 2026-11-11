"""Archived 3D samples must remain historical, never attached to a live PCB."""
import copy
import sys
import unittest

try:
    if sys.platform!='win32': raise ImportError()
    import wx
    from quick_emerge_plugin.saved_antenna_viewer import create_viewer
except ImportError: wx=None


@unittest.skipIf(wx is None,'Native wx viewer unavailable')
class SavedAntennaViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=wx.App.Get() or wx.App(False)

    def test_archive_shows_lobes_polarization_and_phase_without_mutating_payload(self):
        from quick_emerge_plugin.model import validate_config
        from quick_emerge_plugin.tests.test_radiation_pattern import pattern
        from unittest import mock
        config=validate_config({})
        radiation=pattern(lambda theta,phi:1)
        radiation['frequency_hz']=2.4e9
        radiation['boresight_polarization']={'ex_ri':[1,0],'ey_ri':[0,1]}
        bundle={'config':config,'radiation':radiation,'frequencies_hz':[2.4e9],
                's_parameters':{'S11':[[.1,0]]},
                'field':{'x_mm':[0,1], 'y_mm':[0,1], 'z_mm':.5, 'frequency_hz':2.4e9,
                         'norm_e_v_m':[[1,1],[1,1]],
                         'e_real_v_m':[[[1,1],[1,1]],[[0,0],[0,0]],[[0,0],[0,0]]],
                         'e_imag_v_m':[[[0,0],[0,0]],[[1,1],[1,1]],[[0,0],[0,0]]]}}
        before=copy.deepcopy(bundle)
        with mock.patch('quick_emerge_plugin.backend.run_request',side_effect=AssertionError('Archive started a solver')):
            frame=create_viewer(None,{'bundle':bundle,'receipt':{'source_state':'changed'}})
            frame.Show(); wx.Yield()
            try:
                page=frame.antenna_3d
                self.assertEqual(page.choice.GetStringSelection(),'3D radiation')
                self.assertGreater(len(page.view.picking),0)
                for name in ('3D polarization','3D phase vectors','3D fields'):
                    page.choice.SetStringSelection(name); page.draw(); wx.Yield()
                    self.assertNotIn('unavailable',page.readout.GetLabel())
                page.choice.SetStringSelection('3D phase vectors'); page.phase.SetValue(90); page.draw(); wx.Yield()
                self.assertAlmostEqual(page.view.picking[0]['instantaneous_vector'][1],-1)
                self.assertTrue(page.view.options['archive_only'])
            finally: frame.Destroy(); wx.Yield()
        self.assertEqual(bundle,before)

    def test_saved_volume_slice_uses_original_coordinates(self):
        from quick_emerge_plugin.model import validate_config
        from quick_emerge_plugin.saved_antenna_viewer import SavedAntennaPanel
        plane={'x_mm':[0,1],'y_mm':[0,1],'z_mm':.5,'frequency_hz':1e9,
               'norm_e_v_m':[[1,1],[1,1]]}
        plane['volume']={'x_mm':[0,1],'y_mm':[0,1],'z_mm':[-.25,.75],
                         'norm_e_v_m':[[[2,2],[2,2]],[[3,3],[3,3]]]}
        result={'config':validate_config({}),'field':plane}
        before=copy.deepcopy(result)
        frame=wx.Frame(None)
        try:
            page=SavedAntennaPanel(frame,result); frame.Show(); wx.Yield()
            page.choice.SetStringSelection('3D fields'); page.slice.SetSelection(2)
            page.draw(); wx.Yield()
            self.assertNotIn('unavailable',page.readout.GetLabel())
            self.assertEqual(page.view.picking[0]['z_mm'],.75)
            self.assertEqual(page.view.picking[0]['value_v_m'],3)
        finally: frame.Destroy(); wx.Yield()
        self.assertEqual(result,before)
