"""Lightweight in-window geometry preview for KiWay routing tools."""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import wx


Line = Tuple[float, float, float, float]
Point = Tuple[float, float]
Rectangle = Tuple[float, float, float, float]


class GeometryPreview(wx.Panel):
    def __init__(self, parent: wx.Window, empty_text: str) -> None:
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.lines: list[Line] = []
        self.points: list[Point] = []
        self.pads: list[Point] = []
        self.outlines: list[Rectangle] = []
        self.point_diameters: list[float] = []
        self.empty_text = empty_text
        self.SetMinSize((-1, 190))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def set_geometry(
        self,
        lines: Iterable[Line] = (),
        points: Iterable[Point] = (),
        pads: Iterable[Point] = (),
        outlines: Iterable[Rectangle] = (),
        point_diameters: Iterable[float] = (),
    ) -> None:
        self.lines = list(lines)
        self.points = list(points)
        self.pads = list(pads)
        self.outlines = list(outlines)
        self.point_diameters = list(point_diameters)
        self.Refresh()

    def clear(self) -> None:
        self.lines = []
        self.points = []
        self.pads = []
        self.outlines = []
        self.point_diameters = []
        self.Refresh()

    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        background = wx.Colour("#161b22")
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        width, height = self.GetClientSize()
        dc.SetPen(wx.Pen(wx.Colour("#2c3642"), 1))
        for x in range(20, width, 40):
            dc.DrawLine(x, 0, x, height)
        for y in range(20, height, 40):
            dc.DrawLine(0, y, width, y)

        coordinates = [
            coordinate
            for line in self.lines
            for coordinate in ((line[0], line[1]), (line[2], line[3]))
        ] + list(self.points) + list(self.pads) + [point for rect in self.outlines for point in ((rect[0], rect[1]), (rect[2], rect[3]))]
        if not coordinates:
            dc.SetTextForeground(wx.Colour("#aab7c4"))
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

        dc.SetPen(wx.Pen(wx.Colour("#28b8d6"), 3))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.SetPen(wx.Pen(wx.Colour("#8fa5b8"), 2))
        for x1, y1, x2, y2 in self.outlines:
            left, top = project((min(x1, x2), max(y1, y2)))
            right, bottom = project((max(x1, x2), min(y1, y2)))
            dc.DrawRectangle(left, top, max(1, right-left), max(1, bottom-top))
        dc.SetPen(wx.Pen(wx.Colour("#28b8d6"), 3))
        for x1, y1, x2, y2 in self.lines:
            dc.DrawLine(*project((x1, y1)), *project((x2, y2)))
        dc.SetPen(wx.Pen(wx.Colour("#c78332"), 2))
        dc.SetBrush(wx.Brush(wx.Colour("#e5a44c")))
        for point in self.pads:
            x, y = project(point)
            dc.DrawCircle(x, y, 6)
        dc.SetPen(wx.Pen(wx.Colour("#e45f55"), 2))
        dc.SetBrush(wx.Brush(wx.Colour("#251d1d")))
        for index, point in enumerate(self.points):
            x, y = project(point)
            diameter = self.point_diameters[index] if index < len(self.point_diameters) else 0.0
            radius = max(5, int(diameter * scale / 2.0))
            dc.DrawCircle(x, y, radius)
