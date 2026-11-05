"""Small native, keyboard-accessible controls for the Review workspace."""
import wx
from wx.lib.buttons import GenButton
from .theme import palette

INK = '#253047'
ACCENT = '#087f8c'
BACKGROUND = '#f4f6fa'


class ActionButton(GenButton):
    def __init__(self, parent, label, handler=None, *, primary=False, compact=False, id=wx.ID_ANY):
        super().__init__(parent, id=id, label=label, style=wx.BORDER_NONE)
        self.compact = compact
        self.primary = primary
        self.active = False
        self.SetBackgroundColour(palette(self)['surface'])
        self.SetForegroundColour(palette(self)['primary_text'] if primary else palette(self)['text'])
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
        colors = palette(self)
        color = colors['primary'] if selected else (colors['hover'] if not self.up else colors['surface'])
        if not self.IsEnabled():
            color = colors['disabled']
        dc.SetPen(wx.Pen(colors['accent'] if selected else colors['border']))
        dc.SetBrush(wx.Brush(color))
        dc.DrawRoundedRectangle(x1, y1, max(1, x2-x1), max(1, y2-y1), 6)

    def DrawLabel(self, dc, width, height, dx=0, dy=0):
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(self.GetForegroundColour() if self.IsEnabled() else palette(self)['disabled_text'])
        label = self.GetLabel()
        tw, th = dc.GetTextExtent(label)
        if not self.up:
            dx = dy = self.labelDelta
        dc.DrawText(label, (width-tw)//2+dx, (height-th)//2+dy)

    def DrawFocusIndicator(self, dc, width, height):
        colors = palette(self)
        dc.SetPen(wx.Pen(colors['primary_text'] if self.primary or self.active else colors['accent'], 2))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRoundedRectangle(3, 3, max(1, width-6), max(1, height-6), 4)

    def set_active(self, active):
        self.active = active
        self.SetForegroundColour(palette(self)['primary_text'] if active or self.primary else palette(self)['text'])
        self.Refresh()


class ReviewSplitter(wx.SplitterWindow):
    """Keep native split interaction while painting the sash in our palette."""
    def __init__(self, parent):
        super().__init__(parent, style=wx.SP_LIVE_UPDATE | wx.SP_NO_XP_THEME | wx.BORDER_NONE)
        self.SetBackgroundColour(palette(self)['background'])
