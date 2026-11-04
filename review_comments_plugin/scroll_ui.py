"""Palette-aware scroll rail for a wx.ScrolledWindow, without OS light chrome."""
import math

import wx

from .theme import palette


class ScrollRail(wx.Control):
    def __init__(self, parent, target):
        super().__init__(parent, size=(10, -1), style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetMinSize((10, 20))
        self.SetName('Scroll comments')
        self.target, self.drag_offset = target, None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.down)
        self.Bind(wx.EVT_LEFT_UP, self.up)
        self.Bind(wx.EVT_MOTION, self.motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda event: setattr(self, 'drag_offset', None))
        self.Bind(wx.EVT_MOUSEWHEEL, self.wheel)
        self.Bind(wx.EVT_KEY_DOWN, self.key)
        for kind in (wx.EVT_SCROLLWIN, wx.EVT_MOUSEWHEEL, wx.EVT_SIZE):
            target.Bind(kind, self.changed)

    def metrics(self):
        unit = max(1, self.target.GetScrollPixelsPerUnit()[1])
        viewport = max(1, self.target.GetClientSize().height)
        total = max(viewport, self.target.GetVirtualSize().height)
        maximum = max(0, math.ceil((total - viewport) / unit))
        position = min(maximum, max(0, self.target.GetViewStart()[1]))
        height = max(1, self.GetClientSize().height)
        thumb = height if not maximum else min(height, max(24, round(height * viewport / total)))
        top = 0 if not maximum else round((height - thumb) * position / maximum)
        return position, maximum, top, thumb, height

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        colors = palette(self)
        dc.SetBackground(wx.Brush(colors['background']))
        dc.Clear()
        _, maximum, top, thumb, _ = self.metrics()
        if maximum:
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(colors['muted']))
            dc.DrawRoundedRectangle(2, top, max(2, self.GetClientSize().width - 4), thumb, 3)

    def changed(self, event):
        event.Skip()
        wx.CallAfter(self.refresh_later)

    def refresh_later(self):
        if self and not self.IsBeingDeleted():
            self.Refresh()

    def move_to(self, y):
        _, maximum, _, thumb, height = self.metrics()
        if maximum and height > thumb:
            ratio = max(0., min(1., (y - (self.drag_offset or 0)) / (height - thumb)))
            self.target.Scroll(-1, round(ratio * maximum))
            self.Refresh()

    def down(self, event):
        _, maximum, top, thumb, _ = self.metrics()
        if not maximum:
            return
        self.SetFocus()
        self.drag_offset = event.GetY() - top if top <= event.GetY() <= top + thumb else thumb / 2
        self.CaptureMouse()
        self.move_to(event.GetY())

    def motion(self, event):
        if self.drag_offset is not None and event.Dragging():
            self.move_to(event.GetY())

    def up(self, event):
        self.drag_offset = None
        if self.HasCapture():
            self.ReleaseMouse()

    def wheel(self, event):
        position, maximum, *_ = self.metrics()
        steps = event.GetWheelRotation() / max(1, event.GetWheelDelta())
        self.target.Scroll(-1, max(0, min(maximum, round(position - 3 * steps))))
        self.Refresh()

    def key(self, event):
        position, maximum, *_ = self.metrics()
        page = max(1, self.target.GetClientSize().height // max(1, self.target.GetScrollPixelsPerUnit()[1]))
        destinations = {wx.WXK_UP:position-1, wx.WXK_DOWN:position+1,
                        wx.WXK_PAGEUP:position-page, wx.WXK_PAGEDOWN:position+page,
                        wx.WXK_HOME:0, wx.WXK_END:maximum}
        if event.GetKeyCode() not in destinations:
            event.Skip()
            return
        self.target.Scroll(-1, max(0, min(maximum, destinations[event.GetKeyCode()])))
        self.Refresh()
