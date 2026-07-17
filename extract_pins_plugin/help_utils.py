"""Safe help launcher for the Extract Pins dashboard."""
from pathlib import Path
import webbrowser
import wx


def open_help(parent, filename: str = "help_doc.html") -> None:
    path = Path(__file__).with_name(filename)
    if not path.exists():
        path = Path(__file__).with_name("help.html")
    if path.exists():
        webbrowser.open(path.resolve().as_uri())
    else:
        wx.MessageBox(f"Help file not found: {path}", "KiWay Help", wx.OK | wx.ICON_ERROR)
