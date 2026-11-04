"""Palette-aware Review search without the native MSW SearchCtrl cue banner."""
from __future__ import annotations

import wx

from .theme import palette


class ReviewSearch(wx.Panel):
    """A plain text search field with stable value and selection across themes.

    EVT_TEXT from the child is a wx command event and propagates to bindings on
    this panel, matching the existing SearchCtrl caller contract.
    """

    def __init__(self, parent, value='', style=wx.TE_PROCESS_ENTER):
        super().__init__(parent, style=wx.BORDER_NONE)
        colors = palette(self)
        self.SetBackgroundColour(colors['surface'])
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.caption = wx.StaticText(self, label='Search')
        self.caption.SetForegroundColour(colors['muted'])
        row.Add(self.caption, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 9)
        self.field = wx.TextCtrl(self, value=value,
                                 style=(style | wx.BORDER_NONE) & ~wx.TE_RICH2)
        self.field.SetBackgroundColour(colors['surface'])
        self.field.SetForegroundColour(colors['text'])
        row.Add(self.field, 1, wx.EXPAND | wx.RIGHT | wx.TOP | wx.BOTTOM, 7)
        self.SetSizer(row)
        self.SetMinSize((-1, 34))
        self.Bind(wx.EVT_PAINT, self._paint)

    def _paint(self, event):
        dc = wx.PaintDC(self)
        width, height = self.GetClientSize()
        if width > 1 and height > 1:
            colors = palette(self)
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.SetPen(wx.Pen(colors['border'], 1))
            dc.DrawRectangle(0, 0, width - 1, height - 1)

    def GetValue(self):
        return self.field.GetValue()

    def SetValue(self, value):
        self.field.SetValue(value)

    def ChangeValue(self, value):
        self.field.ChangeValue(value)

    def SetFocus(self):
        self.field.SetFocus()

    def SelectAll(self):
        self.field.SelectAll()

    def SetDescriptiveText(self, value):
        self.caption.SetLabel('Search thread' if 'thread' in str(value).casefold() else 'Search')
        self.Layout()
