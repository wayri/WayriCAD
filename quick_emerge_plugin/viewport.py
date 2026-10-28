"""Native scientific viewport with persistent cameras and sample-aware picking."""
from dataclasses import dataclass
import math
import time

import numpy as np
import wx
from matplotlib.figure import Figure
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg, NavigationToolbar2WxAgg
from mpl_toolkits.mplot3d import proj3d


PRESETS = {'Isometric': (28, -55), 'Top': (90, -90), 'Bottom': (-90, -90),
           'Front': (0, -90), 'Right': (0, 0)}


@dataclass
class Camera:
    elevation: float = 28
    azimuth: float = -55
    projection: str = 'ortho'
    physical_aspect: bool = True
    roll: float = 0


def closest_projected(points, axes, pixel_x, pixel_y, tolerance=14):
    """Pick an original sample near the cursor, never invent a 3D intersection."""
    if not len(points):
        return None
    points = np.asarray(points, dtype=float)
    x, y, z = proj3d.proj_transform(points[:, 0], points[:, 1], points[:, 2], axes.get_proj())
    pixels = axes.transData.transform(np.column_stack((x, y)))
    distance = np.sum((pixels-np.array([pixel_x, pixel_y]))**2, axis=1)
    distance[~np.isfinite(distance)] = np.inf
    index = int(np.argmin(distance))
    return index if distance[index] <= tolerance**2 else None


class PlotViewport(wx.Panel):
    def __init__(self, parent, name, callback):
        super().__init__(parent)
        self.name = name
        self.callback = callback
        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.canvas = FigureCanvasWxAgg(self, wx.ID_ANY, self.figure)
        self.canvas.SetMinSize((1, 1))
        self.toolbar = NavigationToolbar2WxAgg(self.canvas)
        self.toolbar.Realize()
        self.toolbar.Hide()
        self.interaction = 'Orbit' if name.startswith('3D') else 'Probe'
        self.mode_buttons = {}
        controls = wx.BoxSizer(wx.HORIZONTAL)
        for mode, tip in [('Orbit', 'Left drag: orbit around the scene. Wheel: zoom.'),
                          ('Pan', 'Left drag: pan the scene without rotating it.'),
                          ('Zoom', 'Left drag: zoom (3D); draw a zoom rectangle (2D).'),
                          ('Probe', 'Left click: select an original sample. Hover: readout. Middle drag: pan; right drag: orbit in 3D.')]:
            button = wx.ToggleButton(self, label=mode, style=wx.BU_EXACTFIT, size=(-1, 25))
            button.SetToolTip(tip)
            button.Bind(wx.EVT_TOGGLEBUTTON, lambda event, mode=mode: self.set_mode(mode))
            self.mode_buttons[mode] = button
            controls.Add(button, 0, wx.RIGHT, 3)
        for label, tip, action in [('Fit', 'Fit original scene bounds [F].', self.fit),
                                   ('+', 'Zoom in; the wheel also zooms.', lambda: self.zoom(.85)),
                                   ('−', 'Zoom out.', lambda: self.zoom(1/.85)),
                                   ('Image…', 'Export the current viewport image.', self.toolbar.save_figure)]:
            button = wx.Button(self, label=label, style=wx.BU_EXACTFIT, size=(-1, 25))
            button.SetToolTip(tip)
            button.Bind(wx.EVT_BUTTON, lambda event, action=action: action())
            controls.Add(button, 0, wx.RIGHT, 3)
        self.interaction_hint = wx.StaticText(self, label='')
        controls.Add(self.interaction_hint, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 6)
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(controls, 0, wx.EXPAND | wx.ALL, 4)
        layout.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(layout)
        self.camera = Camera()
        self.options = {}
        self.home = None
        self.renderer = None
        self.arguments = None
        self.picking = []
        self.press = None
        self.last_hover = 0
        self.markers = []
        self.selection = None
        self.profile = None
        self.dark = False
        self.canvas.mpl_connect('button_press_event', self._press)
        self.canvas.mpl_connect('button_release_event', self._release)
        self.canvas.mpl_connect('motion_notify_event', self._hover)
        self.canvas.mpl_connect('scroll_event', self._scroll)
        self.canvas.mpl_connect('key_press_event', self._key)
        self.Bind(wx.EVT_SIZE, self._resize)

    def _resize(self, event):
        self.Layout()
        wx.CallAfter(self.refresh_canvas)
        event.Skip()

    def refresh_canvas(self):
        if not self or self.IsBeingDeleted():
            return
        width, height = self.canvas.GetClientSize()
        if width > 1 and height > 1:
            self.figure.set_size_inches(width/self.figure.dpi, height/self.figure.dpi, forward=False)
            self._layout_axes()
            self.canvas.draw_idle()

    def _layout_axes(self):
        if self.is_3d():
            self.axes().set_anchor('C')
            self.axes().set_position([.04, .12, .76 if len(self.figure.axes) > 1 else .92, .72])
            if len(self.figure.axes) > 1:
                right = self.axes().get_position().x1
                self.figure.axes[1].set_position([min(.9, right+.07), .22, .022, .5])

    def axes(self):
        return self.figure.axes[0] if self.figure.axes else None

    def is_3d(self):
        return getattr(self.axes(), 'name', '') == '3d'

    def _bounds(self):
        axes = self.axes()
        if axes is None:
            return None
        return (axes.get_xlim(), axes.get_ylim(), axes.get_zlim() if self.is_3d() else None)

    def _camera_from_axes(self):
        if self.is_3d():
            self.camera.elevation = self.axes().elev
            self.camera.azimuth = self.axes().azim
            self.camera.roll = self.axes().roll

    def render(self, renderer=None, arguments=None, *, reset=False, options=None):
        saved = self._bounds() if not reset else None
        self._camera_from_axes()
        if renderer is not None:
            self.renderer, self.arguments = renderer, arguments
        if options is not None:
            self.options = dict(options)
        if self.renderer is None:
            return
        self.renderer(self.figure, self.arguments, self.options)
        self.home = self._bounds()
        if saved:
            axes = self.axes()
            axes.set_xlim(saved[0]); axes.set_ylim(saved[1])
            if self.is_3d() and saved[2]:
                axes.set_zlim(saved[2])
        if reset:
            self.camera.elevation, self.camera.azimuth = PRESETS['Isometric']
            self.camera.roll = 0
        self._apply_camera()
        self._layout_axes()
        self._style()
        self._configure_interaction()
        self._draw_markers()
        self.canvas.draw_idle()

    def clear(self):
        self.figure.clear()
        self.renderer = self.arguments = self.home = None
        self.picking = []
        self.markers = []
        self.selection = self.profile = None
        self.canvas.draw_idle()

    def _apply_camera(self):
        if not self.is_3d():
            return
        axes = self.axes()
        axes.view_init(elev=self.camera.elevation, azim=self.camera.azimuth, roll=self.camera.roll)
        axes.set_proj_type(self.camera.projection)
        ranges = [abs(b-a) for a, b in (axes.get_xlim(), axes.get_ylim(), axes.get_zlim())]
        if not self.camera.physical_aspect and self.name != '3D radiation':
            ranges[2] *= 4
        axes.set_box_aspect(ranges)

    def _style(self):
        background = '#111c28' if self.dark else '#f6f8fa'
        foreground = '#dce7f0' if self.dark else '#263746'
        self.figure.set_facecolor(background)
        for axes in self.figure.axes:
            axes.set_facecolor(background)
            axes.tick_params(colors=foreground, labelsize=8)
            axes.title.set_color(foreground)
            axes.xaxis.label.set_color(foreground); axes.yaxis.label.set_color(foreground)
            for spine in axes.spines.values():
                spine.set_color('#627180')
            if getattr(axes, 'name', '') == '3d':
                axes.zaxis.label.set_color(foreground)
                for axis in (axes.xaxis, axes.yaxis, axes.zaxis):
                    axis.set_pane_color((.08, .13, .18, 1) if self.dark else (.94, .96, .97, 1))
                axes.grid(bool(self.options.get('mesh', False)))
        axes = self.axes()
        if self.is_3d():
            label = 'ORTHOGRAPHIC' if self.camera.projection == 'ortho' else 'PERSPECTIVE'
            if self.name != '3D radiation':
                label += '  ·  TRUE ASPECT' if self.camera.physical_aspect else '  ·  Z ×4 DISPLAY'
            axes.text2D(.02, .02, label, transform=axes.transAxes, color=foreground, fontsize=8)

    def set_camera(self, *, preset=None, projection=None, physical_aspect=None):
        self._camera_from_axes()
        if preset:
            self.camera.elevation, self.camera.azimuth = PRESETS[preset]
            self.camera.roll = 0
        if projection:
            self.camera.projection = projection
        if physical_aspect is not None:
            self.camera.physical_aspect = physical_aspect
        self._apply_camera()
        self.render()

    def fit(self):
        axes = self.axes()
        if axes and self.home:
            axes.set_xlim(self.home[0]); axes.set_ylim(self.home[1])
            if self.is_3d():
                axes.set_zlim(self.home[2])
                self._apply_camera()
            self.canvas.draw_idle()

    def zoom(self, scale):
        self._camera_from_axes()
        axes = self.axes()
        if axes is None:
            return
        for get, set_ in [(axes.get_xlim, axes.set_xlim), (axes.get_ylim, axes.set_ylim)] + (
                [(axes.get_zlim, axes.set_zlim)] if self.is_3d() else []):
            lo, hi = get(); center = (lo+hi)/2
            set_(center+(lo-center)*scale, center+(hi-center)*scale)
        self._apply_camera()
        self.canvas.draw_idle()

    def set_samples(self, rows):
        self.picking = rows

    def set_mode(self, mode):
        if mode not in self.mode_buttons:
            raise ValueError('Unknown viewport interaction mode: '+str(mode))
        if mode == 'Orbit' and not self.is_3d():
            mode = 'Probe'
        self.interaction = mode
        self.press = None
        self._configure_interaction()
        self.canvas.SetFocus()

    def _configure_interaction(self):
        axes = self.axes()
        if axes is None:
            return
        # Release Matplotlib's 2D navigation lock before changing modes.
        current = str(self.toolbar.mode).lower()
        if current:
            self.toolbar.pan() if 'pan' in current else self.toolbar.zoom()
        if self.is_3d():
            mappings = {'Orbit': dict(rotate_btn=1, pan_btn=2, zoom_btn=3),
                        'Pan': dict(rotate_btn=3, pan_btn=[1, 2], zoom_btn=[]),
                        'Zoom': dict(rotate_btn=3, pan_btn=2, zoom_btn=1),
                        'Probe': dict(rotate_btn=3, pan_btn=2, zoom_btn=[])}
            axes.mouse_init(**mappings[self.interaction])
        elif self.interaction == 'Pan':
            self.toolbar.pan()
        elif self.interaction == 'Zoom':
            self.toolbar.zoom()
        elif self.interaction == 'Orbit':
            self.interaction = 'Probe'
        for mode, button in self.mode_buttons.items():
            button.SetValue(mode == self.interaction)
            button.Enable(mode != 'Orbit' or self.is_3d())
        hints = {'Orbit': 'Drag to orbit · wheel zoom', 'Pan': 'Drag to pan · wheel zoom',
                 'Zoom': 'Drag to zoom · wheel zoom', 'Probe': 'Hover readout · click sample'}
        self.interaction_hint.SetLabel(hints[self.interaction])
        self.canvas.SetCursor(wx.Cursor(wx.CURSOR_CROSS if self.interaction == 'Probe' else wx.CURSOR_HAND))

    def _pick(self, event):
        if self.is_3d():
            points = [row['display_xyz'] if 'display_xyz' in row else
                      (row['x_mm'], row['y_mm'], row['z_mm']) for row in self.picking]
            index = closest_projected(points, self.axes(), event.x, event.y)
            return self.picking[index] if index is not None else None
        return None

    def _press(self, event):
        self.press = (event.x, event.y) if event.button == 1 else None
        self.canvas.SetFocus()

    def _release(self, event):
        self._camera_from_axes()
        if (self.interaction == 'Probe' and self.press and event.button == 1 and event.inaxes is self.axes() and
                not self.toolbar.mode and math.hypot(event.x-self.press[0], event.y-self.press[1]) < 4):
            self.callback(self.name, event, self._pick(event), True)
        self.press = None

    def _hover(self, event):
        if (self.press or self.toolbar.mode or event.inaxes is not self.axes() or
                time.monotonic()-self.last_hover < .08):
            return
        self.last_hover = time.monotonic()
        self.callback(self.name, event, self._pick(event), False)

    def _scroll(self, event):
        if event.inaxes is self.axes() and not self.toolbar.mode:
            self.zoom(.85 if event.button == 'up' else 1/.85)

    def _key(self, event):
        modes = {'o': 'Orbit', 'p': 'Pan', 'z': 'Zoom', 'i': 'Probe'}
        if event.key in modes:
            self.set_mode(modes[event.key])
        elif event.key in ('f', 'home'):
            self.fit()
        elif event.key in ('+', '='):
            self.zoom(.85)
        elif event.key == '-':
            self.zoom(1/.85)
        elif event.key in ('1', '2', '3', '4'):
            self.set_camera(preset=list(PRESETS)[int(event.key)-1])

    def set_selection(self, row=None, *, pins=None, profile=None):
        self.selection = row
        if pins is not None:
            self.markers = pins
        if profile is not None:
            self.profile = profile
        self._draw_markers()
        self.canvas.draw_idle()

    def _draw_markers(self):
        axes = self.axes()
        if axes is None:
            return
        for artist in list(axes.lines)+list(axes.collections)+list(axes.texts):
            if artist.get_gid() == 'inspection-marker':
                artist.remove()
        if self.name not in ('Field probes', '3D fields', '3D radiation'):
            return
        bounds = self._bounds()
        for row, color in [(row, '#41d9cb') for row in self.markers] + (
                [(self.selection, '#ff566a')] if self.selection else []):
            if self.name == '3D radiation' and row.get('kind') == 'radiation':
                x, y, z = row['display_xyz']
            elif self.name != '3D radiation' and row.get('kind') == 'field':
                x, y, z = row['x_mm'], row['y_mm'], row['z_mm']
            else:
                continue
            artist = axes.scatter([x], [y], [z], s=60, color=color, edgecolor='#102536', zorder=20) if self.is_3d() else axes.scatter([x], [y], s=60, color=color, edgecolor='#102536', zorder=20)
            artist.set_gid('inspection-marker')
        axes.set_xlim(bounds[0]); axes.set_ylim(bounds[1])
        if self.is_3d():
            axes.set_zlim(bounds[2])
        if self.profile:
            start, end = self.profile
            artist, = axes.plot([start[0], end[0]], [start[1], end[1]],
                                *([[start[2], end[2]]] if self.is_3d() else []),
                                color='#41d9cb', linewidth=2, zorder=21)
            artist.set_gid('inspection-marker')
