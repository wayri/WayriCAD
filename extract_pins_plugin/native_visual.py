"""Native SVG diagram viewer that does not depend on Edge WebView2."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import wx


class NativeSvgPreview(wx.ScrolledWindow):
    def __init__(self, parent, on_net=None):
        super().__init__(parent, style=wx.HSCROLL | wx.VSCROLL | wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(wx.Colour('#15191d'))
        self.SetScrollRate(20, 20)
        self._svg = ''
        self._natural = (900, 600)
        self._scale = 1.0
        self._bitmap = None
        self._error = ''
        self._areas = []
        self._on_net = on_net
        self._drag = None
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self._mouse_down)
        self.Bind(wx.EVT_LEFT_UP, self._mouse_up)
        self.Bind(wx.EVT_MOTION, self._motion)
        self.Bind(wx.EVT_LEFT_DCLICK, self._fit)

    @property
    def rendered_size(self):
        return tuple(self._bitmap.GetSize()) if self._bitmap and self._bitmap.IsOk() else (0, 0)

    @property
    def render_error(self):
        return self._error

    def SetSVG(self, svg):
        self._svg = svg or ''
        self._bitmap = None
        self._error = ''
        self._areas = []
        if not svg:
            self.Refresh()
            return
        try:
            root = ET.fromstring(svg)
            view = [float(value) for value in root.attrib.get('viewBox', '0 0 900 600').replace(',', ' ').split()]
            if len(view) != 4 or view[2] <= 0 or view[3] <= 0:
                raise ValueError('SVG has no positive viewBox')
            self._natural = (min(4000, round(view[2])), min(4000, round(view[3])))
            for group in root.iter():
                if 'net-row' not in group.attrib.get('class', '').split():
                    continue
                net = group.attrib.get('data-net', '')
                for item in group:
                    if item.tag.rsplit('}', 1)[-1] != 'rect':
                        continue
                    try:
                        area = tuple(float(item.attrib[key]) for key in ('x', 'y', 'width', 'height'))
                    except (KeyError, ValueError):
                        continue
                    self._areas.append((net, *area))
                    break
            self._render()
        except Exception as exc:
            self._error = f'Native SVG preview unavailable: {exc}. SVG export is still available.'
            self.Refresh()

    def _render(self):
        width = max(1, min(6000, round(self._natural[0] * self._scale)))
        height = max(1, min(6000, round(self._natural[1] * self._scale)))
        try:
            bundle = wx.BitmapBundle.FromSVG(self._svg.encode('utf-8'), wx.Size(width, height))
            self._bitmap = bundle.GetBitmap(wx.Size(width, height))
            if not self._bitmap.IsOk():
                raise ValueError('SVG did not produce a bitmap')
            self._error = ''
            self.SetVirtualSize(width, height)
        except Exception as exc:
            self._bitmap = None
            self._error = f'Native SVG preview unavailable: {exc}. SVG export is still available.'
        self.Refresh()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        self.PrepareDC(dc)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        if self._bitmap:
            dc.DrawBitmap(self._bitmap, 0, 0)
        elif self._error:
            dc.SetTextForeground(wx.Colour('#eff7fa'))
            dc.DrawText(self._error, 16, 16)

    def _wheel(self, event):
        if not self._svg:
            return
        self._scale = max(0.25, min(3.0, self._scale * (1.15 if event.GetWheelRotation() > 0 else 1 / 1.15)))
        self._render()

    def _mouse_down(self, event):
        x, y = self.CalcUnscrolledPosition(event.GetPosition())
        x /= self._scale
        y /= self._scale
        for net, left, top, width, height in reversed(self._areas):
            if net and left <= x <= left + width and top <= y <= top + height:
                if self._on_net:
                    self._on_net(net)
                return
        self._drag = (event.GetPosition(), self.GetViewStart())
        self.CaptureMouse()

    def _motion(self, event):
        if not self._drag or not event.Dragging():
            return
        start, scroll = self._drag
        here = event.GetPosition()
        self.Scroll(max(0, scroll[0] + round((start.x - here.x) / 20)),
                    max(0, scroll[1] + round((start.y - here.y) / 20)))

    def _mouse_up(self, event):
        self._drag = None
        if self.HasCapture():
            self.ReleaseMouse()

    def _fit(self, event):
        if not self._svg:
            return
        width, height = self.GetClientSize()
        self._scale = max(0.25, min(1.0, (width - 20) / self._natural[0], (height - 20) / self._natural[1]))
        self._render()
        self.Scroll(0, 0)
