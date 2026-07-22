"""Native, path-safe help launcher for KiWay Extract Pins."""

from pathlib import Path
from typing import Any, List

import wx
import wx.html

try:
    import wx.html2 as wxhtml2
except ImportError:  # pragma: no cover - depends on KiCad wx build
    wxhtml2 = None


_HELP_WINDOWS: List[Any] = []


def _resolve_help_file(filename: str) -> Path:
    plugin_dir = Path(__file__).resolve().parent
    candidates = [plugin_dir / filename, plugin_dir / "help.html", plugin_dir / "help_doc.html"]
    return next((path for path in candidates if path.is_file()), candidates[0])


def open_help(parent: Any = None, filename: str = "help.html") -> None:
    """Open packaged help inside KiCad instead of relying on file URL shells."""
    path = _resolve_help_file(filename)
    if not path.is_file():
        wx.MessageBox(f"Help file not found: {path}", "KiWay Help", wx.OK | wx.ICON_ERROR)
        return

    frame = wx.Frame(parent, title="KiWay Extract Pins Help", size=(1040, 760))
    panel = wx.Panel(frame)
    root = wx.BoxSizer(wx.VERTICAL)
    if wxhtml2 is not None:
        viewer = wxhtml2.WebView.New(panel)
        def on_navigating(event: Any) -> None:
            url = str(event.GetURL())
            if url.startswith(("http://", "https://")):
                event.Veto()
                wx.LaunchDefaultBrowser(url)
        viewer.Bind(wxhtml2.EVT_WEBVIEW_NAVIGATING, on_navigating)
        viewer.LoadURL(path.as_uri())
    else:
        viewer = wx.html.HtmlWindow(panel, style=wx.html.HW_SCROLLBAR_AUTO)
        viewer.LoadPage(path.as_uri())
    root.Add(viewer, 1, wx.EXPAND)

    actions = wx.BoxSizer(wx.HORIZONTAL)
    actions.AddStretchSpacer()
    browser_button = wx.Button(panel, label="Open in Browser")
    browser_button.Bind(wx.EVT_BUTTON, lambda _event: wx.LaunchDefaultBrowser(path.as_uri()))
    actions.Add(browser_button, 0, wx.ALL, 6)
    close_button = wx.Button(panel, label="Close")
    close_button.Bind(wx.EVT_BUTTON, lambda _event: frame.Close())
    actions.Add(close_button, 0, wx.ALL, 6)
    root.Add(actions, 0, wx.EXPAND)
    panel.SetSizer(root)

    _HELP_WINDOWS.append(frame)

    def on_close(event: Any) -> None:
        if frame in _HELP_WINDOWS:
            _HELP_WINDOWS.remove(frame)
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, on_close)
    frame.CentreOnParent()
    frame.Show()
    frame.Raise()
