"""Small native, keyboard-accessible controls for the Review workspace."""
import wx
from wx.lib.buttons import GenButton

INK = '#253047'
ACCENT = '#087f8c'
BACKGROUND = '#f4f6fa'


class ActionButton(GenButton):
    def __init__(self, parent, label, handler=None, *, primary=False, compact=False):
        super().__init__(parent, label=label, style=wx.BORDER_NONE)
        self.compact = compact
        self.primary = primary
        self.active = False
        self.SetBackgroundColour('#ffffff')
        self.SetForegroundColour('#ffffff' if primary else INK)
        font = self.GetFont()
        font.SetPointSize(9)
        font.SetWeight(wx.FONTWEIGHT_BOLD if primary else wx.FONTWEIGHT_NORMAL)
        self.SetFont(font)
        self.SetMinSize((self.GetTextExtent(label).width + (18 if compact else 26), 30 if compact else 36))
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.SetToolTip(label)
        if handler:
            self.Bind(wx.EVT_BUTTON, handler)

    def SetLabel(self, label):
        super().SetLabel(label)
        if hasattr(self, 'compact'):
            self.SetMinSize((self.GetTextExtent(label).width + (18 if self.compact else 26), 30 if self.compact else 36))
            self.InvalidateBestSize()

    def DrawBezel(self, dc, x1, y1, x2, y2):
        selected = self.primary or self.active
        color = ACCENT if selected else ('#e4eef1' if not self.up else '#ffffff')
        if not self.IsEnabled():
            color = '#dce3e8'
        dc.SetPen(wx.Pen(color if selected else '#d7e0e8'))
        dc.SetBrush(wx.Brush(color))
        dc.DrawRoundedRectangle(x1, y1, max(1, x2-x1), max(1, y2-y1), 6)

    def set_active(self, active):
        self.active = active
        self.SetForegroundColour('#ffffff' if active or self.primary else INK)
        self.Refresh()
