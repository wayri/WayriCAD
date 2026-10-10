"""Native QuickTherm workspace with scoped inputs, board views and evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time

import wx
from matplotlib.figure import Figure

from .plot_canvas import FigureCanvasWxAgg, NavigationToolbar2WxAgg


from .thermal_inputs import _parse_sink_areas
from .thermal_plot import update_component_hover

def _wrap_text(control, text, width=270):
    """Keep native text inside the sidebar even on wx builds with weak Wrap."""
    lines=[]
    for paragraph in str(text).split('\n'):
        line=''
        for word in paragraph.split():
            candidate=(line+' '+word).strip()
            if line and control.GetTextExtent(candidate).width>width:
                lines.append(line);line=word
            else:line=candidate
        lines.append(line)
    control.SetLabel('\n'.join(lines))
    control.SetMinSize((min(width,max((control.GetTextExtent(line).width for line in lines),default=1)),
                        len(lines)*control.GetTextExtent('Ag').height+2))

class QuickThermFrame(wx.Frame):
    def __init__(self, parent, board_path):
        super().__init__(parent, title="WayriCAD QuickTherm", size=(1440, 900))
        icons = wx.IconBundle()
        for size in (24, 48, 96):
            path = Path(__file__).with_name("resources") / f"icon-{size}.png"
            if path.is_file():
                icons.AddIcon(wx.Icon(str(path), wx.BITMAP_TYPE_PNG))
        if icons.GetIcon(wx.Size(48, 48)).IsOk():
            self.SetIcons(icons)
        self.SetMinSize((940, 680))
        self.board_path = str(Path(board_path).resolve())
        self.thermal_bundle = {}
        self.inventory = {}
        self.manual_values = {}
        self.manual_temperature_limits = {}
        self.virtual_heatsinks = {}
        self.therm_probe_definitions = []
        self.therm_probe_mode = False
        self._thermal_default_view = True
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        self._thermal_playing = False
        self._thermal_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._thermal_tick, self._thermal_timer)
        # Optional remembered solver paths must not open a modal wx log dialog
        # on read-only Windows profiles or restricted validation runtimes.
        with wx.LogNull():
            self._solver_config = wx.Config("WayriCAD QuickTherm")
            self._calculix_executable = self._solver_config.Read('calculix_executable', '')
        self.main_panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self.main_panel, label="QuickTherm · Saved-board thermal screening")
        font = heading.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(font)
        title.Add(heading, 1, wx.ALIGN_CENTER_VERTICAL)
        filename = wx.StaticText(self.main_panel, label=Path(self.board_path).name)
        filename.SetToolTip(self.board_path)
        title.Add(filename, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(title, 0, wx.EXPAND | wx.ALL, 6)
        self.book = wx.Notebook(self.main_panel)
        self._build_thermal_page()
        root.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        self.status = wx.StaticText(self.main_panel, label="Reading saved PCB…")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 6)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.reload = wx.Button(self.main_panel, label="Reload saved PCB")
        self.reload.Bind(wx.EVT_BUTTON, lambda event: self._inspect())
        footer.Add(self.reload, 0, wx.RIGHT, 8)
        self.help_button = wx.Button(self.main_panel, wx.ID_HELP, label="Help")
        self.help_button.Bind(wx.EVT_BUTTON, self.on_help)
        footer.Add(self.help_button, 0, wx.RIGHT, 8)
        self.cancel = wx.Button(self.main_panel, label="Cancel")
        self.cancel.Bind(wx.EVT_BUTTON, self.on_cancel)
        footer.Add(self.cancel, 0, wx.RIGHT, 8)
        footer.AddStretchSpacer()
        self.close_button = wx.Button(self.main_panel, wx.ID_CLOSE, label="Close")
        self.close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        footer.Add(self.close_button, 0)
        root.Add(footer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.main_panel.SetSizer(root)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self._buttons()
        self.Centre()
        self.Maximize(True)
        wx.CallAfter(self._inspect)

    def _buttons(self):
        self.reload.Enable(not self._busy)
        self.therm_run.Enable(not self._busy)
        self.therm_whole_board.Enable(not self._busy)
        self.therm_manual_button.Enable(not self._busy)
        if hasattr(self, 'therm_inputs'):
            self.therm_inputs.Enable(not self._busy)
        self.therm_export.Enable(not self._busy and bool(self.thermal_bundle.get("quick_therm")))
        self.therm_sink_button.Enable(not self._busy)
        self.therm_sync.Enable(not self._busy and bool(self.thermal_bundle))
        self.cancel.Enable(self._busy)
        self._therm_controls()

    def _task(self, operation, finished, message="Working…"):
        if self._busy or self._closed:
            return
        self._stop_thermal_playback()
        self._busy = True
        self._cancel.clear()
        self.status.SetLabel(message)
        self._buttons()

        def worker():
            try:
                answer, error = operation(), None
            except Exception as exc:
                answer, error = None, exc
            wx.CallAfter(self._finish, finished, answer, error)

        threading.Thread(target=worker, name="WayriCAD QuickTherm job", daemon=True).start()

    def _finish(self, finished, answer, error):
        if self._closed:
            return
        self._busy = False
        if error:
            message = "Cancelled." if self._cancel.is_set() else str(error)
            self.status.SetLabel(message)
            self.therm_status.SetLabel(message)
        else:
            try:
                finished(answer)
                self.status.SetLabel("Ready.")
            except Exception as exc:
                self.status.SetLabel(str(exc))
                self.therm_status.SetLabel(str(exc))
        self._buttons()

    def _job(self, request, finished, message):
        from .service import run_job

        def show_progress(item):
            if self._closed:
                return
            eta = item.get("eta_s")
            suffix = f" · ETA {eta:.0f} s" if eta is not None else ""
            label = (f"{item['stage']} · {item['percent']:.0f}% · "
                     f"{item['elapsed_s']:.0f} s elapsed{suffix}")
            wx.CallAfter(lambda: self.status.SetLabel(label) if not self._closed else None)

        self._task(lambda: run_job(request, cancelled=self._cancel.is_set,
                                   progress=show_progress), finished, message)

    def _inspect(self):
        if self._closed:
            return
        same_board = getattr(self, '_inventory_board_path', None) == self.board_path
        controls = {'power_w': self.therm_power, 'theta_ja_air_k_per_w': self.therm_ja,
                    'theta_jb_k_per_w': self.therm_jb, 'theta_jc_k_per_w': self.therm_jc}
        previous = {key: control.GetValue() for key, control in controls.items()} if same_board else {}
        other_controls = (self.therm_model_jb, self.therm_limit_min, self.therm_limit_max)
        previous_other = [control.GetValue() for control in other_controls] if same_board else ['', '', '']
        selected = {self.therm_refs.GetString(i) for i in range(self.therm_refs.GetCount())
                    if self.therm_refs.IsChecked(i)} if same_board else set()
        self.inventory = {}
        self._invalidate_thermal()

        def loaded(inventory):
            self.inventory = inventory
            self._inventory_board_path = self.board_path
            fields = ["", *inventory.get("field_names", [])]
            from .quick_therm import restored_field_mapping
            mapping = restored_field_mapping(fields[1:], previous)
            for key, choice in controls.items():
                choice.Set(fields)
                choice.SetValue(mapping[key])
            for choice, value in zip(other_controls, previous_other):
                choice.Set(fields)
                choice.SetValue(value if value in fields else '')
            if not self.therm_model_jb.GetValue():
                self.therm_model_jb.SetValue(mapping['theta_jb_k_per_w'])
            from .component_inputs import restored_temperature_mapping
            limit_mapping=restored_temperature_mapping(fields[1:],{
                'minimum_c':previous_other[1],'maximum_c':previous_other[2]})
            self.therm_limit_min.SetValue(limit_mapping['minimum_c'])
            self.therm_limit_max.SetValue(limit_mapping['maximum_c'])
            refs = inventory.get("component_references", [])
            self.therm_refs.Set(refs)
            for i, ref in enumerate(refs):
                self.therm_refs.Check(i, ref in selected or (not same_board and len(refs) == 1))
            self._therm_mount_candidates = inventory.get("mounting_holes", [])
            self.therm_mounts.Set([
                f"{row['reference']}.{row['pad_number'] or '?'} · {row['net'] or 'no net'} · "
                f"{'PTH' if row['plated'] else 'NPTH'} · Ø{row['drill_mm']:.3g} mm"
                for row in self._therm_mount_candidates
            ])
            self.virtual_heatsinks = {
                ref: sink for ref, sink in self.virtual_heatsinks.items() if ref in refs
            }
            self.manual_values = {ref: values for ref, values in self.manual_values.items()
                                  if same_board and ref in refs}
            self.therm_inputs.load(inventory, mapping, self.manual_values,
                [self.therm_refs.GetString(i) for i in range(self.therm_refs.GetCount())
                 if self.therm_refs.IsChecked(i)], self._temperature_field_map())
            self._update_thermal_scope()
            self.therm_status.SetLabel(
                f"{len(refs)} components. Review saved field mappings or enter manual values; "
                "select the dissipating parts, then run."
            )

        self._job({"action": "inspect", "board_path": self.board_path}, loaded,
                  "Reading saved footprint fields and mounting holes…")

    def on_export_diagnostic(self, kind="quick_therm"):
        if not self.thermal_bundle.get("quick_therm"):
            return
        name = Path(self.board_path).stem + "-quick-therm.html"
        with wx.FileDialog(self, "Export QuickTherm evidence",
                           defaultDir=str(Path(self.board_path).parent), defaultFile=name,
                           wildcard="HTML report (*.html)|*.html",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        from .report import write_report

        self._task(lambda: write_report(path, self.thermal_bundle),
                   lambda result: self.therm_status.SetLabel("Exported " + result["html"]),
                   "Writing local HTML and JSON evidence…")

    def on_help(self, event=None):
        import wx.html

        dialog = wx.Dialog(self, title="QuickTherm · Help", size=(960, 740),
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        browser = wx.html.HtmlWindow(dialog)
        browser.LoadPage(str(Path(__file__).with_name("QUICK_THERM_USER_GUIDE.html")))
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(browser, 1, wx.EXPAND | wx.ALL, 10)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE), 0, wx.ALIGN_RIGHT | wx.ALL, 10)
        dialog.SetSizer(layout)
        dialog.Bind(wx.EVT_BUTTON, lambda evt: dialog.EndModal(wx.ID_CLOSE), id=wx.ID_CLOSE)
        dialog.ShowModal()
        dialog.Destroy()

    def on_cancel(self, event=None):
        self._cancel.set()
        self.status.SetLabel("Cancelling the worker…")

    def on_close(self, event):
        self._stop_thermal_playback()
        self._cancel.set()
        self._closed = True
        self.Destroy()

    def _build_thermal_page(self):
        board_page=wx.Panel(self.book)
        self.therm_board_page=board_page
        workspace=wx.BoxSizer(wx.HORIZONTAL)
        page=wx.ScrolledWindow(board_page,style=wx.VSCROLL);page.SetScrollRate(0,10);layout=wx.BoxSizer(wx.VERTICAL)
        page.SetMinSize((340, -1))
        self._therm_input_page=page
        note=wx.StaticText(page,label='Review component inputs, choose the heat model, then run.')
        note.Wrap(270);layout.Add(note,0,wx.EXPAND|wx.ALL,8)
        setup=wx.FlexGridSizer(0,2,6,8);setup.AddGrowableCol(1)
        self.therm_input_mode=wx.Choice(page,choices=['Scanned values + edits','Saved fields only'])
        self.therm_input_mode.SetSelection(0)
        self.therm_env=wx.Choice(page,choices=['Air','Vacuum','Forced air','Potting','Sealed enclosure']);self.therm_env.SetSelection(0)
        self.therm_ambient=wx.TextCtrl(page,value='20',size=(80,-1))
        self.therm_manual_button=wx.Button(page,label='▦  Component inputs')
        self.therm_manual_button.Bind(wx.EVT_BUTTON,self.on_manual_setup)
        for label,control in [('Input source',self.therm_input_mode),('Environment',self.therm_env),
                              ('Ambient °C',self.therm_ambient)]:
            setup.Add(wx.StaticText(page,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            setup.Add(control,1,wx.EXPAND)
        setup.AddSpacer(1);setup.Add(self.therm_manual_button,0,wx.EXPAND)
        layout.Add(setup,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.therm_time_enabled=wx.CheckBox(page,label='Transient · watch board heating')
        self.therm_time_enabled.Bind(wx.EVT_CHECKBOX,self._transient_setup_changed)
        layout.Add(self.therm_time_enabled,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.therm_environment_note=wx.StaticText(page,label='')
        layout.Add(self.therm_environment_note,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        vacuum_row=wx.BoxSizer(wx.VERTICAL)
        vacuum_row.Add(wx.StaticText(page,label='Vacuum board-to-environment K/W'),0,wx.BOTTOM,4)
        self.therm_board_r=wx.TextCtrl(page,value='',size=(120,-1))
        self.therm_board_r.SetHint('Enter a reviewed heat path')
        vacuum_row.Add(self.therm_board_r,0)
        layout.Add(vacuum_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        advanced=wx.CollapsiblePane(page,label='Environment boundaries',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        advanced_host=advanced.GetPane();advanced_form=wx.FlexGridSizer(0,2,6,8);advanced_form.AddGrowableCol(1)
        self.therm_explicit_h=wx.TextCtrl(advanced_host,value='20')
        self.therm_enclosure_c=wx.TextCtrl(advanced_host,value='20')
        self.therm_potting_k=wx.TextCtrl(advanced_host,value='1')
        self.therm_potting_thickness=wx.TextCtrl(advanced_host,value='2')
        self.therm_potting_outer_h=wx.TextCtrl(advanced_host,value='10')
        for label,ctrl in [('Explicit convection h W/m²K',self.therm_explicit_h),('Fixed enclosure °C',self.therm_enclosure_c),('Potting conductivity W/mK',self.therm_potting_k),('Potting thickness mm',self.therm_potting_thickness),('Potting outer h W/m²K',self.therm_potting_outer_h)]:
            caption=wx.StaticText(advanced_host,label=label);caption.Wrap(140)
            advanced_form.Add(caption,0,wx.ALIGN_CENTER_VERTICAL);advanced_form.Add(ctrl,1,wx.EXPAND)
            ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        advanced_box=wx.BoxSizer(wx.VERTICAL);advanced_box.Add(advanced_form,1,wx.EXPAND|wx.ALL,6)
        advanced_host.SetSizer(advanced_box);layout.Add(advanced,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.therm_transient_pane=wx.CollapsiblePane(page,label='Transient setup',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        transient_host=self.therm_transient_pane.GetPane();transient_box=wx.BoxSizer(wx.VERTICAL)
        transient_form=wx.FlexGridSizer(0,2,6,8);transient_form.AddGrowableCol(1)
        self.therm_time_duration=wx.TextCtrl(transient_host,value='60')
        self.therm_time_step=wx.TextCtrl(transient_host,value='1')
        self.therm_time_initial=wx.TextCtrl(transient_host,value='20')
        self.therm_copper_capacity=wx.TextCtrl(transient_host,value='3450000')
        self.therm_dielectric_capacity=wx.TextCtrl(transient_host,value='1800000')
        self.therm_schedule_interpolation=wx.Choice(transient_host,choices=['Linear ramps','Power steps'])
        self.therm_schedule_interpolation.SetSelection(0)
        self.therm_schedule_interpolation.Bind(wx.EVT_CHOICE,self._invalidate_thermal)
        for label,ctrl in [('Duration s',self.therm_time_duration),('Max time step s',self.therm_time_step),('Initial °C',self.therm_time_initial),('Copper capacity J/m³K',self.therm_copper_capacity),('Dielectric capacity J/m³K',self.therm_dielectric_capacity),('Schedule',self.therm_schedule_interpolation)]:
            caption=wx.StaticText(transient_host,label=label);caption.Wrap(130)
            transient_form.Add(caption,0,wx.ALIGN_CENTER_VERTICAL);transient_form.Add(ctrl,1,wx.EXPAND)
            if isinstance(ctrl,wx.TextCtrl):ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        transient_box.Add(transient_form,0,wx.EXPAND|wx.ALL,6)
        steps=wx.Button(transient_host,label='Power steps…');steps.Bind(wx.EVT_BUTTON,self._edit_power_steps)
        self.therm_power_steps=steps
        transient_box.Add(steps,0,wx.EXPAND|wx.ALL,6)
        self._component_storage={}
        self._copper_loss_import=None
        component_rc=wx.Button(transient_host,label='Component heating · R / C…')
        component_rc.Bind(wx.EVT_BUTTON,self._edit_component_storage)
        transient_box.Add(component_rc,0,wx.EXPAND|wx.ALL,6)
        capacity_note=wx.StaticText(transient_host,label='Capacity defaults are illustrative. Review materials before relying on heating times.')
        _wrap_text(capacity_note,capacity_note.GetLabel());transient_box.Add(capacity_note,0,wx.ALL,6)
        schedule_pane=wx.CollapsiblePane(transient_host,label='Advanced schedules + sinks',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        schedule_host=schedule_pane.GetPane();schedule_box=wx.BoxSizer(wx.VERTICAL)
        self.therm_power_schedule=wx.TextCtrl(schedule_host,value='{}')
        self.therm_sink_capacity=wx.TextCtrl(schedule_host,value='{}')
        for label,ctrl in [('Power multipliers JSON: reference → [[s, multiplier]]',self.therm_power_schedule),('Sink heat capacity JSON: reference → J/K',self.therm_sink_capacity)]:
            caption=wx.StaticText(schedule_host,label=label);_wrap_text(caption,label)
            schedule_box.Add(caption,0,wx.EXPAND|wx.TOP,5);schedule_box.Add(ctrl,0,wx.EXPAND)
            ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        schedule_host.SetSizer(schedule_box);transient_box.Add(schedule_pane,0,wx.EXPAND|wx.ALL,6)
        transient_host.SetSizer(transient_box);layout.Add(self.therm_transient_pane,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        for pane in (advanced,self.therm_transient_pane,schedule_pane):
            pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(page.Layout(),page.FitInside()))
        self.therm_fields_pane=wx.CollapsiblePane(page,label='Field mapping + limits',
                                                 style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        fields_host=self.therm_fields_pane.GetPane()
        form=wx.FlexGridSizer(0,2,7,8);form.AddGrowableCol(1)
        self.therm_power=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        self.therm_ja=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        self.therm_jb=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        self.therm_jc=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        self.therm_limit_min=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        self.therm_limit_max=wx.ComboBox(fields_host,style=wx.CB_READONLY)
        for name,ctrl in [('Dissipation field',self.therm_power),('RθJA field',self.therm_ja),('RθJB field',self.therm_jb),
                          ('RθJC field · heatsinks',self.therm_jc)]:
            form.Add(wx.StaticText(fields_host,label=name),0,wx.ALIGN_CENTER_VERTICAL);form.Add(ctrl,1,wx.EXPAND)
        for name,ctrl in [('Minimum Tj limit field',self.therm_limit_min),
                          ('Maximum Tj limit field',self.therm_limit_max)]:
            form.Add(wx.StaticText(fields_host,label=name),0,wx.ALIGN_CENTER_VERTICAL);form.Add(ctrl,1,wx.EXPAND)
        fields_host.SetSizer(form)
        layout.Add(self.therm_fields_pane,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.therm_fields_pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(page.FitInside(),page.Layout()))
        self.therm_input_mode.Bind(wx.EVT_CHOICE,self._input_mode_changed)
        self.therm_model=wx.CollapsiblePane(page,label='Board heat model',
                                           style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        model_pane=self.therm_model.GetPane();model_grid=wx.FlexGridSizer(0,2,6,8);model_grid.AddGrowableCol(1)
        self.therm_model_enabled=wx.CheckBox(model_pane,label='Include board heat model in next run')
        self.therm_model_kind=wx.Choice(model_pane,choices=['Thin sheet (screening)','Copper layers + vertical paths',
                                                       'CalculiX 3D · fixed lower face'])
        self.therm_model_kind.SetSelection(0)
        self.therm_k=wx.TextCtrl(model_pane,value='0.3');self.therm_k.SetToolTip('Assumed effective in-plane conductivity W/(m·K); check against your stackup.')
        self.therm_dielectric_k=wx.TextCtrl(model_pane,value='')
        self.therm_dielectric_k.SetHint('Measured W/m·K')
        self.therm_copper_k=wx.TextCtrl(model_pane,value='385')
        self.therm_plating=wx.TextCtrl(model_pane,value='')
        self.therm_plating.SetHint('Fabrication value, mm')
        self.therm_ccx_mesh=wx.TextCtrl(model_pane,value='0.5')
        self.therm_ccx_bottom=wx.TextCtrl(model_pane,value='20')
        self.therm_ccx_executable=wx.TextCtrl(
            model_pane,value=self._calculix_executable)
        self.therm_ccx_executable.SetHint('Optional full path to ccx executable; otherwise PATH')
        self.therm_blur=wx.Choice(model_pane,choices=['0 · exact cell occupancy','0.5 cell','1 cell'])
        self.therm_blur.SetSelection(0)
        self.therm_model_jb=wx.ComboBox(model_pane,style=wx.CB_READONLY)
        self.therm_emissivity=wx.TextCtrl(model_pane,value='0.9')
        self.therm_air_board=wx.TextCtrl(model_pane,value='0')
        self.therm_air_sink=wx.TextCtrl(model_pane,value='0')
        self.therm_grid=wx.SpinCtrl(model_pane,min=12,max=80,initial=48,size=(80,-1))
        self.therm_sink_area=wx.TextCtrl(model_pane,value='');self.therm_sink_area.SetHint('One: 1200 · multiple: U1=1200, U2=800')
        for heading in (self.therm_model_enabled,
                        wx.StaticText(model_pane,label='Saved thickness used automatically'),
                        wx.StaticText(model_pane,label='Steady-state approximation; no CFD')):
            model_grid.Add(heading,0,wx.ALIGN_CENTER_VERTICAL)
            model_grid.AddSpacer(1)
        for label,control in [('In-plane board k W/m·K',self.therm_k),('Board emissivity 0–1',self.therm_emissivity),
                              ('Board airflow m/s',self.therm_air_board),('Sink airflow m/s',self.therm_air_sink),
                              ('Mesh cells · long axis',self.therm_grid),
                              ('Sink exposed area mm² by part',self.therm_sink_area),
                              ('Board model',self.therm_model_kind),
                              ('Dielectric k W/m·K (layered)',self.therm_dielectric_k),
                              ('Copper k W/m·K (layered)',self.therm_copper_k),
                              ('Via plating mm (layered)',self.therm_plating),
                              ('Copper simplification (layered)',self.therm_blur),
                              ('CalculiX XY mesh target mm',self.therm_ccx_mesh),
                              ('CalculiX lower-face temperature °C',self.therm_ccx_bottom),
                              ('CalculiX executable',self.therm_ccx_executable)]:
            caption=wx.StaticText(model_pane,label=label);caption.Wrap(140)
            model_grid.Add(caption,0,wx.ALIGN_CENTER_VERTICAL)
            model_grid.Add(control,1,wx.EXPAND)
        model_layout=wx.BoxSizer(wx.VERTICAL);model_layout.Add(model_grid,0,wx.EXPAND)
        solver_setup=wx.BoxSizer(wx.VERTICAL)
        self.therm_ccx_browse=wx.Button(model_pane,label='Locate CalculiX…')
        self.therm_ccx_browse.Bind(wx.EVT_BUTTON,self.on_calculix_browse)
        self.therm_ccx_check=wx.Button(model_pane,label='Check solver setup')
        self.therm_ccx_check.Bind(wx.EVT_BUTTON,self.on_calculix_check)
        self.therm_ccx_status=wx.StaticText(model_pane,label='Select CalculiX mode to check the external solver.')
        solver_setup.Add(self.therm_ccx_browse,0,wx.RIGHT,7)
        solver_setup.Add(self.therm_ccx_check,0,wx.RIGHT,10)
        solver_setup.Add(self.therm_ccx_status,0,wx.EXPAND|wx.TOP,5)
        model_layout.Add(solver_setup,0,wx.EXPAND|wx.TOP|wx.BOTTOM,8)
        self.therm_ccx_status.Wrap(250)
        mount_row=wx.BoxSizer(wx.VERTICAL)
        self.therm_mounts=wx.CheckListBox(model_pane,size=(240,80))
        self._therm_mount_candidates=[]
        mount_row.Add(self.therm_mounts,1,wx.EXPAND|wx.RIGHT,8)
        mount_fields=wx.FlexGridSizer(0,2,4,6)
        self.therm_mount_temp=wx.TextCtrl(model_pane,value='10')
        self.therm_mount_r=wx.TextCtrl(model_pane,value='0')
        self.therm_mount_mechanical=wx.CheckBox(model_pane,label='Mechanical fixture contacts selected NPTH holes')
        for label,ctrl in [('Fixture temperature °C',self.therm_mount_temp),('Contact resistance K/W',self.therm_mount_r)]:
            mount_fields.Add(wx.StaticText(model_pane,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            mount_fields.Add(ctrl,1,wx.EXPAND)
        mount_fields.AddGrowableCol(1,1);mount_row.Add(mount_fields,1,wx.EXPAND)
        contacts_note=wx.StaticText(model_pane,label='Fixed-temperature contacts · select saved plated pads. NPTH requires mechanical contact evidence.');contacts_note.Wrap(250)
        model_layout.Add(contacts_note,0,wx.TOP|wx.BOTTOM,6)
        model_layout.Add(mount_row,0,wx.EXPAND)
        model_layout.Add(self.therm_mount_mechanical,0,wx.TOP,5)
        losses=wx.Button(model_pane,label='Import PI copper losses…')
        losses.Bind(wx.EVT_BUTTON,self._import_copper_losses)
        model_layout.Add(losses,0,wx.EXPAND|wx.TOP,6)
        self.therm_copper_loss_status=wx.StaticText(model_pane,label='Copper losses: none imported')
        self.therm_copper_loss_status.Wrap(270)
        model_layout.Add(self.therm_copper_loss_status,0,wx.EXPAND|wx.TOP,4)
        clear_losses=wx.Button(model_pane,label='Clear imported losses')
        clear_losses.Bind(wx.EVT_BUTTON,lambda e:self._clear_copper_losses())
        model_layout.Add(clear_losses,0,wx.TOP,4)
        model_pane.SetSizer(model_layout);layout.Add(self.therm_model,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.therm_model.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(page.FitInside(),page.Layout()))
        self.therm_env.Bind(wx.EVT_CHOICE,lambda e:self._therm_controls())
        self._therm_controls()
        # The scope lives in the full-width editable inputs table. Keep the
        # existing checklist as the controller's scope store for editor sync.
        self.therm_refs=wx.CheckListBox(page);self.therm_refs.Hide()
        scope=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_scope=wx.StaticText(page,label='0 components included')
        scope.Add(self.therm_scope,1,wx.ALIGN_CENTER_VERTICAL)
        for label,checked in [('All',True),('None',False)]:
            button=wx.Button(page,label=label,size=(50,-1))
            button.Bind(wx.EVT_BUTTON,lambda e,checked=checked:self._check_thermal_refs(checked))
            scope.Add(button,0,wx.LEFT,4)
        layout.Add(scope,0,wx.EXPAND|wx.ALL,8)
        self.therm_run=wx.Button(page,label='▶  Run thermal');self.therm_run.Bind(wx.EVT_BUTTON,self.on_quick_therm)
        self.therm_whole_board=wx.Button(page,label='Board model…');self.therm_whole_board.Bind(wx.EVT_BUTTON,self.on_whole_board_setup)
        self.therm_whole_board.SetToolTip('Review materials and boundaries for a physical board field.')
        self.therm_sink_button=wx.Button(page,label='Heatsinks…');self.therm_sink_button.Bind(wx.EVT_BUTTON,self.on_virtual_heatsinks)
        self.therm_export=wx.Button(page,label='Export…');self.therm_export.Bind(wx.EVT_BUTTON,lambda e:self.on_export_diagnostic('quick_therm'))
        actions=wx.FlexGridSizer(0,2,5,5)
        for col in (0,1):actions.AddGrowableCol(col)
        for control in (self.therm_run,self.therm_whole_board,self.therm_sink_button,self.therm_export):actions.Add(control,0,wx.EXPAND)
        layout.Add(actions,0,wx.EXPAND|wx.ALL,8)
        self.therm_status=wx.StaticText(page,label='Open Component inputs to review scanned values and include parts.');self.therm_status.Wrap(270)
        layout.Add(self.therm_status,0,wx.EXPAND|wx.ALL,8)
        page.SetSizer(layout);page.FitInside()
        self.therm_model_jb.Hide()
        def compact(window):
            for child in window.GetChildren():
                if isinstance(child,wx.StaticText):
                    _wrap_text(child,child.GetLabel(),130 if child.GetParent() in (fields_host,model_pane,advanced_host) or child.GetContainingSizer() is transient_form else 270)
                elif isinstance(child,(wx.ComboBox,wx.Choice,wx.TextCtrl)):
                    child.SetMinSize((120,-1))
                elif isinstance(child,wx.Button):child.SetMinSize((90,-1))
                compact(child)
        compact(page);page.Layout();page.FitInside()
        workspace.Add(page,0,wx.EXPAND|wx.RIGHT,6)

        visual_host=wx.Panel(board_page)
        visual=wx.BoxSizer(wx.VERTICAL);switch=wx.WrapSizer(wx.HORIZONTAL)
        settings=wx.ToggleButton(visual_host,label='☰  Setup');settings.SetValue(True)
        settings.Bind(wx.EVT_TOGGLEBUTTON,lambda e:(page.Show(settings.GetValue()),board_page.Layout()))
        switch.Add(settings,0,wx.RIGHT,5)
        for label,mode in [('Top','Top-side map'),('Bottom','Bottom-side map'),('3D','3D overview')]:
            button=wx.Button(visual_host,label=label,size=(55,-1))
            button.Bind(wx.EVT_BUTTON,lambda e,mode=mode:self._set_thermal_view(mode))
            switch.Add(button,0,wx.RIGHT,4)
            if mode=='3D overview':self.therm_3d_button=button
        fit=wx.Button(visual_host,label='Fit',size=(45,-1));fit.Bind(wx.EVT_BUTTON,self._fit_thermal_view)
        switch.Add(fit,0,wx.RIGHT,5)
        self.therm_step_models=wx.CheckBox(visual_host,label='STEP models')
        self.therm_step_models.SetValue(True)
        self.therm_step_models.SetToolTip('Load actual saved STEP models with KiCad and FreeCAD when running. Missing models remain footprint outlines.')
        self.therm_step_models.Bind(wx.EVT_CHECKBOX,self._invalidate_thermal)
        switch.Add(self.therm_step_models,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
        self.therm_mode=wx.Choice(visual_host,choices=['Top-side map','Bottom-side map','Top-side contour','Bottom-side contour',
            'Top board model','Bottom board model','3D overview','Temperature chart']);self.therm_mode.SetSelection(0)
        switch.Add(self.therm_mode,0,wx.RIGHT,5)
        self.therm_result_time=wx.Choice(visual_host,choices=['Steady state']);self.therm_result_time.SetSelection(0)
        self.therm_result_time.Bind(wx.EVT_CHOICE,lambda e:self._thermal_time_changed());switch.Add(self.therm_result_time,0,wx.RIGHT,5)
        self.therm_probe_button=wx.ToggleButton(visual_host,label='⌖  Probe');self.therm_probe_button.Bind(wx.EVT_TOGGLEBUTTON,self._toggle_thermal_probe)
        switch.Add(self.therm_probe_button,0,wx.RIGHT,5)
        self.therm_expand=wx.Button(visual_host,label='Top + bottom');self.therm_expand.Bind(wx.EVT_BUTTON,self.on_expand_thermal)
        switch.Add(self.therm_expand,0,wx.RIGHT,5)
        inspect=wx.ToggleButton(visual_host,label='Details');inspect.SetValue(True);switch.Add(inspect,0)
        visual.Add(switch,0,wx.EXPAND|wx.BOTTOM,5)
        timeline=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_play=wx.Button(visual_host,label='▶ Play',size=(70,-1))
        self.therm_play.Bind(wx.EVT_BUTTON,self._toggle_thermal_playback);timeline.Add(self.therm_play,0,wx.RIGHT,5)
        self.therm_time_slider=wx.Slider(visual_host,minValue=0,maxValue=1,value=0)
        self.therm_time_slider.Bind(wx.EVT_SLIDER,self._scrub_thermal_time);timeline.Add(self.therm_time_slider,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
        self.therm_time_label=wx.StaticText(visual_host,label='Run a transient study');timeline.Add(self.therm_time_label,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
        self.therm_play_speed=wx.Choice(visual_host,choices=['1×','5×','20×']);self.therm_play_speed.SetSelection(1)
        self.therm_play_speed.Bind(wx.EVT_CHOICE,self._thermal_speed_changed);timeline.Add(self.therm_play_speed,0)
        visual.Add(timeline,0,wx.EXPAND|wx.BOTTOM,3)
        self.therm_figure=Figure(figsize=(8,6),dpi=100);self.therm_canvas=FigureCanvasWxAgg(visual_host,wx.ID_ANY,self.therm_figure)
        self.therm_canvas.SetMinSize((250,250))
        self.therm_canvas.mpl_connect('button_press_event',self._thermal_plot_pressed)
        self.therm_canvas.mpl_connect('button_release_event',self._thermal_plot_clicked)
        self.therm_canvas.mpl_connect('motion_notify_event',self._thermal_plot_hovered)
        self.therm_canvas.mpl_connect('scroll_event',self._thermal_plot_scrolled)
        self.therm_canvas.Bind(wx.EVT_LEAVE_WINDOW,self._clear_thermal_hover)
        self.therm_navigation=NavigationToolbar2WxAgg(self.therm_canvas);self.therm_navigation.Realize()
        visual.Add(self.therm_navigation,0,wx.EXPAND)
        visual.Add(self.therm_canvas,1,wx.EXPAND)
        self.therm_cursor=wx.StaticText(visual_host,label='Hover to inspect · drag to pan · wheel to zoom · 3D: drag to orbit')
        visual.Add(self.therm_cursor,0,wx.EXPAND|wx.TOP,4)
        visual_host.SetSizer(visual);workspace.Add(visual_host,1,wx.EXPAND)

        inspector=wx.Notebook(board_page);inspector.SetMinSize((300,-1))
        self.therm_inspector=inspector
        inspect.Bind(wx.EVT_TOGGLEBUTTON,lambda e:(inspector.Show(inspect.GetValue()),board_page.Layout()))
        details=wx.ScrolledWindow(inspector);details.SetScrollRate(0,10);detail_layout=wx.BoxSizer(wx.VERTICAL)
        self.therm_view_note=wx.StaticText(details,label='Junction estimates and interpolated fields are distinct from physical board fields.');self.therm_view_note.Wrap(270)
        detail_layout.Add(self.therm_view_note,0,wx.EXPAND|wx.ALL,8)
        self.therm_analytics=wx.StaticText(details,label='Run thermal to see temperatures, power and coverage.');self.therm_analytics.Wrap(270)
        detail_layout.Add(self.therm_analytics,0,wx.EXPAND|wx.ALL,8)
        self.therm_selection_detail=wx.StaticText(details,label='Select a component on the board or in the inputs/results table.');self.therm_selection_detail.Wrap(270)
        detail_layout.Add(self.therm_selection_detail,0,wx.EXPAND|wx.ALL,8)
        angles=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_azim=wx.SpinCtrl(details,min=-180,max=180,initial=-60,size=(70,-1))
        self.therm_elev=wx.SpinCtrl(details,min=-90,max=90,initial=28,size=(65,-1))
        for label,ctrl in [('Azimuth',self.therm_azim),('Elevation',self.therm_elev)]:
            angles.Add(wx.StaticText(details,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4);angles.Add(ctrl,0,wx.RIGHT,5)
        detail_layout.Add(angles,0,wx.ALL,8)
        self.therm_sync=wx.Button(details,label='Read PCB selection');self.therm_sync.Bind(wx.EVT_BUTTON,self._sync_thermal_selection)
        detail_layout.Add(self.therm_sync,0,wx.ALL,8)
        details.SetSizer(detail_layout);inspector.AddPage(details,'Details')
        self.therm_table=wx.ListCtrl(inspector,style=wx.LC_REPORT)
        for i,(name,width) in enumerate([('Reference',80),('Junction °C',95),('Min Tj °C',85),('Max Tj °C',85),
            ('Limit check',85),('Power W',75),('Side',55),('Heat path',100),('Rθ K/W',80),('Rise K',75),
            ('Board site °C',100),('Sink °C',80),('Component °C',105),('X mm',75),('Y mm',75),('Status',200)]):
            self.therm_table.InsertColumn(i,name,width=width)
        inspector.AddPage(self.therm_table,'Results')
        probes=wx.Panel(inspector);probe_layout=wx.BoxSizer(wx.VERTICAL)
        self.therm_clear_probes=wx.Button(probes,label='Clear probes');self.therm_clear_probes.Bind(wx.EVT_BUTTON,self._clear_thermal_probes)
        probe_layout.Add(self.therm_clear_probes,0,wx.ALL,5)
        self.therm_probe_table=wx.ListCtrl(probes,style=wx.LC_REPORT)
        for i,(name,width) in enumerate([('Probe',65),('Side',60),('X mm',75),('Y mm',75),('Temperature °C',120),('Source',180),('Status',90)]):self.therm_probe_table.InsertColumn(i,name,width=width)
        probe_layout.Add(self.therm_probe_table,1,wx.EXPAND);probes.SetSizer(probe_layout);inspector.AddPage(probes,'Probes')
        workspace.Add(inspector,0,wx.EXPAND|wx.LEFT,6)
        board_page.SetSizer(workspace);self.book.AddPage(board_page,'Board + results')

        inputs_page=wx.Panel(self.book);inputs_layout=wx.BoxSizer(wx.VERTICAL)
        from .component_input_grid import ComponentInputPanel
        self.therm_inputs=ComponentInputPanel(inputs_page,on_change=self._component_inputs_changed,on_select=self._component_input_selected)
        inputs_layout.Add(self.therm_inputs,1,wx.EXPAND|wx.ALL,8)
        input_actions=wx.BoxSizer(wx.HORIZONTAL)
        mapping_button=wx.Button(inputs_page,label='Field mapping…');mapping_button.Bind(wx.EVT_BUTTON,self._show_field_mapping)
        run_button=wx.Button(inputs_page,label='▶  Run thermal');run_button.Bind(wx.EVT_BUTTON,self.on_quick_therm)
        input_actions.Add(mapping_button,0,wx.RIGHT,6);input_actions.AddStretchSpacer();input_actions.Add(run_button,0)
        inputs_layout.Add(input_actions,0,wx.EXPAND|wx.ALL,8);inputs_page.SetSizer(inputs_layout)
        self.book.AddPage(inputs_page,'Component inputs',select=True)
        self._thermal_rows=[];self._thermal_selected=None;self._thermal_sort=(1,True)
        self.therm_mode.Bind(wx.EVT_CHOICE,self._thermal_mode_changed)
        self.therm_azim.Bind(wx.EVT_SPINCTRL,lambda e:self._draw_thermal())
        self.therm_elev.Bind(wx.EVT_SPINCTRL,lambda e:self._draw_thermal())
        self.therm_table.Bind(wx.EVT_LIST_ITEM_SELECTED,self._thermal_table_selected)
        self.therm_table.Bind(wx.EVT_LIST_COL_CLICK,self._thermal_sort_clicked)
        for ctrl in (self.therm_power,self.therm_ja,self.therm_jb,self.therm_jc,
                     self.therm_limit_min,self.therm_limit_max):ctrl.Bind(wx.EVT_COMBOBOX,self._invalidate_thermal)
        self.therm_env.Bind(wx.EVT_CHOICE,self._thermal_environment_changed)
        for ctrl in (self.therm_ambient,self.therm_board_r):ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        for ctrl in (self.therm_k,self.therm_emissivity,self.therm_air_board,self.therm_air_sink,self.therm_sink_area,
                     self.therm_dielectric_k,self.therm_copper_k,self.therm_plating,self.therm_mount_temp,self.therm_mount_r,
                     self.therm_ccx_mesh,self.therm_ccx_bottom,self.therm_ccx_executable):ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        self.therm_model_jb.Bind(wx.EVT_COMBOBOX,self._invalidate_thermal)
        self.therm_grid.Bind(wx.EVT_SPINCTRL,self._invalidate_thermal)
        self.therm_model_enabled.Bind(wx.EVT_CHECKBOX,self._therm_model_changed)
        self.therm_model_kind.Bind(wx.EVT_CHOICE,self._therm_model_changed)
        self.therm_blur.Bind(wx.EVT_CHOICE,self._invalidate_thermal)
        self.therm_mounts.Bind(wx.EVT_CHECKLISTBOX,self._invalidate_thermal)
        self.therm_mount_mechanical.Bind(wx.EVT_CHECKBOX,self._invalidate_thermal)
        self.therm_refs.Bind(wx.EVT_CHECKLISTBOX,self._invalidate_thermal)
        page.Layout();page.FitInside()


    def _therm_controls(self):
        vacuum=self.therm_env.GetSelection()==1
        selected=self.therm_model_kind.GetSelection() if self.therm_model_enabled.GetValue() else -1
        for ctrl in (self.therm_time_enabled,self.therm_env,self.therm_ambient,self.therm_input_mode,
                     self.therm_model_enabled,self.therm_model_kind):ctrl.Enable(not self._busy)
        for ctrl in (self.therm_time_duration,self.therm_time_step,self.therm_time_initial,
                     self.therm_copper_capacity,self.therm_dielectric_capacity,self.therm_power_schedule,
                     self.therm_sink_capacity,self.therm_schedule_interpolation,self.therm_power_steps):
            ctrl.Enable(self.therm_time_enabled.GetValue() and not self._busy)
        environment=self.therm_env.GetSelection()
        _wrap_text(self.therm_environment_note,(
            'Air: convection + radiation to ambient. Airflow is a boundary assumption.' if environment==0 else
            'Vacuum: convection is zero. Review emissivity and fixture conduction; in-air RθJA is not used.' if vacuum else
            'Forced air: enter the effective convection coefficient.' if environment==2 else
            'Potting: declared coating resistance to external ambient.' if environment==3 else
            'Sealed enclosure: fixed enclosure temperature boundary.'))
        # These are input mappings, not a statement of which heat path a run uses.
        for ctrl in (self.therm_ja,self.therm_jb,self.therm_jc,self.therm_model_jb):
            ctrl.Enable(not self._busy)
        self.therm_board_r.Enable(vacuum and selected not in (1,2))
        self.therm_emissivity.Enable(selected in (0,1) and not self._busy)
        for ctrl in (self.therm_grid,self.therm_sink_area):
            ctrl.Enable(selected in (0,1) and not self._busy)
        for ctrl in (self.therm_air_board,self.therm_air_sink):
            ctrl.Enable(selected in (0,1) and environment==0 and not self._busy)
        self.therm_explicit_h.Enable(environment in (2,4) and not self._busy)
        self.therm_enclosure_c.Enable(environment==4 and not self._busy)
        for ctrl in (self.therm_potting_k,self.therm_potting_thickness,self.therm_potting_outer_h):
            ctrl.Enable(environment==3 and not self._busy)
        if hasattr(self,'therm_sink_button'):
            self.therm_sink_button.Enable(selected!=2 and not self._busy)
        self.therm_k.Enable(selected==0 and not self._busy)
        for ctrl in (self.therm_dielectric_k,self.therm_copper_k):
            ctrl.Enable(selected in (1,2) and not self._busy)
        for ctrl in (self.therm_plating,self.therm_blur,self.therm_mounts,self.therm_mount_temp,
                     self.therm_mount_r,self.therm_mount_mechanical):
            ctrl.Enable(selected==1 and not self._busy)
        for ctrl in (self.therm_ccx_mesh,self.therm_ccx_bottom,self.therm_ccx_executable):
            ctrl.Enable(selected==2 and not self._busy)
        for ctrl in (self.therm_ccx_browse,self.therm_ccx_check):
            ctrl.Enable(selected==2 and not self._busy)
        self._update_thermal_timeline()

    def _thermal_environment_changed(self,event=None):
        self._invalidate_thermal(event)
        self._therm_input_page.Layout();self._therm_input_page.FitInside()

    def _transient_setup_changed(self,event=None):
        enabled=self.therm_time_enabled.GetValue()
        self.therm_transient_pane.Collapse(not enabled)
        if enabled:
            self.therm_model_enabled.SetValue(True)
            self.therm_model_kind.SetSelection(1)
            self.therm_grid.SetRange(24,80)
            self.therm_model.Collapse(False)
        self._invalidate_thermal(event)
        self._therm_input_page.Layout();self._therm_input_page.FitInside()

    def _edit_power_steps(self,event=None):
        import wx.grid
        from .thermal_playback import step_schedules
        references=self.therm_inputs.selected_references()
        if not references:
            self.status.SetLabel('Include heat sources in Component inputs before editing power steps.');return
        self.therm_inputs.commit_pending_edits()
        dialog=wx.Dialog(self,title='Transient power steps',size=(660,420))
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='Multiplier × entered power. Leave switch time blank for constant power.\nFor several steps or ramps use Advanced schedules + sinks.')
        layout.Add(note,0,wx.ALL,10)
        grid=wx.grid.Grid(dialog);grid.CreateGrid(len(references),5)
        for column,label in enumerate(('Part','Base W','Initial ×','Switch s','After ×')):grid.SetColLabelValue(column,label)
        try:previous=json.loads(self.therm_power_schedule.GetValue())
        except ValueError:previous={}
        if not isinstance(previous,dict) or any(not isinstance(points,list) or not points or len(points)>2 or
                any(not isinstance(point,list) or len(point)!=2 for point in points) for points in previous.values()):
            dialog.Destroy();self.status.SetLabel('Existing multi-step profiles: edit Advanced schedules + sinks to retain every event.');return
        values=self.therm_inputs.effective_values(include_limits=False)
        for row,ref in enumerate(references):
            points=previous.get(ref,[[0,1]])
            cells=[ref,str(values.get(ref,{}).get('power_w','Unknown')),str(points[0][1]),
                   str(points[1][0]) if len(points)==2 else '',str(points[1][1]) if len(points)==2 else '']
            for column,value in enumerate(cells):grid.SetCellValue(row,column,value)
            grid.SetReadOnly(row,0);grid.SetReadOnly(row,1)
        grid.AutoSizeColumns();layout.Add(grid,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        error=wx.StaticText(dialog,label='');layout.Add(error,0,wx.EXPAND|wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10)
        def apply(event):
            grid.SaveEditControlValue();grid.HideCellEditControl()
            try:
                schedules=step_schedules([(ref,grid.GetCellValue(row,2),grid.GetCellValue(row,3),grid.GetCellValue(row,4))
                    for row,ref in enumerate(references)],float(self.therm_time_duration.GetValue()))
            except ValueError as exc:error.SetLabel(str(exc));return
            self.therm_power_schedule.ChangeValue(json.dumps(schedules))
            self.therm_schedule_interpolation.SetSelection(1)
            self._invalidate_thermal();dialog.EndModal(wx.ID_OK)
        dialog.Bind(wx.EVT_BUTTON,apply,id=wx.ID_OK);dialog.SetSizer(layout)
        dialog.ShowModal();dialog.Destroy()

    def _edit_component_storage(self,event=None):
        references=self.therm_inputs.selected_references()
        if not references:
            self.status.SetLabel('Include heat sources in Component inputs before entering thermal RC.');return
        from .component_storage_inputs import edit_storage
        if getattr(self,'_component_storage_board_sha',None)!=self.inventory.get('source_sha256'):
            self._component_storage={}
        updated=edit_storage(self,references,self._component_storage)
        if updated is None:return
        self._component_storage=updated
        self._component_storage_board_sha=self.inventory.get('source_sha256')
        if updated:
            self.therm_model_enabled.SetValue(True);self.therm_model_kind.SetSelection(1)
            self.therm_time_enabled.SetValue(True);self._transient_setup_changed()
            self.therm_step_models.SetValue(True)
        self._invalidate_thermal()
        self.status.SetLabel(f'{len(updated)} component RC definitions. Run to compute their heating.')

    def _clear_copper_losses(self):
        self._copper_loss_import=None
        self.therm_copper_loss_status.SetLabel('Copper losses: none imported')
        self._invalidate_thermal()

    def _import_copper_losses(self,event=None):
        with wx.FileDialog(self,'Import solved Quick PI JSON report',wildcard='JSON reports (*.json)|*.json',
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as picker:
            if picker.ShowModal()!=wx.ID_OK:return
            from .copper_loss_import import import_losses
            try:
                path=Path(picker.GetPath())
                if path.stat().st_size>100*1024*1024:raise ValueError('PI report exceeds 100 MiB.')
                imported=import_losses(json.loads(path.read_text(encoding='utf-8-sig')),self.inventory.get('source_sha256'))
            except (ValueError,OSError,KeyError,TypeError) as exc:
                self.status.SetLabel('Copper loss import: '+str(exc));return
        self._copper_loss_import=imported
        self.therm_model_enabled.SetValue(True);self.therm_model_kind.SetSelection(1)
        self.therm_copper_loss_status.SetLabel(f"{len(imported['sources'])} conductor sources · {imported['input_w']:.5g} W. "+imported['meaning'])
        self.therm_copper_loss_status.Wrap(270)
        self._invalidate_thermal()

    def on_calculix_browse(self,event=None):
        with wx.FileDialog(self,'Select CalculiX ccx executable',
                           style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as picker:
            if picker.ShowModal()!=wx.ID_OK:return
            self.therm_ccx_executable.SetValue(picker.GetPath())
        self.on_calculix_check()

    def on_calculix_check(self,event=None):
        from .thermal_calculix import find_calculix
        try:
            solver=find_calculix(self.therm_ccx_executable.GetValue().strip() or None)
        except ValueError as exc:
            self.therm_ccx_status.SetLabel(str(exc))
            return False
        if not solver:
            self.therm_ccx_status.SetLabel('CalculiX ccx is missing. Locate it above or add it to PATH.')
            return False
        self.therm_ccx_status.SetLabel('Ready: '+Path(solver).name+' · Gmsh will be checked when the model runs.')
        chosen=self.therm_ccx_executable.GetValue().strip()
        if chosen:
            with wx.LogNull():
                saved=self._solver_config.Write('calculix_executable',chosen) and self._solver_config.Flush()
            if not saved:self.therm_ccx_status.SetLabel(self.therm_ccx_status.GetLabel()+' · Preference could not be saved.')
        return True


    def _input_mode_changed(self,event=None):
        manual=self.therm_input_mode.GetSelection()==0
        self.therm_fields_pane.Collapse(manual)
        self.therm_manual_button.Enable(not self._busy)
        self._therm_input_page.FitInside()
        self.main_panel.Layout()
        self._invalidate_thermal(event)
        self.therm_status.SetLabel('Select dissipating components, then enter their power and Rθ.' if manual else
                                   'Map saved power and thermal-resistance footprint fields, then select components.')


    def on_manual_setup(self,event=None):
        self.book.SetSelection(1)
        self.therm_inputs.grid.SetFocus()
        self.status.SetLabel('Edit scanned values or fill unknown cells. Select all / none controls the run scope.')
        return True

    def _thermal_field_map(self):
        return {key:ctrl.GetValue() for key,ctrl in (
            ('power_w',self.therm_power),('theta_ja_air_k_per_w',self.therm_ja),
            ('theta_jb_k_per_w',self.therm_jb),('theta_jc_k_per_w',self.therm_jc))}

    def _temperature_field_map(self):
        return {key:ctrl.GetValue() for key,ctrl in (
            ('minimum_c',self.therm_limit_min),('maximum_c',self.therm_limit_max)) if ctrl.GetValue()}

    def _component_inputs_changed(self,state):
        self.manual_values=state['manual_values']
        self.manual_temperature_limits=state['manual_limits']
        selected=set(state['references'])
        for i in range(self.therm_refs.GetCount()):
            self.therm_refs.Check(i,self.therm_refs.GetString(i) in selected)
        self._update_thermal_scope()
        self._invalidate_thermal()

    def _update_thermal_scope(self):
        count=sum(self.therm_refs.IsChecked(i) for i in range(self.therm_refs.GetCount()))
        self.therm_scope.SetLabel(f'{count} / {self.therm_refs.GetCount()} included')

    def _component_input_selected(self,reference):
        item=next((item for item in self.thermal_bundle.get('board_thermal_view',{}).get('components',[])
                   if item['reference']==reference),None)
        if item:self._thermal_choose(item['id'],from_editor=True)

    def _show_field_mapping(self,event=None):
        self.book.SetSelection(0)
        self._therm_input_page.Show();self.therm_fields_pane.Collapse(False)
        self._therm_input_page.Layout();self._therm_input_page.FitInside();self.therm_board_page.Layout()

    def _set_thermal_view(self,mode):
        self.book.SetSelection(0)
        self.therm_mode.SetStringSelection(mode)
        self._thermal_mode_changed()
        if not self.thermal_bundle:self.status.SetLabel('Run thermal first to inspect interactive board results.')

    def _fit_thermal_view(self,event=None):
        if not self.therm_figure.axes:return
        if self.therm_mode.GetStringSelection()=='3D overview':
            from .thermal_plot import fit_thermal_3d
            fit_thermal_3d(self.therm_figure.axes[0]);self.therm_canvas.draw_idle()
        else:self._draw_thermal()

    def _therm_model_changed(self,event):
        self.therm_grid.SetRange(24 if self.therm_model_kind.GetSelection()==1 else 12,80)
        self._therm_controls()
        self._invalidate_thermal(event)
        if self.therm_model_enabled.GetValue() and self.therm_model_kind.GetSelection()==2:
            self.on_calculix_check()


    def on_whole_board_setup(self,event=None):
        """Expose the existing physical study inputs without extrapolating junctions."""
        if self._busy:return
        self.book.SetSelection(0);self._therm_input_page.Show();self.therm_board_page.Layout()
        changed=not self.therm_model_enabled.GetValue()
        self.therm_model_enabled.SetValue(True)
        self.therm_model.Collapse(False)
        self._therm_controls()
        if changed:self._invalidate_thermal()
        self._thermal_default_view=True
        page=self._therm_input_page
        page.Layout();page.FitInside()
        point=page.CalcUnscrolledPosition(self.therm_model.GetPosition())
        page.Scroll(0,max(0,point.y//10))
        focus=self.therm_k if self.therm_model_kind.GetSelection()==0 else self.therm_dielectric_k
        focus.SetFocus()
        self.therm_status.SetLabel('Whole-board setup: review material conductivity, saved thickness and cooling/fixture boundaries; include every actual heat source, then Run QuickTherm. Existing values are retained, not inferred from the contour.')

    def on_virtual_heatsinks(self,event=None):
        from .virtual_heatsink_editor import VirtualHeatsinkDialog
        references=[self.therm_refs.GetString(i) for i in range(self.therm_refs.GetCount())]
        if not references:
            self.therm_status.SetLabel('Load a saved board with footprints before assigning virtual heatsinks.');return
        updated=VirtualHeatsinkDialog(self,references,self.virtual_heatsinks).show()
        if updated is not None:
            self.virtual_heatsinks=updated;self._therm_controls();self._invalidate_thermal()
            self.therm_status.SetLabel(f'{len(updated)} virtual heatsink assignment(s). Map RθJC and rerun QuickTherm.')


    def _check_thermal_refs(self,checked):
        for index in range(self.therm_refs.GetCount()):self.therm_refs.Check(index,checked)
        self.therm_inputs.model.select_all(included=checked)
        self.therm_inputs._refresh_rows()
        self._update_thermal_scope()
        self._invalidate_thermal()


    def _invalidate_thermal(self,event=None):
        self._stop_thermal_playback()
        self._thermal_frame_cache=None
        if event and event.GetEventObject() in (self.therm_power,self.therm_ja,self.therm_jb,self.therm_jc,
                self.therm_limit_min,self.therm_limit_max):
            self.therm_inputs.set_mappings(self._thermal_field_map(),self._temperature_field_map())
        self.thermal_bundle={};self.therm_table.DeleteAllItems();self.therm_figure.clear()
        self._thermal_rows=[];self._thermal_selected=None;self.therm_analytics.SetLabel('Run QuickTherm to see min, max, mean, median and coverage.')
        _wrap_text(self.therm_analytics,self.therm_analytics.GetLabel())
        _wrap_text(self.therm_status,self.therm_status.GetLabel())
        self.therm_canvas.draw_idle();self.therm_status.SetLabel('Inputs changed. Run QuickTherm to update the estimate.')
        self._buttons()
        if event:event.Skip()


    def on_quick_therm(self,event=None):
        if self._busy:return
        environment=('air','vacuum','forced_air','potting','sealed')[self.therm_env.GetSelection()]
        references=[self.therm_refs.GetString(i) for i in range(self.therm_refs.GetCount()) if self.therm_refs.IsChecked(i)]
        sinks={ref:self.virtual_heatsinks[ref] for ref in references if ref in self.virtual_heatsinks}
        unsinked=set(references)-set(sinks)
        field=self.therm_jb if environment=='vacuum' else self.therm_ja
        kind='theta_jb_k_per_w' if environment=='vacuum' else 'theta_ja_air_k_per_w'
        manual=self.therm_input_mode.GetSelection()==0
        calculix=(self.therm_model_enabled.GetValue() and
                  self.therm_model_kind.GetSelection()==2)
        board_power_only=self.therm_model_enabled.GetValue() and not sinks
        power_only=board_power_only or calculix or (environment=='vacuum' and self.therm_model_enabled.GetValue() and self.therm_model_kind.GetSelection()==1) or environment not in ('air','vacuum') or self.therm_time_enabled.GetValue()
        if not references and not self._copper_loss_import:
            self.therm_status.SetLabel('Select at least one dissipating component before running QuickTherm.');return
        if manual:
            try:
                # Commit the active grid editor before taking a detached worker copy.
                self.therm_inputs.commit_pending_edits()
                if self.manual_values!=self.therm_inputs.model.manual_values():
                    self.therm_inputs.load(self.inventory,self._thermal_field_map(),
                        self.manual_values,references,self._temperature_field_map())
                effective=self.therm_inputs.effective_values(include_limits=False)
                missing=[ref for ref in references if 'power_w' not in effective.get(ref,{}) or
                    (not power_only and ('theta_jc_k_per_w' if ref in sinks else kind) not in effective.get(ref,{}))]
                if missing:
                    self.on_manual_setup()
                    self.status.SetLabel('Missing power or required heat-path resistance: '+', '.join(missing[:12]))
                    return
            except ValueError as exc:
                self.on_manual_setup();self.status.SetLabel(str(exc));return
        elif references and (not self.therm_power.GetValue() or (not power_only and unsinked and not field.GetValue()) or (not power_only and sinks and not self.therm_jc.GetValue())):
            self.therm_status.SetLabel('Map power and RθJA/RθJB for selected parts, plus RθJC for virtual heatsinks.');return
        try:
            request={'action':'quick_therm','board_path':self.board_path,'environment':environment,
                     'ambient_c':float(self.therm_ambient.GetValue()),'references':references,
                     'expected_source_sha256':self.inventory.get('source_sha256'),
                     'heatsinks':sinks,
                     'board_power_only':board_power_only,
                     'limit_fields':{key:name for key,name in (
                         ('minimum_c',self.therm_limit_min.GetValue()),
                         ('maximum_c',self.therm_limit_max.GetValue())) if name},
                     'probes':list(self.therm_probe_definitions)}
            request['load_step_models']=self.therm_step_models.GetValue()
            if manual:
                request['input_mode']='manual'
                request['manual_values']={ref:effective[ref] for ref in references}
                request['manual_temperature_limits']=self.therm_inputs.export_state()['manual_limits']
                request['component_input_sources']={ref:{key:{
                    'source':cell.source,'field':cell.source_field,'saved_value':cell.source_raw}
                    for key in effective[ref] if (cell:=self.therm_inputs.model.cell(ref,key))}
                    for ref in references}
            else:
                request['field_map']={'power_w':self.therm_power.GetValue()}
                if field.GetValue() and not power_only:request['field_map'][kind]=field.GetValue()
                if sinks:request['field_map']['theta_jc_k_per_w']=self.therm_jc.GetValue()
            if environment=='vacuum' and unsinked and not power_only:
                request['vacuum_board_to_environment_k_per_w']=float(self.therm_board_r.GetValue())
        except ValueError as exc:self.therm_status.SetLabel('Enter valid ambient and board-to-environment values: '+str(exc));return
        if (environment not in ('air','vacuum') or self.therm_time_enabled.GetValue()) and (not self.therm_model_enabled.GetValue() or self.therm_model_kind.GetSelection()!=1):
            self.therm_status.SetLabel('This environment or time-varying run requires the multilayer board model.');return
        if self.therm_model_enabled.GetValue():
            try:
                model_index=self.therm_model_kind.GetSelection()
                if model_index==2 and sinks:
                    raise ValueError('CalculiX board mode does not model virtual heatsinks.')
                if model_index==2 and not self.on_calculix_check():
                    self.therm_status.SetLabel(self.therm_ccx_status.GetLabel())
                    return
                settings={} if model_index==2 else {
                    'board_k_w_mk':float(self.therm_k.GetValue()),
                    'board_emissivity':float(self.therm_emissivity.GetValue()),
                    'board_airflow_m_s':float(self.therm_air_board.GetValue()),
                    'sink_airflow_m_s':float(self.therm_air_sink.GetValue()),
                    'grid_cells_long_axis':self.therm_grid.GetValue()}
                storage=self._component_storage if getattr(self,'_component_storage_board_sha',None)==self.inventory.get('source_sha256') else {}
                storage={ref:values for ref,values in storage.items() if ref in references}
                if storage and model_index!=1:
                    raise ValueError('Component heating requires the multilayer board model.')
                if storage:
                    settings['component_storage']={ref:{key:value for key,value in spec.items() if key!='contact_pad_number'} for ref,spec in storage.items()}
                    settings['source_contact_pad_numbers']={ref:spec['contact_pad_number'] for ref,spec in storage.items() if spec.get('contact_pad_number')}
                imported=self._copper_loss_import
                if imported:
                    if model_index!=1:raise ValueError('Copper loss transfer requires the multilayer board model.')
                    if imported['source_sha256']!=self.inventory.get('source_sha256'):
                        raise ValueError('Imported PI losses are stale; clear them and regenerate the PI report.')
                    settings['copper_loss_sources']=imported['sources']
                    request['copper_loss_binding']={key:value for key,value in imported.items() if key!='sources'}
                if environment=='vacuum':
                    settings.update(board_airflow_m_s=0, sink_airflow_m_s=0, board_h_w_m2k=0, sink_h_w_m2k=0)
                if environment in ('forced_air','sealed'):
                    settings['board_h_w_m2k']=float(self.therm_explicit_h.GetValue())
                if environment=='sealed':settings['enclosure_temperature_c']=float(self.therm_enclosure_c.GetValue())
                if environment=='potting':
                    settings.update(potting_k_w_mk=float(self.therm_potting_k.GetValue()),potting_thickness_mm=float(self.therm_potting_thickness.GetValue()),potting_outer_h_w_m2k=float(self.therm_potting_outer_h.GetValue()))
                if self.therm_time_enabled.GetValue():
                    request['transient_settings']={'duration_s':float(self.therm_time_duration.GetValue()),'timestep_s':float(self.therm_time_step.GetValue()),'initial_c':float(self.therm_time_initial.GetValue()),'copper_volumetric_capacity_j_m3k':float(self.therm_copper_capacity.GetValue()),'dielectric_volumetric_capacity_j_m3k':float(self.therm_dielectric_capacity.GetValue()),'power_schedules':json.loads(self.therm_power_schedule.GetValue()),'sink_capacity_j_k':json.loads(self.therm_sink_capacity.GetValue()),'schedule_interpolation':('linear','step')[self.therm_schedule_interpolation.GetSelection()]}
                if sinks:
                    settings['sink_exposed_area_mm2']=_parse_sink_areas(self.therm_sink_area.GetValue(),sinks)
                if model_index==1:
                    request['thermal_model_kind']='multilayer'
                    settings.update({'dielectric_k_w_mk':float(self.therm_dielectric_k.GetValue()),
                                     'copper_k_w_mk':float(self.therm_copper_k.GetValue()),
                                     'via_plating_mm':float(self.therm_plating.GetValue()),
                                     'copper_blur_cells':(0,.5,1)[self.therm_blur.GetSelection()],
                                     'mount_boundaries':[{'id':self._therm_mount_candidates[i]['id'],
                                         'temperature_c':float(self.therm_mount_temp.GetValue()),
                                         'contact_r_k_w':float(self.therm_mount_r.GetValue()),
                                         'mechanical_contact':self.therm_mount_mechanical.GetValue() and not self._therm_mount_candidates[i]['plated']}
                                         for i in range(self.therm_mounts.GetCount()) if self.therm_mounts.IsChecked(i)]})
                elif model_index==2:
                    request['thermal_model_kind']='calculix'
                    request['calculix_settings']={
                        'gmsh_mesh_size_mm':float(self.therm_ccx_mesh.GetValue()),
                        'display_grid_mm':float(self.therm_ccx_mesh.GetValue())/2,
                        'bottom_temperature_c':float(self.therm_ccx_bottom.GetValue()),
                        'dielectric_k_w_mk':float(self.therm_dielectric_k.GetValue()),
                        'copper_k_w_mk':float(self.therm_copper_k.GetValue())}
                    executable=self.therm_ccx_executable.GetValue().strip()
                    if executable:request['calculix_executable']=executable
                    request['calculix_run']=True
                request['thermal_network_settings']=settings
                if not manual and self.therm_jb.GetValue():request['thermal_network_component_field']=self.therm_jb.GetValue()
            except ValueError as exc:
                self.therm_status.SetLabel('Enter numeric thermal material, plating, contact and airflow values: '+str(exc));return
        self._stop_thermal_playback()
        self.thermal_bundle={};self.therm_table.DeleteAllItems();self._thermal_rows=[];self._thermal_selected=None
        self.therm_figure.clear();self.therm_canvas.draw_idle();self.therm_analytics.SetLabel('Analysis running…')
        self.therm_status.SetLabel('Reading saved board geometry and running the selected thermal model…')
        self._job(request,self._accept_therm,'Running QuickTherm on the saved board…')


    def _accept_therm(self,bundle):
        self.book.SetSelection(0)
        self.thermal_bundle=bundle;result=bundle['quick_therm']
        self._populate_thermal_probes()
        network=bundle.get('thermal_network') or {}
        self._stop_thermal_playback()
        self._thermal_frame_cache=None
        frames=(network.get('transient') or {}).get('frames',[])
        self.therm_result_time.Set(['Steady state']+[f"{frame['time_s']:.3g} s" for frame in frames])
        self.therm_result_time.SetSelection(1 if frames else 0)
        from .thermal_playback import transient_temperature_limits
        self._thermal_time_limits=transient_temperature_limits(network.get('transient') or {})
        self._update_thermal_timeline()
        original_mode=self.therm_mode.GetStringSelection()
        modes=['Top-side map','Bottom-side map','Top-side contour','Bottom-side contour',
               'Top board model','Bottom board model','3D overview','Temperature chart']
        modes.extend('Layer model: '+layer['name'] for layer in network.get('layers',[]))
        self.therm_mode.Set(modes)
        view=bundle.get('board_thermal_view',{})
        from .thermal_plot import default_thermal_mode
        if self._thermal_default_view or original_mode not in modes:
            original_mode=default_thermal_mode(view,network,'bottom' if 'Bottom' in original_mode or original_mode.startswith('Layer model: B.') else 'top')
            if view.get('component_models',{}).get('components'):original_mode='3D overview'
        self.therm_mode.SetStringSelection(original_mode)
        solved={row['reference']:row for row in result['components']}
        self._thermal_rows=[(item,solved.get(item['reference'])) for item in view.get('components',[]) if item.get('in_scope')]
        self._populate_thermal_table();self._draw_thermal()
        stats=view.get('analytics',{});temperature=stats.get('temperature_c',{})
        def fmt(key):return '—' if temperature.get(key) is None else f"{temperature[key]:.3g} °C"
        self.therm_analytics.SetLabel('Estimated junctions  ·  Min '+fmt('min')+'  ·  Max '+fmt('max')+
            '  ·  Mean '+fmt('mean')+'  ·  Median '+fmt('median')+
            f"  ·  Power {stats.get('power_w',{}).get('solved_total',0):.3g} W"+
            '  ·  Hottest '+str(stats.get('hottest_reference') or '—')+
            '  ·  Limits '+bundle.get('temperature_limits',{}).get('status','UNKNOWN'))
        _wrap_text(self.therm_analytics,self.therm_analytics.GetLabel())
        coverage=result['coverage'];board=f" · board {result['board_c']:.4g} °C" if result.get('board_c') is not None else ''
        network=bundle.get('thermal_network')
        if network:
            balance=network['heat_balance']
            if network.get('model') == 'CalculiX 3D steady conduction':
                layers=network['layers'];lo=min(row['sampled_min_c'] for row in layers)
                hi=max(row['sampled_max_c'] for row in layers)
                board+=(f" · CalculiX top/bottom {lo:.3g}–{hi:.3g} °C"
                        f" · lower-face outflow {balance['bottom_outflow_w']:.3g} W"
                        f" · heat residual {balance['residual_w']:.3g} W")
            elif network.get('layers'):
                layers=network['layers'];lo=min(row['sampled_min_c'] for row in layers)
                hi=max(row['sampled_max_c'] for row in layers)
                board+=(f" · {len(layers)} copper layers {lo:.3g}–{hi:.3g} °C"
                        f" · fixture flux {balance.get('mount_flux_w',0):.3g} W"
                        f" · heat residual {balance['residual_w']:.3g} W")
            else:
                field=network['board_field']
                board+=(f" · modeled board {field['sampled_min_c']:.3g}–{field['sampled_max_c']:.3g} °C"
                        f" · {field['active_cells']} cells · heat residual {balance['residual_w']:.3g} W")
        self.therm_status.SetLabel((
            f"{coverage.get('power_sources',0)} power sources modeled{board}. "
            f"Junction estimates: {coverage['solved']}/{coverage['scoped']} with declared RθJB."
            if (network or {}).get('model') == 'CalculiX 3D steady conduction' else
            f"{coverage['solved']}/{coverage['scoped']} selected components solved{board}. "
            +('Incomplete mapped fields; inspect the report.' if coverage['excluded'] else
              'Layer-resolved steady-state screen; inspect assumptions.' if (network or {}).get('layers') else
              'Board model is a thin-sheet screen, not CFD.' if network else
              'Lumped steady-state screen from entered assumptions; not a board temperature field.'
              if result.get('input_source') else
              'Lumped steady-state screen; not a board temperature field.')))
        _wrap_text(self.therm_status,self.therm_status.GetLabel())
        models=view.get('component_models',{})
        if models:
            coverage=models.get('coverage',{})
            self.therm_status.SetLabel(self.therm_status.GetLabel()+
                f" STEP: {len(coverage.get('loaded',[]))} parts loaded; {len(coverage.get('missing',[]))} coverage gaps. "+
                str(models.get('diagnostic','')))
            _wrap_text(self.therm_status,self.therm_status.GetLabel())
        self._therm_input_page.Layout();self._therm_input_page.FitInside()
        self.therm_inspector.GetPage(0).Layout();self.therm_inspector.GetPage(0).FitInside()
        self._buttons()
        if frames:self._thermal_time_changed()


    def _populate_thermal_table(self):
        self.therm_table.DeleteAllItems();column,descending=self._thermal_sort
        display=self._display_network() or {}
        transient='display_time_s' in display
        network={row['reference']:row for row in display.get('components',[])}
        limits={row['reference']:row for row in self.thermal_bundle.get('temperature_limits',{}).get('rows',[])}
        def cells(pair):
            item,row=pair;xy=item.get('position_mm') or [None,None]
            model=network.get(item['reference'],{})
            limit=dict(limits.get(item['reference'],{}))
            if transient:
                from .thermal_review import frame_limit_status
                row=model
                limit['status']=frame_limit_status(limit,row.get('junction_c'))
            num=lambda value:'—' if value is None else f'{value:.5g}'
            path=('CalculiX board field' if (self.thermal_bundle.get('thermal_network') or {}).get('model') == 'CalculiX 3D steady conduction' else
                  'Virtual heatsink' if row.get('heat_path')=='heatsink' else
                  ('RθJA air' if self.thermal_bundle['quick_therm']['environment']=='air' else 'Shared board')) if row else '—'
            return [item['reference'],num(row.get('junction_c') if row else None),
                    num(limit.get('minimum_c')),num(limit.get('maximum_c')),
                    limit.get('status','UNKNOWN'),num(row.get('power_w') if row else None),
                    item.get('side','—'),path,num(row.get('resistance_k_per_w') if row else None),
                    num(row.get('rise_above_ambient_k') if row else None),num(model.get('board_site_c')),
                    num(model.get('sink_c')),num(model.get('component_temperature_c',model.get('junction_c'))),num(xy[0]),num(xy[1]),
                    (model.get('temperature_kind','junction').capitalize()+' RC' if model.get('storage_node') is not None else
                     'Solved' if row.get('junction_c') is not None else 'Board solved; Tj unknown') if row else
                    '; '.join(item.get('issues',[])) or 'Excluded']
        self._thermal_rows.sort(key=lambda pair:(cells(pair)[column]=='—',
            float(cells(pair)[column]) if column in (1,2,3,5,8,9,10,11,12,13,14) and cells(pair)[column]!='—' else cells(pair)[column]),reverse=descending)
        for item,row in self._thermal_rows:
            values=cells((item,row));index=self.therm_table.InsertItem(self.therm_table.GetItemCount(),values[0])
            for col,value in enumerate(values[1:],1):self.therm_table.SetItem(index,col,value)
            colour={'PASS':wx.Colour(20,125,83),'FAIL':wx.Colour(190,50,50),
                    'UNKNOWN':wx.Colour(160,112,20)}.get(values[4])
            if colour:self.therm_table.SetItemTextColour(index,colour)


    def _thermal_frames(self):
        return ((self.thermal_bundle.get('thermal_network') or {}).get('transient') or {}).get('frames',[])

    def _update_thermal_timeline(self):
        if not hasattr(self,'therm_play'):return
        frames=self._thermal_frames();enabled=bool(frames) and not self._busy
        for ctrl in (self.therm_play,self.therm_time_slider,self.therm_play_speed):ctrl.Enable(enabled)
        self.therm_result_time.Enable(bool(self.thermal_bundle) and not self._busy)
        self.therm_time_slider.SetRange(0,max(1,len(frames)-1))
        index=self.therm_result_time.GetSelection()-1
        if frames:
            self.therm_time_slider.SetValue(max(0,index))
            self.therm_time_label.SetLabel(('Steady state' if index<0 else f"{frames[index]['time_s']:.3g} s")+f" / {frames[-1]['time_s']:.3g} s")
        else:self.therm_time_label.SetLabel('Run a transient study')

    def _stop_thermal_playback(self):
        self._thermal_timer.Stop();self._thermal_playing=False
        if hasattr(self,'therm_play'):self.therm_play.SetLabel('▶ Play')

    def _toggle_thermal_playback(self,event=None):
        if self._thermal_playing:
            self._stop_thermal_playback();return
        frames=self._thermal_frames()
        if not frames or self._busy:return
        index=self.therm_result_time.GetSelection()-1
        if index<0 or index==len(frames)-1:
            index=0;self.therm_result_time.SetSelection(1);self._thermal_time_changed(stop=False)
        self._thermal_play_start=time.monotonic()
        self._thermal_play_time=frames[index]['time_s']
        self._thermal_playing=True;self.therm_play.SetLabel('Ⅱ Pause');self._thermal_timer.Start(100)

    def _thermal_speed_changed(self,event=None):
        if self._thermal_playing:
            self._stop_thermal_playback();self._toggle_thermal_playback()

    def _thermal_tick(self,event=None):
        if self._closed or not self._thermal_playing:return
        from .thermal_playback import frame_at_time
        frames=self._thermal_frames()
        if not frames:self._stop_thermal_playback();return
        simulated=self._thermal_play_time+(time.monotonic()-self._thermal_play_start)*(1,5,20)[self.therm_play_speed.GetSelection()]
        index=frame_at_time(frames,simulated)
        if self.therm_result_time.GetSelection()!=index+1:
            self.therm_result_time.SetSelection(index+1);self._thermal_time_changed(stop=False)
        if simulated>=frames[-1]['time_s']:self._stop_thermal_playback()

    def _scrub_thermal_time(self,event=None):
        self.therm_result_time.SetSelection(self.therm_time_slider.GetValue()+1)
        self._thermal_time_changed()

    def _thermal_time_changed(self,stop=True):
        if stop:self._stop_thermal_playback()
        from .thermal_review import sample_probes
        self.thermal_bundle['probes']=sample_probes(self._display_view(),self._display_network(),self.therm_probe_definitions)
        self._populate_thermal_probes();self._draw_thermal(preserve_camera=True);self._populate_thermal_table()
        for index,(item,result) in enumerate(self._thermal_rows):
            if item['id']==self._thermal_selected:
                self.therm_table.Select(index)
                self._thermal_selection_text(item,result)
                break
        self._update_thermal_timeline()
        self.therm_analytics.SetLabel('Computed board and declared component RC temperatures. Fixed scale across the study; body nodes leave junction limits unknown.' if self.therm_result_time.GetSelection()>0 else 'Steady-state result selected.')
        _wrap_text(self.therm_analytics,self.therm_analytics.GetLabel())

    def _display_view(self,network=None):
        from .thermal_review import frame_view
        return frame_view(self.thermal_bundle.get('board_thermal_view',{}),network if network is not None else self._display_network())

    def _display_network(self):
        network=self.thermal_bundle.get('thermal_network')
        frames=((network or {}).get('transient') or {}).get('frames',[])
        choices=['Steady state']+[f"{frame['time_s']:.3g} s" for frame in frames]
        if list(self.therm_result_time.GetStrings())!=choices:
            self.therm_result_time.Set(choices);self.therm_result_time.SetSelection(0)
        index=self.therm_result_time.GetSelection()-1
        if index>=0:
            from .thermal_review import transient_frame_network
            cache=getattr(self,'_thermal_frame_cache',None)
            if cache is None or cache[0]!=(id(network),index):
                cache=((id(network),index),transient_frame_network(network,index));self._thermal_frame_cache=cache
            return cache[1]
        return network

    def _thermal_mode_changed(self,event=None):
        self._thermal_default_view=False
        self._draw_thermal()
        if event:event.Skip()

    def _draw_thermal(self,preserve_camera=False):
        if not self.thermal_bundle:return
        from .thermal_plot import draw_thermal_view, field_available
        network=self._display_network();mode=self.therm_mode.GetStringSelection()
        if network and 'display_time_s' in network and mode in ('Top-side map','Bottom-side map','Top-side contour','Bottom-side contour'):
            mode='Bottom board model' if 'Bottom' in mode else 'Top board model'
        view=self._display_view(network)
        side='bottom' if 'Bottom' in mode else 'top'
        partial=('board model' not in mode.lower() and not mode.startswith('Layer model: ') and
                 mode not in ('3D overview','Temperature chart') and
                 field_available(view.get('fields_by_side',{}).get(side,view.get('field',{}))))
        self.therm_view_note.SetLabel(
            'Partial junction interpolation · component anchor hull only; not a board surface field.\nBlank regions are unknown · Whole-board study… opens materials and boundaries.' if partial else
            'Board/layer model: review declared materials, heat sources, boundaries and heat balance.' if 'board model' in mode.lower() or mode.startswith('Layer model: ') else
            'Component junction estimates and illustrative geometry; review the model assumptions.')
        if mode=='3D overview':
            self.therm_view_note.SetLabel('3D saved-board geometry · drag to orbit, Shift-drag to pan, wheel to zoom.\n'
                f"STEP: {len(view.get('component_models',{}).get('components',{}))} real parts. Missing models remain footprint outlines.\n"
                'Each RC part shows one uniform body/junction temperature; gray means unknown.')
        _wrap_text(self.therm_view_note,self.therm_view_note.GetLabel())
        self.therm_view_note.GetParent().Layout();self.therm_view_note.GetParent().FitInside()
        camera=None
        if preserve_camera and self.therm_figure.axes:
            old=self.therm_figure.axes[0]
            camera=(old.get_xlim(),old.get_ylim(),old.get_zlim3d() if hasattr(old,'get_zlim3d') else None,
                    getattr(old,'elev',None),getattr(old,'azim',None))
        axes=draw_thermal_view(self.therm_figure,view,
                          mode,self._thermal_selected,
                          self._display_network(),self.therm_azim.GetValue(),self.therm_elev.GetValue(),
                          probes=self.thermal_bundle.get('probes',[]),viewport=True,
                          temperature_limits_c=getattr(self,'_thermal_time_limits',None) if self.therm_result_time.GetSelection()>0 else None)
        if camera:
            axes.set_xlim(camera[0]);axes.set_ylim(camera[1])
            if camera[2] is not None and hasattr(axes,'get_zlim3d'):
                axes.set_zlim(camera[2]);axes.view_init(elev=camera[3],azim=camera[4])
        self.therm_canvas.draw_idle()

    def _populate_thermal_probes(self):
        self.therm_probe_table.DeleteAllItems()
        for probe in self.thermal_bundle.get('probes', []):
            values=[probe['label'],probe['side'],f"{probe['x_mm']:.3f}",f"{probe['y_mm']:.3f}",
                    '—' if probe['temperature_c'] is None else f"{probe['temperature_c']:.3f}",
                    probe.get('source') or '—',probe['status']]
            index=self.therm_probe_table.InsertItem(self.therm_probe_table.GetItemCount(),values[0])
            for column,value in enumerate(values[1:],1):self.therm_probe_table.SetItem(index,column,value)

    def _toggle_thermal_probe(self,event=None):
        self.therm_probe_mode=self.therm_probe_button.GetValue()
        self.therm_status.SetLabel('Click a board position to add a virtual probe.' if self.therm_probe_mode
                                   else 'Probe placement off.')

    def _clear_thermal_probes(self,event=None):
        self.therm_probe_definitions=[]
        if self.thermal_bundle:
            self.thermal_bundle['probes']=[]
            self._populate_thermal_probes()
            self._draw_thermal()

    def _add_thermal_probe(self,x,y,mode):
        from .thermal_review import sample_probes
        if not self.thermal_bundle.get('quick_therm'):
            return
        side=getattr(self,'_thermal_pick_side','top') if mode=='3D overview' else 'bottom' if 'Bottom' in mode or mode.startswith('Layer model: B.') else 'top'
        definition={'label':f'P{len(self.therm_probe_definitions)+1}',
                    'x_mm':float(x),'y_mm':float(y),'side':side}
        self.therm_probe_definitions.append(definition)
        sampled=sample_probes(self.thermal_bundle.get('board_thermal_view',{}),
                              self._display_network(),[definition])[0]
        self.thermal_bundle.setdefault('probes',[]).append(sampled)
        self._populate_thermal_probes()
        self._draw_thermal()
        self.therm_status.SetLabel(f"{sampled['label']}: "+
            (f"{sampled['temperature_c']:.3f} °C ({sampled['source']}; nearest cell)" if sampled['status']=='ESTIMATE'
             else sampled['reason']))

    def on_expand_thermal(self, event=None):
        if not self.thermal_bundle.get('quick_therm'):
            self.therm_status.SetLabel('Run QuickTherm before opening the board workspace.')
            return
        from .thermal_plot import draw_thermal_view
        from .thermal_review import cursor_readout

        screen = wx.GetDisplaySize()
        dialog = wx.Dialog(self, title='QuickTherm · Top and bottom thermal workspace',
                           size=(min(screen.width - 60, 1600), min(screen.height - 60, 1000)),
                           style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        dialog.SetMinSize((950, 690))
        layout = wx.BoxSizer(wx.VERTICAL)
        controls = wx.BoxSizer(wx.HORIZONTAL)
        controls.Add(wx.StaticText(dialog, label='Overlay'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        network = self.thermal_bundle.get('thermal_network')
        modes = wx.Choice(dialog, choices=(['Board temperature', 'Component estimates']
                                          if network else ['Component estimates']))
        modes.SetSelection(0)
        controls.Add(modes, 0, wx.RIGHT, 12)
        probe_button=wx.ToggleButton(dialog,label='Place probe')
        controls.Add(probe_button,0,wx.RIGHT,12)
        controls.Add(wx.StaticText(dialog, label='Wheel: zoom · drag: pan · click a part: select in PCB Editor'),
                     1, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(controls, 0, wx.EXPAND | wx.ALL, 12)
        plots = wx.BoxSizer(wx.HORIZONTAL)
        figures = {}
        canvases = {}
        for side in ('top', 'bottom'):
            panel = wx.Panel(dialog)
            column = wx.BoxSizer(wx.VERTICAL)
            title = wx.StaticText(panel, label=side.title()+' side · saved PCB')
            font = title.GetFont()
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            title.SetFont(font)
            column.Add(title, 0, wx.LEFT | wx.BOTTOM, 5)
            figure = Figure(figsize=(7, 5), dpi=100)
            canvas = FigureCanvasWxAgg(panel, wx.ID_ANY, figure)
            canvas.SetMinSize((400, 340))
            column.Add(canvas, 1, wx.EXPAND)
            panel.SetSizer(column)
            plots.Add(panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
            figures[side], canvases[side] = figure, canvas
        layout.Add(plots, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        cursor = wx.StaticText(dialog, label='Move the cursor over either board to read temperature and part junction estimate.')
        layout.Add(cursor, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        summary = wx.ListCtrl(dialog, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 190))
        columns = [('Reference', 110), ('Side', 70), ('Junction °C', 120),
                   ('Model Tj °C', 115), ('Board site °C', 135),
                   ('Power W', 90), ('Limit', 90)]
        for index, (name, width) in enumerate(columns):
            summary.InsertColumn(index, name, width=width)
        layout.Add(summary, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        hint = wx.StaticText(dialog, label='Board temperature requires the optional board model. Component-estimate overlays interpolate junction values; they are not solved board temperatures.')
        hint.Wrap(max(800, dialog.GetSize().width-60))
        layout.Add(hint, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)

        rows = [(item, row) for item, row in self._thermal_rows if row]
        modeled = {item['reference']: item for item in (network or {}).get('components', [])}
        limits = {item['reference']: item for item in
                  self.thermal_bundle.get('temperature_limits', {}).get('rows', [])}
        def summary_values(item, row):
            model = modeled.get(item['reference'], {})
            return [item['reference'], item['side'],
                    f"{row['junction_c']:.2f}" if row.get('junction_c') is not None else '—',
                    f"{model['junction_c']:.2f}" if model.get('junction_c') is not None else '—',
                    f"{model['board_site_c']:.2f}" if model.get('board_site_c') is not None else '—',
                    f"{row['power_w']:.3g}" if row.get('power_w') is not None else '—',
                    limits.get(item['reference'], {}).get('status', 'UNKNOWN')]

        def fill_summary():
            summary.DeleteAllItems()
            for item, row in rows:
                values = summary_values(item, row)
                index = summary.InsertItem(summary.GetItemCount(), values[0])
                for col, value in enumerate(values[1:], 1):
                    summary.SetItem(index, col, value)

        rows.sort(key=lambda pair: pair[1].get('junction_c')
                  if pair[1].get('junction_c') is not None else -math.inf, reverse=True)
        fill_summary()

        sort_column = [2]
        sort_descending = [True]

        def sort_summary(event):
            column = event.GetColumn()
            descending = not sort_descending[0] if column == sort_column[0] else column in (2, 3, 4, 5)
            sort_column[0], sort_descending[0] = column, descending

            def key(pair):
                value = summary_values(*pair)[column]
                if column in (2, 3, 4, 5):
                    return float(value) if value != '—' else -math.inf
                return value.casefold()

            rows.sort(key=key, reverse=descending)
            fill_summary()

        summary.Bind(wx.EVT_LIST_COL_CLICK, sort_summary)

        def plot_mode(side):
            if modes.GetSelection() == 0 and network:
                return side.title()+' board model'
            return side.title()+'-side map'

        def draw(event=None):
            view = self.thermal_bundle.get('board_thermal_view', {})
            if modes.GetSelection() == 0 and network:
                fields = ([network['layers'][0], network['layers'][-1]]
                          if network.get('layers') else [network.get('board_field', {})])
            else:
                fields = list(view.get('fields_by_side', {}).values())
            temperatures = [value for field in fields for row in field.get('values_c', [])
                            for value in row if value is not None and math.isfinite(float(value))]
            scale = None
            if temperatures:
                low, high = min(temperatures), max(temperatures)
                scale = (low, high) if high > low else (low-.5, high+.5)
            for side in ('top', 'bottom'):
                draw_thermal_view(figures[side], view,
                                  plot_mode(side), self._thermal_selected, network,
                                  self.therm_azim.GetValue(), self.therm_elev.GetValue(),
                                  probes=self.thermal_bundle.get('probes', []),
                                  temperature_limits_c=scale)
                canvases[side].draw()

        def select(identifier):
            self._thermal_choose(identifier)
            for index, (item, _) in enumerate(rows):
                if item['id'] == identifier:
                    summary.Select(index)
                    summary.EnsureVisible(index)
                    break
            draw()

        def clicked(point, side):
            if not point.inaxes or point.xdata is None or point.ydata is None:
                return
            if probe_button.GetValue():
                self._add_thermal_probe(point.xdata, point.ydata, plot_mode(side))
                draw()
                return
            info = cursor_readout(self.thermal_bundle.get('board_thermal_view', {}),
                                  network if modes.GetSelection() == 0 else None,
                                  point.xdata, point.ydata, side)
            if info['component_id']:
                select(info['component_id'])

        def hovered(point, side):
            update_component_hover(figures[side].axes[0],point)
            if not point.inaxes or point.xdata is None or point.ydata is None:
                return
            info = cursor_readout(self.thermal_bundle.get('board_thermal_view', {}),
                                  network if modes.GetSelection() == 0 else None,
                                  point.xdata, point.ydata, side)
            if not info['on_board']:
                cursor.SetLabel(f'{side.title()} · outside verified board outline')
                return
            value = (f"{info['temperature_c']:.2f} °C" if info['temperature_c'] is not None
                     else 'unknown')
            part = (f" · {info['reference']} Tj≈{info['junction_c']:.2f} °C"
                    if info['junction_c'] is not None else
                    f" · {info['reference']} Tj unknown" if info['reference'] else '')
            if info['model_junction_c'] is not None:
                part += f" · model Tj≈{info['model_junction_c']:.2f} °C"
            cursor.SetLabel(f"{side.title()} · X {info['x_mm']:.2f} mm · Y {info['y_mm']:.2f} mm · "
                            f"{info['field_source']}: {value}{part}")

        modes.Bind(wx.EVT_CHOICE, draw)
        for side, canvas in canvases.items():
            canvas.mpl_connect('button_release_event',
                               lambda point, side=side: clicked(point, side))
            canvas.mpl_connect('motion_notify_event',
                               lambda point, side=side: hovered(point, side))
            def leave(event, side=side):
                update_component_hover(figures[side].axes[0]);event.Skip()
            canvas.Bind(wx.EVT_LEAVE_WINDOW,leave)
        summary.Bind(wx.EVT_LIST_ITEM_SELECTED,
                     lambda item: select(rows[item.GetIndex()][0]['id'])
                     if 0 <= item.GetIndex() < len(rows) and
                     rows[item.GetIndex()][0]['id'] != self._thermal_selected else None)
        close = wx.Button(dialog, wx.ID_CLOSE, label='Close')
        close.Bind(wx.EVT_BUTTON, lambda evt: dialog.EndModal(wx.ID_CLOSE))
        layout.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        dialog.SetSizer(layout)
        dialog.Layout()
        draw()
        dialog.ShowModal()
        dialog.Destroy()


    def _thermal_sort_clicked(self,event):
        column=event.GetColumn();previous,descending=self._thermal_sort
        self._thermal_sort=(column,not descending if column==previous else column in (1,2,3,5,8,9,10,11,12,13,14))
        self._populate_thermal_table()


    def _thermal_selection_text(self,item,result):
        if self.therm_result_time.GetSelection()>0:
            result=next((row for row in (self._display_network() or {}).get('components',[])
                         if row['reference']==item['reference']),None)
        details=[item['reference'],f"{item.get('side','unknown')} · {item.get('value','')}"]
        if result:
            details.extend([f"Power {result.get('power_w','unknown')} W",
                f"Junction {result['junction_c']:.5g} °C" if result.get('junction_c') is not None else 'Junction unknown',
                f"Heat path: {result.get('heat_path','unknown')}"])
            model=next((row for row in (self._display_network() or {}).get('components',[]) if row['reference']==item['reference']),{})
            if model.get('component_temperature_c') is not None:
                details.extend([f"{model['temperature_kind'].capitalize()} RC {model['component_temperature_c']:.5g} °C",
                                f"R {model['resistance_k_per_w']:g} K/W · C {model['capacity_j_k']:g} J/K",
                                f"Heat to contact {model.get('contact_heat_w',0):.5g} W"])
        models=self.thermal_bundle.get('board_thermal_view',{}).get('component_models',{})
        for gap in models.get('coverage',{}).get('missing',[]):
            if gap['reference']==item['reference']:details.append('STEP: '+gap['reason'])
        if item['reference'] in self.therm_inputs.model.components:
            cell=self.therm_inputs.model.cell(item['reference'],'theta_jb_k_per_w')
            details.append('RθJB '+(f'{cell.value:g} K/W' if cell.value is not None else 'unknown'))
        _wrap_text(self.therm_selection_detail,'\n'.join(details))
        self.therm_selection_detail.GetParent().Layout();self.therm_selection_detail.GetParent().FitInside()

    def _thermal_choose(self,identifier,from_editor=False):
        for index,(item,result) in enumerate(self._thermal_rows):
            if item['id']==identifier:
                self._thermal_selected=identifier
                self._thermal_selection_text(item,result)
                self.therm_table.Select(index);self.therm_table.EnsureVisible(index);self._draw_thermal()
                if not from_editor:self._task(lambda:self._select_thermal_in_editor(identifier),
                    lambda answer:self.therm_status.SetLabel('Selected '+item['reference']+' in PCB Editor; focus '+answer['focus']+'.'))
                return


    def _thermal_table_selected(self,event):
        index=event.GetIndex()
        if 0<=index<len(self._thermal_rows):
            identifier=self._thermal_rows[index][0]['id']
            if identifier!=self._thermal_selected:self._thermal_choose(identifier)


    def _thermal_plot_pressed(self,event):
        self._thermal_press=(event.x,event.y)
        self._thermal_pan=None
        if event.inaxes is None or not self.therm_figure.axes or event.inaxes is not self.therm_figure.axes[0]:return
        if self.therm_mode.GetStringSelection()=='3D overview':
            shift='shift' in str(event.key).lower() or bool(event.guiEvent and event.guiEvent.ShiftDown())
            if shift:event.button=2
        elif event.button==1 and not hasattr(self.therm_canvas,'_drag') and not self.therm_navigation.mode:
            ax=event.inaxes
            self._thermal_pan=(ax,ax.get_xlim(),ax.get_ylim(),ax.transData.frozen().inverted())

    def _thermal_plot_scrolled(self,event):
        if event.inaxes is None or not self.therm_figure.axes or event.inaxes is not self.therm_figure.axes[0]:return
        ax=event.inaxes;factor=.85**max(-10,min(10,event.step))
        if self.therm_mode.GetStringSelection()=='3D overview':
            for getter,setter in ((ax.get_xlim3d,ax.set_xlim3d),(ax.get_ylim3d,ax.set_ylim3d),(ax.get_zlim3d,ax.set_zlim3d)):
                limits=getter();center=sum(limits)/2;setter(*[center+(value-center)*factor for value in limits])
        elif event.xdata is not None and event.ydata is not None:
            for center,getter,setter in ((event.xdata,ax.get_xlim,ax.set_xlim),(event.ydata,ax.get_ylim,ax.set_ylim)):
                setter(*[center+(value-center)*factor for value in getter()])
        self.therm_canvas.draw_idle()

    def _thermal_plot_point(self,event,mode):
        if mode=='3D overview':
            from .thermal_review import board_point_from_3d
            z=getattr(event.inaxes,'_thermal_board_z',{}).get('top',0.0)
            planes=getattr(event.inaxes,'_thermal_field_planes',[])
            available=[plane for plane in planes if plane.get('available')]
            if available:
                side='top' if event.inaxes.elev>=0 else 'bottom'
                plane=next((plane for plane in available if plane['side']==side),available[0])
                z=plane['z_mm']
                self._thermal_pick_side=plane['side'] if plane['side'] in ('top','bottom') else side
            else:self._thermal_pick_side='top' if event.inaxes.elev>=0 else 'bottom'
            return board_point_from_3d(event.inaxes,event.x,event.y,
                                      z)
        return (event.xdata,event.ydata)

    def _thermal_plot_clicked(self,event):
        self._thermal_pan=None
        mode=self.therm_mode.GetStringSelection()
        if not self.thermal_bundle or event.inaxes is None or event.inaxes is not self.therm_figure.axes[0] or event.xdata is None:return
        if mode=='3D overview':
            self.therm_azim.SetValue(round(event.inaxes.azim));self.therm_elev.SetValue(round(event.inaxes.elev))
        press=getattr(self,'_thermal_press',None)
        if press and (event.x-press[0])**2+(event.y-press[1])**2>25:return
        if self.therm_probe_mode and mode=='Temperature chart':
            rows=sorted((item for item in self._display_view().get('components',[]) if item.get('solved')),key=lambda item:item['junction_c'])
            index=round(event.ydata)
            if 0<=index<len(rows):
                item=rows[index];event.inaxes.annotate(f"{item['reference']}: {item['junction_c']:.2f} C",(item['junction_c'],index),xytext=(12,10),textcoords='offset points',bbox={'boxstyle':'round','fc':'white','alpha':.9});self.therm_canvas.draw_idle()
            return
        if self.therm_probe_mode and mode!='Temperature chart':
            point=self._thermal_plot_point(event,mode)
            if point:self._add_thermal_probe(*point,mode)
            return
        ax=event.inaxes;points=[]
        if mode=='Temperature chart':
            rows=sorted((item for item in self._display_view().get('components',[])
                         if item.get('solved')),key=lambda item:item['junction_c'])
            index=round(event.ydata) if event.ydata is not None else -1
            if 0<=index<len(rows):self._thermal_choose(rows[index]['id'])
            return
        if mode=='3D overview':
            from .thermal_plot import component_at_event
            item=component_at_event(ax,event)
            if item:self._thermal_choose(item['id'],from_editor=True)
            return
        for item,_ in self._thermal_rows:
            if item.get('position_mm') and item.get('side')==('bottom' if 'Bottom' in mode else 'top'):
                x,y=ax.transData.transform(item['position_mm']);distance=(x-event.x)**2+(y-event.y)**2
                points.append((distance,item['id']))
        if points:
            distance,identifier=min(points)
            if distance<=14**2:self._thermal_choose(identifier)


    def _thermal_plot_hovered(self, event):
        pan=getattr(self,'_thermal_pan',None)
        if pan and self._thermal_press:
            ax,xlim,ylim,inverse=pan
            start=inverse.transform(self._thermal_press);current=inverse.transform((event.x,event.y))
            dx,dy=current-start;ax.set_xlim(xlim[0]-dx,xlim[1]-dx);ax.set_ylim(ylim[0]-dy,ylim[1]-dy)
            self.therm_canvas.draw_idle();return
        if self.therm_figure.axes:update_component_hover(self.therm_figure.axes[0],event)
        if (not self.thermal_bundle or not self.therm_figure.axes or
                event.inaxes is not self.therm_figure.axes[0] or
                event.xdata is None or event.ydata is None):
            return
        mode=self.therm_mode.GetStringSelection()
        if mode=='Temperature chart':
            rows=sorted((item for item in self._display_view().get('components',[])
                         if item.get('solved')),key=lambda item:item['junction_c'])
            index=round(event.ydata)
            if 0<=index<len(rows):
                item=rows[index];self.therm_cursor.SetLabel(f"{item['reference']} · junction {item['junction_c']:.2f} °C")
            return
        point=self._thermal_plot_point(event,mode)
        if not point:return
        from .thermal_review import cursor_readout

        side=getattr(self,'_thermal_pick_side','top') if mode=='3D overview' else 'bottom' if 'Bottom' in mode else 'top'
        model=self._display_network() if (self.therm_result_time.GetSelection()>0 or 'board model' in mode.lower() or mode=='3D overview' or mode.startswith('Layer model: ')) else None
        info=cursor_readout(self._display_view(model),model,
                            point[0],point[1],side)
        if not info['on_board']:
            self.therm_cursor.SetLabel(side.title()+' · outside verified board outline')
            return
        value=(f"{info['temperature_c']:.2f} °C" if info['temperature_c'] is not None
               else 'unknown')
        part=(f" · {info['reference']} Tj≈{info['junction_c']:.2f} °C"
              if info['junction_c'] is not None else
              f" · {info['reference']} Tj unknown" if info['reference'] else '')
        if info['model_junction_c'] is not None:
            part+=f" · model Tj≈{info['model_junction_c']:.2f} °C"
        self.therm_cursor.SetLabel(f"{side.title()} · X {info['x_mm']:.2f} mm · "
                                   f"Y {info['y_mm']:.2f} mm · "
                                   f"{info['field_source']}: {value}{part}")

    def _clear_thermal_hover(self,event=None):
        if self.therm_figure.axes:update_component_hover(self.therm_figure.axes[0])
        if event:event.Skip()


    def _select_thermal_in_editor(self,identifier):
        from .thermal_selection import select_origin_component
        return select_origin_component(self.board_path,identifier,
            expected_sha256=self.thermal_bundle.get('source_sha256'))


    def _sync_thermal_selection(self,event=None):
        if not self.thermal_bundle:return
        from .thermal_selection import selected_origin_component_ids
        self._task(lambda:selected_origin_component_ids(self.board_path,
            expected_sha256=self.thermal_bundle.get('source_sha256')),
            lambda ids:self._thermal_choose(ids[0],from_editor=True) if ids else self.therm_status.SetLabel('No scoped footprint selected in PCB Editor.'))
