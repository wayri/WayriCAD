from types import SimpleNamespace

import pytest

wx = pytest.importorskip('wx')
from review_comments_plugin.scroll_ui import ScrollRail

_APP = None


@pytest.fixture
def scrolling():
    global _APP
    _APP = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None)
    panel = wx.Panel(frame, size=(350, 250))
    target = wx.ScrolledWindow(panel, size=(300, 200), style=wx.VSCROLL | wx.BORDER_NONE)
    target.SetScrollRate(0, 8)
    target.SetVirtualSize((300, 2000))
    target.ShowScrollbars(wx.SHOW_SB_NEVER, wx.SHOW_SB_NEVER)
    rail = ScrollRail(panel, target)
    rail.SetSize((10, 200))
    yield target, rail
    frame.Destroy()
    _APP.Yield()


def test_palette_rail_navigates_entire_hidden_native_scroll_range(scrolling):
    target, rail = scrolling
    _, maximum, top, thumb, height = rail.metrics()
    assert maximum > 0 and 0 < thumb < height and top == 0
    rail.key(SimpleNamespace(GetKeyCode=lambda: wx.WXK_END))
    assert target.GetViewStart()[1] == maximum
    assert rail.metrics()[2] == height - thumb
    rail.key(SimpleNamespace(GetKeyCode=lambda: wx.WXK_HOME))
    assert target.GetViewStart()[1] == 0
    rail.drag_offset = thumb / 2
    rail.move_to(height)
    assert target.GetViewStart()[1] == maximum


def test_short_content_has_no_scroll_thumb_or_division_by_zero(scrolling):
    target, rail = scrolling
    target.SetVirtualSize((300, 100))
    position, maximum, top, thumb, height = rail.metrics()
    assert position == maximum == top == 0 and thumb == height
    rail.move_to(height)
    assert target.GetViewStart()[1] == 0
