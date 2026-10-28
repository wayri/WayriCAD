"""Native wx workbench; the solver runs outside the GUI process."""
import json
import csv
import math
from pathlib import Path
import sys
import threading

import wx
import wx.lib.scrolledpanel
from matplotlib.figure import Figure
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg, NavigationToolbar2WxAgg

from . import plots
from .backend import atomic_json
from .model import DEFAULT_CONFIG, metrics, validate_config
from .session import StudySession
from .inspection import FieldInspection, scale_limits
from .viewport import PlotViewport, PRESETS


GROUPS = [
    ('Sweep and excitation', ['f_start_hz', 'f_stop_hz', 'points', 'z0_ohm']),
    ('Substrate • explicit material', ['substrate_x_mm', 'substrate_y_mm', 'thickness_mm', 'er']),
    ('Inset patch', ['patch_width_mm', 'patch_length_mm', 'feed_width_mm', 'inset_width_mm', 'inset_length_mm']),
    ('Internal PCB builder • line coupon', ['line_length_mm', 'line_width_mm']),
    ('Mesh, air and field samples', ['air_margin_mm', 'mesh_edge_mm', 'resolution', 'field_z_mm', 'field_grid']),
    ('Adaptivity • 0 steps disables mesh refinement', ['adaptive_steps', 'convergence', 'max_tets']),
]


class QuickEMergeFrame(wx.Frame):
    def __init__(self, board, *, auto_setup=False):
        super().__init__(None, title='WayriCAD Quick EMerge • beta', size=(1360, 900))
        self.SetMinSize((980, 650))
        self.session = StudySession(board)
        self.result = None
        self.running = False
        self.closed = False
        self.dependency_busy = False
        self.region_busy = False
        self.region_cancel = threading.Event()
        self.region_listing = None
        self.region_plan = None
        self.dependency_cancel = threading.Event()
        self.inputs = {}
        self.figures = {}
        self.viewports = {}
        self.inspection = None
        self.current_probe = None
        self.pins = []
        self.profile_rows = []
        self.line_start = None
        self.display_options = {}
        self.CreateStatusBar()
        self.SetStatusText('Review template geometry, then run. Saved PCB supplies context only.')
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label='Quick EMerge  /  electromagnetic workbench')
        font = title.GetFont(); font.SetPointSize(17); font.MakeBold(); title.SetFont(font)
        outer.Add(title, 0, wx.ALL, 12)
        source = wx.StaticText(panel, label=f'Saved PCB context: {Path(board).name}   •   templates do not import board copper')
        self.source_label = source
        outer.Add(source, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        self.workspace_splitter = splitter
        settings = wx.lib.scrolledpanel.ScrolledPanel(splitter)
        self.settings = settings
        form = wx.BoxSizer(wx.VERTICAL)
        form.Add(wx.StaticText(settings, label='1  Choose a model and review its geometry'), 0, wx.ALL, 8)
        self.mode = wx.Choice(settings, choices=['Inset-fed patch antenna', 'PCB transmission-line coupon', 'Saved PCB rule-area region'])
        self.mode.SetSelection(0)
        self.mode.Bind(wx.EVT_CHOICE, self.invalidate)
        form.Add(self.mode, 0, wx.EXPAND | wx.ALL, 8)
        region_box = wx.StaticBoxSizer(wx.VERTICAL, settings, 'PCB enclosure • saved copper / two-layer stack')
        self.load_areas_button = wx.Button(settings, label='Load saved PCB rule areas')
        self.load_areas_button.Bind(wx.EVT_BUTTON, self.load_rule_areas)
        region_box.Add(self.load_areas_button, 0, wx.EXPAND | wx.ALL, 4)
        self.rule_area = wx.Choice(settings)
        self.signal_net = wx.Choice(settings)
        self.reference_net = wx.Choice(settings)
        for label, control in [('Enclosure', self.rule_area), ('F.Cu signal net', self.signal_net), ('B.Cu reference net', self.reference_net)]:
            region_box.Add(wx.StaticText(settings, label=label), 0, wx.LEFT | wx.TOP, 4)
            region_box.Add(control, 0, wx.EXPAND | wx.ALL, 4)
            control.Bind(wx.EVT_CHOICE, self.invalidate)
        self.region_material_review = wx.CheckBox(settings, label='Review entered εr • lossless bare-copper crop')
        self.region_material_review.Bind(wx.EVT_CHECKBOX, self.invalidate)
        region_box.Add(self.region_material_review, 0, wx.ALL, 4)
        self.region_notice = wx.StaticText(settings, label='Enclosure crops physical copper; outside PCB is omitted.\nPreview shows boundary ports and any blockers.')
        region_box.Add(self.region_notice, 0, wx.ALL, 4)
        form.Add(region_box, 0, wx.EXPAND | wx.ALL, 6)
        self.solver = wx.Choice(settings, choices=['SUPERLU', 'PARDISO', 'UMFPACK', 'AASDS', 'CUDSS', 'SPARTA'])
        self.solver.SetSelection(0)
        self.solver.Bind(wx.EVT_CHOICE, self.invalidate)
        form.Add(wx.StaticText(settings, label='Solver • optional backends need their dependencies'), 0, wx.ALL, 8)
        form.Add(self.solver, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.sweep = wx.Choice(settings, choices=['Linear frequency sweep', 'Adaptive AAA sweep (points = sample budget)'])
        self.sweep.SetSelection(0)
        self.sweep.Bind(wx.EVT_CHOICE, self.invalidate)
        form.Add(self.sweep, 0, wx.EXPAND | wx.ALL, 8)
        for heading, keys in GROUPS:
            box = wx.StaticBoxSizer(wx.VERTICAL, settings, heading)
            grid = wx.FlexGridSizer(cols=2, hgap=8, vgap=6)
            grid.AddGrowableCol(1)
            for key in keys:
                label = key.replace('_mm', ' [mm]').replace('_hz', ' [Hz]').replace('_ohm', ' [Ω]').replace('_', ' ')
                grid.Add(wx.StaticText(settings, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                control = wx.TextCtrl(settings, value=str(DEFAULT_CONFIG[key]), size=(100, -1))
                self.inputs[key] = control
                control.Bind(wx.EVT_TEXT, self.invalidate)
                grid.Add(control, 1, wx.EXPAND)
            box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
            form.Add(box, 0, wx.EXPAND | wx.ALL, 6)
        form.Add(wx.StaticText(settings, label='Solver Python • managed EMerge 3+ or manual override'), 0, wx.ALL, 8)
        self.python = wx.FilePickerCtrl(settings, path=sys.executable, message='Select solver Python executable')
        form.Add(self.python, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        form.Add(wx.StaticText(settings, label='Run folders • request, result and solver log'), 0, wx.ALL, 8)
        self.output = wx.DirPickerCtrl(settings, path=str(Path(board).parent/'.quick-emerge'))
        form.Add(self.output, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in [('Load setup', self.load_setup), ('Save setup', self.save_setup)]:
            button = wx.Button(settings, label=label); button.Bind(wx.EVT_BUTTON, handler); row.Add(button, 1, wx.ALL, 4)
        form.Add(row, 0, wx.EXPAND | wx.ALL, 4)
        settings.SetSizer(form)
        settings.SetupScrolling(scroll_x=False)
        right = wx.Panel(splitter)
        self.workspace = right
        body = wx.BoxSizer(wx.VERTICAL)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(right, label='1  Preview setup')
        self.run_button = wx.Button(right, label='2  Run EMerge')
        self.cancel_button = wx.Button(right, label='Cancel run')
        self.dependencies_button = wx.Button(right, label='Set up / check updates')
        self.rollback_button = wx.Button(right, label='Restore previous runtime')
        self.run_button.Disable(); self.cancel_button.Disable()
        for button, handler in [(self.preview_button, self.preview), (self.run_button, self.run), (self.cancel_button, self.cancel)]:
            button.Bind(wx.EVT_BUTTON, handler); actions.Add(button, 0, wx.ALL, 5)
        body.Add(actions, 0, wx.EXPAND)
        dependencies = wx.BoxSizer(wx.HORIZONTAL)
        for button, handler in [(self.dependencies_button, self.setup_dependencies), (self.rollback_button, self.rollback_runtime)]:
            button.Bind(wx.EVT_BUTTON, handler); dependencies.Add(button, 0, wx.ALL, 5)
        body.Add(dependencies, 0, wx.EXPAND)
        self._build_view_controls(right, body)
        self.visual_splitter = wx.SplitterWindow(right, style=wx.SP_LIVE_UPDATE)
        self.visual_splitter.SetMinimumPaneSize(120)
        self.tabs = wx.Notebook(self.visual_splitter)
        for name in ('3D setup', 'S-parameters', 'Smith chart', 'Field probes', '3D fields', '3D radiation', 'PCB enclosure'):
            page = PlotViewport(self.tabs, name, self._viewport_probe)
            self.tabs.AddPage(page, name)
            self.viewports[name] = page
            self.figures[name] = (page.figure, page.canvas)
        self.details = wx.Notebook(self.visual_splitter)
        inspector_page = wx.Panel(self.details)
        inspector_layout = wx.BoxSizer(wx.VERTICAL)
        tools = wx.WrapSizer(wx.HORIZONTAL)
        self.mouse_mode = wx.Choice(inspector_page, choices=['Inspect samples', 'Line cut: select two field samples'])
        self.mouse_mode.SetSelection(0)
        self.mouse_mode.Bind(wx.EVT_CHOICE, self.inspection_mode_changed)
        tools.Add(self.mouse_mode, 0, wx.ALL, 3)
        self.pin_button = wx.Button(inspector_page, label='Pin sample')
        self.pin_button.Bind(wx.EVT_BUTTON, self.pin_probe)
        self.pin_button.Disable()
        tools.Add(self.pin_button, 0, wx.ALL, 3)
        for label, key in [('Field minimum', 'min'), ('Field maximum', 'max')]:
            button = wx.Button(inspector_page, label=label)
            button.Bind(wx.EVT_BUTTON, lambda event, key=key: self.field_extreme(key))
            tools.Add(button, 0, wx.ALL, 3)
        inspector_layout.Add(tools, 0, wx.EXPAND)
        self.inspector_text = wx.TextCtrl(inspector_page, style=wx.TE_MULTILINE | wx.TE_READONLY)
        inspector_layout.Add(self.inspector_text, 1, wx.EXPAND | wx.ALL, 4)
        inspector_page.SetSizer(inspector_layout)
        self.details.AddPage(inspector_page, 'Inspector')
        pins_page = wx.Panel(self.details)
        pins_layout = wx.BoxSizer(wx.VERTICAL)
        self.pins_list = wx.ListCtrl(pins_page, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate([('#', 40), ('Kind', 75), ('GHz', 100), ('Location / sample', 300), ('Value', 220)]):
            self.pins_list.InsertColumn(index, label, width=width)
        self.pins_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select_pin)
        pins_layout.Add(self.pins_list, 1, wx.EXPAND)
        pin_actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, callback in [('Export probes CSV', self.export_probes), ('Clear probes', self.clear_probes)]:
            button = wx.Button(pins_page, label=label); button.Bind(wx.EVT_BUTTON, callback)
            pin_actions.Add(button, 0, wx.ALL, 3)
        pins_layout.Add(pin_actions, 0)
        pins_page.SetSizer(pins_layout)
        self.details.AddPage(pins_page, 'Pinned probes')
        profile_page = wx.Panel(self.details)
        profile_layout = wx.BoxSizer(wx.VERTICAL)
        self.profile_figure = Figure(figsize=(8, 2), dpi=100)
        self.profile_canvas = FigureCanvasWxAgg(profile_page, wx.ID_ANY, self.profile_figure)
        self.profile_canvas.SetMinSize((1, 1))
        profile_layout.Add(self.profile_canvas, 1, wx.EXPAND)
        profile_export = wx.Button(profile_page, label='Export line samples CSV')
        profile_export.Bind(wx.EVT_BUTTON, self.export_profile)
        profile_layout.Add(profile_export, 0, wx.ALL, 3)
        profile_page.SetSizer(profile_layout)
        self.details.AddPage(profile_page, 'Line profile')
        self.log = wx.TextCtrl(self.details, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.details.AddPage(self.log, 'Console')
        self.visual_splitter.SplitHorizontally(self.tabs, self.details, 440)
        self.visual_splitter.SetSashGravity(1.)
        body.Add(self.visual_splitter, 1, wx.EXPAND)
        self.probe_label = wx.StaticText(right, label='Drag to orbit · wheel to zoom · F to fit · 1–4 camera presets · hover to inspect · click to select')
        body.Add(self.probe_label, 0, wx.EXPAND | wx.ALL, 8)
        right.SetSizer(body)
        splitter.SplitVertically(settings, right, sashPosition=365)
        splitter.SetMinimumPaneSize(280)
        outer.Add(splitter, 1, wx.EXPAND)
        panel.SetSizer(outer)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.poll, self.timer)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_CHAR_HOOK, self._shortcut)
        self.preview(None)
        if auto_setup:
            wx.CallAfter(self.setup_dependencies)

    def _build_view_controls(self, parent, layout):
        camera = wx.WrapSizer(wx.HORIZONTAL)
        self.camera_preset = wx.Choice(parent, choices=list(PRESETS)); self.camera_preset.SetSelection(0)
        self.projection = wx.Choice(parent, choices=['Orthographic', 'Perspective']); self.projection.SetSelection(0)
        self.true_aspect = wx.CheckBox(parent, label='True Z scale'); self.true_aspect.SetValue(True)
        self.sample_grid = wx.CheckBox(parent, label='Sample grid')
        self.theme = wx.Choice(parent, choices=['Light view', 'Dark view']); self.theme.SetSelection(0)
        self.focus_button = wx.ToggleButton(parent, label='Focus view [F11]')
        self.focus_button.Bind(wx.EVT_TOGGLEBUTTON, self.focus_view)
        fit = wx.Button(parent, label='Fit [F]')
        fit.Bind(wx.EVT_BUTTON, lambda event: self.viewports[self.tabs.GetPageText(self.tabs.GetSelection())].fit())
        for control in (self.camera_preset, self.projection, fit, self.true_aspect, self.sample_grid, self.theme, self.focus_button):
            camera.Add(control, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 3)
        self.camera_preset.Bind(wx.EVT_CHOICE, self.change_camera)
        self.projection.Bind(wx.EVT_CHOICE, self.change_camera)
        self.true_aspect.Bind(wx.EVT_CHECKBOX, self.change_camera)
        self.sample_grid.Bind(wx.EVT_CHECKBOX, self.refresh_views)
        self.theme.Bind(wx.EVT_CHOICE, self.refresh_views)
        layout.Add(camera, 0, wx.EXPAND)
        display = wx.WrapSizer(wx.HORIZONTAL)
        self.visibility = {}
        for key, label in [('show_context', 'Substrate'), ('copper', 'Copper'), ('ports', 'Ports'), ('field', 'Field')]:
            control = wx.CheckBox(parent, label=label); control.SetValue(True)
            control.Bind(wx.EVT_CHECKBOX, self.refresh_views)
            display.Add(control, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 3)
            self.visibility[key] = control
        self.colormap = wx.Choice(parent, choices=['inferno', 'viridis', 'cividis', 'plasma', 'turbo']); self.colormap.SetSelection(0)
        self.color_scale = wx.Choice(parent, choices=['Linear color', 'Log color']); self.color_scale.SetSelection(0)
        for control in (self.colormap, self.color_scale):
            control.Bind(wx.EVT_CHOICE, self.refresh_views); display.Add(control, 0, wx.ALL, 3)
        self.manual_range = wx.CheckBox(parent, label='Field range [V/m]')
        self.range_min = wx.TextCtrl(parent, value='0', size=(65, -1))
        self.range_max = wx.TextCtrl(parent, value='1000', size=(65, -1))
        self.range_min.SetToolTip('Minimum display value; positive for a logarithmic scale.')
        self.range_max.SetToolTip('Maximum display value. Changes colors only; source samples remain unchanged.')
        apply_range = wx.Button(parent, label='Apply scale')
        apply_range.Bind(wx.EVT_BUTTON, self.refresh_views)
        for control in (self.manual_range, self.range_min, self.range_max, apply_range):
            display.Add(control, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 3)
        layout.Add(display, 0, wx.EXPAND)
        self.display_options = dict(show_context=True, copper=True, ports=True, field=True,
                                    mesh=False, cmap='inferno', scale='linear')

    def _shortcut(self, event):
        if event.GetKeyCode() == wx.WXK_F11:
            self.focus_button.SetValue(not self.focus_button.GetValue())
            self.focus_view()
        else:
            event.Skip()

    def focus_view(self, event=None):
        if self.focus_button.GetValue():
            self.saved_sashes = (self.workspace_splitter.GetSashPosition(), self.visual_splitter.GetSashPosition())
            self.workspace_splitter.Unsplit(self.settings)
            self.visual_splitter.Unsplit(self.details)
            self.focus_button.SetLabel('Restore panels [F11]')
        else:
            self.settings.Show(); self.details.Show()
            self.workspace_splitter.SplitVertically(self.settings, self.workspace, self.saved_sashes[0])
            self.visual_splitter.SplitHorizontally(self.tabs, self.details, self.saved_sashes[1])
            self.focus_button.SetLabel('Focus view [F11]')
        self.Layout()
        for view in self.viewports.values():
            wx.CallAfter(view.refresh_canvas)

    def change_camera(self, event):
        preset = self.camera_preset.GetStringSelection() if event.GetEventObject() is self.camera_preset else None
        for view in self.viewports.values():
            view.set_camera(preset=preset, projection='ortho' if self.projection.GetSelection() == 0 else 'persp',
                            physical_aspect=self.true_aspect.GetValue())

    def inspection_mode_changed(self, event):
        self.line_start = None
        for name in ('Field probes', '3D fields'):
            self.viewports[name].set_mode('Probe')
        current = self.tabs.GetPageText(self.tabs.GetSelection())
        if self.mouse_mode.GetSelection() == 1 and current not in ('Field probes', '3D fields'):
            self.tabs.SetSelection(3)
        else:
            self.viewports[current].set_mode('Probe')

    def refresh_views(self, event=None):
        try:
            options = {key: control.GetValue() for key, control in self.visibility.items()}
            options.update(mesh=self.sample_grid.GetValue(), cmap=self.colormap.GetStringSelection(),
                           scale='linear' if self.color_scale.GetSelection() == 0 else 'log')
            if self.manual_range.GetValue():
                lo, hi = scale_limits([1.], options['scale'], self.range_min.GetValue(), self.range_max.GetValue())
                options.update(minimum=lo, maximum=hi)
            self.display_options = options
            for name, view in self.viewports.items():
                view.dark = self.theme.GetSelection() == 1
                local = dict(options)
                if name == '3D radiation':
                    local.pop('minimum', None); local.pop('maximum', None)
                view.render(options=local)
        except Exception as exc:
            self.message(exc)

    def clear_inspection(self):
        self.inspection = None
        self.current_probe = None
        self.pins = []
        self.line_start = None
        self.profile_rows = []
        self.pins_list.DeleteAllItems()
        self.pin_button.Disable()
        self.inspector_text.ChangeValue('Hover a solved field, network curve or radiation surface. Click to select a sample.\nThe originating PCB is context only; model geometry is a template.')
        self.profile_figure.clear(); self.profile_canvas.draw_idle()

    def install_result(self, result):
        self.clear_inspection()
        self.result = result
        self.inspection = FieldInspection(result['field'])
        if result['config']['mode'] == 'pcb_region':
            from . import region_view
            self.region_plan = result['region']
            self.viewports['3D setup'].render(region_view.geometry, result['region'], reset=True, options=self.display_options)
            self.viewports['PCB enclosure'].render(region_view.enclosure, result['region'], reset=True, options=self.display_options)
            self.source_label.SetLabel(f'Saved PCB source: {self.session.board.name} • solved rule-area copper crop')
        renderers = {'S-parameters': lambda figure, data, options: plots.response(figure, data),
                     'Smith chart': lambda figure, data, options: plots.smith(figure, data),
                     'Field probes': plots.near_field, '3D fields': plots.near_field3d,
                     '3D radiation': plots.radiation}
        for name, renderer in renderers.items():
            view = self.viewports[name]
            options = dict(self.display_options)
            if name == '3D radiation':
                options.pop('minimum', None); options.pop('maximum', None)
            view.render(renderer, result, reset=True, options=options)
        field = self.inspection
        rows = [dict(field.probe(x, y), kind='field') for y in field.y for x in field.x]
        self.viewports['3D fields'].set_samples(rows)
        if result.get('radiation'):
            radiation = result['radiation']
            peak = max(max(row) for row in radiation['norm_e'])
            rows = []
            for i, theta in enumerate(radiation['theta_rad']):
                for j, phi in enumerate(radiation['phi_rad']):
                    radius = radiation['norm_e'][i][j]/peak
                    rows.append(dict(kind='radiation', frequency_hz=radiation['frequency_hz'],
                                     theta_deg=math.degrees(theta), phi_deg=math.degrees(phi), relative_e=radius,
                                     display_xyz=(radius*math.sin(theta)*math.cos(phi), radius*math.sin(theta)*math.sin(phi), radius*math.cos(theta))))
            self.viewports['3D radiation'].set_samples(rows)
        scope = 'Actual saved two-layer rule-area copper crop; external board/components omitted.' if result['config']['mode'] == 'pcb_region' else 'Template geometry; saved PCB is context only.'
        self.inspector_text.ChangeValue(f'{len(field.x)} × {len(field.y)} original field samples at {field.frequency/1e9:g} GHz, Z={field.z:g} mm.\n{scope}\nHover for readouts; click selects the same sample in 2D and 3D. Line cuts use nearest original samples; no interpolation.\n3D picking chooses a projected sample within 14 pixels, not an arbitrary volume intersection.')
        self.probe_label.SetLabel('Solved samples ready • choose Probe to inspect fields or radiation; drag in Orbit/Pan/Zoom to navigate.')

    def _viewport_probe(self, name, event, sample=None, selected=False):
        if self.result is None or event.inaxes is None:
            return
        try:
            if name in ('Field probes', '3D fields'):
                if not self.visibility['field'].GetValue():
                    return
                if name == 'Field probes':
                    sample = dict(self.inspection.probe(event.xdata, event.ydata), kind='field')
                if sample is None:
                    return
                value = 'unknown' if sample['value_v_m'] is None else f'{sample["value_v_m"]:.7g} V/m'
                text = f'Original sample [{sample["ix"]}, {sample["iy"]}] • {sample["frequency_hz"]/1e9:g} GHz\nX={sample["x_mm"]:g} mm  Y={sample["y_mm"]:g} mm  Z={sample["z_mm"]:g} mm  |E|={value}'
            elif name == '3D radiation':
                if sample is None or not self.visibility['field'].GetValue():
                    return
                text = f'Radiation sample • {sample["frequency_hz"]/1e9:g} GHz\nθ={sample["theta_deg"]:.5g}°  φ={sample["phi_deg"]:.5g}°  relative |E|={sample["relative_e"]:.7g}\nNormalized radius; not gain or physical distance.'
            elif name in ('S-parameters', 'Smith chart'):
                f = self.result['frequencies_hz']
                s = [complex(*pair) for pair in self.result['s_parameters']['S11']]
                index = min(range(len(f)), key=(lambda i: abs(f[i]/1e9-event.xdata)) if name == 'S-parameters'
                            else lambda i: abs(s[i]-complex(event.xdata, event.ydata)))
                values = metrics(f, s, self.result['config']['z0_ohm'])
                sample = dict(kind='network', frequency_hz=f[index], s11_db=values['s11_db'][index],
                              return_loss_db=values['return_loss_db'][index], vswr=values['vswr'][index],
                              impedance_real_ohm=values['impedance_real_ohm'][index], impedance_imag_ohm=values['impedance_imag_ohm'][index])
                text = f'{f[index]/1e9:.7g} GHz • S11={sample["s11_db"]:.6g} dB • return loss={sample["return_loss_db"]:.6g} dB\nVSWR={sample["vswr"]}  Z={sample["impedance_real_ohm"]}+j{sample["impedance_imag_ohm"]} Ω\nField views stay at their recorded solved frequency.'
            else:
                return
            status = text.split('\n')[0]
            if sample['kind'] == 'field':
                status = f'X {sample["x_mm"]:g}, Y {sample["y_mm"]:g}, Z {sample["z_mm"]:g} mm • |E| {value} • {sample["frequency_hz"]/1e9:g} GHz'
            elif sample['kind'] == 'radiation':
                status = f'θ {sample["theta_deg"]:.5g}°, φ {sample["phi_deg"]:.5g}° • relative |E| {sample["relative_e"]:.6g}'
            self.probe_label.SetLabel(('Selected: ' if selected else 'Hover: ')+status)
            if selected:
                self.current_probe = sample
                self.pin_button.Enable()
                self.inspector_text.ChangeValue(text)
                for field_view in ('Field probes', '3D fields', '3D radiation'):
                    self.viewports[field_view].set_selection(sample, pins=self.pins)
                if sample['kind'] == 'field' and self.mouse_mode.GetSelection() == 1:
                    self.line_sample(sample)
            elif self.current_probe is None:
                self.inspector_text.ChangeValue(text)
        except (ValueError, TypeError):
            return

    def field_extreme(self, key):
        if self.inspection:
            sample = self.inspection.extrema()[key]
            if sample:
                event = type('SampleEvent', (), dict(inaxes=True, xdata=sample['x_mm'], ydata=sample['y_mm']))()
                self._viewport_probe('Field probes', event, selected=True)

    def pin_probe(self, event):
        if self.current_probe is None:
            return
        row = dict(self.current_probe)
        row['id'] = len(self.pins)+1
        self.pins.append(row)
        index = self.pins_list.InsertItem(self.pins_list.GetItemCount(), str(row['id']))
        self.pins_list.SetItem(index, 1, row['kind'])
        self.pins_list.SetItem(index, 2, f'{row["frequency_hz"]/1e9:.7g}')
        location = f'({row["x_mm"]:g}, {row["y_mm"]:g}, {row["z_mm"]:g}) mm' if row['kind'] == 'field' else (
            f'θ={row["theta_deg"]:g}°, φ={row["phi_deg"]:g}°' if row['kind'] == 'radiation' else 'S11 / input impedance')
        value = ('unknown' if row['value_v_m'] is None else f'{row["value_v_m"]:.7g} V/m') if row['kind'] == 'field' else (
            f'{row["relative_e"]:.7g} relative |E|' if row['kind'] == 'radiation' else f'{row["s11_db"]:.6g} dB')
        self.pins_list.SetItem(index, 3, location); self.pins_list.SetItem(index, 4, value)
        for name in ('Field probes', '3D fields', '3D radiation'):
            self.viewports[name].set_selection(self.current_probe, pins=self.pins)

    def select_pin(self, event):
        row = self.pins[event.GetIndex()]
        self.current_probe = row
        self.inspector_text.ChangeValue('\n'.join(f'{key}: {value}' for key, value in row.items() if key != 'display_xyz'))
        for name in ('Field probes', '3D fields', '3D radiation'):
            self.viewports[name].set_selection(row, pins=self.pins)

    def clear_probes(self, event=None):
        self.pins = []
        self.pins_list.DeleteAllItems()
        for name in ('Field probes', '3D fields', '3D radiation'):
            self.viewports[name].set_selection(self.current_probe, pins=[])

    def line_sample(self, row):
        point = (row['x_mm'], row['y_mm'])
        if self.line_start is None:
            self.line_start = point
            self.probe_label.SetLabel('Line cut: select the second field sample.')
            return
        self.profile_rows = self.inspection.line(self.line_start, point, count=200)
        self.profile_figure.clear()
        axes = self.profile_figure.add_subplot(111)
        axes.plot([p['distance_mm'] for p in self.profile_rows], [p['value_v_m'] for p in self.profile_rows], color='#147e88')
        axes.set(xlabel='Distance along selected line [mm]', ylabel='|E| [V/m]', title=f'Nearest original samples • {row["frequency_hz"]/1e9:g} GHz; no interpolation')
        axes.grid(alpha=.25)
        self.profile_figure.subplots_adjust(left=.09, right=.98, bottom=.32, top=.78)
        self.profile_canvas.draw_idle()
        for name in ('Field probes', '3D fields'):
            self.viewports[name].set_selection(row, pins=self.pins, profile=(self.line_start+(row['z_mm'],), point+(row['z_mm'],)))
        self.line_start = None
        self.details.SetSelection(2)

    def _export_rows(self, rows, title):
        if not rows:
            self.message('There are no samples to export.')
            return
        with wx.FileDialog(self, title, wildcard='CSV samples (*.csv)|*.csv', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
            if path.suffix.lower() != '.csv':
                self.message('Choose a .csv filename for sample export.')
                return
            provenance = dict(config_sha256=self.result.get('config_sha256', ''),
                              context_source_sha256=self.result.get('source', {}).get('sha256', ''),
                              model_scope=self.result.get('model_scope', 'parametric-template')) if self.result else {}
            rows = [dict(row, **provenance) for row in rows]
            keys = [key for row in rows for key in row if key != 'display_xyz']
            with path.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, list(dict.fromkeys(keys)), extrasaction='ignore')
                writer.writeheader(); writer.writerows(rows)

    def export_probes(self, event):
        self._export_rows(self.pins, 'Export pinned original samples')

    def export_profile(self, event):
        self._export_rows(self.profile_rows, 'Export nearest-sample line cut')

    def setup_dependencies(self, event=None):
        self._dependency_task(force=event is not None)

    def load_rule_areas(self, event=None):
        self._region_task()

    def _region_task(self, area=None, *, config=None):
        if self.running or self.dependency_busy or self.region_busy or self.closed:
            self.SetStatusText('Finish the current operation before extracting a rule area.')
            return
        from .region_service import extract_region
        self.region_busy = True
        self.region_cancel.clear()
        self.running_state(False)
        self.details.SetSelection(3)
        def progress(text):
            wx.CallAfter(self._dependency_progress, text)
        def work():
            try:
                result = extract_region(self.session.board, area, cancel=self.region_cancel, progress=progress)
                if config is not None:
                    from .region_backend import check_complexity
                    from .region_ports import plan_region
                    check_complexity(result)
                    result['prepared_plan'] = plan_region(result, config['signal_net'], config['reference_net'])
                wx.CallAfter(self._region_done, result, config, None)
            except Exception as exc:
                wx.CallAfter(self._region_done, None, config, str(exc))
        threading.Thread(target=work, name='QuickEMergeNativeRegion').start()

    def _region_done(self, data, config, error):
        if self.closed:
            return
        self.region_busy = False
        try:
            if error:
                raise ValueError(error)
            from .model import source_identity
            if data['source'] != source_identity(self.session.board):
                raise ValueError('Saved PCB changed during extraction; reload rule areas.')
            if config is None:
                self.region_listing = data
                self.rule_area.Clear()
                for area in data['areas']:
                    self.rule_area.Append(f'{area["name"] or "Unnamed area"} [{area["id"][:8]}]')
                if data['areas']:
                    self.rule_area.SetSelection(0)
                nets = [net for net in data['copper_net_names'] if net]
                for control in (self.signal_net, self.reference_net):
                    control.Set(nets)
                    control.SetSelection(wx.NOT_FOUND)
                if 'SIGNAL' in nets:
                    self.signal_net.SetStringSelection('SIGNAL')
                if 'GND' in nets:
                    self.reference_net.SetStringSelection('GND')
                pending = getattr(self, '_pending_region_setup', None)
                if pending:
                    wanted = next((i for i, area in enumerate(data['areas']) if area['id'] == pending['rule_area_id']), wx.NOT_FOUND)
                    self.rule_area.SetSelection(wanted)
                    self.signal_net.SetStringSelection(pending['signal_net'])
                    self.reference_net.SetStringSelection(pending['reference_net'])
                    self._pending_region_setup = None
                self.mode.SetSelection(2)
                self.invalidate()
                self.region_notice.SetLabel(f'{len(data["areas"])} saved rule areas. Choose nets, review εr, then Preview setup.')
                self.SetStatusText('Rule areas loaded from the saved PCB; unsaved editor changes are excluded.')
                self.log.ChangeValue(self.region_notice.GetLabel())
                return
            from . import region_view
            plan = data['prepared_plan']
            for key in ('board_outline', 'curve_tolerance_mm', 'kicad_version', 'unsupported'):
                if key in data:
                    plan[key] = data[key]
            self.region_plan = plan
            # These entries are read-only source dimensions in region mode.
            points = [point for shape in plan['substrate']['outline'] for point in shape['outer_mm']]
            native_values = dict(thickness_mm=plan['substrate']['thickness_mm'],
                                 substrate_x_mm=max(p[0] for p in points)-min(p[0] for p in points),
                                 substrate_y_mm=max(p[1] for p in points)-min(p[1] for p in points))
            for key, value in native_values.items():
                config[key] = value
                self.inputs[key].ChangeValue(str(value))
            self.result = None
            self.clear_inspection()
            for view in self.viewports.values():
                view.clear()
            self.viewports['3D setup'].render(region_view.geometry, plan, reset=True, options=self.display_options)
            self.viewports['PCB enclosure'].render(region_view.enclosure, plan, reset=True, options=self.display_options)
            issues = list(plan['blockers'])+list(data.get('diagnostics', []))
            notes = [f'Rule area: {plan["area"].get("name") or plan["area"]["id"]}',
                     f'{len(plan["copper"])} copper/net groups • {len(plan["ports"])} ideal boundary ports',
                     f'Saved dielectric separation: {plan["substrate"]["thickness_mm"]:g} mm • entered εr={config["er"]:g}',
                     'Bare two-layer copper crop. External PCB and components omitted.']
            notes.extend('BLOCK: '+issue for issue in plan['blockers'])
            notes.extend(data.get('diagnostics', []))
            self.inspector_text.ChangeValue('\n'.join(notes))
            self.details.SetSelection(0)
            self.tabs.SetSelection(6)
            self.source_label.SetLabel(f'Saved PCB source: {self.session.board.name} • rule-area copper crop, two-layer stack')
            self.region_notice.SetLabel(f'{len(plan["ports"])} ports • {len(plan["blockers"])} blocking issues; see Inspector.')
            self.probe_label.SetLabel(f'Rule-area preview • {len(plan["ports"])} boundary ports • {len(plan["blockers"])} blocking issues')
            if not plan['blockers']:
                self.session.preview(config, region=plan)
                self.SetStatusText('Region geometry and boundary ports ready for review • saved copper only')
            else:
                self.session.review = None
                self.SetStatusText('Region preview only • resolve blocking issues before simulation')
        except Exception as exc:
            self.session.review = None
            self.log.ChangeValue(str(exc))
            self.SetStatusText(str(exc))
        finally:
            self.running_state(False)

    def rollback_runtime(self, event):
        self._dependency_task(rollback=True)

    def _dependency_task(self, *, force=False, rollback=False):
        if self.running or self.dependency_busy or self.region_busy or self.closed:
            return
        from .dependencies import DependencyManager
        self.dependency_busy = True
        self.dependency_cancel.clear()
        self.running_state(False)
        self.SetStatusText('Preparing solver dependencies…')
        self.details.SetSelection(3)
        self.log.ChangeValue('Dependency setup: the active environment stays available if an update fails.\n')
        def progress(text):
            wx.CallAfter(self._dependency_progress, text)
        def work():
            try:
                manager = DependencyManager()
                result = manager.rollback() if rollback else manager.ensure(
                    force=force, cancel=self.dependency_cancel, progress=progress)
                wx.CallAfter(self._dependency_done, result, None)
            except Exception as exc:
                wx.CallAfter(self._dependency_done, None, str(exc))
        # Non-daemon ensures cancellation can reap pip/solver workers after close.
        self.dependency_thread = threading.Thread(target=work, name='QuickEMergeDependencies')
        self.dependency_thread.start()

    def _dependency_progress(self, text):
        if not self.closed:
            self.log.ChangeValue(str(text)[-8000:])

    def _dependency_done(self, result, error):
        if self.closed:
            return
        self.dependency_busy = False
        if result:
            self.python.SetPath(result['python'])
            self.log.ChangeValue(result['message'])
            self.SetStatusText(f'EMerge {result["version"]} ready • {result["message"]}')
        else:
            self.log.ChangeValue(error)
            self.SetStatusText('Dependency setup incomplete • retry setup or select a solver Python')
        self.running_state(False)

    def config(self):
        raw = {k: ctrl.GetValue() for k, ctrl in self.inputs.items()}
        raw['mode'] = ('patch', 'pcb_line', 'pcb_region')[self.mode.GetSelection()]
        if raw['mode'] == 'pcb_region':
            index = self.rule_area.GetSelection()
            raw['rule_area_id'] = self.region_listing['areas'][index]['id'] if self.region_listing and index >= 0 else ''
            raw['signal_net'] = self.signal_net.GetStringSelection()
            raw['reference_net'] = self.reference_net.GetStringSelection()
            raw['region_er_reviewed'] = self.region_material_review.GetValue()
        raw['solver'] = self.solver.GetStringSelection()
        raw['sweep'] = 'linear' if self.sweep.GetSelection() == 0 else 'adaptive'
        return validate_config(raw)

    def message(self, error):
        self.SetStatusText(str(error))
        wx.MessageBox(str(error), 'Quick EMerge', wx.OK | wx.ICON_INFORMATION, parent=self)

    def invalidate(self, event=None):
        self.session.review = None
        self.result = None
        self.region_plan = None
        is_region = self.mode.GetSelection() == 2
        for key, control in self.inputs.items():
            if key.startswith(('patch_', 'inset_', 'feed_', 'line_', 'substrate_')) or key == 'thickness_mm':
                control.Enable(not is_region)
        self.run_button.Disable()
        self.probe_label.SetLabel('Setup changed. Preview again; previous plots are cleared.')
        self.clear_inspection()
        for view in self.viewports.values():
            view.clear()
        self.SetStatusText('Setup changed • preview required')
        if event:
            event.Skip()

    def preview(self, event):
        try:
            config = self.config()
            if config['mode'] == 'pcb_region':
                self._region_task(config['rule_area_id'], config=config)
                return
            self.session.preview(config)
            self.source_label.SetLabel(f'Saved PCB context: {self.session.board.name} • templates do not import board copper')
            self.result = None
            self.clear_inspection()
            for name, view in self.viewports.items():
                view.clear()
                if name == '3D setup':
                    view.render(plots.geometry, config, reset=True, options=self.display_options)
            self.run_button.Enable()
            self.tabs.SetSelection(0)
            self.SetStatusText('Preview ready • PEC, lossless dielectric, absorbing boundary • template only')
        except Exception as exc:
            self.message(exc)

    def running_state(self, running):
        self.running = running
        busy = running or self.dependency_busy or self.region_busy
        self.settings.Enable(not busy)
        self.preview_button.Enable(not busy)
        self.run_button.Enable(not busy and self.session.review is not None)
        self.cancel_button.Enable(busy)
        self.cancel_button.SetLabel('Cancel setup' if self.dependency_busy else 'Cancel extraction' if self.region_busy else 'Cancel run')
        self.dependencies_button.Enable(not busy)
        self.rollback_button.Enable(not busy)

    def run(self, event):
        try:
            self.session.start(self.config(), self.python.GetPath(), self.output.GetPath())
            self.result = None
            self.clear_inspection()
            for name, view in self.viewports.items():
                if name != '3D setup':
                    view.clear()
            self.running_state(True)
            self.log.SetValue(f'Run: {self.session.run_dir}\n')
            self.details.SetSelection(3)
            self.SetStatusText('EMerge worker started • Cancel stops this run')
            self.timer.Start(500)
        except Exception as exc:
            self.message(exc)

    def poll(self, event):
        try:
            self.log.ChangeValue(self.session.log_tail())
            if self.session.process.poll() is None:
                return
            self.timer.Stop()
            result = self.session.collect()
            self.install_result(result)
            self.tabs.SetSelection(1)
            self.details.SetSelection(0)
            self.SetStatusText(f'Completed • unqualified mesh • {self.session.run_dir.name}')
        except Exception as exc:
            self.timer.Stop()
            self.result = None
            self.message(f'{exc}\nRun evidence: {self.session.run_dir}')
        finally:
            if not self.timer.IsRunning():
                self.running_state(False)

    def cancel(self, event):
        if self.region_busy:
            self.region_cancel.set()
            self.SetStatusText('Cancelling native region extraction…')
            return
        if self.dependency_busy:
            self.dependency_cancel.set()
            self.SetStatusText('Cancelling dependency setup…')
            return
        self.timer.Stop()
        self.session.cancel()
        self.running_state(False)
        self.SetStatusText('Run cancelled • request and diagnostic log retained')

    def probe(self, name, event):
        self._viewport_probe(name, event, selected=True)

    def save_setup(self, event):
        try:
            config = self.config()
            with wx.FileDialog(self, 'Save setup', wildcard='JSON setup (*.json)|*.json', style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    path = Path(dialog.GetPath())
                    if path.suffix.lower() != '.json':
                        raise ValueError('Save setup using a .json filename.')
                    atomic_json(path, {'schema': 1, 'config': config})
        except Exception as exc:
            self.message(exc)

    def load_setup(self, event):
        try:
            with wx.FileDialog(self, 'Load setup', wildcard='JSON setup (*.json)|*.json', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                payload = json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8'))
                if payload.get('schema') != 1:
                    raise ValueError('Unsupported setup schema.')
                config = validate_config(payload['config'])
                self.mode.SetSelection(('patch', 'pcb_line', 'pcb_region').index(config['mode']))
                self.region_material_review.SetValue(config['region_er_reviewed'])
                self.solver.SetStringSelection(config['solver'])
                self.sweep.SetSelection(0 if config['sweep'] == 'linear' else 1)
                for key, control in self.inputs.items():
                    control.ChangeValue(str(config[key]))
                self.invalidate()
                if config['mode'] == 'pcb_region':
                    self._pending_region_setup = config
                    self.load_rule_areas()
                else:
                    self.preview(None)
        except Exception as exc:
            self.message(exc)

    def close(self, event):
        self.region_cancel.set()
        self.dependency_cancel.set()
        self.timer.Stop()
        self.session.cancel()
        self.closed = True
        self.Destroy()
