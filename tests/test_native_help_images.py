"""Actual wx.html fallback reflows screenshots, links and resize lifetimes."""
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import wx
    import wx.html
except ImportError:wx=None


class Images(HTMLParser):
    def __init__(self,text):super().__init__();self.images=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.images.append(dict(attrs))


@unittest.skipIf(wx is None,'Native wx HTML runtime required')
class NativeHelpImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_native_sizes_anchors_reading_position_and_destroy_timer(self):
        from wayricad_runtime.help import open_help
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);bitmap=wx.Bitmap(1280,720);bitmap.SaveFile(str(root/'figure.png'),wx.BITMAP_TYPE_PNG)
            text=('<html><body><h1>Help</h1><img src="figure.png" width="1280" height="400">'+
                  ('<p>Readable help paragraph.</p>'*50)+'<h2 id="tail">Last section</h2><a href="#tail">Anchor</a></body></html>')
            path=root/'help.html';path.write_text(text,encoding='utf-8')
            with patch('wayricad_runtime.local_webview.try_new_webview',return_value=(None,'Test native renderer')):
                frame=open_help(None,path)
            try:
                viewer=frame._help_viewer
                for width in (480,900,1400):
                    frame.SetClientSize((width,650));frame.Layout();self.app.Yield();viewer._reflow();self.app.Yield()
                    rows=Images(viewer._rendered_html).images;figure=rows[0]
                    self.assertLessEqual(int(figure['width']),viewer.GetClientSize().width-24)
                    self.assertAlmostEqual(int(figure['height'])/int(figure['width']),720/1280,delta=1/int(figure['width']))
                    self.assertLessEqual(viewer.GetVirtualSize().width,viewer.GetClientSize().width+2)
                    self.assertTrue(viewer.ScrollToAnchor('tail'))
                viewer.Scroll(0,max(1,viewer.GetScrollRange(wx.VERTICAL)//3));old=viewer.GetViewStart()[1]
                frame.SetClientSize((900,650));frame.Layout();self.app.Yield();viewer._reflow();self.app.Yield()
                self.assertGreater(viewer.GetViewStart()[1],0)
                viewer.OnLinkClicked(wx.html.HtmlLinkInfo('#tail'))
                self.assertGreater(viewer.GetViewStart()[1],0)
                viewer._resized(type('Event',(),{'Skip':lambda self:None})())
                self.assertIsNotNone(viewer._timer)
            finally:
                frame.Destroy();self.app.Yield()
                self.assertTrue(viewer._dead);self.assertIsNone(viewer._timer)


if __name__=='__main__':unittest.main()
