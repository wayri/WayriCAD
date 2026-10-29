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
        super().__init__(None, title='Quick EMerge', size=(1400, 900))
        self.SetIcon(wx.Icon(str(Path(__file__).with_name('icon.png')), wx.BITMAP_TYPE_PNG))
        self.SetMinSize((980, 650))
        self.session = StudySession(board)
        self.result = None
        self.running = False
        self.closed = False
        self.dependency_busy = False
        self._solver_explicit = False
        self._solver_probe_generation = 0
        self.solver_probe_busy = False
        self.solver_probe_python = None
        self.solver_probe_available = None
        self.solver_environment = {}
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
        from .workbench_layout import build
        build(self, board)
        self.solver.Unbind(wx.EVT_CHOICE)
        self.solver.Bind(wx.EVT_CHOICE, self._solver_selected)
        self.python.Bind(wx.EVT_FILEPICKER_CHANGED, self.probe_solver_runtime)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.poll, self.timer)
        self.Bind(wx.EVT_CLOSE, self.close)
        self.Bind(wx.EVT_CHAR_HOOK, self._shortcut)
        if auto_setup:
            self.mode.SetSelection(2)
            self.invalidate()
            self.SetStatusText('Reading saved PCB outlines and rule areas...')
            wx.CallAfter(self.load_rule_areas)
            wx.CallAfter(self.setup_dependencies)
        else:
            self.preview(None)

    def build_advanced_fields(self):
        from .advanced import ADVANCED_FIELDS
        from .workbench_layout import section
        self.study_ids = next(field['choices'] for field in ADVANCED_FIELDS if field['key']=='study')
        labels={'driven':'Driven EM','periodic':'Periodic / Floquet','scattering':'Scattering / RCS','thermal':'Thermal','optimization':'Parameter optimization'}
        self.study.Set([labels.get(name,name.replace('_',' ').title()) for name in self.study_ids])
        self.study.SetSelection(0)
        for field in ADVANCED_FIELDS:
            key = field['key']
            if key in ('study', 'step_sha256', 'import_sha256'):
                continue
            group = field.get('group', 'Physics')
            if group not in self.advanced_groups:
                self.advanced_groups[group] = section(self.advanced_parent, self.advanced_layout, group, collapsed=True)
            pane, parent, layout = self.advanced_groups[group]
            row = wx.Panel(parent); row_layout = wx.BoxSizer(wx.VERTICAL)
            label = field['label'] + (f" [{field['unit']}]" if field.get('unit') else '')
            caption = wx.StaticText(row, label=label); caption.Wrap(270)
            row_layout.Add(caption, 0, wx.TOP | wx.BOTTOM, 3)
            if field['kind'] in ('bool', 'boolean'):
                control = wx.CheckBox(row, label='Enabled'); control.SetValue(bool(field['default']))
                control.Bind(wx.EVT_CHECKBOX, self.invalidate)
            elif field['kind'] == 'choice':
                control = wx.Choice(row, choices=field['choices']); control.SetStringSelection(str(field['default']))
                control.Bind(wx.EVT_CHOICE, self.invalidate)
            elif key == 'import_path':
                from .workbench_layout import SourcePicker
                control = SourcePicker(row, self.invalidate)
            elif field['kind'] == 'path':
                control = wx.FilePickerCtrl(row, path=str(field['default']), message=label)
                control.Bind(wx.EVT_FILEPICKER_CHANGED, self.invalidate)
            else:
                control = wx.TextCtrl(row, value=str(field['default']))
                control.Bind(wx.EVT_TEXT, self.invalidate)
            row_layout.Add(control, 0, wx.EXPAND); row.SetSizer(row_layout)
            layout.Add(row, 0, wx.EXPAND | wx.ALL, 5)
            self.advanced_inputs[key] = control; self.advanced_rows[key] = (row, field, group)

    def update_model_sections(self):
        if 'convergence' in self.inputs:
            self.inputs['convergence'].Enable(self.sweep.GetSelection() == 1)
        if not hasattr(self, 'model_sections'):
            return
        mode = self.mode.GetSelection()
        visible = {'region': mode == 2, 'substrate': mode != 2, 'patch': mode == 0, 'line': mode == 1}
        for name, panel in self.model_sections.items():
            panel.Show(visible[name])
        study = self.study_ids[max(0, self.study.GetSelection())]
        groups = {}
        for key, (row, field, group) in self.advanced_rows.items():
            show = not field.get('studies') or study in field['studies']
            row.Show(show); groups[group] = groups.get(group, False) or show
        for group, (pane, _, _) in self.advanced_groups.items():
            pane.Show(groups[group])
        for page in [self.setup_book.GetPage(i) for i in range(self.setup_book.GetPageCount())]:
            page.Layout(); page.FitInside()

    def navigate(self, group):
        self.current_group = group
        if hasattr(self, 'chart_quantity'): self.chart_quantity.Show(group == 'Charts')
        if hasattr(self,'network_tools_button'):
            self.network_tools_button.Show(group=='Charts');self.network_export_button.Show(group=='Charts')
        for name, control in self.navigation.items():
            control.SetValue(name == group)
        if group in ('Results', 'Report'):
            self.workspace_stack.SetSelection(1 if group == 'Results' else 2)
            return
        mapping = {'3D': ['3D setup', '3D fields', '3D radiation'],
                   '2D': ['PCB enclosure', 'Field probes'],
                   'Charts': ['S-parameters', 'Smith chart']}
        self.workspace_stack.SetSelection(0)
        names = mapping[group]
        if group == '3D':
            names = ['3D setup']
            if self.result and ('field' in self.result or 'thermal' in self.result): names.append('3D fields')
            if self.result and 'radiation' in self.result: names.append('3D radiation')
        previous = self.tabs.GetPageText(self.tabs.GetSelection()) if self.tabs.GetSelection() >= 0 else ''
        self.view_choice.Set(names); self.view_choice.SetSelection(names.index(previous) if previous in names else 0)
        self.choose_view()

    def choose_view(self, event=None):
        name = self.view_choice.GetStringSelection()
        if not name:
            return
        index = next(i for i in range(self.tabs.GetPageCount()) if self.tabs.GetPageText(i) == name)
        self.tabs.SetSelection(index)
        self.viewports[name].Layout()
        wx.CallAfter(self.viewports[name].refresh_canvas)

    def change_chart_quantity(self, event=None):
        self.display_options['network_quantity']=self.chart_quantity.GetStringSelection()
        self.select_view('S-parameters')
        if self.result and self.result.get('s_parameters'):
            self.viewports['S-parameters'].render(plots.response,getattr(self,'network_chart_result',None) or self.result,options=self.display_options)

    def select_view(self, name):
        group = '3D' if name.startswith('3D') else '2D' if name in ('PCB enclosure', 'Field probes') else 'Charts'
        self.navigate(group)
        self.view_choice.SetStringSelection(name); self.choose_view()

    def toggle_inspector(self, event=None, *, show=None):
        current = self.visual_splitter.IsSplit()
        show = not current if show is None else show
        if show and not current:
            self.details.Show()
            self.visual_splitter.SplitHorizontally(self.tabs, self.details, max(200, self.visual_splitter.GetClientSize().height - 200))
            self.visual_splitter.SetSashGravity(1.)
        elif not show and current:
            self.visual_splitter.Unsplit(self.details)
        self.workspace.Layout()

    def show_view_options(self, event=None):
        self.view_options.Show(); self.view_options.Raise()

    def network_tools(self, event=None):
        if not self.result or not self.result.get('s_parameters'):
            self.message('Complete a network simulation before using network tools.'); return
        if getattr(self,'network_busy',False): return
        source=self.session.run_dir/'result.json' if self.session.run_dir else None
        if source is None or not source.is_file():
            self.message('Network tools need a saved solver result from this study.'); return
        from .network_tools import NetworkToolsDialog
        try:
            with NetworkToolsDialog(self,self.result) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                operation=dialog.normalized_operation()
            import hashlib,uuid
            from .model import config_digest
            self.network_signature=config_digest(self.config())
            folder=self.session.run_dir/('network-'+uuid.uuid4().hex);folder.mkdir()
            request={'schema':1,'source_result_path':str(source),'source_result_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                     'operation':operation,'output_path':str(folder/'derived.json')}
            atomic_json(folder/'request.json',request)
            self.network_busy=True;self.running_state(False);self.SetStatusText('Processing derived network; original fields remain unchanged...')
            self.network_process=None
            def work():
                import subprocess
                try:
                    with (folder/'worker.log').open('wb') as log:
                        process=subprocess.Popen([self.python.GetPath(),'-I',str(Path(__file__).with_name('network_worker.py')),str(folder/'request.json')],
                            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        self.network_process=process
                        try:status=process.wait(timeout=180)
                        except subprocess.TimeoutExpired:
                            process.kill();process.wait(timeout=5);raise RuntimeError('Network operation timed out. Inspect worker.log.')
                    if status:raise RuntimeError((folder/'worker.log').read_text(encoding='utf-8',errors='replace')[-3000:])
                    output=json.loads((folder/'derived.json').read_text(encoding='utf-8'))
                    wx.CallAfter(self._network_ready,output,None)
                except Exception as exc:wx.CallAfter(self._network_ready,None,str(exc))
            threading.Thread(target=work,name='QuickEMergeNetwork',daemon=True).start()
        except Exception as exc:self.message(exc)

    def _network_ready(self, output, error):
        if self.closed:return
        self.network_busy=False;self.network_process=None;self.running_state(False)
        if error:self.message(error);return
        from .model import config_digest
        if self.result is None or config_digest(self.config())!=self.network_signature:
            self.message('Setup changed; derived network was not attached to the current view.');return
        self.network_output=output
        raw=output['derived_network']
        chart=dict(self.result,frequencies_hz=raw['frequencies_hz'],port_count=raw['port_count'],port_names=raw['port_names'],
                   reference_impedance_ohm=raw['reference_impedance_ohm'],s_parameters=raw['s_parameters'],network_view_label='Derived network: '+output['operation']['kind'])
        self.network_chart_result=chart
        self.viewports['S-parameters'].render(plots.response,chart,reset=True,options=self.display_options)
        self.viewports['Smith chart'].render(lambda fig,data,opts:plots.smith(fig,data),chart,reset=True,options=self.display_options)
        from .reporting import fit_validation_notice
        notice = fit_validation_notice(output.get('fit'))
        self.select_view('S-parameters');self.SetStatusText(notice or 'Derived network shown; original solved fields are unchanged. Reports retain both datasets.')

    def export_network(self,event=None):
        if not self.result or not self.result.get('s_parameters'):
            self.message('Complete a network simulation before exporting.');return
        try:
            from .network import from_result
            from .network_extensions import deserialize_network,export_touchstone
            output=getattr(self,'network_output',None)
            network=deserialize_network(output['derived_network']) if output else from_result(self.result)
            with wx.FileDialog(self,'Export current network',wildcard=f'Touchstone (*.s{network.port_count}p)|*.s{network.port_count}p',style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                paths=export_touchstone(Path(dialog.GetPath()),network)
                self.SetStatusText('Network and provenance exported: '+str(paths))
        except Exception as exc:self.message(exc)

    def refresh_results(self):
        self.result_table.DeleteAllItems()
        result = self.result
        if not result:
            self.result_summary.SetLabel('Run a study to see its results.')
            return
        backend = result.get('backend', 'EMerge')
        if isinstance(backend, dict):
            backend = ' '.join(str(backend[key]) for key in ('backend', 'version') if backend.get(key)) or 'Unknown'
        rows = [('Model', result.get('model_scope', 'Unknown'), ''),
                ('Backend', backend, ''),
                ('Numerical status', 'Mesh not convergence-qualified', ''),
                ('Port count', result.get('port_count', 0), ''),
                ('Frequency samples', len(result.get('frequencies_hz', [])), '')]
        if result.get('s_parameters'):
            from .network import from_result
            analysis = from_result(result).analyze()
            rows.extend([('Sampled passive', analysis['sampled_passive'], 'Not a broadband certificate'),('Sampled reciprocal', analysis['sampled_reciprocal'], 'Port-reference dependent'),('Maximum singular value',float(max(analysis['largest_singular_value'])), 'Unitless'),('Reciprocity error',float(max(analysis['reciprocity_error'])), 'Unitless')])
            values = metrics(result['frequencies_hz'], [complex(*v) for v in result['s_parameters']['S11']], result['config']['z0_ohm'])
            rows.append(('Minimum sampled reflection', f"{values['resonance_hz']/1e9:.8g}", 'GHz; sampled minimum'))
        thermal = result.get('thermal')
        if thermal:
            rows.extend([('Peak temperature', thermal.get('peak_k'), 'K'), ('Reference peak', thermal.get('reference_peak_k'), 'K')])
        scattering = result.get('scattering')
        if scattering:
            for key, value in scattering.items():
                if isinstance(value, (str, int, float)):
                    rows.append((key.replace('_', ' '), value, ''))
        for item in result.get('assumptions', []): rows.append(('Assumption', item, ''))
        for label, value, unit in rows:
            index = self.result_table.InsertItem(self.result_table.GetItemCount(), label)
            self.result_table.SetItem(index, 1, str(value)); self.result_table.SetItem(index, 2, unit)
        self.result_summary.SetLabel(f"{result.get('model_scope', 'Study')}  |  {self.render_backend}  |  original solved data")

    def generate_report(self, kind='preview'):
        if not self.result:
            self.message('Complete a simulation before generating a report.'); return
        if getattr(self, 'report_busy', False):
            return
        path = None
        if kind != 'preview':
            with wx.FileDialog(self, f'Export {kind.upper()} report', wildcard=f'{kind.upper()} report (*.{kind})|*.{kind}',
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() != wx.ID_OK: return
                path = Path(dialog.GetPath())
        try:
            expected = self.config()
            from .model import config_digest
            signature = config_digest(expected)
        except Exception as exc:
            self.message(exc); return
        import copy
        result, pins, profile, derived = copy.deepcopy((self.result, self.pins, self.profile_rows, getattr(self,'network_output',None)))
        self.report_busy = True; self.report_status.SetLabel('Generating report from verified results...')
        def work():
            try:
                from . import reporting
                kwargs = dict(expected_config=expected, probes=pins, line_profile=profile or None, derived_network=derived)
                if kind == 'preview': output = reporting.build_html_report(result, **kwargs)
                elif kind == 'html': output = reporting.export_html(path, result, **kwargs)
                else: output = reporting.export_pdf(path, result, **kwargs)
                wx.CallAfter(self._report_ready, kind, output, signature, None)
            except Exception as exc:
                wx.CallAfter(self._report_ready, kind, None, signature, str(exc))
        threading.Thread(target=work, name='QuickEMergeReport', daemon=True).start()

    def _report_ready(self, kind, output, signature, error):
        if self.closed: return
        self.report_busy = False
        if error:
            self.report_status.SetLabel(error); self.message(error); return
        from .model import config_digest
        try:
            if self.result is None or config_digest(self.config()) != signature:
                self.report_status.SetLabel('Setup changed; generate a report from new simulation results.')
                return
            if kind == 'preview':
                if not hasattr(self, 'report_preview'):
                    from .report_preview import ReportPreview
                    self.report_preview = ReportPreview(self.report_host, self._report_loaded, self._report_failed)
                    self.report_browser = self.report_preview.browser
                    self.report_host.GetSizer().Add(self.report_preview, 1, wx.EXPAND)
                self.report_preview_ready = False
                self.report_status.SetLabel('Loading report preview...')
                self.report_preview.show_report(output, signature)
                self.report_host.Layout()
            else:
                self.report_status.SetLabel(f'Report saved: {output}')
        except Exception as exc:
            self.report_status.SetLabel(str(exc)); self.message(exc)

    def _report_loaded(self, signature):
        if self.closed: return
        from .model import config_digest
        try:
            current = signature == config_digest(self.config()) and self.result is not None
        except ValueError:
            current = False
        self.report_preview_ready = current
        if current:
            self.report_status.SetLabel('Report ready: verified source, original samples and declared model limits.')
        else:
            self.report_preview.clear()
            self.report_status.SetLabel('Setup changed; generate a report from new simulation results.')

    def _report_failed(self, error):
        if self.closed: return
        self.report_preview_ready = False
        self.report_status.SetLabel('Preview could not load. Export HTML or PDF instead. '+str(error))

    def _build_view_controls(self, parent, layout):
        camera = wx.WrapSizer(wx.HORIZONTAL)
        self.camera_preset = wx.Choice(parent, choices=list(PRESETS)); self.camera_preset.SetSelection(0)
        self.projection = wx.Choice(parent, choices=['Orthographic', 'Perspective']); self.projection.SetSelection(0)
        self.true_aspect = wx.CheckBox(parent, label='True Z scale'); self.true_aspect.SetValue(True)
        self.sample_grid = wx.CheckBox(parent, label='Sample grid')
        self.theme = wx.Choice(parent, choices=['Light view', 'Dark view']); self.theme.SetSelection(0)
        fit = wx.Button(parent, label='Fit [F]')
        fit.Bind(wx.EVT_BUTTON, lambda event: self.viewports[self.tabs.GetPageText(self.tabs.GetSelection())].fit())
        for control in (self.camera_preset, self.projection, fit, self.true_aspect, self.sample_grid, self.theme):
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
        self.field_quantity = wx.Choice(parent, choices=['E magnitude', 'H magnitude', 'Power-flow magnitude', 'Temperature'])
        self.field_view = wx.Choice(parent, choices=['Plane', 'Volume samples']); self.field_view.SetSelection(0)
        self.field_view.Bind(wx.EVT_CHOICE, self.change_field_quantity); display.Add(self.field_view, 0, wx.ALL, 3)
        self.field_slice = wx.Choice(parent, choices=['Solved Z plane']); self.field_slice.SetSelection(0)
        self.field_slice.Bind(wx.EVT_CHOICE, self.change_field_quantity); display.Add(self.field_slice, 0, wx.ALL, 3)
        self.field_quantity.SetSelection(0); self.field_quantity.Bind(wx.EVT_CHOICE, self.change_field_quantity)
        display.Add(self.field_quantity, 0, wx.ALL, 3)
        self.colormap = wx.Choice(parent, choices=['inferno', 'viridis', 'cividis', 'plasma', 'turbo']); self.colormap.SetSelection(0)
        self.color_scale = wx.Choice(parent, choices=['Linear color', 'Log color']); self.color_scale.SetSelection(0)
        for control in (self.colormap, self.color_scale):
            control.Bind(wx.EVT_CHOICE, self.refresh_views); display.Add(control, 0, wx.ALL, 3)
        self.manual_range = wx.CheckBox(parent, label='Manual scalar range')
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
        if event.GetKeyCode() == wx.WXK_F1:
            self.on_help()
        elif event.GetKeyCode() == wx.WXK_F11:
            self.focus_button.SetValue(not self.focus_button.GetValue())
            self.focus_view()
        else:
            event.Skip()

    def on_help(self, event=None):
        from wayricad_runtime.help import open_help
        return open_help(self, Path(__file__).with_name('help.html'), 'Quick EMerge · KiCad guide')

    def dense_sampling(self, event=None):
        self.inputs['points'].ChangeValue(81)
        self.inputs['field_grid'].ChangeValue(81)
        self.sweep.SetSelection(0)
        self.invalidate()

    def focus_view(self, event=None):
        if self.focus_button.GetValue():
            self.saved_sashes = (self.workspace_splitter.GetSashPosition(), self.visual_splitter.GetSashPosition(), self.visual_splitter.IsSplit())
            self.workspace_splitter.Unsplit(self.settings)
            if self.visual_splitter.IsSplit(): self.visual_splitter.Unsplit(self.details)
            self.focus_button.SetLabel('Restore panels')
        elif not self.workspace_splitter.IsSplit():
            self.settings.Show()
            self.workspace_splitter.SplitVertically(self.settings, self.workspace, self.saved_sashes[0])
            if self.saved_sashes[2]: self.toggle_inspector(show=True)
            self.focus_button.SetLabel('Focus')
        self.Layout()
        wx.CallAfter(self.viewports[self.tabs.GetPageText(self.tabs.GetSelection())].refresh_canvas)

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
            self.select_view('Field probes')
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

    def reset_report_preview(self, message):
        self.report_preview_ready = False
        if hasattr(self, 'report_status'):
            self.report_status.SetLabel(message)
        if hasattr(self, 'report_preview'):
            self.report_preview.clear(message)

    def install_result(self, result):
        from .field_display import field_for_display
        self.clear_inspection()
        self.result = result
        self.reset_report_preview('Simulation complete. Generate a report from these results.')
        self.network_output=self.network_chart_result=None
        for view in self.viewports.values(): view.clear()
        volume=result.get('field',{}).get('volume')
        self.field_slice.Set([f"Z {z:g} mm" for z in volume['z_mm']] if volume else ['Solved Z plane'])
        self.field_slice.SetSelection(len(volume['z_mm'])-1 if volume else 0)
        self.field_slice.Enable(bool(volume)); self.field_view.Enable(bool(volume))
        self.field_view.SetSelection(0)
        old_quantity=self.field_quantity.GetStringSelection()
        quantities=(['E magnitude','H magnitude','Power-flow magnitude'] if result.get('field') else [])+(['Temperature'] if result.get('thermal') else [])
        self.field_quantity.Set(quantities or ['E magnitude'])
        self.field_quantity.SetStringSelection(old_quantity if old_quantity in quantities else quantities[0] if quantities else 'E magnitude')
        self.inspection = FieldInspection(field_for_display(result, self.field_quantity.GetStringSelection())) if result.get('field') or result.get('thermal') else None
        display = dict(result)
        if self.inspection:
            shown=field_for_display(result,self.field_quantity.GetStringSelection())
            if shown['display_unit']=='K': display.pop('field',None);display['thermal']=shown
            else: display.pop('thermal',None);display['field']=shown
        if result['config']['mode'] == 'pcb_region':
            from . import region_view
            self.region_plan = result['region']
            self.viewports['3D setup'].render(region_view.geometry, result['region'], reset=True, options=self.display_options)
            self.viewports['PCB enclosure'].render(region_view.enclosure, result['region'], reset=True, options=self.display_options)
        else:
            preview_config = result.get('optimization', {}).get('best_config', result['config'])
            self.viewports['3D setup'].render(plots.geometry, preview_config, reset=True, options=self.display_options)
        renderers = {}
        if result.get('s_parameters'):
            renderers.update({'S-parameters': plots.response, 'Smith chart': lambda figure, data, options: plots.smith(figure, data)})
        if self.inspection:
            renderers.update({'Field probes': plots.near_field, '3D fields': plots.near_field3d})
        if result.get('radiation'): renderers['3D radiation'] = plots.radiation
        for name, renderer in renderers.items():
            options = dict(self.display_options)
            if name == '3D radiation': options.pop('minimum', None); options.pop('maximum', None)
            self.viewports[name].render(renderer, display, reset=True, options=options)
        if self.inspection:
            field = self.inspection
            rows = [dict(field.probe(x, y), kind='field') for y in field.y for x in field.x]
            self.viewports['3D fields'].set_samples(rows)
            context = f"{field.frequency/1e9:g} GHz" if field.frequency is not None else f"{field.time:g} s"
            self.inspector_text.ChangeValue(f'{len(field.x)} x {len(field.y)} original {field.quantity} samples [{field.unit}], {context}, Z={field.z:g} mm.\nNearest original samples; no arbitrary volume interpolation.\n'+result.get('model_scope', ''))
        if result.get('radiation'):
            radiation = result['radiation']; peak = max(max(row) for row in radiation['norm_e'])
            rows = []
            if peak > 0:
                for i, theta in enumerate(radiation['theta_rad']):
                    for j, phi in enumerate(radiation['phi_rad']):
                        radius = radiation['norm_e'][i][j]/peak
                        rows.append(dict(kind='radiation', frequency_hz=radiation['frequency_hz'],theta_deg=math.degrees(theta),phi_deg=math.degrees(phi),relative_e=radius,
                                         display_xyz=(radius*math.sin(theta)*math.cos(phi),radius*math.sin(theta)*math.sin(phi),radius*math.cos(theta))))
            self.viewports['3D radiation'].set_samples(rows)
        self.source_label.SetLabel(f"{self.session.board.name} | {result.get('model_scope', '')}")
        self.probe_label.SetLabel('Select Probe to inspect original samples. Orbit, pan and zoom to navigate.')
        self.refresh_field_views(reset=True)
        self.refresh_results()

    def refresh_field_views(self, *, reset=False):
        if not self.result or not (self.result.get('field') or self.result.get('thermal')): return
        from .field_display import field_for_display, volume_samples
        quantity=self.field_quantity.GetStringSelection()
        volume=self.result.get('field',{}).get('volume')
        index=max(0,self.field_slice.GetSelection()) if volume else None
        field=field_for_display(self.result,quantity,index)
        self.inspection=FieldInspection(field)
        display=dict(self.result)
        if field['display_unit']=='K': display.pop('field',None);display['thermal']=field
        else: display.pop('thermal',None);display['field']=field
        options=dict(self.display_options,field_view='Volume' if self.field_view.GetSelection()==1 and volume else 'Plane')
        self.display_options.update(field_view=options['field_view'])
        self.viewports['Field probes'].render(plots.near_field,display,reset=reset,options=options)
        self.viewports['3D fields'].render(plots.near_field3d,display,reset=reset,options=options)
        rows=volume_samples(field) if options['field_view']=='Volume' else [dict(self.inspection.probe(x,y),kind='field') for y in self.inspection.y for x in self.inspection.x]
        self.viewports['3D fields'].set_samples(rows)

    def change_field_quantity(self, event=None):
        if not self.result: return
        try:
            self.refresh_field_views()
            self.select_view('3D fields' if self.current_group == '3D' else 'Field probes')
        except Exception as exc: self.message(exc)

    def _viewport_probe(self, name, event, sample=None, selected=False):
        if self.result is None or event.inaxes is None:
            return
        try:
            if name in ('Field probes', '3D fields'):
                if not self.visibility['field'].GetValue():
                    return
                if name == 'Field probes':
                    sample = dict(self.inspection.probe(event.xdata, event.ydata), kind='field') if self.inspection else None
                if sample is None:
                    return
                if self.inspection is None: return
                if name=='3D fields' and 'iz' in sample and sample['iz']!=self.field_slice.GetSelection():
                    self.field_slice.SetSelection(sample['iz']); self.refresh_field_views()
                key = self.inspection.value_key
                value = 'unknown' if sample[key] is None else f'{sample[key]:.7g} {self.inspection.unit}'
                context = f"{sample['frequency_hz']/1e9:g} GHz" if 'frequency_hz' in sample else f"{sample['time_s']:g} s"
                text = f"Original sample [{sample['ix']}, {sample['iy']}] | {context}\nX={sample['x_mm']:g} mm Y={sample['y_mm']:g} mm Z={sample['z_mm']:g} mm | {self.inspection.quantity}={value}"
            elif name == '3D radiation':
                if sample is None or not self.visibility['field'].GetValue():
                    return
                text = f'Radiation sample • {sample["frequency_hz"]/1e9:g} GHz\nθ={sample["theta_deg"]:.5g}°  φ={sample["phi_deg"]:.5g}°  relative |E|={sample["relative_e"]:.7g}\nNormalized radius; not gain or physical distance.'
            elif name in ('S-parameters', 'Smith chart'):
                network_result=getattr(self,'network_chart_result',None) or self.result
                f = network_result['frequencies_hz']
                s = [complex(*pair) for pair in network_result['s_parameters']['S11']]
                index = min(range(len(f)), key=(lambda i: abs(f[i]/1e9-event.xdata)) if name == 'S-parameters'
                            else lambda i: abs(s[i]-complex(event.xdata, event.ydata)))
                reference=network_result.get('reference_impedance_ohm',network_result['config']['z0_ohm'])
                values = metrics(f, s, reference[0] if isinstance(reference,(list,tuple)) else reference)
                sample = dict(kind='network',network_view=network_result.get('network_view_label','Original solved network'), frequency_hz=f[index], s11_db=values['s11_db'][index],
                              return_loss_db=values['return_loss_db'][index], vswr=values['vswr'][index],
                              impedance_real_ohm=values['impedance_real_ohm'][index], impedance_imag_ohm=values['impedance_imag_ohm'][index])
                text = f'{f[index]/1e9:.7g} GHz • S11={sample["s11_db"]:.6g} dB • return loss={sample["return_loss_db"]:.6g} dB\nVSWR={sample["vswr"]}  Z={sample["impedance_real_ohm"]}+j{sample["impedance_imag_ohm"]} Ω\nField views stay at their recorded solved frequency.'
            else:
                return
            status = text.split('\n')[0]
            if sample['kind'] == 'field':
                context = f"{sample['frequency_hz']/1e9:g} GHz" if 'frequency_hz' in sample else f"{sample['time_s']:g} s"
                status = f"X {sample['x_mm']:g}, Y {sample['y_mm']:g}, Z {sample['z_mm']:g} mm | {self.inspection.quantity}: {value} | {context}"
            elif sample['kind'] == 'radiation':
                status = f'θ {sample["theta_deg"]:.5g}°, φ {sample["phi_deg"]:.5g}° • relative |E| {sample["relative_e"]:.6g}'
            self.probe_label.SetLabel(('Selected: ' if selected else 'Hover: ')+status)
            if selected:
                self.current_probe = sample
                self.pin_button.Enable()
                self.inspector_text.ChangeValue(text)
                self.toggle_inspector(show=True)
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
        self.pins_list.SetItem(index, 2, f"{row['frequency_hz']/1e9:.7g}" if 'frequency_hz' in row else f"t={row.get('time_s', 0):g}s")
        location = f'({row["x_mm"]:g}, {row["y_mm"]:g}, {row["z_mm"]:g}) mm' if row['kind'] == 'field' else (
            f'θ={row["theta_deg"]:g}°, φ={row["phi_deg"]:g}°' if row['kind'] == 'radiation' else 'S11 / input impedance')
        value = ('unknown' if row.get(self.inspection.value_key) is None else f"{row[self.inspection.value_key]:.7g} {self.inspection.unit}") if row['kind'] == 'field' else (
            f"{row['relative_e']:.7g} relative |E|" if row['kind'] == 'radiation' else f"{row['s11_db']:.6g} dB")
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
        axes.plot([p['distance_mm'] for p in self.profile_rows], [p[self.inspection.value_key] for p in self.profile_rows], color='#147e88')
        axes.set(xlabel='Distance along selected line [mm]', ylabel=f'{self.inspection.quantity} [{self.inspection.unit}]', title='Nearest original samples; no interpolation')
        axes.grid(alpha=.25)
        self.profile_figure.subplots_adjust(left=.09, right=.98, bottom=.32, top=.78)
        self.profile_canvas.draw_idle()
        for name in ('Field probes', '3D fields'):
            self.viewports[name].set_selection(row, pins=self.pins, profile=(self.line_start+(row['z_mm'],), point+(row['z_mm'],)))
        self.line_start = None
        self.details.SetSelection(2)
        self.toggle_inspector(show=True)

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
        if self.running or self.region_busy or self.closed:
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
                from . import region_view
                self.viewports['PCB enclosure'].render(region_view.board_context, data, reset=True, options=self.display_options)
                self.select_view('PCB enclosure')
                if not data['areas']:
                    self.region_notice.SetLabel('No saved rule areas. Draw an enclosure in KiCad, or choose an antenna/line template.')
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
            self.select_view('PCB enclosure')
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
            self.region_notice.SetLabel('Cannot preview this saved enclosure: '+str(exc))
            if config is None:
                self.region_listing = None
                self.rule_area.Clear()
            self.log.ChangeValue(str(exc))
            self.SetStatusText(str(exc))
        finally:
            self.running_state(False)

    def rollback_runtime(self, event):
        self._dependency_task(rollback=True)

    def _dependency_task(self, *, force=False, rollback=False):
        if self.running or self.dependency_busy or self.closed:
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
            self.probe_solver_runtime()
            self.log.ChangeValue(result['message'])
            self.SetStatusText(f'EMerge {result["version"]} ready • {result["message"]}')
        else:
            self.log.ChangeValue(error)
            self.SetStatusText('Dependency setup incomplete • retry setup or select a solver Python')
        self.running_state(False)

    def _solver_selected(self, event):
        self._solver_explicit = True
        self.invalidate(event)

    def probe_solver_runtime(self, event=None):
        if self.closed: return
        import subprocess
        executable = self.python.GetPath()
        self._solver_probe_generation += 1
        generation = self._solver_probe_generation
        previous = getattr(self, 'solver_probe_process', None)
        if previous is not None and previous.poll() is None: previous.terminate()
        self.solver_probe_busy = True
        self.running_state(self.running)
        self.solver.SetToolTip('Checking the selected runtime with tiny complex linear systems...')
        def work():
            process = None
            try:
                process = subprocess.Popen([executable, '-I', '-X', 'utf8', str(Path(__file__).with_name('solver_probe.py'))],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if self.closed or generation != self._solver_probe_generation:
                    process.terminate(); process.communicate(); return
                self.solver_probe_process = process
                output, errors = process.communicate(timeout=35)
                if process.returncode or len(output) > 32768:
                    raise RuntimeError(errors.decode('utf-8', errors='replace')[-1200:] or 'Solver probe failed')
                result = json.loads(output.decode('utf-8'))
                wx.CallAfter(self._solver_probe_done, generation, executable, result, None)
            except Exception as exc:
                if process is not None and process.poll() is None:
                    process.kill(); process.communicate()
                wx.CallAfter(self._solver_probe_done, generation, executable, None, str(exc))
        threading.Thread(target=work, name='QuickEMergeSolverProbe', daemon=True).start()

    def _solver_probe_done(self, generation, executable, result, error):
        if self.closed or generation != self._solver_probe_generation: return
        self.solver_probe_busy = False
        self.solver_probe_python = executable
        self.solver_environment = {}
        self.solver_probe_available = []
        if error or not result or result.get('schema') != 1:
            self.solver.SetToolTip('Runtime check failed: '+str(error or 'Invalid probe response'))
        else:
            available = result.get('available', [])
            self.solver_probe_available = available
            library = result.get('diagnostics', {}).get('PARDISO', {}).get('library')
            if library: self.solver_environment['EMERGE_PARDISO_PATH'] = library
            self.solver.SetToolTip('Verified: '+(', '.join(available) or 'none')+'. Other backends require their optional dependencies.')
            preferred = result.get('preferred')
            if preferred and not self._solver_explicit and self.result is None:
                self.solver.SetStringSelection(preferred)
                if self.session.review is not None:
                    try: self.session.preview(self.config(), region=self.region_plan)
                    except ValueError: self.session.review = None
            if not self.running and not self.region_busy and not self.dependency_busy:
                self.SetStatusText(('Verified '+preferred+' solver. ' if preferred else 'No compatible solver found. ')+
                                  ('Ready to run.' if self.session.review else 'Review geometry and material, then Preview.'))
        self.running_state(self.running)

    def config(self):
        raw = {k: ctrl.GetValue() for k, ctrl in self.inputs.items()}
        raw['mode'] = ('patch', 'pcb_line', 'pcb_region')[self.mode.GetSelection()]
        if raw['mode'] == 'pcb_region':
            index = self.rule_area.GetSelection()
            raw['rule_area_id'] = self.region_listing['areas'][index]['id'] if self.region_listing and index >= 0 else ''
            raw['signal_net'] = self.signal_net.GetStringSelection()
            raw['reference_net'] = self.reference_net.GetStringSelection()
            raw['region_er_reviewed'] = self.region_material_review.GetValue()
        advanced = {'study': self.study_ids[max(0, self.study.GetSelection())]}
        for key, control in self.advanced_inputs.items():
            advanced[key] = control.GetStringSelection() if isinstance(control, wx.Choice) else control.GetPath() if hasattr(control, 'GetPath') else control.GetValue()
        if advanced.get('step_path'):
            import hashlib
            advanced['step_sha256'] = hashlib.sha256(Path(advanced['step_path']).read_bytes()).hexdigest()
        if advanced.get('import_kind', 'none') != 'none' and advanced.get('import_path') and advanced.get('import_recipe_path'):
            from .advanced_imports import import_identity
            advanced['import_sha256'] = import_identity(advanced['import_kind'], advanced['import_path'], advanced['import_recipe_path'])['sha256']
        raw['advanced'] = advanced
        raw['solver'] = self.solver.GetStringSelection()
        raw['sweep'] = 'linear' if self.sweep.GetSelection() == 0 else 'adaptive'
        return validate_config(raw)

    def message(self, error):
        self.SetStatusText(str(error))
        wx.MessageBox(str(error), 'Quick EMerge', wx.OK | wx.ICON_INFORMATION, parent=self)

    def invalidate(self, event=None):
        self.session.review = None
        self.result = None
        self.network_output=self.network_chart_result=None
        self.region_plan = None
        self.update_model_sections()
        self.refresh_results()
        self.reset_report_preview('Setup changed; complete a new simulation to generate its report.')
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
            self.select_view('3D setup')
            self.SetStatusText('Preview ready • PEC, lossless dielectric, absorbing boundary • template only')
        except Exception as exc:
            self.message(exc)

    def running_state(self, running):
        self.running = running
        busy = running or self.dependency_busy or self.region_busy or getattr(self,'network_busy',False)
        self.settings.Enable(not (running or self.region_busy or getattr(self,'network_busy',False)))
        self.preview_button.Enable(not (running or self.region_busy or getattr(self,'network_busy',False)))
        can_run = not busy and not self.solver_probe_busy and self.session.review is not None
        verified = getattr(self, 'solver_probe_available', None)
        if verified is not None and self.solver_probe_python == self.python.GetPath():
            selected = self.solver.GetStringSelection()
            can_run = can_run and bool(verified) and (selected in verified or selected not in ('SUPERLU', 'PARDISO'))
        self.run_button.Enable(can_run)
        self.cancel_button.Enable(busy)
        self.cancel_button.SetLabel('Cancel extraction' if self.region_busy else 'Cancel setup' if self.dependency_busy else 'Cancel run')
        self.dependencies_button.Enable(not busy)
        self.rollback_button.Enable(not busy)

    def run(self, event):
        try:
            self.session.start(self.config(), self.python.GetPath(), self.output.GetPath(),
                               solver_environment=self.solver_environment if self.solver_probe_python == self.python.GetPath() else None)
            self.result = None
            self.reset_report_preview('Simulation running. Generate a report when it completes.')
            self.clear_inspection()
            for name, view in self.viewports.items():
                if name not in ('3D setup', 'PCB enclosure'):
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
            self.select_view('S-parameters') if result.get('s_parameters') else self.select_view('3D fields')
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
        process=getattr(self,'network_process',None)
        if process is not None and process.poll() is None:
            process.terminate();self.SetStatusText('Cancelling network operation...');return
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
                self._solver_explicit = True
                config = validate_config(payload['config'])
                self.mode.SetSelection(('patch', 'pcb_line', 'pcb_region').index(config['mode']))
                self.region_material_review.SetValue(config['region_er_reviewed'])
                self.solver.SetStringSelection(config['solver'])
                self.sweep.SetSelection(0 if config['sweep'] == 'linear' else 1)
                advanced = config.get('advanced', {})
                self.study.SetSelection(self.study_ids.index(advanced.get('study', 'driven')))
                for key, control in self.advanced_inputs.items():
                    if key not in advanced: continue
                    if isinstance(control, wx.CheckBox): control.SetValue(bool(advanced[key]))
                    elif isinstance(control, wx.Choice): control.SetStringSelection(str(advanced[key]))
                    elif hasattr(control, 'SetPath'): control.SetPath(str(advanced[key]))
                    else: control.ChangeValue(str(advanced[key]))
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
        self._solver_probe_generation += 1
        probe = getattr(self, 'solver_probe_process', None)
        if probe is not None and probe.poll() is None: probe.terminate()
        process=getattr(self,'network_process',None)
        if process is not None and process.poll() is None:process.terminate()
        self.region_cancel.set()
        self.dependency_cancel.set()
        self.timer.Stop()
        self.session.cancel()
        self.closed = True
        self.Destroy()
