"""Shared pan/zoom scene canvas for KiWay engineering previews."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Optional, Tuple

import wx


WorldPoint = Tuple[float, float]
Bounds = Tuple[float, float, float, float]

BACKGROUND = "#161b22"
GRID = "#232b35"
GRID_STRONG = "#2c3642"
TEXT = "#aab7c4"
ACCENT_TEXT = "#d9e2ea"


def severity_colour(status: str) -> str:
    value = (status or "").upper()
    if value.startswith("PASS") or value.startswith("OK"):
        return "#3fa56b"
    if value.startswith("WARN"):
        return "#d4a62a"
    if value.startswith("FAIL") or value.startswith("ERROR"):
        return "#e34a43"
    if value.startswith("INFO"):
        return "#3399cc"
    return "#8fa5b8"


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exponent = 10 ** float(("%e" % raw).split("e")[1])
    mantissa = raw / exponent
    for candidate in (1.0, 2.0, 5.0, 10.0):
        if mantissa <= candidate:
            return candidate * exponent
    return 10.0 * exponent


def pick_nearest(picks: List[dict], screen_x: float, screen_y: float, tolerance_px: float = 11.0):
    """Nearest pick entry within tolerance of a screen point, else None.

    Pure geometry so tests can exercise hit-testing without a wx App.
    """
    best = None
    best_distance: Optional[float] = None
    for pick in picks:
        distance = math.hypot(pick["sx"] - screen_x, pick["sy"] - screen_y)
        radius = max(float(pick.get("r", 6.0)), 4.0)
        allowed = max(tolerance_px, radius + 5.0)
        if distance <= allowed and (best_distance is None or distance < best_distance):
            best = pick
            best_distance = distance
    return best


def pcb_select_items(items: Iterable[Any]) -> int:
    """Mark board items selected inside PCB Editor; returns count marked."""
    count = 0
    try:
        for item in items:
            setter = getattr(item, "SetSelected", None)
            if callable(setter):
                setter(True)
                count += 1
        import pcbnew

        pcbnew.Refresh()
    except Exception:
        pass
    return count


def pcb_highlight_net(board: Any, net_name: str) -> bool:
    """Best-effort cross-version net highlight in PCB Editor."""
    if not net_name:
        return False
    code = 0
    try:
        for footprint in board.GetFootprints():
            for pad in footprint.Pads():
                if str(getattr(pad, "GetNetname", lambda: "")()) == net_name:
                    code = int(pad.GetNetCode())
                    break
            if code:
                break
        if not code:
            for track in getattr(board, "GetTracks", lambda: [])():
                if str(getattr(track, "GetNetname", lambda: "")()) == net_name:
                    code = int(track.GetNetCode())
                    break
    except Exception:
        code = 0
    highlighted = False
    for attempt in (
        lambda: board.SetHighLightNet(code),
        lambda: board.HighlightNet(code),
        lambda: board.SetHighlightedNet(code),
    ):
        try:
            attempt()
            highlighted = True
            break
        except Exception:
            continue
    try:
        import pcbnew

        pcbnew.Refresh()
    except Exception:
        pass
    return highlighted


class PanZoomCanvas(wx.Panel):
    """Antialiased world-space canvas with grid, legend, pan and zoom.

    Subclasses implement ``draw_scene(gc, project)`` and may override
    ``scene_bounds()`` to control fitting. World coordinates are millimetres
    with Y pointing up.
    """

    def __init__(self, parent: wx.Window, empty_text: str = "") -> None:
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.empty_text = empty_text
        self.legend_items: List[Tuple[str, str]] = []
        self.hover_world: Optional[WorldPoint] = None
        self.hover_screen: Optional[Tuple[int, int]] = None
        self.scale = 1.0
        self.center_x = 0.0
        self.center_y = 0.0
        self._pan_start: Optional[Tuple[int, int]] = None
        self._pan_center: Optional[Tuple[float, float]] = None
        self.picks: List[dict] = []
        self.on_pick = None
        self.highlight_data: Any = None
        self.SetMinSize((-1, 200))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        for event, handler in (
            (wx.EVT_PAINT, self.on_paint),
            (wx.EVT_SIZE, self.on_resize),
            (wx.EVT_MOUSEWHEEL, self.on_wheel),
            (wx.EVT_LEFT_DOWN, self.on_left_down),
            (wx.EVT_LEFT_UP, self.on_left_up),
            (wx.EVT_LEFT_DCLICK, lambda e: (self.fit(), e.Skip())),
            (wx.EVT_MOTION, self.on_motion),
            (wx.EVT_LEAVE_WINDOW, self.on_leave),
        ):
            self.Bind(event, handler)

    # ------------------------------------------------------------------ API
    def set_picks(self, picks: Iterable[dict]) -> None:
        """Register clickable world points: {"x","y","r","data"} entries.

        Screen positions are recomputed on every paint; consumers set
        ``on_pick`` to receive the ``data`` of the clicked entry and call
        ``set_highlight`` to keep a marker visible.
        """
        self.picks = list(picks)

    def set_highlight(self, data: Any) -> None:
        """Keep a double-ring marker on every pick whose data matches."""
        self.highlight_data = data
        self.Refresh()

    def refresh_pick_screens(self) -> None:
        for pick in self.picks:
            sx, sy = self.project((pick["x"], pick["y"]))
            pick["sx"] = sx
            pick["sy"] = sy
    def set_legend(self, items: Iterable[Tuple[str, str]]) -> None:
        self.legend_items = list(items)
        self.Refresh()

    def zoom(self, factor: float) -> None:
        self.scale = max(1e-6, min(1e6, self.scale * factor))
        self.Refresh()

    def fit(self) -> None:
        size = self.GetClientSize()
        bounds = self.scene_bounds()
        if bounds is None or size.width < 40 or size.height < 40:
            return
        min_x, min_y, max_x, max_y = bounds
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        margin = 46.0
        self.scale = min((size.width - margin * 2) / span_x, (size.height - margin * 2) / span_y)
        self.center_x = (min_x + max_x) / 2.0
        self.center_y = (min_y + max_y) / 2.0
        self.Refresh()

    # ------------------------------------------------------- subclass hooks
    def draw_scene(self, gc: wx.GraphicsContext, project) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def scene_bounds(self) -> Optional[Bounds]:  # pragma: no cover - interface
        return None

    def status_for(self, world: Optional[WorldPoint]) -> str:
        if world is None:
            return ""
        return f"{world[0]:.3f}, {world[1]:.3f} mm"

    # ---------------------------------------------------------- transforms
    def project(self, point: WorldPoint) -> Tuple[float, float]:
        size = self.GetClientSize()
        return (
            size.width / 2.0 + (point[0] - self.center_x) * self.scale,
            size.height / 2.0 - (point[1] - self.center_y) * self.scale,
        )

    def unproject(self, sx: float, sy: float) -> WorldPoint:
        size = self.GetClientSize()
        return (
            self.center_x + (sx - size.width / 2.0) / self.scale,
            self.center_y - (sy - size.height / 2.0) / self.scale,
        )

    # -------------------------------------------------------------- events
    def on_resize(self, event: wx.SizeEvent) -> None:
        self.Refresh()
        event.Skip()

    def on_wheel(self, event: wx.MouseEvent) -> None:
        anchor = self.unproject(event.GetPosition()[0], event.GetPosition()[1])
        rotation = event.GetWheelRotation() / max(event.GetWheelDelta(), 1)
        factor = 1.15 ** rotation
        new_scale = max(1e-6, min(1e6, self.scale * factor))
        if new_scale == self.scale:
            return
        size = self.GetClientSize()
        # Keep the world point under the cursor stationary while zooming.
        self.center_x = anchor[0] - (event.GetPosition()[0] - size.width / 2.0) / new_scale
        self.center_y = anchor[1] + (event.GetPosition()[1] - size.height / 2.0) / new_scale
        self.scale = new_scale
        self.Refresh()

    def on_left_down(self, event: wx.MouseEvent) -> None:
        self._pan_start = (event.GetPosition()[0], event.GetPosition()[1])
        self._pan_center = (self.center_x, self.center_y)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        event.Skip()

    def on_left_up(self, event: wx.MouseEvent) -> None:
        start = self._pan_start
        self._pan_start = None
        self._pan_center = None
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        if start is not None and callable(self.on_pick):
            moved = math.hypot(event.GetPosition()[0] - start[0], event.GetPosition()[1] - start[1])
            if moved < 4.0:
                self.refresh_pick_screens()
                hit = pick_nearest(self.picks, event.GetPosition()[0], event.GetPosition()[1])
                if hit is not None:
                    self.set_highlight(hit.get("data"))
                    try:
                        self.on_pick(hit.get("data"))
                    except Exception:
                        pass
                    return
        event.Skip()

    def on_motion(self, event: wx.MouseEvent) -> None:
        position = event.GetPosition()
        self.hover_screen = (position[0], position[1])
        self.hover_world = self.unproject(position[0], position[1])
        if self._pan_start and self._pan_center:
            dx = position[0] - self._pan_start[0]
            dy = position[1] - self._pan_start[1]
            self.center_x = self._pan_center[0] - dx / self.scale
            self.center_y = self._pan_center[1] + dy / self.scale
        self.Refresh()
        event.Skip()

    def on_leave(self, _event: wx.Event) -> None:
        self.hover_screen = None
        self.hover_world = None
        self.Refresh()

    # -------------------------------------------------------------- paint
    def on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(BACKGROUND))
        dc.Clear()
        size = self.GetClientSize()
        gc = wx.GraphicsContext.Create(dc)
        if size.width < 30 or size.height < 30:
            return
        self._draw_grid(gc, size)
        try:
            self.draw_scene(gc, self.project)
        except Exception:
            pass
        self._draw_picks_and_highlight(gc)
        self._draw_overlays(gc, size)

    def _draw_grid(self, gc: wx.GraphicsContext, size: wx.Size) -> None:
        if self.scale <= 0:
            return
        raw = 90.0 / self.scale
        step = _nice_step(raw)
        corner_a = self.unproject(0, size.height)
        corner_b = self.unproject(size.width, 0)
        gc.SetPen(wx.Pen(wx.Colour(GRID), 1))
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), TEXT)
        first_x = int(corner_a[0] // step) * step
        x_value = first_x
        while x_value <= corner_b[0]:
            sx = self.project((x_value, 0.0))[0]
            gc.StrokeLine(sx, 0, sx, size.height)
            if step * self.scale >= 52:
                gc.DrawText(f"{x_value:g}", sx + 3, size.height - 16)
            x_value += step
        first_y = int(corner_a[1] // step) * step
        y_value = first_y
        while y_value <= corner_b[1]:
            sy = self.project((0.0, y_value))[1]
            gc.StrokeLine(0, sy, size.width, sy)
            if step * self.scale >= 52:
                gc.DrawText(f"{y_value:g}", 4, sy - 14)
            y_value += step

    def _draw_picks_and_highlight(self, gc: wx.GraphicsContext) -> None:
        self.refresh_pick_screens()
        for pick in self.picks:
            if pick.get("marker", True) is False:
                continue
            sx, sy = pick["sx"], pick["sy"]
            gc.SetPen(wx.Pen(wx.Colour("#f4d48d"), 1))
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.DrawEllipse(sx - 4.0, sy - 4.0, 8.0, 8.0)
        if self.highlight_data is not None:
            for pick in self.picks:
                if pick.get("data") == self.highlight_data:
                    sx, sy = pick["sx"], pick["sy"]
                    gc.SetPen(wx.Pen(wx.Colour("#ffcf5c"), 3))
                    gc.SetBrush(wx.TRANSPARENT_BRUSH)
                    gc.DrawEllipse(sx - 11.0, sy - 11.0, 22.0, 22.0)
                    gc.SetPen(wx.Pen(wx.Colour("#ffffff"), 1))
                    gc.DrawEllipse(sx - 15.0, sy - 15.0, 30.0, 30.0)

    def _draw_overlays(self, gc: wx.GraphicsContext, size: wx.Size) -> None:
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), TEXT)

        # Scale bar (bottom left).
        target_px = 110.0
        world_len = _nice_step(target_px / max(self.scale, 1e-9)) if self.scale > 0 else 1.0
        bar_px = world_len * self.scale
        x0, y0 = 12.0, size.height - 26.0
        gc.SetPen(wx.Pen(wx.Colour(TEXT), 2))
        gc.StrokeLine(x0, y0, x0 + bar_px, y0)
        gc.StrokeLine(x0, y0 - 4, x0, y0 + 4)
        gc.StrokeLine(x0 + bar_px, y0 - 4, x0 + bar_px, y0 + 4)
        gc.DrawText(f"{world_len:g} mm", x0 + bar_px + 6, y0 - 7)

        # Legend chips (top right).
        pen_x = size.width - 10.0
        gc.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), ACCENT_TEXT)
        for colour, label in reversed(self.legend_items):
            extent = gc.GetTextExtent(label)
            chip_w = extent[0] + 24.0
            pen_x -= chip_w + 8.0
            top = 10.0
            gc.SetBrush(wx.Brush(wx.Colour("#1d242d")))
            gc.SetPen(wx.Pen(wx.Colour(colour), 2))
            gc.DrawRectangle(pen_x, top, chip_w, 20.0)
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(wx.Colour(colour)))
            gc.DrawEllipse(pen_x + 7.0, top + 6.0, 8.0, 8.0)
            gc.DrawText(label, pen_x + 19.0, top + 3.0)

        # Hover crosshair + readout.
        if self.hover_screen is not None:
            sx, sy = self.hover_screen
            gc.SetPen(wx.Pen(wx.Colour("#3f4c5a"), 1, wx.PENSTYLE_SHORT_DASH))
            gc.StrokeLine(sx, 0, sx, size.height)
            gc.StrokeLine(0, sy, size.width, sy)
            readout = self.status_for(self.hover_world)
            if readout:
                extent = gc.GetTextExtent(readout)
                box_x = min(sx + 10.0, size.width - extent[0] - 18.0)
                box_y = min(sy + 10.0, size.height - 26.0)
                gc.SetBrush(wx.Brush(wx.Colour("#10151b")))
                gc.SetPen(wx.Pen(wx.Colour(GRID_STRONG), 1))
                gc.DrawRectangle(box_x, box_y, extent[0] + 12.0, 20.0)
                gc.DrawText(readout, box_x + 6.0, box_y + 3.0)

        if not self.has_content():
            gc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL), TEXT)
            gc.DrawLabel(
                self.empty_text,
                wx.Rect(18, 18, max(1, size.width - 36), max(1, size.height - 36)),
                wx.ALIGN_CENTER,
            )

    def has_content(self) -> bool:  # pragma: no cover - interface
        return True


def add_zoom_toolbar(panel: wx.Panel, canvas: PanZoomCanvas, sizer: wx.Sizer) -> None:
    """Attach a compact Fit/zoom toolbar row beneath ``canvas``."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    for label, handler in (
        ("Fit", lambda _e: canvas.fit()),
        ("+", lambda _e: canvas.zoom(1.25)),
        ("\u2212", lambda _e: canvas.zoom(0.8)),
    ):
        button = wx.Button(panel, label=label, size=(46, 26))
        button.Bind(wx.EVT_BUTTON, handler)
        row.Add(button, 0, wx.RIGHT, 6)
    hint = wx.StaticText(panel, label="Drag to pan \u00b7 scroll to zoom \u00b7 double-click to fit")
    hint.Wrap(420)
    row.Add(hint, 0, wx.ALIGN_CENTER_VERTICAL)
    sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.BOTTOM, 4)
