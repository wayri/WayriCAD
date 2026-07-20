"""Lightweight in-window geometry preview for KiWay routing tools."""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import wx


Line = Tuple[float, float, float, float]
Point = Tuple[float, float]


class GeometryPreview(wx.Panel):
    def __init__(self, parent: wx.Window, empty_text: str) -> None:
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.lines: list[Line] = []
        self.points: list[Point] = []
        self.empty_text = empty_text
        self.SetMinSize((-1, 190))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def set_geometry(
        self,
        lines: Iterable[Line] = (),
        points: Iterable[Point] = (),
    ) -> None:
        self.lines = list(lines)
        self.points = list(points)
        self.Refresh()

    def clear(self) -> None:
        self.lines = []
        self.points = []
        self.Refresh()

    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        background = wx.Colour("#f7f9fb")
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        width, height = self.GetClientSize()
        dc.SetPen(wx.Pen(wx.Colour("#d7dfe6"), 1))
        for x in range(20, width, 40):
            dc.DrawLine(x, 0, x, height)
        for y in range(20, height, 40):
            dc.DrawLine(0, y, width, y)

        coordinates = [
            coordinate
            for line in self.lines
            for coordinate in ((line[0], line[1]), (line[2], line[3]))
        ] + list(self.points)
        if not coordinates:
            dc.SetTextForeground(wx.Colour("#4f5b66"))
            dc.DrawLabel(self.empty_text, wx.Rect(18, 18, max(1, width - 36), max(1, height - 36)), wx.ALIGN_CENTER)
            return

        min_x = min(point[0] for point in coordinates)
        max_x = max(point[0] for point in coordinates)
        min_y = min(point[1] for point in coordinates)
        max_y = max(point[1] for point in coordinates)
        span_x = max(max_x - min_x, 0.001)
        span_y = max(max_y - min_y, 0.001)
        margin = 24
        scale = min((width - margin * 2) / span_x, (height - margin * 2) / span_y)

        def project(point: Point) -> tuple[int, int]:
            x = margin + int((point[0] - min_x) * scale)
            y = height - margin - int((point[1] - min_y) * scale)
            return x, y

        dc.SetPen(wx.Pen(wx.Colour("#1769aa"), 3))
        for x1, y1, x2, y2 in self.lines:
            dc.DrawLine(*project((x1, y1)), *project((x2, y2)))
        dc.SetPen(wx.Pen(wx.Colour("#9b3527"), 2))
        dc.SetBrush(wx.Brush(wx.Colour("#f2a38f")))
        for point in self.points:
            x, y = project(point)
            dc.DrawCircle(x, y, 5)
