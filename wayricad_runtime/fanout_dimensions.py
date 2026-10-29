"""Small dimensioned schematic for the fanout form; never board geometry."""
import math
import wx


class FanoutDimensions(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent, size=(-1, 205))
        self.SetMinSize((180, 205))
        self.frame = frame
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def dimensions(self):
        values = {}
        effective = None
        if self.frame.use_netclass_rules.GetValue():
            # Resolve through the planner's authoritative rule precedence so the
            # guide does not show disabled, superseded manual width/via fields.
            from .routing import FanoutPlanner
            try:
                effective = FanoutPlanner(self.frame.board, self.frame._routing_api,
                    self.frame._settings_snapshot())._dimensions()
            except (ValueError, TypeError, KeyError, OSError):
                return None
        for name in ('width', 'length', 'via_diameter', 'via_drill', 'escape_angle', 'stagger_pitch'):
            try:
                value = float(effective[name] if effective is not None else getattr(self.frame, name).GetValue())
                if not math.isfinite(value) or value < 0:
                    raise ValueError()
                values[name] = value
            except (ValueError, TypeError):
                return None
        return values

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
        dc.Clear()
        dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        dc.SetFont(self.GetFont())
        dc.DrawText('Dimension guide · illustrative', 6, 4)
        values = self.dimensions()
        if values is None:
            dc.DrawText('Enter valid dimensions to update.', 6, 32)
            return
        w = self.GetClientSize().width
        radius = 23
        x, y = max(38, w//2), 55
        dc.SetPen(wx.Pen('#087f98', 2));dc.SetBrush(wx.Brush('#b6dce0'))
        dc.DrawCircle(x, y, radius)
        drill = min(radius, max(1, round(radius*values['via_drill']/max(values['via_diameter'], .001))))
        dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
        dc.DrawCircle(x, y, drill)
        dc.DrawLine(x-radius, y, x+radius, y)
        dc.DrawText(f"Via Ø {values['via_diameter']:g} mm · drill {values['via_drill']:g} mm", 6, 84)
        # Fixed canvas bounds keep even very large entered values inside the card.
        angle = math.radians(values['escape_angle'] % 360)
        x0, y0 = max(12, w/2-30), 128
        run = 30
        x1, y1 = x0+run, y0
        x2, y2 = x1+run*math.cos(angle), y1+run*math.sin(angle)
        width = max(1, min(12, round(2*radius*values['width']/max(values['via_diameter'], .001))))
        dc.SetPen(wx.Pen('#087f98', width))
        dc.DrawLines([wx.Point(round(x0), round(y0)), wx.Point(round(x1), round(y1)), wx.Point(round(x2), round(y2))])
        dc.DrawText(f"Angle setting {values['escape_angle']:g}°", 6, 160)
        dc.DrawText(f"Trace {values['width']:g} mm · reach {values['length']:g} mm", 6, 175)
        dc.DrawText(f"Alternating extra reach {values['stagger_pitch']:g} mm", 6, 190)
