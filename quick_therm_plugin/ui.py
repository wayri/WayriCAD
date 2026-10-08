"""Native QuickTherm workspace with scoped inputs, board views and evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
import threading

import wx
from matplotlib.figure import Figure

from .plot_canvas import FigureCanvasWxAgg, NavigationToolbar2WxAgg


from .thermal_inputs import _parse_sink_areas

class QuickThermFrame(wx.Frame):
    def __init__(self, parent, board_path):
        super().__init__(parent, title="WayriCAD QuickTherm", size=(1180, 800))
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
        self.virtual_heatsinks = {}
        self.therm_probe_definitions = []
        self.therm_probe_mode = False
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        self._solver_config = wx.Config("WayriCAD QuickTherm")
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
        root.Add(title, 0, wx.EXPAND | wx.ALL, 12)
        self.book = wx.Notebook(self.main_panel)
        self._build_thermal_page()
        root.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.status = wx.StaticText(self.main_panel, label="Reading saved PCB…")
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 12)
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
        wx.CallAfter(self._inspect)

    def _buttons(self):
        self.reload.Enable(not self._busy)
        self.therm_run.Enable(not self._busy)
        self.therm_manual_button.Enable(not self._busy and self.therm_input_mode.GetSelection() == 0)
        self.therm_export.Enable(not self._busy and bool(self.thermal_bundle.get("quick_therm")))
        self.therm_sink_button.Enable(not self._busy)
        self.therm_sync.Enable(not self._busy and bool(self.thermal_bundle))
        self.cancel.Enable(self._busy)
        if not self._busy:
            self._therm_controls()

    def _task(self, operation, finished, message="Working…"):
        if self._busy or self._closed:
            return
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
        self.thermal_bundle = {}
        self.manual_values = {}
        self.therm_table.DeleteAllItems()
        self.therm_figure.clear()
        self.therm_canvas.draw_idle()

        def loaded(inventory):
            self.inventory = inventory
            fields = ["", *inventory.get("field_names", [])]
            for choice in (self.therm_power, self.therm_ja, self.therm_jb,
                           self.therm_jc, self.therm_model_jb,
                           self.therm_limit_min, self.therm_limit_max):
                choice.Set(fields)
                choice.SetSelection(0)
            refs = inventory.get("component_references", [])
            self.therm_refs.Set(refs)
            self._therm_mount_candidates = inventory.get("mounting_holes", [])
            self.therm_mounts.Set([
                f"{row['reference']}.{row['pad_number'] or '?'} · {row['net'] or 'no net'} · "
                f"{'PTH' if row['plated'] else 'NPTH'} · Ø{row['drill_mm']:.3g} mm"
                for row in self._therm_mount_candidates
            ])
            self.virtual_heatsinks = {
                ref: sink for ref, sink in self.virtual_heatsinks.items() if ref in refs
            }
            self.therm_status.SetLabel(
                f"{len(refs)} components. Select the dissipating parts, enter their power and Rθ, then run. "
                "Use saved-field mode if the board already carries thermal values."
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
        self._cancel.set()
        self._closed = True
        self.Destroy()

    def _build_thermal_page(self):
        page=wx.ScrolledWindow(self.book,style=wx.VSCROLL);page.SetScrollRate(0,10);layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(page,label='1  Choose the cooling environment and dissipating parts.  2  Enter measured or reviewed power and thermal resistance.  3  Run and inspect the estimated temperatures.')
        note.Wrap(1050);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        setup=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_input_mode=wx.Choice(page,choices=['Enter values per component','Use saved footprint fields'])
        self.therm_input_mode.SetSelection(0)
        self.therm_env=wx.Choice(page,choices=['Air','Vacuum','Forced air','Potting','Sealed enclosure']);self.therm_env.SetSelection(0)
        self.therm_ambient=wx.TextCtrl(page,value='20',size=(80,-1))
        self.therm_manual_button=wx.Button(page,label='Enter component inputs…')
        self.therm_manual_button.Bind(wx.EVT_BUTTON,self.on_manual_setup)
        for label,control in [('Input source',self.therm_input_mode),('Environment',self.therm_env),
                              ('Ambient °C',self.therm_ambient)]:
            setup.Add(wx.StaticText(page,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
            setup.Add(control,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,16)
        setup.Add(self.therm_manual_button,0,wx.ALIGN_CENTER_VERTICAL)
        layout.Add(setup,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        vacuum_row=wx.BoxSizer(wx.HORIZONTAL)
        vacuum_row.Add(wx.StaticText(page,label='Vacuum board-to-environment resistance K/W'),
                       0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.therm_board_r=wx.TextCtrl(page,value='',size=(120,-1))
        self.therm_board_r.SetHint('Enter a reviewed heat path')
        vacuum_row.Add(self.therm_board_r,0)
        layout.Add(vacuum_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        advanced=wx.CollapsiblePane(page,label='Environment boundaries and time-varying analysis',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        advanced_host=advanced.GetPane();advanced_form=wx.FlexGridSizer(0,4,6,10)
        self.therm_explicit_h=wx.TextCtrl(advanced_host,value='20')
        self.therm_enclosure_c=wx.TextCtrl(advanced_host,value='20')
        self.therm_potting_k=wx.TextCtrl(advanced_host,value='1')
        self.therm_potting_thickness=wx.TextCtrl(advanced_host,value='2')
        self.therm_potting_outer_h=wx.TextCtrl(advanced_host,value='10')
        self.therm_time_enabled=wx.CheckBox(advanced_host,label='Time-varying multilayer simulation')
        self.therm_time_duration=wx.TextCtrl(advanced_host,value='60')
        self.therm_time_step=wx.TextCtrl(advanced_host,value='1')
        self.therm_time_initial=wx.TextCtrl(advanced_host,value='20')
        self.therm_copper_capacity=wx.TextCtrl(advanced_host,value='3450000')
        self.therm_dielectric_capacity=wx.TextCtrl(advanced_host,value='1800000')
        self.therm_power_schedule=wx.TextCtrl(advanced_host,value='{}')
        self.therm_sink_capacity=wx.TextCtrl(advanced_host,value='{}')
        for label,ctrl in [('Explicit convection h W/m²K',self.therm_explicit_h),('Fixed enclosure °C',self.therm_enclosure_c),('Potting conductivity W/mK',self.therm_potting_k),('Potting thickness mm',self.therm_potting_thickness),('Potting outer h W/m²K',self.therm_potting_outer_h),('Duration s',self.therm_time_duration),('Time step s',self.therm_time_step),('Initial temperature °C',self.therm_time_initial),('Copper volumetric capacity J/m³K',self.therm_copper_capacity),('Dielectric volumetric capacity J/m³K',self.therm_dielectric_capacity),('Power multiplier schedules JSON: U1: [[time,multiplier]]',self.therm_power_schedule),('Sink heat capacity JSON: U1: J/K',self.therm_sink_capacity)]:
            advanced_form.Add(wx.StaticText(advanced_host,label=label),0,wx.ALIGN_CENTER_VERTICAL);advanced_form.Add(ctrl,1,wx.EXPAND)
            ctrl.Bind(wx.EVT_TEXT,self._invalidate_thermal)
        advanced_box=wx.BoxSizer(wx.VERTICAL);advanced_box.Add(self.therm_time_enabled,0,wx.ALL,6);advanced_box.Add(advanced_form,1,wx.EXPAND|wx.ALL,6)
        self.therm_time_enabled.Bind(wx.EVT_CHECKBOX,self._invalidate_thermal)
        advanced_host.SetSizer(advanced_box);layout.Add(advanced,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.therm_fields_pane=wx.CollapsiblePane(page,label='Saved footprint fields and optional temperature limits',
                                                 style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        fields_host=self.therm_fields_pane.GetPane()
        form=wx.FlexGridSizer(0,4,7,10)
        for col in (1,3):form.AddGrowableCol(col,1)
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
        self.therm_model=wx.CollapsiblePane(page,label='Optional board conduction / radiation / virtual airflow model',
                                           style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        model_pane=self.therm_model.GetPane();model_grid=wx.FlexGridSizer(0,6,6,9)
        for col in (1,3,5):model_grid.AddGrowableCol(col,1)
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
            model_pane,value=self._solver_config.Read('calculix_executable', ''))
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
                              ('Model junction-to-board RθJB field',self.therm_model_jb),
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
            model_grid.Add(wx.StaticText(model_pane,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            model_grid.Add(control,1,wx.EXPAND)
        model_layout=wx.BoxSizer(wx.VERTICAL);model_layout.Add(model_grid,0,wx.EXPAND)
        solver_setup=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_ccx_browse=wx.Button(model_pane,label='Locate CalculiX…')
        self.therm_ccx_browse.Bind(wx.EVT_BUTTON,self.on_calculix_browse)
        self.therm_ccx_check=wx.Button(model_pane,label='Check solver setup')
        self.therm_ccx_check.Bind(wx.EVT_BUTTON,self.on_calculix_check)
        self.therm_ccx_status=wx.StaticText(model_pane,label='Select CalculiX mode to check the external solver.')
        solver_setup.Add(self.therm_ccx_browse,0,wx.RIGHT,7)
        solver_setup.Add(self.therm_ccx_check,0,wx.RIGHT,10)
        solver_setup.Add(self.therm_ccx_status,1,wx.ALIGN_CENTER_VERTICAL)
        model_layout.Add(solver_setup,0,wx.EXPAND|wx.TOP|wx.BOTTOM,8)
        mount_row=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_mounts=wx.CheckListBox(model_pane,size=(420,80))
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
        model_layout.Add(wx.StaticText(model_pane,label='Fixed-temperature contacts · choose plated pads on the saved board; NPTH requires separate mechanical contact evidence'),0,wx.TOP|wx.BOTTOM,6)
        model_layout.Add(mount_row,0,wx.EXPAND)
        model_layout.Add(self.therm_mount_mechanical,0,wx.TOP,5)
        model_pane.SetSizer(model_layout);layout.Add(self.therm_model,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.therm_model.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:(page.FitInside(),page.Layout()))
        self.therm_env.Bind(wx.EVT_CHOICE,lambda e:self._therm_controls())
        self._therm_controls()
        selection=wx.BoxSizer(wx.HORIZONTAL)
        selection.Add(wx.StaticText(page,label='Dissipating components in scope'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,12)
        for label,method in [('Select all',True),('Clear',False)]:
            button=wx.Button(page,label=label);button.Bind(wx.EVT_BUTTON,lambda e,checked=method:self._check_thermal_refs(checked));selection.Add(button,0,wx.RIGHT,7)
        self.therm_run=wx.Button(page,label='Run QuickTherm');self.therm_run.Bind(wx.EVT_BUTTON,self.on_quick_therm)
        self.therm_sink_button=wx.Button(page,label='Virtual heatsinks…');self.therm_sink_button.Bind(wx.EVT_BUTTON,self.on_virtual_heatsinks)
        self.therm_export=wx.Button(page,label='Export report…');self.therm_export.Bind(wx.EVT_BUTTON,lambda e:self.on_export_diagnostic('quick_therm'))
        self.therm_expand=wx.Button(page,label='Open top + bottom workspace…');self.therm_expand.Bind(wx.EVT_BUTTON,self.on_expand_thermal)
        self.therm_probe_button=wx.ToggleButton(page,label='Place probe')
        self.therm_probe_button.Bind(wx.EVT_TOGGLEBUTTON,self._toggle_thermal_probe)
        self.therm_clear_probes=wx.Button(page,label='Clear probes')
        self.therm_clear_probes.Bind(wx.EVT_BUTTON,self._clear_thermal_probes)
        layout.Add(selection,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.therm_sink_button,0,wx.RIGHT,7)
        actions.Add(self.therm_run,0,wx.RIGHT,7)
        actions.Add(self.therm_export,0)
        actions.Add(self.therm_expand,0,wx.LEFT,7)
        actions.Add(self.therm_probe_button,0,wx.LEFT,7)
        actions.Add(self.therm_clear_probes,0,wx.LEFT,7)
        layout.Add(actions,0,wx.LEFT|wx.RIGHT|wx.TOP,10)
        body=wx.BoxSizer(wx.HORIZONTAL)
        self.therm_refs=wx.CheckListBox(page,size=(180,-1));body.Add(self.therm_refs,0,wx.EXPAND|wx.RIGHT,10)
        visual=wx.BoxSizer(wx.VERTICAL);switch=wx.BoxSizer(wx.HORIZONTAL)
        switch.Add(wx.StaticText(page,label='Board view'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.therm_mode=wx.Choice(page,choices=['Top-side map','Bottom-side map','Top-side contour','Bottom-side contour',
                                               'Top board model','Bottom board model','3D overview','Temperature chart']);self.therm_mode.SetSelection(0)
        switch.Add(self.therm_mode,0,wx.RIGHT,12)
        switch.Add(wx.StaticText(page,label='3D azimuth'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
        self.therm_azim=wx.SpinCtrl(page,min=-180,max=180,initial=-60,size=(70,-1));switch.Add(self.therm_azim,0,wx.RIGHT,8)
        switch.Add(wx.StaticText(page,label='Elevation'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,4)
        self.therm_elev=wx.SpinCtrl(page,min=-90,max=90,initial=28,size=(65,-1));switch.Add(self.therm_elev,0,wx.RIGHT,8)
        self.therm_sync=wx.Button(page,label='Read PCB selection');self.therm_sync.Bind(wx.EVT_BUTTON,self._sync_thermal_selection)
        switch.Add(self.therm_sync,0,wx.RIGHT,8)
        visual.Add(switch,0,wx.EXPAND|wx.BOTTOM,6)
        time_row=wx.BoxSizer(wx.HORIZONTAL);time_row.Add(wx.StaticText(page,label='Result time'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.therm_result_time=wx.Choice(page,choices=['Steady state']);self.therm_result_time.SetSelection(0)
        self.therm_result_time.Bind(wx.EVT_CHOICE,lambda e:self._thermal_time_changed());time_row.Add(self.therm_result_time,0)
        visual.Add(time_row,0,wx.EXPAND|wx.BOTTOM,6)
        self.therm_figure=Figure(figsize=(8,4),dpi=100);self.therm_canvas=FigureCanvasWxAgg(page,wx.ID_ANY,self.therm_figure)
        self.therm_canvas.SetMinSize((700,460))
        self.therm_canvas.mpl_connect('button_press_event',self._thermal_plot_pressed)
        self.therm_canvas.mpl_connect('button_release_event',self._thermal_plot_clicked)
        self.therm_canvas.mpl_connect('motion_notify_event',self._thermal_plot_hovered)
        self.therm_navigation=NavigationToolbar2WxAgg(self.therm_canvas);self.therm_navigation.Realize()
        visual.Add(self.therm_navigation,0,wx.EXPAND)
        visual.Add(self.therm_canvas,1,wx.EXPAND)
        self.therm_cursor=wx.StaticText(page,label='Move over the board to read a field temperature and component Tj.')
        visual.Add(self.therm_cursor,0,wx.EXPAND|wx.TOP,5)
        body.Add(visual,1,wx.EXPAND);layout.Add(body,1,wx.EXPAND|wx.ALL,10)
        self.therm_analytics=wx.StaticText(page,label='Run QuickTherm to see min, max, mean, median and coverage.');layout.Add(self.therm_analytics,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        # The table scrolls its own columns.  A width of -1 lets its many
        # columns inflate the whole page and push the board preview offscreen.
        self.therm_table=wx.ListCtrl(page,style=wx.LC_REPORT,size=(700,170))
        for i,(name,width) in enumerate([('Reference',100),('Junction °C',105),('Min Tj °C',95),
                                         ('Max Tj °C',95),('Limit check',100),('Power W',85),
                                         ('Side',55),('Heat path',120),('Rθ K/W',90),('Rise K',85),
                                         ('Board site °C',110),('Sink °C',90),('Model Tj °C',105),
                                         ('X mm',75),('Y mm',75),('Status',200)]):
            self.therm_table.InsertColumn(i,name,width=width)
        layout.Add(self.therm_table,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.therm_probe_table=wx.ListCtrl(page,style=wx.LC_REPORT,size=(700,105))
        for index,(name,width) in enumerate([('Probe',100),('Side',90),('X mm',90),('Y mm',90),
                                              ('Temperature °C',145),('Source',230),('Status',100)]):
            self.therm_probe_table.InsertColumn(index,name,width=width)
        layout.Add(wx.StaticText(page,label='Virtual temperature probes · click Place probe, then the board view'),
                   0,wx.LEFT|wx.RIGHT|wx.TOP,10)
        layout.Add(self.therm_probe_table,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self._thermal_rows=[];self._thermal_selected=None;self._thermal_sort=(1,True)
        self.therm_mode.Bind(wx.EVT_CHOICE,lambda e:self._draw_thermal())
        self.therm_azim.Bind(wx.EVT_SPINCTRL,lambda e:self._draw_thermal())
        self.therm_elev.Bind(wx.EVT_SPINCTRL,lambda e:self._draw_thermal())
        self.therm_table.Bind(wx.EVT_LIST_ITEM_SELECTED,self._thermal_table_selected)
        self.therm_table.Bind(wx.EVT_LIST_COL_CLICK,self._thermal_sort_clicked)
        self.therm_status=wx.StaticText(page,label='Select dissipating components, then enter their power and thermal resistance.')
        layout.Add(self.therm_status,0,wx.EXPAND|wx.ALL,10)
        for ctrl in (self.therm_power,self.therm_ja,self.therm_jb,self.therm_jc,
                     self.therm_limit_min,self.therm_limit_max):ctrl.Bind(wx.EVT_COMBOBOX,self._invalidate_thermal)
        self.therm_env.Bind(wx.EVT_CHOICE,self._invalidate_thermal)
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
        page.SetSizer(layout);page.FitInside();self.book.AddPage(page,'QuickTherm')


    def _therm_controls(self):
        vacuum=self.therm_env.GetSelection()==1
        selected=self.therm_model_kind.GetSelection() if self.therm_model_enabled.GetValue() else -1
        self.therm_ja.Enable(not vacuum and selected!=2)
        self.therm_jb.Enable(vacuum and selected!=2)
        self.therm_jc.Enable(bool(self.virtual_heatsinks) and selected!=2)
        self.therm_board_r.Enable(vacuum and selected not in (1,2))
        self.therm_emissivity.Enable(selected in (0,1) and not self._busy)
        for ctrl in (self.therm_air_board,self.therm_air_sink,self.therm_grid,self.therm_sink_area):
            ctrl.Enable(selected in (0,1) and not self._busy)
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
            self._solver_config.Write('calculix_executable',chosen)
            self._solver_config.Flush()
        return True


    def _input_mode_changed(self,event=None):
        manual=self.therm_input_mode.GetSelection()==0
        self.therm_fields_pane.Collapse(manual)
        self.therm_manual_button.Enable(manual and not self._busy)
        self.book.GetCurrentPage().FitInside()
        self.main_panel.Layout()
        self._invalidate_thermal(event)
        self.therm_status.SetLabel('Select dissipating components, then enter their power and Rθ.' if manual else
                                   'Map saved power and thermal-resistance footprint fields, then select components.')


    def on_manual_setup(self,event=None):
        references=[self.therm_refs.GetString(i) for i in range(self.therm_refs.GetCount())
                    if self.therm_refs.IsChecked(i)]
        if not references:
            self.therm_status.SetLabel('Select only the components whose dissipation you can specify, then enter inputs.')
            return False
        from .manual_setup import ManualThermalDialog
        environment=('air','vacuum','forced_air','potting','sealed')[self.therm_env.GetSelection()]
        power_only=(self.therm_model_enabled.GetValue() and
                    (self.therm_model_kind.GetSelection()==2 or (environment=='vacuum' and self.therm_model_kind.GetSelection()==1) or environment not in ('air','vacuum') or self.therm_time_enabled.GetValue()))
        with ManualThermalDialog(self,references,environment,self.virtual_heatsinks,
                                 self.manual_values,power_only=power_only) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:
                return False
            self.manual_values.update(dialog.values)
        self._invalidate_thermal()
        details='power' if power_only else 'power and Rθ'
        self.therm_status.SetLabel(f'Explicit {details} entered for {len(references)} selected component(s). Run QuickTherm to see the estimate.')
        return True


    def _therm_model_changed(self,event):
        self._therm_controls()
        self._invalidate_thermal(event)
        if self.therm_model_enabled.GetValue() and self.therm_model_kind.GetSelection()==2:
            self.on_calculix_check()


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
        self._invalidate_thermal()


    def _invalidate_thermal(self,event=None):
        self.thermal_bundle={};self.therm_table.DeleteAllItems();self.therm_figure.clear()
        self._thermal_rows=[];self._thermal_selected=None;self.therm_analytics.SetLabel('Run QuickTherm to see min, max, mean, median and coverage.')
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
        power_only=calculix or (environment=='vacuum' and self.therm_model_enabled.GetValue() and self.therm_model_kind.GetSelection()==1) or environment not in ('air','vacuum') or self.therm_time_enabled.GetValue()
        if not references:
            self.therm_status.SetLabel('Select at least one dissipating component before running QuickTherm.');return
        if manual:
            if any('power_w' not in self.manual_values.get(ref,{}) or
                   (not power_only and ('theta_jc_k_per_w' if ref in sinks else kind)
                    not in self.manual_values.get(ref,{}))
                   for ref in references):
                if not self.on_manual_setup():return
        elif not self.therm_power.GetValue() or (not power_only and unsinked and not field.GetValue()) or (not power_only and sinks and not self.therm_jc.GetValue()):
            self.therm_status.SetLabel('Map power and RθJA/RθJB for selected parts, plus RθJC for virtual heatsinks.');return
        try:
            request={'action':'quick_therm','board_path':self.board_path,'environment':environment,
                     'ambient_c':float(self.therm_ambient.GetValue()),'references':references,
                     'expected_source_sha256':self.inventory.get('source_sha256'),
                     'heatsinks':sinks,
                     'limit_fields':{key:name for key,name in (
                         ('minimum_c',self.therm_limit_min.GetValue()),
                         ('maximum_c',self.therm_limit_max.GetValue())) if name},
                     'probes':list(self.therm_probe_definitions)}
            if manual:
                request['input_mode']='manual'
                request['manual_values']={ref:self.manual_values[ref] for ref in references}
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
                if environment=='vacuum':
                    settings.update(board_airflow_m_s=0, sink_airflow_m_s=0, board_h_w_m2k=0, sink_h_w_m2k=0)
                if environment in ('forced_air','sealed'):
                    settings['board_h_w_m2k']=float(self.therm_explicit_h.GetValue())
                if environment=='sealed':settings['enclosure_temperature_c']=float(self.therm_enclosure_c.GetValue())
                if environment=='potting':
                    settings.update(potting_k_w_mk=float(self.therm_potting_k.GetValue()),potting_thickness_mm=float(self.therm_potting_thickness.GetValue()),potting_outer_h_w_m2k=float(self.therm_potting_outer_h.GetValue()))
                if self.therm_time_enabled.GetValue():
                    request['transient_settings']={'duration_s':float(self.therm_time_duration.GetValue()),'timestep_s':float(self.therm_time_step.GetValue()),'initial_c':float(self.therm_time_initial.GetValue()),'copper_volumetric_capacity_j_m3k':float(self.therm_copper_capacity.GetValue()),'dielectric_volumetric_capacity_j_m3k':float(self.therm_dielectric_capacity.GetValue()),'power_schedules':json.loads(self.therm_power_schedule.GetValue()),'sink_capacity_j_k':json.loads(self.therm_sink_capacity.GetValue())}
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
                if self.therm_model_jb.GetValue():request['thermal_network_component_field']=self.therm_model_jb.GetValue()
            except ValueError as exc:
                self.therm_status.SetLabel('Enter numeric thermal material, plating, contact and airflow values: '+str(exc));return
        self.thermal_bundle={};self.therm_table.DeleteAllItems();self._thermal_rows=[];self._thermal_selected=None
        self.therm_figure.clear();self.therm_canvas.draw_idle();self.therm_analytics.SetLabel('Analysis running…')
        self.therm_status.SetLabel('Reading saved board geometry and running the selected thermal model…')
        self._job(request,self._accept_therm,'Running QuickTherm on the saved board…')


    def _accept_therm(self,bundle):
        self.thermal_bundle=bundle;result=bundle['quick_therm']
        self._populate_thermal_probes()
        network=bundle.get('thermal_network') or {}
        original_mode=self.therm_mode.GetStringSelection()
        modes=['Top-side map','Bottom-side map','Top-side contour','Bottom-side contour',
               'Top board model','Bottom board model','3D overview','Temperature chart']
        modes.extend('Layer model: '+layer['name'] for layer in network.get('layers',[]))
        self.therm_mode.Set(modes)
        self.therm_mode.SetStringSelection('Top board model' if network.get('model') == 'CalculiX 3D steady conduction'
                                           else original_mode if original_mode in modes else 'Top-side map')
        view=bundle.get('board_thermal_view',{})
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
        self._buttons()


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
                    num(model.get('sink_c')),num(model.get('junction_c')),num(xy[0]),num(xy[1]),
                    ('Solved' if row.get('junction_c') is not None else 'Board solved; Tj unknown') if row else
                    '; '.join(item.get('issues',[])) or 'Excluded']
        self._thermal_rows.sort(key=lambda pair:(cells(pair)[column]=='—',
            float(cells(pair)[column]) if column in (1,2,3,5,8,9,10,11,12,13,14) and cells(pair)[column]!='—' else cells(pair)[column]),reverse=descending)
        for item,row in self._thermal_rows:
            values=cells((item,row));index=self.therm_table.InsertItem(self.therm_table.GetItemCount(),values[0])
            for col,value in enumerate(values[1:],1):self.therm_table.SetItem(index,col,value)
            colour={'PASS':wx.Colour(20,125,83),'FAIL':wx.Colour(190,50,50),
                    'UNKNOWN':wx.Colour(160,112,20)}.get(values[4])
            if colour:self.therm_table.SetItemTextColour(index,colour)


    def _thermal_time_changed(self):
        from .thermal_review import sample_probes
        self.thermal_bundle['probes']=sample_probes(self._display_view(),self._display_network(),self.therm_probe_definitions)
        self._populate_thermal_probes();self._draw_thermal();self._populate_thermal_table()
        self.therm_analytics.SetLabel('Selected time: board field and massless junction offsets; package thermal storage is not modeled.' if self.therm_result_time.GetSelection()>0 else 'Steady-state result selected.')

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

    def _draw_thermal(self):
        if not self.thermal_bundle:return
        from .thermal_plot import draw_thermal_view
        network=self._display_network();mode=self.therm_mode.GetStringSelection()
        if network and 'display_time_s' in network and mode in ('Top-side map','Bottom-side map','Top-side contour','Bottom-side contour'):
            mode='Bottom board model' if 'Bottom' in mode else 'Top board model'
        draw_thermal_view(self.therm_figure,self._display_view(network),
                          mode,self._thermal_selected,
                          self._display_network(),self.therm_azim.GetValue(),self.therm_elev.GetValue(),
                          probes=self.thermal_bundle.get('probes',[]))
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
        side='bottom' if 'Bottom' in mode or mode.startswith('Layer model: B.') else 'top'
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


    def _thermal_choose(self,identifier,from_editor=False):
        for index,(item,_) in enumerate(self._thermal_rows):
            if item['id']==identifier:
                self._thermal_selected=identifier
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

    def _thermal_plot_point(self,event,mode):
        if mode=='3D overview':
            from .thermal_review import board_point_from_3d
            view=self.thermal_bundle.get('board_thermal_view',{})
            return board_point_from_3d(event.inaxes,event.x,event.y,
                                      view.get('board_thickness_mm') or 1.6)
        return (event.xdata,event.ydata)

    def _thermal_plot_clicked(self,event):
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
            from mpl_toolkits.mplot3d import proj3d
            thickness=self.thermal_bundle.get('board_thermal_view',{}).get('board_thickness_mm') or 1.6
            for item,_ in self._thermal_rows:
                if item.get('position_mm'):
                    x,y=item['position_mm'];z=thickness+.8 if item.get('top_side') else -.8
                    px,py,_=proj3d.proj_transform(x,y,z,ax.get_proj())
                    sx,sy=ax.transData.transform((px,py))
                    points.append(((sx-event.x)**2+(sy-event.y)**2,item['id']))
            if points:
                distance,identifier=min(points)
                if distance<=15**2:self._thermal_choose(identifier)
            return
        for item,_ in self._thermal_rows:
            if item.get('position_mm') and item.get('side')==('bottom' if 'Bottom' in mode else 'top'):
                x,y=ax.transData.transform(item['position_mm']);distance=(x-event.x)**2+(y-event.y)**2
                points.append((distance,item['id']))
        if points:
            distance,identifier=min(points)
            if distance<=14**2:self._thermal_choose(identifier)


    def _thermal_plot_hovered(self, event):
        if not self.thermal_bundle or event.xdata is None or event.ydata is None:
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

        side='bottom' if 'Bottom' in mode else 'top'
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
