"""Optional real-wx icon decode smoke tests; not full KiCad GUI acceptance.

Run using KiCad's Python with WAYRICAD_EMBED3D_NATIVE_TESTS=1, an active display,
and WAYRICAD_EMBED3D_NO_REGISTER=1. No design files are touched.
"""
import importlib.util
import os
import unittest
AVAILABLE = importlib.util.find_spec('wx') is not None and os.environ.get('WAYRICAD_EMBED3D_NATIVE_TESTS') == '1'


@unittest.skipUnless(AVAILABLE, 'Real wx/KiCad icon rendering not available/enabled')
class NativeIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.GetApp() or wx.App(False)
    def test_native_window_icons_decode(self):
        from embed_3d_plugin.assets import set_window_icons
        window = self.wx.Dialog(None, title='WayriCAD Embed3D icon test')
        try:
            self.assertTrue(set_window_icons(window,self.wx))
            self.assertGreater(window.GetIcons().GetIconCount(),0)
        finally: window.Destroy()
    def test_native_header_bundle_decodes(self):
        from embed_3d_plugin.assets import make_header_icon
        window = self.wx.Dialog(None, title='WayriCAD Embed3D icon test')
        try:
            control = make_header_icon(window,self.wx)
            self.assertIsNotNone(control)
            self.assertTrue(control.GetBitmap().IsOk())
        finally: window.Destroy()


if __name__ == '__main__': unittest.main()
