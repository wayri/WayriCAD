"""Keep BOM Studio responsive while a saved KiCad project is parsed."""

from pathlib import Path
import sys
import threading

_wx_app = None


def _show_loading(done):
    """Show an indeterminate native window until the worker finishes.

    A wx main loop has not started yet. Yielding from the main thread keeps the
    loading window painted without starting a nested loop before the desktop
    host creates its own window.
    """
    try:
        import wx
    except ImportError:
        done.wait()
        return

    global _wx_app
    _wx_app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None, title='WayriCAD BOM Studio — loading', size=(460, 190),
                     style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.CLOSE_BOX))
    icon_path = Path(__file__).resolve().parents[1] / 'resources' / 'icon.ico'
    if sys.platform == 'win32' and icon_path.is_file():
        try:
            icon = wx.Icon(str(icon_path), wx.BITMAP_TYPE_ICO)
            if icon.IsOk():
                frame.SetIcon(icon)
        except Exception:
            pass
    panel = wx.Panel(frame)
    panel.SetBackgroundColour('#f5f8f8')
    layout = wx.BoxSizer(wx.VERTICAL)
    title = wx.StaticText(panel, label='WayriCAD BOM Studio')
    title.SetFont(title.GetFont().Bold().Scale(1.45))
    layout.Add(title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 22)
    detail = wx.StaticText(panel, label='Reading the saved KiCad project and preparing your workspace…')
    layout.Add(detail, 0, wx.LEFT | wx.RIGHT | wx.TOP, 22)
    gauge = wx.Gauge(panel, range=100)
    layout.Add(gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 22)
    note = wx.StaticText(panel, label='Large projects can take a little longer. No project file is changed.')
    layout.Add(note, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 22)
    panel.SetSizer(layout)
    frame.CentreOnScreen()
    frame.Show()
    try:
        wx.YieldIfNeeded()
        while not done.wait(.08):
            gauge.Pulse()
            wx.YieldIfNeeded()
    finally:
        frame.Destroy()
        wx.YieldIfNeeded()


def load_with_progress(factory, *, enabled=True, threshold=.35):
    """Run file parsing off the UI thread, showing progress only if it is slow.

    Errors from the worker are raised on the caller's thread so the existing
    startup error dialog and exit status remain authoritative.
    """
    if not enabled:
        return factory()
    done = threading.Event()
    outcome = {}

    def work():
        try:
            outcome['value'] = factory()
        except BaseException as exc:
            outcome['error'] = exc
        finally:
            done.set()

    worker = threading.Thread(target=work, name='wayricad-bom-project-load', daemon=True)
    worker.start()
    if not done.wait(threshold):
        _show_loading(done)
    worker.join()
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']
