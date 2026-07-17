"""Small, dependency-light help launcher used by the KiWay GUI."""
from pathlib import Path
import webbrowser
import wx


def open_help(parent, filename: str = "help.html") -> None:
    path = Path(__file__).with_name(filename)
    if path.exists():
        webbrowser.open(path.resolve().as_uri())
    else:
        wx.MessageBox(f"Help file not found: {path}", "KiWay Help", wx.OK | wx.ICON_ERROR)
