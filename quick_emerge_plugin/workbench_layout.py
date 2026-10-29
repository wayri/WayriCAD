"""Compact native workbench layout, separate from simulation/controller logic."""
from pathlib import Path
import sys
import wx
import wx.lib.scrolledpanel
from matplotlib.figure import Figure
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
from .model import DEFAULT_CONFIG
from .viewport import PlotViewport


class SourcePicker(wx.Panel):
    """Accept fabrication files or unpacked fabrication directories."""
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.path = wx.TextCtrl(self)
        self.path.Bind(wx.EVT_TEXT, callback)
        layout = wx.BoxSizer(wx.HORIZONTAL); layout.Add(self.path, 1, wx.EXPAND)
        for label, directory in [('File…', False), ('Folder…', True)]:
            control = wx.Button(self, label=label, style=wx.BU_EXACTFIT)
            control.Bind(wx.EVT_BUTTON, lambda event, folder=directory: self.browse(folder))
            layout.Add(control, 0, wx.LEFT, 3)
        self.SetSizer(layout)
    def browse(self, directory):
        dialog = wx.DirDialog(self, 'Choose unpacked fabrication source') if directory else wx.FileDialog(self, 'Choose fabrication source', style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        with dialog:
            if dialog.ShowModal() == wx.ID_OK: self.SetPath(dialog.GetPath())
    def GetPath(self): return self.path.GetValue()
    def SetPath(self, value): self.path.SetValue(value)


class QuantityInput(wx.TextCtrl):
    """Display convenient units while the controller reads canonical solver units."""
    def __init__(self, parent, value, scale=1.):
        self.scale = scale
        super().__init__(parent, value=format(float(value)/scale, '.8g'), size=(105, -1))
    def GetValue(self):
        raw = super().GetValue()
        if self.scale == 1.: return raw
        try: return str(float(raw)*self.scale)
        except ValueError: return raw
    def ChangeValue(self, value):
        super().ChangeValue(format(float(value)/self.scale, '.8g'))
    def SetValue(self, value):
        super().SetValue(format(float(value)/self.scale, '.8g'))


def button(parent, label, callback, *, toggle=False):
    control = (wx.ToggleButton if toggle else wx.Button)(parent, label=label, style=wx.BU_EXACTFIT)
    control.SetMinSize((-1, parent.FromDIP(28)))
    art = {'Preview': wx.ART_FIND, 'Run simulation': wx.ART_GO_FORWARD, 'Cancel': wx.ART_CROSS_MARK,
           'Open setup': wx.ART_FILE_OPEN, 'Save setup': wx.ART_FILE_SAVE}.get(label)
    if art: control.SetBitmap(wx.ArtProvider.GetBitmap(art, wx.ART_BUTTON, parent.FromDIP(wx.Size(16,16))))
    control.Bind(wx.EVT_TOGGLEBUTTON if toggle else wx.EVT_BUTTON, callback)
    return control


def scroller(parent):
    page = wx.lib.scrolledpanel.ScrolledPanel(parent)
    page.SetBackgroundColour('#f7f8fa')
    layout = wx.BoxSizer(wx.VERTICAL)
    page.SetSizer(layout)
    page.SetupScrolling(scroll_x=False, rate_y=12)
    page.SetMinSize((1,1))
    return page, layout


def section(parent, layout, label, *, collapsed=False):
    pane = wx.CollapsiblePane(parent, label=label, style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
    content = pane.GetPane(); rows = wx.BoxSizer(wx.VERTICAL); content.SetSizer(rows)
    pane.Collapse(collapsed)
    def relayout(event):
        current = parent
        while current and not isinstance(current, wx.TopLevelWindow):
            current.Layout()
            if isinstance(current, wx.lib.scrolledpanel.ScrolledPanel): current.FitInside()
            current = current.GetParent()
        event.Skip()
    pane.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, relayout)
    layout.Add(pane, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
    return pane, content, rows


def text_row(frame, parent, layout, key, label, *, scale=1.):
    row = wx.BoxSizer(wx.HORIZONTAL)
    caption = wx.StaticText(parent, label=label)
    row.Add(caption, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
    control = QuantityInput(parent, DEFAULT_CONFIG[key], scale)
    control.Bind(wx.EVT_TEXT, frame.invalidate)
    frame.inputs[key] = control
    row.Add(control, 0)
    layout.Add(row, 0, wx.EXPAND | wx.ALL, 5)
    return control


def build(frame, board):
    frame.SetBackgroundColour('#f7f8fa')
    panel = wx.Panel(frame); outer = wx.BoxSizer(wx.VERTICAL)
    font = panel.GetFont(); font.SetPointSize(9); panel.SetFont(font)
    header = wx.Panel(panel); header.SetBackgroundColour('#ffffff')
    bar = wx.BoxSizer(wx.HORIZONTAL)
    mark=wx.Image(str(Path(__file__).with_name('icon.png')),wx.BITMAP_TYPE_PNG)
    mark.Rescale(*header.FromDIP(wx.Size(30,30)),wx.IMAGE_QUALITY_HIGH)
    bar.Add(wx.StaticBitmap(header,bitmap=wx.Bitmap(mark)),0,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,12)
    brand = wx.StaticText(header, label='Quick EMerge')
    font = brand.GetFont(); font.SetPointSize(12); font.MakeBold(); brand.SetFont(font)
    bar.Add(brand, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 10)
    frame.source_label = wx.StaticText(header, label=Path(board).name, style=wx.ST_ELLIPSIZE_MIDDLE)
    frame.source_label.SetMinSize((80,-1))
    frame.source_label.SetToolTip('Saved board: '+Path(board).name+' · geometry is read-only')
    frame.source_label.SetForegroundColour('#65717f')
    bar.Add(frame.source_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
    frame.preview_button = button(header, 'Preview', frame.preview)
    frame.run_button = button(header, 'Run simulation', frame.run)
    frame.run_button.SetBackgroundColour('#127f82'); frame.run_button.SetForegroundColour('#ffffff')
    frame.cancel_button = button(header, 'Cancel', frame.cancel)
    for control in (frame.preview_button, frame.run_button, frame.cancel_button):
        bar.Add(control, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
    frame.help_button = button(header, 'Help', frame.on_help)
    frame.help_button.SetToolTip('KiCad board, rule-area, sampling and probing guide · F1')
    bar.Add(frame.help_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
    frame.cancel_button.Disable(); frame.run_button.Disable()
    header.SetSizer(bar); outer.Add(header, 0, wx.EXPAND | wx.BOTTOM, 1)
    split = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_NOBORDER)
    frame.workspace_splitter = split
    frame.settings = wx.Panel(split); sidebar = wx.BoxSizer(wx.VERTICAL)
    setup_header=wx.BoxSizer(wx.HORIZONTAL)
    setup_title=wx.StaticText(frame.settings,label='Study setup');setup_title.SetFont(setup_title.GetFont().Bold())
    setup_header.Add(setup_title,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
    for label, callback in [('Open setup',frame.load_setup),('Save setup',frame.save_setup)]:
        control=button(frame.settings,label.split()[0],callback)
        control.SetBitmap(wx.ArtProvider.GetBitmap(wx.ART_FILE_OPEN if label.startswith('Open') else wx.ART_FILE_SAVE,wx.ART_BUTTON,wx.Size(16,16)))
        control.SetToolTip(label+' · parameters and selected geometry source')
        setup_header.Add(control,0,wx.LEFT,4)
    sidebar.Add(setup_header,0,wx.EXPAND|wx.ALL,10)
    frame.setup_book = wx.Notebook(frame.settings)
    model, model_rows = scroller(frame.setup_book)
    physics, physics_rows = scroller(frame.setup_book)
    run, run_rows = scroller(frame.setup_book)
    for page, label in [(model, '1  Geometry'), (physics, '2  Physics'), (run, '3  Solve')]: frame.setup_book.AddPage(page, label)
    sidebar.Add(frame.setup_book, 1, wx.EXPAND); frame.settings.SetSizer(sidebar)
    model_rows.Add(wx.StaticText(model, label='Geometry source'), 0, wx.LEFT | wx.TOP, 14)
    frame.mode = wx.Choice(model, choices=['Patch antenna', 'Transmission-line coupon', 'Saved PCB rule area'])
    frame.mode.SetSelection(0); frame.mode.Bind(wx.EVT_CHOICE, frame.invalidate)
    model_rows.Add(frame.mode, 0, wx.EXPAND | wx.ALL, 12)
    frame.model_sections = {}
    pane, content, rows = section(model, model_rows, 'PCB enclosure')
    frame.model_sections['region'] = pane
    frame.load_areas_button = button(content, 'Load rule areas from PCB', frame.load_rule_areas)
    rows.Add(frame.load_areas_button, 0, wx.EXPAND | wx.ALL, 5)
    frame.rule_area = wx.Choice(content); frame.signal_net = wx.Choice(content); frame.reference_net = wx.Choice(content)
    for label, control in [('Enclosure', frame.rule_area), ('Signal net (F.Cu)', frame.signal_net), ('Reference net (B.Cu)', frame.reference_net)]:
        rows.Add(wx.StaticText(content, label=label), 0, wx.LEFT | wx.TOP, 5)
        rows.Add(control, 0, wx.EXPAND | wx.ALL, 5); control.Bind(wx.EVT_CHOICE, frame.invalidate)
    frame.region_material_review = wx.CheckBox(content, label='Reviewed material and bare-copper model')
    frame.region_material_review.Bind(wx.EVT_CHECKBOX, frame.invalidate); rows.Add(frame.region_material_review, 0, wx.ALL, 5)
    frame.region_notice = wx.StaticText(content, label='Load a saved enclosure to review copper and ports.')
    frame.region_notice.Wrap(275); rows.Add(frame.region_notice, 0, wx.EXPAND | wx.ALL, 5)
    for name, label, fields in [
        ('substrate', 'Substrate', [('substrate_x_mm','Width [mm]'),('substrate_y_mm','Length [mm]'),('thickness_mm','Thickness [mm]')]),
        ('patch', 'Patch geometry', [('patch_width_mm','Width [mm]'),('patch_length_mm','Length [mm]'),('feed_width_mm','Feed width [mm]'),('inset_width_mm','Inset gap [mm]'),('inset_length_mm','Inset length [mm]')]),
        ('line', 'Line geometry', [('line_length_mm','Length [mm]'),('line_width_mm','Width [mm]')])]:
        pane, content, rows = section(model, model_rows, label); frame.model_sections[name] = pane
        for key, caption in fields: text_row(frame, content, rows, key, caption)
    pane, content, rows = section(physics, physics_rows, 'Material')
    material_content, material_rows = content, rows
    text_row(frame, content, rows, 'er', 'Relative permittivity')
    advanced_pane, advanced_content, advanced_rows = section(physics, physics_rows, 'Advanced study options', collapsed=True)
    frame.advanced_pane = advanced_pane
    advanced_pane.SetToolTip('Optional boundary conditions, imports, field sampling, coupled studies and exports')
    frame.advanced_parent = advanced_content; frame.advanced_layout = advanced_rows
    frame.advanced_inputs = {}; frame.advanced_rows = {}; frame.advanced_groups = {}
    frame.study = wx.Choice(physics, choices=['Driven electromagnetic study']); frame.study.SetSelection(0)
    physics_rows.Insert(0, frame.study, 0, wx.EXPAND | wx.ALL, 12)
    frame.study.Bind(wx.EVT_CHOICE, frame.invalidate)
    pane, content, rows = section(physics, physics_rows, 'Mesh refinement', collapsed=True)
    for key, label in [('air_margin_mm','Air margin [mm]'),('mesh_edge_mm','Copper mesh [mm]'),('resolution','Global wavelength fraction'),('adaptive_steps','Local refinement passes'),('max_tets','Maximum tetrahedra')]:
        text_row(frame, content, rows, key, label)
    pane, content, rows = section(run, run_rows, 'Frequency sweep')
    text_row(frame, content, rows, 'f_start_hz', 'Start [GHz]', scale=1e9)
    text_row(frame, content, rows, 'f_stop_hz', 'Stop [GHz]', scale=1e9)
    text_row(frame, content, rows, 'points', 'Frequency samples')
    text_row(frame, content, rows, 'z0_ohm', 'Port impedance [ohm]')
    frame.sweep = wx.Choice(content, choices=['Linear sweep','Adaptive AAA sweep'])
    frame.sweep.SetSelection(0); frame.sweep.Bind(wx.EVT_CHOICE, frame.invalidate); rows.Add(frame.sweep, 0, wx.EXPAND | wx.ALL, 5)
    text_row(frame, content, rows, 'convergence', 'Adaptive AAA response tolerance')
    pane, content, rows = section(run, run_rows, 'Output sampling', collapsed=True)
    text_row(frame, content, rows, 'field_z_mm', 'Field plane Z [mm]')
    text_row(frame, content, rows, 'field_grid', 'Field samples per axis')
    sampling_note = wx.StaticText(content, label='Linear sweep: actual FEM frequency solves.\nField grid: samples of the solved FEM field.\nDriven/array radiation: 2° (91 × 181).\nScattering RCS: 6° (31 × 61).\nMore output samples do not refine the mesh.')
    sampling_note.Wrap(260); rows.Add(sampling_note, 0, wx.EXPAND | wx.ALL, 6)
    frame.dense_sampling_button = button(content, 'Use dense sampling', frame.dense_sampling)
    frame.dense_sampling_button.SetToolTip('Set 81 linear FEM frequencies and an 81 × 81 field grid. Longer solve time; mesh settings stay unchanged.')
    rows.Add(frame.dense_sampling_button, 0, wx.ALL, 5)
    pane, content, rows = section(run, run_rows, 'Solver')
    frame.solver = wx.Choice(content, choices=['SUPERLU','PARDISO','UMFPACK','AASDS','CUDSS','SPARTA'])
    frame.solver.SetSelection(0); frame.solver.Bind(wx.EVT_CHOICE, frame.invalidate); rows.Add(frame.solver, 0, wx.EXPAND | wx.ALL, 5)
    pane, content, rows = section(run, run_rows, 'Runtime and storage', collapsed=True)
    rows.Add(wx.StaticText(content, label='Solver Python'), 0, wx.ALL, 5)
    frame.python = wx.FilePickerCtrl(content, path=sys.executable, message='Solver Python')
    rows.Add(frame.python, 0, wx.EXPAND | wx.ALL, 5)
    rows.Add(wx.StaticText(content, label='Study output folder'), 0, wx.ALL, 5)
    frame.output = wx.DirPickerCtrl(content, path=str(Path(board).parent/'.quick-emerge'))
    rows.Add(frame.output, 0, wx.EXPAND | wx.ALL, 5)
    frame.dependencies_button = button(content, 'Check dependencies', frame.setup_dependencies)
    frame.rollback_button = button(content, 'Restore previous runtime', frame.rollback_runtime)
    for control in (frame.dependencies_button, frame.rollback_button): rows.Add(control, 0, wx.EXPAND | wx.ALL, 5)
    frame.workspace = wx.Panel(split); body = wx.BoxSizer(wx.VERTICAL)
    # The native default stretches the last item on every wrapped row.
    # Tool buttons must keep their content width at every DPI/window size.
    nav = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES); frame.navigation = {}
    for name in ['3D','2D','Charts','Results','Report']:
        control=button(frame.workspace,name,lambda event,name=name:frame.navigate(name),toggle=True)
        nav.Add(control,0,wx.RIGHT,4);frame.navigation[name]=control
    nav.AddSpacer(10)
    nav.Add(button(frame.workspace,'Inspector',frame.toggle_inspector),0,wx.RIGHT,4)
    nav.Add(button(frame.workspace,'View options',frame.show_view_options),0,wx.RIGHT,4)
    frame.focus_button=button(frame.workspace,'Focus',frame.focus_view,toggle=True);nav.Add(frame.focus_button,0)
    body.Add(nav,0,wx.EXPAND | wx.ALL,10)
    frame.workspace_stack=wx.Simplebook(frame.workspace)
    viewer=wx.Panel(frame.workspace_stack); viewer_rows=wx.BoxSizer(wx.VERTICAL)
    frame.view_choice=wx.Choice(viewer)
    # The controller populates this choice after construction; an initially
    # empty native Choice otherwise retains a tiny best width on Windows.
    frame.view_choice.SetMinSize((viewer.FromDIP(170),-1))
    frame.view_choice.SetToolTip('Choose the geometry, field or chart view')
    frame.view_choice.Bind(wx.EVT_CHOICE,frame.choose_view)
    selectors=wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES);selectors.Add(frame.view_choice,0,wx.RIGHT|wx.BOTTOM,6)
    frame.chart_quantity=wx.Choice(viewer,choices=['Magnitude','Phase','Group delay','Impedance','Diagnostics']);frame.chart_quantity.SetSelection(0)
    frame.chart_quantity.Bind(wx.EVT_CHOICE,frame.change_chart_quantity);selectors.Add(frame.chart_quantity,0,wx.RIGHT,8);frame.chart_quantity.Hide()
    frame.network_tools_button=button(viewer,'Network tools',frame.network_tools);selectors.Add(frame.network_tools_button,0,wx.RIGHT,8);frame.network_tools_button.Hide()
    frame.network_export_button=button(viewer,'Export Touchstone',frame.export_network);selectors.Add(frame.network_export_button,0);frame.network_export_button.Hide()
    viewer_rows.Add(selectors,0,wx.LEFT | wx.RIGHT | wx.BOTTOM,8)
    frame.visual_splitter=wx.SplitterWindow(viewer,style=wx.SP_LIVE_UPDATE | wx.SP_NOBORDER)
    frame.visual_splitter.SetMinimumPaneSize(130)
    frame.tabs=wx.Simplebook(frame.visual_splitter)
    frame.render_backend='Matplotlib software view'
    try:
        from .scene_viewport import SceneViewport
        frame.scene_viewport_class=SceneViewport;frame.render_backend='VTK hardware 3D'
    except ImportError:
        frame.scene_viewport_class=None
    for name in ['3D setup','S-parameters','Smith chart','Field probes','3D fields','3D radiation','PCB enclosure']:
        factory=frame.scene_viewport_class if name.startswith('3D') and frame.scene_viewport_class else PlotViewport
        page=factory(frame.tabs,name,frame._viewport_probe)
        if isinstance(page, PlotViewport): page.defer_hidden=True
        frame.tabs.AddPage(page,name);frame.viewports[name]=page
        frame.figures[name]=(getattr(page,'figure',None),getattr(page,'canvas',None))
    frame.details=wx.Notebook(frame.visual_splitter)
    inspector=wx.Panel(frame.details);inspector_rows=wx.BoxSizer(wx.VERTICAL)
    tools=wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
    frame.mouse_mode=wx.Choice(inspector,choices=['Point probe','Line cut (two points)']);frame.mouse_mode.SetSelection(0)
    frame.mouse_mode.Bind(wx.EVT_CHOICE,frame.inspection_mode_changed);tools.Add(frame.mouse_mode,0,wx.ALL,3)
    frame.pin_button=button(inspector,'Pin probe',frame.pin_probe);frame.pin_button.Disable();tools.Add(frame.pin_button,0,wx.ALL,3)
    for label,key in [('Minimum','min'),('Maximum','max')]:tools.Add(button(inspector,label,lambda event,key=key:frame.field_extreme(key)),0,wx.ALL,3)
    inspector_rows.Add(tools,0,wx.EXPAND)
    frame.inspector_text=wx.TextCtrl(inspector,style=wx.TE_MULTILINE | wx.TE_READONLY)
    inspector_rows.Add(frame.inspector_text,1,wx.EXPAND | wx.ALL,3);inspector.SetSizer(inspector_rows);frame.details.AddPage(inspector,'Inspector')
    pins=wx.Panel(frame.details);pin_rows=wx.BoxSizer(wx.VERTICAL)
    frame.pins_list=wx.ListCtrl(pins,style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    for i,(label,width) in enumerate([('#',35),('Kind',70),('GHz',85),('Location / sample',240),('Value',160)]):frame.pins_list.InsertColumn(i,label,width=width)
    frame.pins_list.Bind(wx.EVT_LIST_ITEM_SELECTED,frame.select_pin);pin_rows.Add(frame.pins_list,1,wx.EXPAND)
    actions=wx.BoxSizer(wx.HORIZONTAL)
    for label,callback in [('Export CSV',frame.export_probes),('Clear',frame.clear_probes)]:actions.Add(button(pins,label,callback),0,wx.ALL,3)
    pin_rows.Add(actions,0);pins.SetSizer(pin_rows);frame.details.AddPage(pins,'Pinned probes')
    profile=wx.Panel(frame.details);profile_rows=wx.BoxSizer(wx.VERTICAL)
    frame.profile_figure=Figure(figsize=(8,2),dpi=100);frame.profile_canvas=FigureCanvasWxAgg(profile,wx.ID_ANY,frame.profile_figure)
    frame.profile_canvas.SetMinSize((1,1));profile_rows.Add(frame.profile_canvas,1,wx.EXPAND)
    profile_rows.Add(button(profile,'Export profile CSV',frame.export_profile),0,wx.ALL,3);profile.SetSizer(profile_rows);frame.details.AddPage(profile,'Line profile')
    frame.log=wx.TextCtrl(frame.details,style=wx.TE_MULTILINE | wx.TE_READONLY);frame.details.AddPage(frame.log,'Log')
    frame.visual_splitter.Initialize(frame.tabs);frame.details.Hide()
    viewer_rows.Add(frame.visual_splitter,1,wx.EXPAND)
    frame.probe_label=wx.StaticText(viewer,label='Drag to inspect · wheel to zoom · double-click to fit',style=wx.ST_ELLIPSIZE_END)
    frame.probe_label.SetMinSize((1,-1))
    frame.probe_label.SetForegroundColour('#607080');viewer_rows.Add(frame.probe_label,0,wx.EXPAND | wx.ALL,8)
    viewer.SetSizer(viewer_rows);frame.workspace_stack.AddPage(viewer,'Viewer')
    results=wx.Panel(frame.workspace_stack);result_rows=wx.BoxSizer(wx.VERTICAL)
    frame.result_summary=wx.StaticText(results,label='Run a study to see its results.');result_rows.Add(frame.result_summary,0,wx.EXPAND | wx.ALL,16)
    frame.result_table=wx.ListCtrl(results,style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
    for i,(caption,width) in enumerate([('Result',250),('Value',230),('Unit / scope',300)]):frame.result_table.InsertColumn(i,caption,width=width)
    result_rows.Add(frame.result_table,1,wx.EXPAND | wx.ALL,12);results.SetSizer(result_rows);frame.workspace_stack.AddPage(results,'Results')
    report=wx.Panel(frame.workspace_stack);report_rows=wx.BoxSizer(wx.VERTICAL)
    report_actions=wx.BoxSizer(wx.HORIZONTAL)
    for label,kind in [('Generate preview','preview'),('Export HTML','html'),('Export PDF','pdf')]:report_actions.Add(button(report,label,lambda event,kind=kind:frame.generate_report(kind)),0,wx.ALL,5)
    report_rows.Add(report_actions,0,wx.ALL,8)
    frame.report_status=wx.StaticText(report,label='Reports include the solved model, source checks, charts, probes and limitations.')
    report_rows.Add(frame.report_status,0,wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,14)
    frame.report_host=wx.Panel(report);frame.report_host.SetSizer(wx.BoxSizer(wx.VERTICAL));report_rows.Add(frame.report_host,1,wx.EXPAND | wx.ALL,12)
    report.SetSizer(report_rows);frame.workspace_stack.AddPage(report,'Report')
    body.Add(frame.workspace_stack,1,wx.EXPAND);frame.workspace.SetSizer(body)
    split.SetMinimumPaneSize(frame.FromDIP(270));split.SetSashGravity(0);split.SplitVertically(frame.settings,frame.workspace,frame.FromDIP(310))
    outer.Add(split,1,wx.EXPAND);panel.SetSizer(outer)
    frame.view_options=wx.Dialog(frame,title='Display options',size=(570,260),style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    options_layout=wx.BoxSizer(wx.VERTICAL);frame._build_view_controls(frame.view_options,options_layout)
    frame.view_options.SetSizer(options_layout)
    frame.view_options.Bind(wx.EVT_CLOSE,lambda event:frame.view_options.Hide())
    frame.build_advanced_fields()
    # Keep routine material choices beside permittivity; retain every optional
    # parameter in the advanced sections with its existing controller binding.
    for key in ('loss_tangent','conductor'):
        row, descriptor, group = frame.advanced_rows[key]
        row.GetContainingSizer().Detach(row); row.Reparent(material_content)
        material_rows.Add(row,0,wx.EXPAND|wx.ALL,5)
        frame.advanced_rows[key]=(row,descriptor,'Material overview')
    # The selected study's defining geometry is a primary control, not an
    # expert solver setting. Other groups remain collapsed until requested.
    for offset, group in enumerate(('Array','Waveguide','Scattering','Optimization')):
        pane, _, _ = frame.advanced_groups[group]
        advanced_rows.Detach(pane); pane.Reparent(physics)
        physics_rows.Insert(2+offset,pane,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        pane.Collapse(False)
    frame.update_model_sections()
    frame.navigate('3D')
