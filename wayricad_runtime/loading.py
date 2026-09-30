"""A small, optional wx loading window for the shared plugin launcher."""
import sys


def ensure_wx_app(wx):
    """Start wx without letting it parse KiCad or plugin command-line options."""
    existing = wx.App.Get()
    if existing is not None:
        return existing
    arguments = sys.argv
    try:
        sys.argv = arguments[:1]
        return wx.App(False)
    finally:
        sys.argv = arguments


class LoadingWindow:
    def __init__(self, title):
        self.window = None
        self.wx = None
        self.app = None
        try:
            import wx
            if not hasattr(wx, 'Frame'):
                return
            self.app = ensure_wx_app(wx)
            window = wx.Frame(None, title='WayriCAD — Loading', size=(400, 132),
                              style=wx.CAPTION | wx.FRAME_TOOL_WINDOW)
            panel = wx.Panel(window)
            layout = wx.BoxSizer(wx.VERTICAL)
            heading = wx.StaticText(panel, label='Opening ' + title)
            font = heading.GetFont()
            font.MakeBold()
            heading.SetFont(font)
            layout.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            layout.Add(wx.StaticText(panel, label='Preparing the plugin…'),
                       0, wx.LEFT | wx.RIGHT | wx.TOP, 16)
            panel.SetSizer(layout)
            window.CentreOnScreen()
            window.Show()
            wx.YieldIfNeeded()
            self.window = window
            self.wx = wx
        except Exception:
            # A missing or unusable GUI must never prevent a plugin from opening.
            self.finish()

    def tick(self):
        if self.window is not None:
            self.wx.YieldIfNeeded()

    def finish(self):
        if self.window is not None:
            window = self.window
            self.window = None
            window.Destroy()
