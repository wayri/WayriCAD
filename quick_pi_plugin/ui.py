"""Native Quick PI window: saved copper, mesh and DC results in one workflow."""
from __future__ import annotations
from pathlib import Path
import math
import threading
import wx
from wayricad_runtime.readable_choice import ReadableChoice, ReadableComboBox
from matplotlib.figure import Figure
from .plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
from .workspace_controls import BoardNavigation,ColorLegend,SidebarText,StatusText,icon_button
from .live_ui import LiveCurrentControls

from .report import (METRICS,draw_view,layer_rows,write_report,via_markers,
                     inspection_record,probe_result,result_scale,validate_scale,
                     terminal_ids,metric_name,feasibility_text,sink_results_text)
import json


def load_values(terminal,current,minimum='',maximum='',*,power=False):
    """Validate editable sink fields; a blank voltage field is unbounded."""
    row={'terminal':terminal}
    demand='power_W' if power else 'current_A'
    for key,text in [(demand,current),('min_voltage_V',minimum),('max_voltage_V',maximum)]:
        if key!=demand and not str(text).strip():continue
        try:value=float(text)
        except (ValueError,TypeError):raise ValueError('Load demand and voltage limits must be numbers.')
        if not math.isfinite(value) or (value<=0 if key==demand else value<0):
            raise ValueError('Sink current/power must be positive; voltage limits must be nonnegative and finite.')
        row[key]=value
    if row.get('max_voltage_V',math.inf)<row.get('min_voltage_V',0):raise ValueError('Maximum sink voltage must be at least the minimum.')
    return row


class QuickPIFrame(LiveCurrentControls,wx.Frame):
    def __init__(self,parent,board_path):
        super().__init__(parent,title='WayriCAD Quick PI',size=(1320,860))
        icon_prefix='icon-'
        icon_dir=Path(__file__).with_name('resources')
        icons=wx.IconBundle()
        for size in (24,48,96):
            icon_path=icon_dir/f'{icon_prefix}{size}.png'
            if icon_path.is_file():icons.AddIcon(wx.Icon(str(icon_path),wx.BITMAP_TYPE_PNG))
        if icons.GetIcon(wx.Size(48,48)).IsOk():self.SetIcons(icons)
        self.SetMinSize((960,600));self.board_path=str(Path(board_path).resolve())
        self.bundle={};self.inventory={};self.return_bundle={};self.sweep_bundle={};self.volume_bundle={}
        self._busy=False;self._closed=False;self._closing=False
        self._series_request=None
        self._package_conduction=[]
        self._cancel=threading.Event();self._terminals=[];self._layers=[];self._plot_keys={};self._probe_controllers={}
        self._extra_sinks=[];self._inspection=None;self._finding_rows=[];self._saved_source_current=True
        self._pin_peer_ids={'source':[],'sink':[]}
        self._board_scene={};self._board_scene_hash=None
        self._history=[];self._history_index=0;self._completions=[];self._completion_prefix=None;self._completion_index=0
        panel=wx.Panel(self);self.main_panel=panel;root=wx.BoxSizer(wx.VERTICAL)
        font=panel.GetFont();font.SetPointSize(9);panel.SetFont(font)
        self._inputs_visible=True;self._inspector_visible=True
        header=wx.BoxSizer(wx.HORIZONTAL)
        title=wx.StaticText(panel,label='Quick PI');bold=title.GetFont();bold.SetWeight(wx.FONTWEIGHT_BOLD);title.SetFont(bold)
        header.Add(title,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
        filename=StatusText(panel,Path(self.board_path).name);filename.SetToolTip(self.board_path)
        header.Add(filename,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,10)
        self.setup_toggle=wx.ToggleButton(panel,label='Setup',style=wx.BU_EXACTFIT);self.setup_toggle.SetValue(True)
        self.inspector_toggle=wx.ToggleButton(panel,label='Inspect',style=wx.BU_EXACTFIT);self.inspector_toggle.SetValue(True)
        self.setup_toggle.SetToolTip('Show or hide source, loads and simulation settings')
        self.inspector_toggle.SetToolTip('Show or hide layers, result colours and probes')
        self.fit_button=icon_button(panel,'Fit',wx.ART_GO_HOME,'Fit the whole board · double-click the board')
        self.zoom_in=icon_button(panel,'+',wx.ART_PLUS,'Zoom in · mouse wheel on the board')
        self.zoom_out=icon_button(panel,'−',wx.ART_MINUS,'Zoom out · drag the board to pan')
        self.image_button=icon_button(panel,'',wx.ART_FILE_SAVE,'Save the current board image')
        self.more=icon_button(panel,'More',wx.ART_LIST_VIEW,'Transient PI, electrothermal, series studies and diagnostics')
        self.help_button=icon_button(panel,'',wx.ART_HELP,'Quick PI help')
        for control in (self.setup_toggle,self.inspector_toggle,self.fit_button,self.zoom_in,self.zoom_out,self.image_button,self.more,self.help_button):
            header.Add(control,0,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,4)
        root.Add(header,0,wx.EXPAND|wx.ALL,6)
        body=wx.BoxSizer(wx.HORIZONTAL)
        self.workspace_splitter=wx.SplitterWindow(panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        self.workspace_splitter.SetMinimumPaneSize(self.FromDIP(220))
        self.workspace_splitter.SetSashGravity(0.)
        self.setup_panel=wx.Panel(self.workspace_splitter);self.setup_panel.SetMinSize((self.FromDIP(220),1))
        setup=wx.BoxSizer(wx.VERTICAL)
        self.inputs=wx.ScrolledWindow(self.setup_panel,style=wx.VSCROLL)
        self.inputs.SetScrollRate(0,12);self.inputs.SetMinSize((1,1))
        controls=wx.BoxSizer(wx.VERTICAL)
        def field(label,control):
            controls.Add(wx.StaticText(self.inputs,label=label),0,wx.EXPAND|wx.TOP|wx.BOTTOM,4)
            control.SetMinSize((1,-1));controls.Add(control,0,wx.EXPAND|wx.BOTTOM,3)
        self.net_search=wx.SearchCtrl(self.inputs);self.net_search.SetHint('Find net: * wildcard, ~ fuzzy');self.net_search.SetMinSize((1,-1))
        controls.Add(self.net_search,0,wx.EXPAND|wx.BOTTOM,4)
        self.net=ReadableComboBox(self.inputs,style=wx.CB_READONLY);field('Net',self.net)
        pick=icon_button(self.inputs,'Pick net',wx.ART_FIND,'Pick a saved pad, track or via on the board to choose its net')
        controls.Add(pick,0,wx.EXPAND|wx.BOTTOM,6);pick.Bind(wx.EVT_BUTTON,self.select_board_net)
        self.source=ReadableChoice(self.inputs);self.sink=ReadableChoice(self.inputs)
        field('Source pad',self.source)
        self.source_pins=wx.CheckBox(self.inputs,label='Include other same-net pins');self.source_pins.Hide()
        controls.Add(self.source_pins,0,wx.EXPAND|wx.BOTTOM,5)
        field('Sink pad',self.sink)
        self.sink_pins=wx.CheckBox(self.inputs,label='Include other same-net pins');self.sink_pins.Hide()
        controls.Add(self.sink_pins,0,wx.EXPAND|wx.BOTTOM,5)
        for control in (self.source_pins,self.sink_pins):control.Bind(wx.EVT_CHECKBOX,self._invalidate)
        self.voltage=wx.TextCtrl(self.inputs,value='1');self.current=wx.TextCtrl(self.inputs,value='1')
        values=wx.FlexGridSizer(2,2,4,8);values.AddGrowableCol(0);values.AddGrowableCol(1)
        self.current_label=wx.StaticText(self.inputs,label='Load · A')
        values.Add(wx.StaticText(self.inputs,label='Source · V'));values.Add(self.current_label)
        for control in (self.voltage,self.current):control.SetMinSize((1,-1));values.Add(control,0,wx.EXPAND)
        controls.Add(values,0,wx.EXPAND|wx.TOP|wx.BOTTOM,5)
        self.load_mode=ReadableChoice(self.inputs,choices=['Sink current · A','Resistive load · Ω','Constant power · W']);self.load_mode.SetSelection(0)
        self.load_mode.SetToolTip('Constant power solves P = Vload × I on the stable high-voltage DC branch. Infeasible/collapsed loads are reported; this is not a converter transient model.')
        self.load_mode.SetMinSize((1,-1));controls.Add(self.load_mode,0,wx.EXPAND|wx.BOTTOM,6)
        limits=wx.FlexGridSizer(2,3,4,5)
        self.source_current_limit=wx.TextCtrl(self.inputs);self.source_current_limit.SetHint('No limit')
        self.sink_min_voltage=wx.TextCtrl(self.inputs);self.sink_min_voltage.SetHint('0')
        self.sink_max_voltage=wx.TextCtrl(self.inputs);self.sink_max_voltage.SetHint('No limit')
        for index,label in enumerate(('Limit · A','Min · V','Max · V')):limits.AddGrowableCol(index);limits.Add(wx.StaticText(self.inputs,label=label))
        for control in (self.source_current_limit,self.sink_min_voltage,self.sink_max_voltage):control.SetMinSize((1,-1));limits.Add(control,0,wx.EXPAND)
        controls.Add(limits,0,wx.EXPAND|wx.BOTTOM,6)
        self.source_current_limit.SetToolTip('Source current budget. Blank means unlimited; zero supplies no current. Demand above this budget is infeasible, not a simulated constant-current response.')
        self.sink_min_voltage.SetToolTip('Minimum allowed voltage at the primary sink; blank means 0 V')
        self.sink_max_voltage.SetToolTip('Maximum allowed voltage at the primary sink; blank means unbounded')
        self.loads_button=icon_button(self.inputs,'Additional sinks (0)…',wx.ART_PLUS,'Add simultaneous loads on this net with individual current and voltage limits')
        controls.Add(self.loads_button,0,wx.EXPAND|wx.BOTTOM,6)
        self.package_button=icon_button(self.inputs,'Package contacts (0)…',wx.ART_LIST_VIEW,'Enter explicit lead, solder and BGA geometry and resistivity per pad face')
        controls.Add(self.package_button,0,wx.EXPAND|wx.BOTTOM,6)
        self.package_button.Bind(wx.EVT_BUTTON,self.on_package_contacts)
        self.model_dimension=ReadableChoice(self.inputs,choices=['2.5D · layered copper','3D · copper volume']);self.model_dimension.SetSelection(0)
        field('Copper model',self.model_dimension)
        self.joule_feedback=wx.CheckBox(self.inputs,label='Include Joule heating /\ntemperature feedback')
        self.joule_feedback.SetToolTip('DC always calculates copper I²R losses. Check this to configure explicit materials, cooling boundaries and steady temperature-to-resistance feedback. Supported for 2.5D prescribed-current loads only.')
        controls.Add(self.joule_feedback,0,wx.EXPAND|wx.BOTTOM,6)
        self.joule_feedback.Bind(wx.EVT_CHECKBOX,self._invalidate)
        self.batch_button=wx.Button(self.inputs,label='Rails / ground returns…')
        self.batch_button.SetToolTip('Set up the ground return for this rail, or add multiple rails with shared return copper. The guided tables show all pad mappings together.')
        controls.Add(self.batch_button,0,wx.EXPAND|wx.BOTTOM,6);self.batch_button.Bind(wx.EVT_BUTTON,self.on_batch)
        self.operation_note=SidebarText(self.inputs,'Source voltage → sink current')
        controls.Add(self.operation_note,0,wx.EXPAND|wx.BOTTOM,6)
        self.options=wx.CollapsiblePane(self.inputs,label='Mesh & material',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.options.Collapse(True);pane=self.options.GetPane();grid=wx.FlexGridSizer(0,2,5,5);grid.AddGrowableCol(1)
        self.edge=wx.TextCtrl(pane,value='0.5');self.plating=wx.TextCtrl(pane,value='0.025')
        self.auto_mesh=wx.CheckBox(pane,label='Automatic mesh');self.auto_mesh.SetValue(True)
        self.auto_mesh.SetToolTip('Recommend the background edge from saved copper extent and refine locally near tracks, pad contacts and via annuli. This is not mesh convergence. Uncheck for a manual edge or 3D.')
        grid.Add(wx.StaticText(pane,label='Sizing'));grid.Add(self.auto_mesh,0,wx.EXPAND)
        self.auto_mesh.Bind(wx.EVT_CHECKBOX,self._invalidate)
        self.temperature=wx.TextCtrl(pane,value='20');self.ambient=wx.TextCtrl(pane,value='20')
        self.pulse=wx.TextCtrl(pane,value='1');self.limit=wx.TextCtrl(pane,value='150');self.max_tetrahedra=wx.TextCtrl(pane,value='250000')
        self.melting=wx.TextCtrl(pane,value='1084.62');self.latent=wx.TextCtrl(pane,value='206750')
        self.melting.SetToolTip('Adiabatic copper melting threshold; initial temperature uses Ambient. Frozen DC current pattern and linear rho(T); melting does not imply fuse opening. NIST Cp range 250–1358 K.')
        self.latent.SetToolTip('Copper heat of fusion, J/kg. Editable nominal pure-copper input; no cooling, arcing or clearing-time prediction.')
        for label,control in [('Mesh · mm',self.edge),('Via plating · mm',self.plating),('Copper · °C',self.temperature),('Initial / ambient · °C',self.ambient),('Pulse · s',self.pulse),('Limit · °C',self.limit),('Copper melt · °C',self.melting),('Latent heat · J/kg',self.latent),('3D cell budget',self.max_tetrahedra)]:
            grid.Add(wx.StaticText(pane,label=label),0,wx.ALIGN_CENTER_VERTICAL);control.SetMinSize((1,-1));grid.Add(control,0,wx.EXPAND)
        pane.SetSizer(grid);controls.Add(self.options,0,wx.EXPAND|wx.TOP|wx.BOTTOM,6)
        self.console=wx.CollapsiblePane(self.inputs,label='Console',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE);self.console.Collapse(True)
        console_panel=self.console.GetPane();console_layout=wx.BoxSizer(wx.VERTICAL)
        self.console_log=wx.TextCtrl(console_panel,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,95));self.console_log.SetMinSize((1,95))
        self.console_input=wx.TextCtrl(console_panel,style=wx.TE_PROCESS_ENTER);self.console_input.SetMinSize((1,-1));self.console_input.SetHint('help · run pi …')
        console_layout.Add(self.console_log,1,wx.EXPAND|wx.BOTTOM,5);console_layout.Add(self.console_input,0,wx.EXPAND)
        console_panel.SetSizer(console_layout);controls.Add(self.console,0,wx.EXPAND|wx.BOTTOM,6)
        self.summary=SidebarText(self.inputs,'Choose a source and sink, then preview or run. Use Additional sinks for simultaneous loads.')
        controls.Add(self.summary,0,wx.EXPAND|wx.TOP,6)
        content=wx.BoxSizer(wx.VERTICAL);content.Add(controls,0,wx.EXPAND|wx.ALL,8);self.inputs.SetSizer(content)
        setup.Add(self.inputs,1,wx.EXPAND)
        actions=wx.GridSizer(0,2,5,5)
        self.preview=icon_button(self.setup_panel,'Preview',wx.ART_FIND,'Preview saved copper before solving')
        self.run=icon_button(self.setup_panel,'Run',wx.ART_GO_FORWARD,'Run the selected copper simulation')
        self.export=icon_button(self.setup_panel,'Save results',wx.ART_FILE_SAVE,'Save HTML, complete numerical JSON and portable Pocket KiVi data')
        self.series_button=icon_button(self.setup_panel,'Series',wx.ART_LIST_VIEW,'Build a series path with explicit components')
        self.power_flow=icon_button(self.setup_panel,'Power flow',wx.ART_REPORT_VIEW,'Open the source-to-sink Sankey power budget')
        self.blender=icon_button(self.setup_panel,'Blender…',wx.ART_FILE_SAVE,'Export solved geometry and fields for Blender visualization')
        self.blender.Bind(wx.EVT_BUTTON,self.on_blender)
        for control in (self.preview,self.run,self.export,self.series_button,self.power_flow,self.blender):actions.Add(control,0,wx.EXPAND)
        setup.Add(actions,0,wx.EXPAND|wx.ALL,8)
        from wayricad_runtime.project_results_ui import add_project_results
        self.project_results=add_project_results(self,self.setup_panel,setup,'quick-pi',self.board_path,
            lambda:[('2.5D DC',self.bundle if self.bundle.get('result') else None),
                    ('3D DC',self.volume_bundle if self.volume_bundle.get('result') else None),
                    ('DC current sweep',self.sweep_bundle),('Return-path review',self.return_bundle)],
            status=lambda text:self.status.SetLabel(text),module_file=__file__)
        self.setup_panel.SetSizer(setup)

        self.splitter=wx.SplitterWindow(self.workspace_splitter,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        self.splitter.SetMinimumPaneSize(self.FromDIP(200));self.splitter.SetSashGravity(1.)
        self.book=wx.Notebook(self.splitter);self.book.SetMinSize((200,200));self.views=[]
        for name in ('Net','Mesh','Results'):
            page=wx.Panel(self.book);layout=wx.BoxSizer(wx.VERTICAL)
            figure=Figure(figsize=(9,7),dpi=100,facecolor='#f3f5f6');canvas=FigureCanvasWxAgg(page,wx.ID_ANY,figure);canvas.SetMinSize((1,1))
            navigation=BoardNavigation(canvas)
            if name=='Results':self._init_live_controls(page,layout,canvas)
            canvas.Bind(wx.EVT_LEFT_DOWN,lambda event,index=len(self.views):self._probe_down(event,index))
            canvas.Bind(wx.EVT_LEFT_UP,lambda event,index=len(self.views):self._probe_up(event,index))
            layout.Add(canvas,1,wx.EXPAND);page.SetSizer(layout)
            self.book.AddPage(page,name);self.views.append((figure,canvas,navigation))
        self._build_return_page()
        from .decoupling.pdn_decoupling_plugin import PdnFrame
        import pcbnew
        self.decoupling=PdnFrame(self.book,None,board_loader=lambda:pcbnew.LoadBoard(self.board_path));self.book.AddPage(self.decoupling,'Decoupling')
        self._build_inspector();self.splitter.SplitVertically(self.book,self.inspector,790)
        self.workspace_splitter.SplitVertically(self.setup_panel,self.splitter,self.FromDIP(260))
        body.Add(self.workspace_splitter,1,wx.EXPAND);root.Add(body,1,wx.EXPAND|wx.LEFT|wx.RIGHT,4)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.status=StatusText(panel,'Reading the saved board…');footer.Add(self.status,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.gauge=wx.Gauge(panel,range=100,size=(100,-1));footer.Add(self.gauge,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.cancel=icon_button(panel,'Cancel',wx.ART_CROSS_MARK,'Cancel the running study');footer.Add(self.cancel,0)
        root.Add(footer,0,wx.EXPAND|wx.ALL,6);panel.SetSizer(root)
        self._controls=[self.joule_feedback,self.batch_button,self.net,self.source,self.sink,self.voltage,self.current,self.source_current_limit,self.sink_min_voltage,self.sink_max_voltage,self.loads_button,self.package_button,self.load_mode,self.model_dimension,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit,self.melting,self.latent,self.max_tetrahedra,self.more,self.series_button,self.layer,self.metric,self.field_style,self.console_input]
        self.net.Bind(wx.EVT_COMBOBOX,self._net_changed);self.net_search.Bind(wx.EVT_TEXT,self._schedule_net_filter)
        self._controls.extend([self.source_pins,self.sink_pins])
        for control in (self.source,self.sink):control.Bind(wx.EVT_CHOICE,self._endpoint_changed)
        for control in (self.voltage,self.current,self.source_current_limit,self.sink_min_voltage,self.sink_max_voltage,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit,self.melting,self.latent,self.max_tetrahedra):control.Bind(wx.EVT_TEXT,self._invalidate)
        self.load_mode.Bind(wx.EVT_CHOICE,self._invalidate);self.model_dimension.Bind(wx.EVT_CHOICE,self._model_changed)
        self.loads_button.Bind(wx.EVT_BUTTON,self.on_loads)
        self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,self._layout_inputs);self.console.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,self._layout_inputs)
        self.console_input.Bind(wx.EVT_TEXT_ENTER,self.on_console);self.console_input.Bind(wx.EVT_KEY_DOWN,self._console_key)
        self.layer.Bind(wx.EVT_CHOICE,lambda event:self._draw());self.metric.Bind(wx.EVT_CHOICE,lambda event:self._draw(preserve=True))
        self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,self._page_changed)
        self.setup_toggle.Bind(wx.EVT_TOGGLEBUTTON,self._toggle_setup);self.inspector_toggle.Bind(wx.EVT_TOGGLEBUTTON,self._toggle_inspector)
        self.fit_button.Bind(wx.EVT_BUTTON,lambda event:self._navigate('fit'))
        self.zoom_in.Bind(wx.EVT_BUTTON,lambda event:self._navigate('zoom',.8));self.zoom_out.Bind(wx.EVT_BUTTON,lambda event:self._navigate('zoom',1.25))
        self.image_button.Bind(wx.EVT_BUTTON,self._save_view_image)
        self.preview.Bind(wx.EVT_BUTTON,self.preview_geometry);self.run.Bind(wx.EVT_BUTTON,self.on_run)
        self.more.Bind(wx.EVT_BUTTON,self.on_more);self.export.Bind(wx.EVT_BUTTON,self.on_export);self.help_button.Bind(wx.EVT_BUTTON,self.on_help)
        self.power_flow.Bind(wx.EVT_BUTTON,self.on_power_flow)
        self.series_button.Bind(wx.EVT_BUTTON,self.on_series_editor);self.cancel.Bind(wx.EVT_BUTTON,self.on_cancel)
        self.Bind(wx.EVT_CLOSE,self.on_close);self.Bind(wx.EVT_ACTIVATE,self._activated)
        self.timer=wx.Timer(self);self.Bind(wx.EVT_TIMER,lambda event:self.gauge.Pulse() if self._busy else None,self.timer);self.timer.Start(120)
        self._buttons();self._draw();self.Centre();self.Maximize(True)
        wx.CallAfter(lambda:self.splitter.SetSashPosition(max(self.FromDIP(200),self.splitter.GetClientSize().width-self.FromDIP(260))))
        wx.CallAfter(self._inspect)
        from wayricad_runtime.layout import install_accessibility
        install_accessibility(self,Path(__file__).with_name('help.html'))

    def _layout_inputs(self,event=None):
        self.inputs.Layout();self.inputs.FitInside();self.setup_panel.Layout()
        if event:event.Skip()

    def _sync_workspace(self):
        placement=self.book.GetSelection()>=len(self.views)
        show_setup=not placement and self._inputs_visible
        if show_setup and not self.workspace_splitter.IsSplit():
            self.setup_panel.Show();self.workspace_splitter.SplitVertically(self.setup_panel,self.splitter,self.FromDIP(260))
        elif not show_setup and self.workspace_splitter.IsSplit():self.workspace_splitter.Unsplit(self.setup_panel)
        visible=not placement and self._inspector_visible
        if not visible and self.splitter.IsSplit():self.splitter.Unsplit(self.inspector)
        elif visible and not self.splitter.IsSplit():
            self.inspector.Show();self.splitter.SplitVertically(self.book,self.inspector,max(self.FromDIP(200),self.splitter.GetClientSize().width-self.FromDIP(260)))
        for toggle,value in ((self.setup_toggle,self._inputs_visible),(self.inspector_toggle,self._inspector_visible)):
            toggle.SetValue(not placement and value);toggle.Enable(not placement)
        for control in (self.fit_button,self.zoom_in,self.zoom_out,self.image_button):control.Enable(not placement)
        self.main_panel.Layout()

    def _toggle_setup(self,event=None):
        self._inputs_visible=self.setup_toggle.GetValue();self._sync_workspace()

    def _toggle_inspector(self,event=None):
        self._inspector_visible=self.inspector_toggle.GetValue();self._sync_workspace()

    def _navigate(self,action,factor=None):
        index=self.book.GetSelection()
        if 0<=index<len(self.views):
            navigation=self.views[index][2]
            navigation.fit() if action=='fit' else navigation.zoom(factor)

    def _save_view_image(self,event=None):
        index=self.book.GetSelection()
        if not 0<=index<len(self.views):return
        with wx.FileDialog(self,'Save board image',defaultFile='Quick-PI.png',wildcard='PNG image (*.png)|*.png',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:self.views[index][0].savefig(dialog.GetPath(),dpi=160)
            except (OSError,ValueError) as error:self.status.SetLabel('Image could not be saved: '+str(error))


    def _build_return_page(self):
        page=wx.Panel(self.book);layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(page,label='1 · Choose a signal or rail   2 · Confirm its return net   3 · Review the board. This checks saved return-plane coverage and stitching; it does not solve return current.')
        note.Wrap(1050);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        from wayricad_runtime.searchable_selection import searchable_row
        settings=wx.WrapSizer(wx.HORIZONTAL,flags=wx.REMOVE_LEADING_SPACES)
        self.return_signal=ReadableChoice(page)
        self.return_signal.SetMinSize((210,-1))
        settings.Add(wx.StaticText(page,label='Signal / rail'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        settings.Add(searchable_row(self.return_signal),0,wx.RIGHT|wx.BOTTOM,8)
        self.return_current=wx.Button(page,label='Use Setup net')
        self.return_current.SetToolTip('Use the net currently selected in the main PI setup.')
        self.return_current.Bind(wx.EVT_BUTTON,self._return_use_current)
        settings.Add(self.return_current,0,wx.RIGHT|wx.BOTTOM,12)
        self.return_primary=ReadableChoice(page,choices=['Choose return net…'])
        self.return_primary.SetSelection(0);self.return_primary.SetMinSize((210,-1))
        settings.Add(wx.StaticText(page,label='Return net'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        settings.Add(searchable_row(self.return_primary),0,wx.RIGHT|wx.BOTTOM,8)
        self.return_suggest=wx.Button(page,label='Use suggested return')
        self.return_suggest.Bind(wx.EVT_BUTTON,self._return_use_suggestion)
        settings.Add(self.return_suggest,0,wx.RIGHT|wx.BOTTOM,12)
        self.return_run=wx.Button(page,label='Review return path');self.return_run.Bind(wx.EVT_BUTTON,self.on_return_path)
        self.return_export=wx.Button(page,label='Save results…');self.return_export.Bind(wx.EVT_BUTTON,lambda e:self.on_export_diagnostic('return_path'))
        settings.Add(self.return_run,0,wx.RIGHT,7);settings.Add(self.return_export,0);layout.Add(settings,0,wx.EXPAND|wx.ALL,10)
        self.return_hint=wx.StaticText(page,label='Choose the actual return; suggestions are names only.')
        layout.Add(self.return_hint,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.return_options=wx.CollapsiblePane(page,label='More return options · multiple nets, optional pads and sampling')
        options=self.return_options.GetPane();side=wx.BoxSizer(wx.HORIZONTAL)
        nets=wx.BoxSizer(wx.VERTICAL);nets.Add(wx.StaticText(options,label='Check additional return nets only if needed'),0,wx.BOTTOM,5)
        from wayricad_runtime.readable_choice import SearchableCheckListBox
        self.return_nets=SearchableCheckListBox(options,size=(240,110));nets.Add(searchable_row(self.return_nets),1,wx.EXPAND)
        side.Add(nets,1,wx.EXPAND|wx.RIGHT,12)
        pads=wx.BoxSizer(wx.VERTICAL)
        self.return_source=ReadableChoice(options,choices=['Not specified']);self.return_source.SetSelection(0)
        self.return_sink=ReadableChoice(options,choices=['Not specified']);self.return_sink.SetSelection(0)
        for label,control in [('Source return pad (optional)',self.return_source),('Load return pad (optional)',self.return_sink)]:
            pads.Add(wx.StaticText(options,label=label),0,wx.TOP,5);pads.Add(searchable_row(control),0,wx.EXPAND|wx.TOP,3)
            control.Bind(wx.EVT_CHOICE,self._invalidate_return)
        sampling=wx.BoxSizer(wx.HORIZONTAL)
        self.return_pitch=wx.TextCtrl(options,value='0.25',size=(65,-1))
        self.return_radius=wx.TextCtrl(options,value='2',size=(65,-1))
        for label,control in [('Sample mm',self.return_pitch),('Via radius mm',self.return_radius)]:
            sampling.Add(wx.StaticText(options,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5)
            sampling.Add(control,0,wx.RIGHT,8)
        pads.Add(sampling,0,wx.TOP,8);side.Add(pads,2,wx.EXPAND);options.SetSizer(side)
        layout.Add(self.return_options,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        self.return_options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:page.Layout())
        self.return_figure=Figure(figsize=(8,4),dpi=100);self.return_canvas=FigureCanvasWxAgg(page,wx.ID_ANY,self.return_figure)
        layout.Add(self.return_canvas,1,wx.EXPAND|wx.ALL,10)
        self.return_table=wx.ListCtrl(page,style=wx.LC_REPORT,size=(-1,145))
        for i,(name,width) in enumerate([('Level',90),('Finding',210),('Layer',100),('Position mm',120),('Detail',510)]):
            self.return_table.InsertColumn(i,name,width=width)
        layout.Add(self.return_table,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        details=wx.CollapsiblePane(page,label='Detailed evidence and model limits')
        detail_layout=wx.BoxSizer(wx.VERTICAL)
        self.return_details=wx.TextCtrl(details.GetPane(),style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,100))
        detail_layout.Add(self.return_details,1,wx.EXPAND);details.GetPane().SetSizer(detail_layout)
        layout.Add(details,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:page.Layout())
        self.return_status=wx.StaticText(page,label='Choose a signal and confirm its return. Optional pad assignments are not required for this geometry review.')
        layout.Add(self.return_status,0,wx.EXPAND|wx.ALL,10)
        self.return_signal.Bind(wx.EVT_CHOICE,self._return_signal_changed)
        self.return_primary.Bind(wx.EVT_CHOICE,self._return_primary_changed)
        for ctrl in (self.return_pitch,self.return_radius):ctrl.Bind(wx.EVT_TEXT,self._invalidate_return)
        self.return_nets.Bind(wx.EVT_CHECKLISTBOX,self._return_nets_changed)
        page.SetSizer(layout);self.book.AddPage(page,'Return path')
        self._return_page=page;self._return_follow_current=True;self._return_pad_ids={}






    def _return_selected_nets(self):
        return [self.return_nets.GetString(i) for i in self.return_nets.GetCheckedItems()]

    def _return_refresh_hint(self):
        from wayricad_runtime.return_setup import suggest_return_nets
        names=list(self.inventory.get('nets',[]));signal=self.return_signal.GetStringSelection()
        candidates=suggest_return_nets(names,signal)
        self._return_suggestion=candidates[0]['name'] if candidates else None
        self.return_suggest.SetLabel(('Use '+self._return_suggestion if len(self._return_suggestion)<36 else 'Use suggested return') if self._return_suggestion else 'No name suggestion')
        self.return_suggest.SetToolTip((self._return_suggestion+' — name suggestion only; confirm the actual return.') if self._return_suggestion else 'Choose the actual return net manually.')
        self.return_suggest.Enable(not self._busy and bool(self._return_suggestion))
        selected=self._return_selected_nets()
        choices=['Choose return net…']+names
        if len(selected)>1:choices.append('Multiple selected · see More options')
        self.return_primary.Set(choices)
        self.return_primary.SetStringSelection(selected[0] if len(selected)==1 else choices[-1] if selected else choices[0])
        text=('Using: '+', '.join(n if len(n)<65 else n[:62]+'…' for n in selected[:3])+(' · +'+str(len(selected)-3)+' more' if len(selected)>3 else '')) if selected else 'Choose the actual return net. A ground-like name is a suggestion, not electrical proof.'
        self.return_hint.SetToolTip('\n'.join(selected))
        self.return_hint.SetLabel(text);self.return_hint.Wrap(max(400,self._return_page.GetClientSize().width-25))

    def _return_primary_changed(self,event=None):
        name=self.return_primary.GetStringSelection()
        if name not in self.inventory.get('nets',[]):return
        for i in range(self.return_nets.GetCount()):self.return_nets.Check(i,self.return_nets.GetString(i)==name)
        self._return_nets_changed()

    def _return_use_suggestion(self,event=None):
        if not getattr(self,'_return_suggestion',None):return
        self.return_primary.SetStringSelection(self._return_suggestion);self._return_primary_changed()

    def _return_use_current(self,event=None):
        name=self.net.GetValue()
        if name in self.return_signal.GetStrings():self.return_signal.SetStringSelection(name)
        self._return_follow_current=True;self._return_signal_changed()

    def _return_signal_changed(self,event=None):
        if event:self._return_follow_current=False
        signal=self.return_signal.GetStringSelection()
        for i in self.return_nets.GetCheckedItems():
            if self.return_nets.GetString(i)==signal:self.return_nets.Check(i,False)
        # An endpoint belongs to the previous signal context, even if the
        # newly chosen signal happens to use the same ground domain.
        self.return_source.SetSelection(0);self.return_sink.SetSelection(0)
        self._return_nets_changed(event)

    def _return_nets_changed(self,event=None):
        from wayricad_runtime.return_setup import return_pad_candidates
        selected=set(self._return_selected_nets())
        rows=return_pad_candidates(self.inventory.get('terminals',[]),selected)
        counts={}
        for row in rows:counts[row['label']]=counts.get(row['label'],0)+1
        self._return_pad_ids={}
        for row in rows:
            label=row['label'] if counts[row['label']]==1 else row['label']+' ['+row['id']+']'
            self._return_pad_ids[label]=row['id']
        choices=['Not specified']+list(self._return_pad_ids)
        for control in (self.return_source,self.return_sink):
            old=control.GetStringSelection();control.Set(choices);control.SetStringSelection(old if old in choices else 'Not specified')
        self._return_refresh_hint()
        self._invalidate_return(event)

    def _invalidate_return(self,event=None):
        self._input_revision=getattr(self,'_input_revision',0)+1
        if self._busy:self._cancel.set()
        self.return_bundle={};self.return_table.DeleteAllItems();self.return_details.Clear();self.return_figure.clear()
        self.return_canvas.draw_idle();self.return_status.SetLabel('Inputs changed. Review the saved return path again.')
        self._buttons()
        if event:event.Skip()

    def _buttons(self):
        if hasattr(self,'live_current'):
            for control in (self.live_scroll,self.live_current,self.live_step):control.Enable(not self._busy and self._live_model is not None)
            if not self._busy and self._live_model and self._live_pending is not None and not self._live_running and self._live_timer is None:
                self._live_timer=wx.CallLater(16,self._start_live_current)
        placement=self.book.GetSelection()>=len(self.views)
        self._sync_workspace()
        for control in self._controls:control.Enable(not self._busy)
        for control in (self.return_signal,self.return_pitch,self.return_radius,self.return_nets,self.return_source,self.return_sink):
            control.Enable(not self._busy)
        selected_returns=self._return_selected_nets();signal=self.return_signal.GetStringSelection()
        self.return_run.Enable(not self._busy and bool(signal and selected_returns) and signal not in selected_returns)
        self.return_primary.Enable(not self._busy);self.return_current.Enable(not self._busy)
        self.return_suggest.Enable(not self._busy and bool(getattr(self,'_return_suggestion',None)))
        self.return_export.Enable(not self._busy and bool(self.return_bundle.get('return_path')))
        self.preview.Enable(not self._busy and bool(self.net.GetValue()))
        volume=self.model_dimension.GetSelection()==1
        self.run.SetLabel('Run 3D' if volume else 'Run')
        self.run.Enable(not self._busy and len(self._terminals)>1 and
                        (not volume or (not self._series_request and self.load_mode.GetSelection()==0)))
        self.export.SetLabel('Export')
        self.export.Enable(not self._busy and bool(self.volume_bundle.get('result') if volume else self.bundle.get('result')) and self._saved_source_current)
        self.power_flow.Enable(self.export.IsEnabled())
        if getattr(self,'_live_running',False) or getattr(self,'_live_pending',None) is not None:self.export.Disable();self.power_flow.Disable()
        if hasattr(self,'blender'):self.blender.Enable(self.export.IsEnabled() and not placement)
        self.cancel.Enable(self._busy);self.cancel.Show(not placement);self.gauge.Show(self._busy and not placement)
        self.more.SetLabel('Reload' if placement else 'More')
        self.more.SetToolTip('Reload the saved board' if placement else 'Transient PI, electrothermal, series studies and diagnostics')
        self.main_panel.Layout()
        if not self._busy:self.metric.Enable(self.book.GetSelection()==2)
        self.field_style.Enable(not self._busy and self.book.GetSelection()==2)
        self.isolate_nets.Enable(not self._busy)
        self.auto_mesh.Enable(not self._busy and not volume)
        self.edge.Enable(not self._busy and not self.auto_mesh.GetValue())
        current=bool(self.bundle.get('geometry')) and self._saved_source_current
        self.inspector_select.Enable(not self._busy and current and bool((self._inspection or {}).get('source_ids')))
        self.inspector_read.Enable(not self._busy and bool(self.bundle.get('geometry')) and self._saved_source_current)
        self.inspector_terminals.Enable(not self._busy and bool(self.bundle.get('geometry')) and self._saved_source_current)
        if self._series_request:
            self.source.Disable();self.sink.Disable();self.loads_button.Disable()
            self.preview.Enable(not self._busy and bool(self.bundle.get('geometry')))
        for control in (self.ambient,self.pulse,self.limit,self.melting,self.latent):control.Enable(not self._busy and not volume)
        self.max_tetrahedra.Enable(not self._busy and volume)
        if self.book.GetSelection()>=len(self.views):
            for control in (self.net,self.source,self.sink,self.voltage,self.current,self.layer,self.metric,self.preview,self.run,self.export,self.power_flow):control.Disable()

    def _build_inspector(self):
        self.inspector=wx.ScrolledWindow(self.splitter)
        self.inspector.SetScrollRate(0,12);self.inspector.SetMinSize((self.FromDIP(200),1))
        layout=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(self.inspector,label='Board & results')
        font=title.GetFont();font.SetWeight(wx.FONTWEIGHT_BOLD);title.SetFont(font)
        layout.Add(title,0,wx.EXPAND|wx.ALL,8)
        self.feasibility_status=SidebarText(self.inspector,width=238)
        layout.Add(self.feasibility_status,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        selection=wx.FlexGridSizer(0,2,5,5);selection.AddGrowableCol(1)
        self.layer=ReadableChoice(self.inspector);self.metric=ReadableChoice(self.inspector,choices=[value[0] for value in METRICS.values()]);self.metric.SetSelection(1)
        for label,control in [('Layer',self.layer),('Result',self.metric)]:
            selection.Add(wx.StaticText(self.inspector,label=label),0,wx.ALIGN_CENTER_VERTICAL);control.SetMinSize((1,-1));selection.Add(control,0,wx.EXPAND)
        layout.Add(selection,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        visibility=wx.BoxSizer(wx.HORIZONTAL)
        self.show_context=wx.CheckBox(self.inspector,label='Board');self.show_copper=wx.CheckBox(self.inspector,label='Copper');self.show_overlay=wx.CheckBox(self.inspector,label='Field')
        self.show_silkscreen=wx.CheckBox(self.inspector,label='Silk')
        self.show_silkscreen.SetToolTip('Optional saved silkscreen. Board outline and holes remain visible with Board enabled.')
        for control in (self.show_context,self.show_copper,self.show_overlay,self.show_silkscreen):
            control.SetValue(control is not self.show_silkscreen);visibility.Add(control,0,wx.RIGHT,7);control.Bind(wx.EVT_CHECKBOX,lambda event:self._draw(preserve=True))
        layout.Add(visibility,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.isolate_nets=wx.CheckBox(self.inspector,label='Only simulated nets')
        self.isolate_nets.SetValue(True)
        self.isolate_nets.SetToolTip('Show only the chosen or solved copper domain. Turn off to review surrounding board copper; probes and PCB selection stay scoped to the simulated nets.')
        self.isolate_nets.Bind(wx.EVT_CHECKBOX,self._scope_changed)
        layout.Add(self.isolate_nets,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.mesh_count=StatusText(self.inspector);layout.Add(self.mesh_count,0,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        self.field_style=ReadableChoice(self.inspector,choices=['Smooth gradient','Solver cells'])
        self.field_style.SetSelection(0)
        self.field_style.SetToolTip('Smooth gradient uses the existing mesh. Potential uses nodal values; current, loss and risk use display interpolation. Probes and peaks retain solver cell values. Select Solver cells to inspect raw resolution.')
        self.field_style.SetMinSize((1,-1));layout.Add(self.field_style,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,8)
        scale=wx.BoxSizer(wx.HORIZONTAL)
        self.scale_mode=ReadableChoice(self.inspector,choices=['Auto: selected layer','Shared: all layers','Manual: this metric'])
        self.scale_mode.SetSelection(0);self.scale_mode.SetMinSize((1,-1));scale.Add(self.scale_mode,1,wx.EXPAND)
        layout.Add(scale,0,wx.EXPAND|wx.ALL,8)
        limits=wx.BoxSizer(wx.HORIZONTAL)
        self.scale_min=wx.TextCtrl(self.inspector);self.scale_min.SetHint('Minimum');self.scale_min.SetMinSize((1,-1))
        self.scale_max=wx.TextCtrl(self.inspector);self.scale_max.SetHint('Maximum');self.scale_max.SetMinSize((1,-1))
        self.scale_apply=wx.Button(self.inspector,label='Set',style=wx.BU_EXACTFIT)
        limits.Add(self.scale_min,1,wx.RIGHT,4);limits.Add(self.scale_max,1,wx.RIGHT,4);limits.Add(self.scale_apply,0)
        self.scale_controls=limits
        layout.Add(limits,0,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        self.scale_unit=StatusText(self.inspector,label='Scale units follow the selected result')
        self.color_legend=ColorLegend(self.inspector);layout.Add(self.color_legend,0,wx.EXPAND|wx.ALL,8)
        layout.Add(self.scale_unit,0,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        self.inspector_views=wx.Notebook(self.inspector)
        self.inspector_views.SetMinSize((1,220))
        findings_page=wx.Panel(self.inspector_views);findings_layout=wx.BoxSizer(wx.VERTICAL)
        self.finding_order=ReadableChoice(findings_page,choices=['Highest current density','Highest volumetric heating','Copper melting bottlenecks'])
        self.finding_order.SetSelection(0);self.finding_order.SetMinSize((1,-1));findings_layout.Add(self.finding_order,0,wx.EXPAND|wx.BOTTOM,5)
        self.findings=wx.ListCtrl(findings_page,style=wx.LC_REPORT|wx.LC_SINGLE_SEL,size=(-1,140))
        for index,(name,width) in enumerate([('Rank / copper',90),('Layer',85),('J A/mm²',90),('Heat W/mm³',95)]):
            self.findings.InsertColumn(index,name,width=width)
        findings_layout.Add(self.findings,1,wx.EXPAND);findings_page.SetSizer(findings_layout)
        self.inspector_views.AddPage(findings_page,'Hotspots')
        from .inspector_tables import InspectorTable
        losses_page=wx.Panel(self.inspector_views);losses_layout=wx.BoxSizer(wx.VERTICAL)
        self.losses_book=wx.Notebook(losses_page)
        layer_page=wx.Panel(self.losses_book);layer_layout=wx.BoxSizer(wx.VERTICAL)
        self.loss_table=InspectorTable(layer_page,[('Layer / loss',125),('Loss · W',90),('Area · mm²',90),('Peak · A/mm²',105),('Cu · µm',85)],self._inspector_table_selected)
        layer_layout.Add(self.loss_table,1,wx.EXPAND);layer_page.SetSizer(layer_layout);self.losses_book.AddPage(layer_page,'By layer')
        heating_page=wx.Panel(self.losses_book);heating_layout=wx.BoxSizer(wx.VERTICAL)
        self.heating_table=InspectorTable(heating_page,[('Copper',130),('Layer',85),('J · A/mm²',95),('Heat · W/mm³',110)],self._inspector_table_selected)
        heating_layout.Add(self.heating_table,1,wx.EXPAND);heating_page.SetSizer(heating_layout);self.losses_book.AddPage(heating_page,'Heating')
        losses_layout.Add(self.losses_book,1,wx.EXPAND)
        losses_details=wx.CollapsiblePane(losses_page,label='Full accounting details',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.accounting_text=wx.TextCtrl(losses_details.GetPane(),style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,120))
        details_layout=wx.BoxSizer(wx.VERTICAL);details_layout.Add(self.accounting_text,1,wx.EXPAND);losses_details.GetPane().SetSizer(details_layout)
        losses_details.Collapse(True);losses_layout.Add(losses_details,0,wx.EXPAND|wx.TOP,4)
        losses_details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:losses_page.Layout())
        losses_page.SetSizer(losses_layout);self.inspector_views.AddPage(losses_page,'Losses')
        layout.Add(self.inspector_views,1,wx.EXPAND|wx.ALL,8)
        probe_page=wx.Panel(self.inspector_views);probe_layout=wx.BoxSizer(wx.VERTICAL)
        differential_controls=wx.BoxSizer(wx.HORIZONTAL)
        self.differential_target=wx.Choice(probe_page,choices=['Single point','Set probe A','Set probe B'])
        self.differential_target.SetSelection(0)
        self.differential_target.SetToolTip('Choose A or B, then click solved sheet copper. The readout is V(A) - V(B) within this one solved reference.')
        differential_clear=wx.Button(probe_page,label='Clear A/B')
        differential_clear.Bind(wx.EVT_BUTTON,self._clear_differential)
        differential_controls.Add(self.differential_target,1,wx.EXPAND|wx.RIGHT,4);differential_controls.Add(differential_clear,0)
        probe_layout.Add(differential_controls,0,wx.EXPAND|wx.BOTTOM,4)
        self.differential_readout=wx.StaticText(probe_page,label='Differential: choose A and B on solved copper.')
        probe_layout.Add(self.differential_readout,0,wx.EXPAND|wx.BOTTOM,6)
        self.probe_table=InspectorTable(probe_page,[('Parameter',125),('Value',100),('Unit',45)],self._inspector_table_selected,fit_columns=True)
        probe_layout.Add(self.probe_table,1,wx.EXPAND)
        probe_details=wx.CollapsiblePane(probe_page,label='Model and selection notes',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.inspection_text=wx.TextCtrl(probe_details.GetPane(),style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,120))
        details_layout=wx.BoxSizer(wx.VERTICAL);details_layout.Add(self.inspection_text,1,wx.EXPAND);probe_details.GetPane().SetSizer(details_layout)
        probe_details.Collapse(True);probe_layout.Add(probe_details,0,wx.EXPAND|wx.TOP,4)
        probe_details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:probe_page.Layout())
        probe_page.SetSizer(probe_layout);self.inspector_views.AddPage(probe_page,'Probe')
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.inspector_select=icon_button(self.inspector,'Select',wx.ART_GO_FORWARD,'Select the inspected object in the PCB editor')
        self.inspector_read=icon_button(self.inspector,'Read',wx.ART_FIND,'Read the current PCB editor selection')
        for button in (self.inspector_select,self.inspector_read):actions.Add(button,1,wx.RIGHT,4)
        layout.Add(actions,0,wx.EXPAND|wx.ALL,8)
        self.inspector_add=wx.CheckBox(self.inspector,label='Add to existing PCB selection')
        layout.Add(self.inspector_add,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        net_scope=icon_button(self.inspector,'Select simulated nets in PCB',wx.ART_FIND,'Replace the PCB selection with only the exact selected or simulated net copper, across all layers')
        net_scope.Bind(wx.EVT_BUTTON,self._select_net_scope)
        layout.Add(net_scope,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.inspector_terminals=icon_button(self.inspector,'Source & sinks',wx.ART_FIND,'Select the source and every sink in the PCB editor')
        layout.Add(self.inspector_terminals,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.model_details=wx.CollapsiblePane(self.inspector,label='Model details',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE);self.model_details.Collapse(True)
        details=self.model_details.GetPane();details_layout=wx.BoxSizer(wx.VERTICAL)
        self.model_basis=wx.TextCtrl(details,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,100));self.model_basis.SetMinSize((1,100))
        details_layout.Add(self.model_basis,1,wx.EXPAND);details.SetSizer(details_layout);layout.Add(self.model_details,0,wx.EXPAND|wx.ALL,8)
        self.model_details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(self.inspector.Layout(),self.inspector.FitInside()))
        self.inspector.SetSizer(layout)
        self.inspector.FitInside()
        self.scale_mode.Bind(wx.EVT_CHOICE,self._scale_changed)
        self.field_style.Bind(wx.EVT_CHOICE,lambda event:self._draw(preserve=True))
        self.scale_apply.Bind(wx.EVT_BUTTON,self._scale_changed)
        self.finding_order.Bind(wx.EVT_CHOICE,lambda event:self._update_inspector(True))
        self.findings.Bind(wx.EVT_LIST_ITEM_SELECTED,self._finding_selected)
        self.inspector_select.Bind(wx.EVT_BUTTON,self._select_inspected)
        self.inspector_read.Bind(wx.EVT_BUTTON,self._read_editor_selection)
        self.inspector_terminals.Bind(wx.EVT_BUTTON,self._select_terminals)

    def _snapshot_current(self):
        import hashlib
        geometry=self.bundle.get('geometry') or self.bundle.get('mesh',{}).get('geometry',{})
        expected=geometry.get('source_sha256') or getattr(self,'_board_scene_hash',None)
        try:return not expected or hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()==expected
        except OSError:return False

    def _activated(self,event):
        if event.GetActive() and not self._busy and not self._closed:self._draw(preserve=True)
        event.Skip()

    def _update_inspector(self,refresh_rows=False,check_source=True):
        geometry=self.bundle.get('geometry') or self.bundle.get('mesh',{}).get('geometry',{})
        result=self.bundle.get('result',{})
        if check_source:self._saved_source_current=self._snapshot_current()
        sha=geometry.get('source_sha256','')
        state='Saved file changed: reload and rerun.' if not self._saved_source_current else 'Saved snapshot '+(sha[:12] if sha else '(not yet extracted)')
        basis='Explicit stackup override' if geometry.get('stackup_source')=='explicit_override' else 'Saved board stackup'
        warnings=self._board_scene.get('warnings',[])
        self.model_basis.SetValue(state+'\n2.5D DC conduction · '+basis+'\nNo AC, transient or thermal-field solve. Local peaks depend on mesh and contacts. Live unsaved edits are not included.'+
                                  ('\nDisplay geometry warnings: '+'; '.join(warnings) if warnings else ''))
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        self.scale_unit.SetLabel(metric_name(self.bundle,metric)+' · '+METRICS[metric][1])
        manual=self.scale_mode.GetSelection()==2
        self.scale_unit.Show(manual)
        self.scale_controls.ShowItems(manual)
        feasibility=result.get('feasibility',{}) if self._saved_source_current else {}
        state=feasibility.get('status','')
        if feasibility.get('feasible') is False:state+=' · requested-load diagnostic'
        self.feasibility_status.SetLabel(state)
        self.feasibility_status.SetToolTip(feasibility_text(result) if self._saved_source_current else 'Reload and rerun after saved PCB changes')
        for control in (self.scale_min,self.scale_max,self.scale_apply):control.Enable(manual)
        if refresh_rows or not result or not self._saved_source_current:
            from .analytics import details_text
            from .display_ids import display_result
            presented=display_result(self.bundle)
            self.accounting_text.SetValue('\n\n'.join(value for value in (feasibility_text(result),sink_results_text(result),details_text(presented)) if value))
            from .inspector_tables import loss_rows,heating_rows
            shown=presented if self._saved_source_current else {}
            self.loss_table.set_rows(loss_rows(shown));self.heating_table.set_rows(heating_rows(shown))
            self.findings.DeleteAllItems()
            key='hotspots_by_heating_density' if self.finding_order.GetSelection()==1 else 'hotspots_by_current_density'
            melting=self.finding_order.GetSelection()==2
            self._finding_rows=list(presented.get('fusing',{}).get('bottlenecks',[]) if melting else presented.get('analytics',{}).get(key,[])) if self._saved_source_current else []
            column=self.findings.GetColumn(3);column.SetText('Melt · s' if melting else 'Heat W/mm³');self.findings.SetColumn(3,column)
            for row in self._finding_rows:
                index=self.findings.InsertItem(self.findings.GetItemCount(),f"{row['rank']}. {row.get('display_id') or row['kind']}")
                last=('Unknown' if row.get('time_to_melt_s') is None else f"{row['time_to_melt_s']:.5g}") if melting else f"{row['power_density_W_mm3']:.5g}"
                for column,value in enumerate([row['layer_name'],f"{row['current_density_A_mm2']:.5g}",last],1):
                    self.findings.SetItem(index,column,value)
        if not geometry or not self._saved_source_current:self._inspection=None
        row=self._inspection
        if row:
            number=lambda value,unit:'Unknown' if value is None else f'{value:.6g} {unit}'
            text=f"{row.get('display_id') or row['id']} · {row['layer_name']}\n"
            text+='XYZ: '+', '.join(f'{value:.6g}' for value in row['location_mm'])+' mm\n'
            text+=metric_name(self.bundle,row['metric'])+': '+number(row.get('value'),row['unit'])+'\n'
            text+='Current density: '+number(row.get('current_density_A_mm2'),'A/mm²')+'\nLoss: '+number(row.get('power_W'),'W')
            if row['kind']=='via':text+='\nBarrel current: '+number(row.get('current_A'),'A')
            if row.get('fusing'):
                screen=row['fusing']
                text+='\nMelting onset: '+number(screen.get('time_to_onset_s'),'s')+'\nFull melting: '+number(screen.get('time_to_melt_s'),'s')
                text+='\nMelting I²t: '+number(screen.get('i2t_to_melt_A2s'),'A²s')
                text+='\nFrozen current pattern; no cooling. Melting is not fuse opening.'
                if screen.get('section_basis'):text+='\n'+screen['section_basis']
            if row['kind']=='object':text+='\nSaved object navigation only; no containing solved cell.'
            text+='\nExact saved object available.' if row.get('source_ids') else '\nMesh cell only; no exact PCB object identity.'
            self.inspection_text.SetValue(text)
        else:self.inspection_text.SetValue('Select a ranked hotspot or click solved copper. Empty space and drill holes have no copper result.\nHotspot heating is W/mm³; the loss map is W/mm².\nPulse risk is adiabatic and does not predict fusing.')
        from .inspector_tables import probe_rows
        self.probe_table.set_rows(probe_rows(self.bundle,row))
        self._update_differential()
        if check_source:self.inspector.Layout();self.inspector.FitInside();self._buttons()

    def _clear_differential(self,event=None):
        self.bundle.pop('differential_probes',None);self.differential_target.SetSelection(0)
        self._draw(preserve=True)

    def _update_differential(self):
        from .differential_probe import saved_probe
        if not hasattr(self,'_differential_locations'):self._differential_locations={}
        if not self._saved_source_current:
            self.differential_readout.SetLabel('Differential unavailable: saved board changed.');return
        result=self.bundle.get('result',{})
        cache_key=(id(result),id(result.get('potential_V')),result.get('sink_current_A'),repr(self.bundle.get('differential_probes')))
        try:
            cached=getattr(self,'_differential_cache',None)
            reading=cached[1] if cached and cached[0]==cache_key else saved_probe(self.bundle,check_source=False,location_cache=self._differential_locations)
            self._differential_cache=(cache_key,reading)
        except (ValueError,OSError) as error:
            self.differential_readout.SetLabel('Differential unavailable: '+str(error));return
        points=self.bundle.get('differential_probes',{})
        if reading:
            value=reading['voltage_a_minus_b_V']
            label='V(A) - V(B): '+('Unknown' if value is None else f'{value:.8g} V ({value*1000:.8g} mV)')
            rows=[]
            for key in ('a','b'):
                point=reading[key];target={'kind':'point','layer':point['layer'],'location_mm':[point['x_mm'],point['y_mm']]}
                rows.append({'cells':(key.upper()+' potential',point['potential_V'],'V'),'target':target,'metric':'voltage'})
                rows.append({'cells':(key.upper()+' X / Y',f"{point['x_mm']:.6g} / {point['y_mm']:.6g}",'mm'),'target':target})
            rows.append({'cells':('A - B',value,'V'),'target':None})
            self.probe_table.set_rows(rows)
        else:label='Differential: '+('A selected; choose B.' if 'a' in points else 'B selected; choose A.' if 'b' in points else 'choose A and B on solved copper.')
        self.differential_readout.SetLabel(label)
        self.differential_readout.Wrap(max(240,self.inspector.GetClientSize().width-28))

    def _scale_limits(self,metric):
        mode=self.scale_mode.GetSelection()
        if mode==1:return result_scale(self.bundle,metric)
        if mode==2:
            setting=self.bundle.get('view_settings',{}).get('manual',{})
            if setting.get('metric')==metric:return tuple(setting['limits'])
        return None

    def _scale_changed(self,event=None):
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        if self.scale_mode.GetSelection()==2:
            try:limits=validate_scale(self.scale_min.GetValue(),self.scale_max.GetValue())
            except ValueError:
                limits=result_scale(self.bundle,metric)
                if limits is None:self.status.SetLabel('Run a solve before setting color limits.');return
                self.scale_min.ChangeValue(f'{limits[0]:.8g}');self.scale_max.ChangeValue(f'{limits[1]:.8g}')
                if event and event.GetEventObject() is self.scale_apply:
                    self.status.SetLabel('Invalid scale. Restored solved limits; minimum must be below maximum.');return
            self.bundle.setdefault('view_settings',{})['manual']={'metric':metric,'limits':list(limits)}
        self.bundle.setdefault('view_settings',{})['scale_mode']=self.scale_mode.GetSelection()
        self._draw(preserve=True)

    def _finding_selected(self,event):
        index=event.GetIndex()
        if not 0<=index<len(self._finding_rows):return
        row=self._finding_rows[index]
        metric='density' if self.finding_order.GetSelection()==0 else 'loss'
        if self.finding_order.GetSelection()==2:
            metric='melt';self.metric.SetSelection(list(METRICS).index(metric))
        record=inspection_record(self.bundle,row['kind'],row['id'],metric)
        if record is not None and self.finding_order.GetSelection()==2:
            record['fusing']=row
            if row.get('source_ids'):record['source_ids']=row['source_ids']
        self._choose_inspection(record,focus=True)

    def _inspector_table_selected(self,row):
        if self._busy or not self._snapshot_current():
            self.status.SetLabel('Reload and rerun after saved PCB changes before navigating table results.');return
        target=row.get('target');metric=row.get('metric')
        if metric in METRICS:self.metric.SetSelection(list(METRICS).index(metric))
        if target is None:
            if row.get('layer') is not None:
                index=next((i for i,item in enumerate(self._layers) if str(item['id'])==str(row['layer'])),None)
                if index is not None:self.layer.SetSelection(index)
                self._inspection=None;self.book.SetSelection(2);self._draw(preserve=False)
            else:self.status.SetLabel('Aggregate loss has no unique PCB object. Select a layer or a ranked copper row to inspect.')
            return
        selected_metric=metric if metric in METRICS else target.get('metric',list(METRICS)[max(0,self.metric.GetSelection())])
        if target['kind']=='point':
            record=probe_result(self.bundle,target['layer'],*target['location_mm'][:2],selected_metric)
        else:record=inspection_record(self.bundle,target['kind'],target['id'],selected_metric)
        if record is None and target.get('kind')=='object':record=dict(target)
        if record is not None:
            if target.get('source_ids'):record['source_ids']=list(target['source_ids'])
            if target.get('fusing'):record['fusing']=target['fusing']
            self._choose_inspection(record,focus=True)

    def _choose_inspection(self,row,focus=False,switch_view=True):
        if row is None:return
        if row.get('location_mm') and not row.get('source_ids'):
            from wayricad_runtime.board_render import hit_test
            layer=row['layer'][0] if isinstance(row['layer'],list) else row['layer']
            net=None if self.bundle.get('request',{}).get('series') else self.bundle.get('geometry',{}).get('net')
            primitives=hit_test(self._board_scene,*row['location_mm'][:2],visible_layers=[layer],net=net)
            row['source_ids']=list(dict.fromkeys(item['uuid'] for item in primitives if item.get('uuid') and item.get('role') in ('track','pad','via')))
        self._inspection=row
        self.inspector_views.SetSelection(2)
        span=row['layer'] if isinstance(row['layer'],list) else [row['layer']]
        selection=next((index for index,value in enumerate(self._layers) if any(str(value['id'])==str(layer) for layer in span)),None)
        if selection is not None:self.layer.SetSelection(selection)
        if switch_view and self.bundle.get('result'):self.book.SetSelection(2)
        self._draw(preserve=not focus)
        if focus:
            figure,canvas,_=self.views[max(0,min(2,self.book.GetSelection()))];ax=figure.axes[0];x,y=row['location_mm'][:2]
            edge=float(self.bundle.get('request',{}).get('edge_mm',.5));radius=max(.25,edge*3)
            ax.set_xlim(x-radius,x+radius);ax.set_ylim(y+radius,y-radius);canvas.draw_idle()

    def _probe_down(self,event,index):
        self._probe_start=(index,event.GetX(),event.GetY());event.Skip()

    def _probe_up(self,event,index):
        start=getattr(self,'_probe_start',None);event.Skip()
        if not start or start[0]!=index or math.hypot(event.GetX()-start[1],event.GetY()-start[2])>4:return
        if index>=len(self.views) or not self.bundle.get('geometry'):return
        figure,canvas,toolbar=self.views[index]
        if getattr(toolbar,'mode','') or not figure.axes:return
        ax=figure.axes[0];pixel=(event.GetX(),canvas.GetClientSize().height-event.GetY())
        if not ax.bbox.contains(*pixel):return
        x,y=ax.transData.inverted().transform(pixel)
        selected=self.layer.GetSelection()
        if selected<0:return
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        layer=self._layers[selected]['id']
        target=self.differential_target.GetSelection()
        if target:
            if not self._snapshot_current():self.status.SetLabel('Saved PCB changed. Reload and rerun before differential probing.');return
            if layer=='all':
                choices=[item for item in self._layers if item['id']!='all']
                with wx.SingleChoiceDialog(self,'Choose the physical layer for this differential point.','Differential layer',[str(item.get('name',item['id'])) for item in choices]) as dialog:
                    if dialog.ShowModal()!=wx.ID_OK:return
                    layer=choices[dialog.GetSelection()]['id']
            from .differential_probe import sample_point
            try:sample=sample_point(self.bundle,layer,x,y,check_source=False)
            except (ValueError,OSError) as error:self.status.SetLabel(str(error));return
            if sample['status']!='SAMPLED':self.status.SetLabel(sample['notice']);return
            key='a' if target==1 else 'b'
            self.bundle.setdefault('differential_probes',{})[key]={'layer':layer,'x_mm':float(x),'y_mm':float(y)}
            self.differential_target.SetSelection(2 if key=='a' else 1)
            self.inspector_views.SetSelection(2);self._draw(preserve=True)
            self.status.SetLabel('Probe '+key.upper()+' selected. V(A) - V(B) uses the same solved potential reference.');return
        if layer=='all':
            hits=[probe_result(self.bundle,item['id'],x,y,metric) for item in self._layers if item['id']!='all']
            hits=[item for item in hits if item]
            if len(hits)>1:
                with wx.SingleChoiceDialog(self,'Several layers overlap here. Choose the layer to inspect.',
                                           'Layer probe',[str(item.get('layer_name',item['layer'])) for item in hits]) as dialog:
                    if dialog.ShowModal()!=wx.ID_OK:return
                    row=hits[dialog.GetSelection()]
            else:row=hits[0] if hits else None
        else:row=probe_result(self.bundle,layer,x,y,metric)
        if row:self._choose_inspection(row,switch_view=False)
        else:
            from wayricad_runtime.board_render import hit_test
            hits=hit_test(self._board_scene,x,y,visible_layers=None if layer=='all' else [layer])
            hits=[item for item in hits if item.get('net') in self._visible_nets()]
            primitive=next((item for item in hits if item.get('uuid') and item.get('role') in ('track','pad','via')),None)
            if primitive:self._choose_inspection(self._object_inspection(primitive,(x,y)),switch_view=False)
            else:self._inspection=None;self._draw(preserve=True);self.status.SetLabel('No solved copper or selectable saved object at this point on the selected layer.')

    def _object_inspection(self,primitive,location=None):
        points=primitive.get('points',[])
        if location is None:
            location=primitive.get('center') or [sum(point[axis] for point in points)/len(points) for axis in range(2)]
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        return {'kind':'object','id':primitive['uuid'],'layer':primitive['layer'],
                'layer_name':str(self._board_scene.get('layers',{}).get(primitive['layer'],primitive['layer'])),
                'location_mm':list(location),'metric':metric,'value':None,'unit':METRICS[metric][1],
                'source_ids':[primitive['uuid']],'current_density_A_mm2':None,'power_W':None}

    def _origin_sha(self):
        return (self.bundle.get('geometry') or self.bundle.get('mesh',{}).get('geometry',{})).get('source_sha256') or self._board_scene_hash

    def _select_ids(self,identifiers,additive=None):
        if not self._snapshot_current():self.status.SetLabel('Saved board changed. Reload and rerun before selecting.');return
        from .origin_selection import select_origin
        expected=self._origin_sha();additive=self.inspector_add.GetValue() if additive is None else additive
        self._task(lambda:select_origin(self.board_path,identifiers,expected_sha256=expected,focus=True,additive=additive),
                   lambda count:self.status.SetLabel(f'Selected {count} exact saved objects in the originating PCB Editor.'),'Selecting reviewed objects in PCB Editor…')

    def _load_result_scene(self,bundle,expected,nets):
        """Refresh missing or differently scoped context without native UI IO."""
        if self._closed or self._closing or self.bundle is not bundle:return
        def finished(result):
            if self.bundle is not bundle:return
            if result.get('source_sha256')!=expected or not self._snapshot_current():
                self.status.SetLabel('Saved board changed. Reload and rerun before viewing context.');return
            from wayricad_runtime.board_render import prepare_scene
            self._board_scene=prepare_scene(result.pop('board_scene'));self._board_scene_hash=expected
            bundle['board_scene']=self._board_scene
            self._draw(preserve=True)
        self._job({'action':'inspect','board_path':self.board_path,'include_display_scene':True,
                   'display_nets':nets if self.isolate_nets.GetValue() else None},finished,
                  'Loading matching saved-board context…')

    def _scope_changed(self,event=None):
        if self.isolate_nets.GetValue() or self._board_scene.get('net_scope') is None:
            self._draw(preserve=True);return
        expected=self._board_scene_hash
        def finished(result):
            if result.get('source_sha256')!=expected or not self._snapshot_current():
                self.isolate_nets.SetValue(True)
                self.status.SetLabel('Saved board changed. Reload before viewing surrounding copper.');return
            from wayricad_runtime.board_render import prepare_scene
            self._board_scene=prepare_scene(result.pop('board_scene'))
            self.bundle['board_scene']=self._board_scene
            self._draw(preserve=True)
            self.status.SetLabel('Surrounding copper loaded. Selection and probes still use the simulated nets.')
        self._job({'action':'inspect','board_path':self.board_path,'include_display_scene':True,
                   'display_nets':None},finished,'Loading surrounding board copper…')

    def _select_net_scope(self,event=None):
        if self._busy:return
        nets=set(self._visible_nets())
        identifiers=sorted({row['uuid'] for row in self._board_scene.get('primitives',[])
                            if row.get('uuid') and row.get('net') in nets
                            and row.get('role') in ('track','pad','via','zone')})
        if not identifiers:
            self.status.SetLabel('No saved copper matches the selected net scope. Preview or reload first.');return
        self._select_ids(identifiers,additive=False)

    def _select_inspected(self,event=None):
        self._select_ids((self._inspection or {}).get('source_ids',[]))

    def _select_terminals(self,event=None):
        request=self.bundle.get('request',{});chosen=terminal_ids(request)
        geometry=self.bundle.get('geometry') or self.bundle.get('mesh',{}).get('geometry',{})
        self._select_ids([row['id'] for row in geometry.get('terminals',[]) if row['id'] in chosen or row.get('label') in chosen])

    def _read_editor_selection(self,event=None):
        from .origin_selection import selected_origin_ids
        def finish(ids):
            wanted=set(ids)
            matched={item.get('uuid') for item in self._board_scene.get('primitives',[])
                     if (item.get('uuid') in wanted or item.get('parent_uuid') in wanted)
                     and item.get('net') in self._visible_nets()}
            related=sorted(matched)
            def show(row):
                row['source_ids']=related
                self._choose_inspection(row,focus=True)
                self.status.SetLabel(f'{len(wanted)} PCB items selected; all matching copper highlighted. Numeric inspector shows the primary hit.')
            for barrel in self.bundle.get('mesh',{}).get('vias',[]):
                row=inspection_record(self.bundle,'via',barrel['id'])
                if row and set(row['source_ids']).intersection(matched):show(row);return
            primitive=next((item for item in self._board_scene.get('primitives',[]) if item.get('uuid') in matched and item.get('role') in ('track','pad','via')),None)
            if primitive:
                row=self._object_inspection(primitive)
                candidate=probe_result(self.bundle,primitive['layer'],*row['location_mm'][:2],list(METRICS)[max(0,self.metric.GetSelection())])
                if candidate:candidate['source_ids']=[primitive['uuid']];row=candidate
                show(row);return
            self.status.SetLabel('No extracted track, pad or via selected in the originating PCB Editor.')
        self._task(lambda:selected_origin_ids(self.board_path,expected_sha256=self._origin_sha()),finish,'Reading selection from originating PCB Editor…')

    def _task(self,operation,finished,message):
        if self._busy:return
        self._busy=True;self._cancel.clear();self.status.SetLabel(message);self._buttons();self.Layout()
        revision=getattr(self,'_input_revision',0)
        def deliver(result,error):
            if revision!=getattr(self,'_input_revision',0):
                error=ValueError('Inputs changed while working; the stale result was discarded. Run again.')
            self._finish(finished,result,error)
        def worker():
            try:result=operation();error=None
            except Exception as exc:result=None;error=exc
            wx.CallAfter(deliver,result,error)
        threading.Thread(target=worker,name='WayriCAD Quick PI job',daemon=True).start()

    def _finish(self,finished,result,error):
        if self._closed:return
        self._busy=False
        if self._closing:self._end();return
        if error:
            self.status.SetLabel('Cancelled.' if self._cancel.is_set() else str(error))
            if self.book.GetSelection()==len(self.views):self.return_status.SetLabel(str(error))
            self._console_write('Error: '+str(error))
            self.status.Wrap(max(600,self.GetClientSize().width-32))
        else:
            try:finished(result)
            except Exception as exc:
                self.status.SetLabel('Could not display the result: '+str(exc))
                self._console_write('Display error: '+str(exc))
        self._buttons();self.Layout()
        if self._closing:self._end()

    def _job(self,request,finished,message):
        if self._closed or self._closing:return
        if request.get('action')!='inspect' and hasattr(self,'_reset_live'):self._reset_live()
        from .service import run_job
        if request.get('action') in ('geometry','mesh','solve'):
            self._inspection=None
            self.bundle.pop('result',None)
            self.bundle.pop('convergence',None)
            self.summary.SetLabel('Waiting for the current request. No current electrical result is available.')
            self._draw(preserve=True)
        if request.get('action') in ('geometry','mesh','solve','converge'):
            request=dict(request,include_display_scene=True)
            if not self.isolate_nets.GetValue():request['display_nets']=None
        self._console_write('Job: '+json.dumps(request,ensure_ascii=False))
        self._task(lambda:run_job(request,cancelled=self._cancel.is_set,timeout=300),finished,message)

    def _inspect(self):
        if self._closed or self._closing:return
        self._reset_live()
        self._series_request=None;self._extra_sinks=[];self.loads_button.SetLabel('Additional sinks (0)…');self.bundle={};self.volume_bundle={};self.return_bundle={}
        self.sweep_bundle={};self.return_table.DeleteAllItems();self.return_details.Clear()
        self.return_figure.clear();self.return_canvas.draw_idle()
        def finished(result):
            from wayricad_runtime.board_render import prepare_scene
            # Win32 native controls otherwise repaint for each inserted net/pad.
            # Keep the exact complete inventory and selections, but publish one
            # coherent update instead of thousands of intermediate layouts.
            self.main_panel.Freeze()
            try:
                self.decoupling.board=None
                self._board_scene=prepare_scene(result.pop('board_scene',{'primitives':[]}))
                self._board_scene_hash=result.get('source_sha256')
                self.decoupling.invalidate()
                self.decoupling.summary.SetLabel('Saved board reloaded; run a fresh placement check.')
                self.inventory=result;names=result.get('nets',[]);self.net.Set(names)
                self.return_signal.Set(names);self.return_nets.Set(names)
                if names:
                    choice=next((n for n in names if n.startswith(('+','VCC','VDD'))),names[0]);self.net.SetValue(choice)
                    self.return_signal.SetStringSelection(choice)
                self._return_follow_current=True;self._return_nets_changed()
                self._set_terminals()
                self.bundle={'board_scene':self._board_scene}
                self._set_layer_choices(result.get('layers',[]))
                self._select_preview_layer()
                self._plot_keys.clear();self.book.SetSelection(0);self._draw()
                self.summary.SetLabel('Saved copper preview. No mesh or electrical result has been calculated.')
                self.status.SetLabel(f'{len(names)} saved nets. Copper loaded; choose source and sink, then Preview or Run.')
            finally:
                self.main_panel.Thaw()
        # Display copper independently of solver stackup/terminal requirements.
        # One worker load supplies inventory and all display copper, so changing
        # the net can filter the cached scene without another extraction.
        self._job({'action':'inspect','board_path':self.board_path,
                   'include_display_scene':True,'display_nets':None},finished,
                  'Reading saved copper, net names and pad terminals…')

    def _set_terminals(self):
        net=self.net.GetValue();self._terminals=[t for t in self.inventory.get('terminals',[]) if t.get('net')==net]
        labels=[t.get('label',t['id']) for t in self._terminals]
        for control in (self.source,self.sink):control.Set(labels)
        if labels:
            self.source.SetSelection(0)
            owner=self._terminals[0].get('footprint_uuid')
            different=next((i for i,row in enumerate(self._terminals) if owner and row.get('footprint_uuid') and row['footprint_uuid']!=owner),None)
            self.sink.SetSelection(different if different is not None else min(1,len(labels)-1))
        self.source_pins.SetValue(False);self.sink_pins.SetValue(False)
        self._pin_peer_ids={'source':[],'sink':[]};self._sync_pin_recommendations()
        if (getattr(self,'_return_follow_current',False) and net in self.return_signal.GetStrings() and
                self.return_signal.GetStringSelection()!=net):
            self.return_signal.SetStringSelection(net);self._return_signal_changed()
        self._buttons()

    def _endpoint_changed(self,event):
        role='source' if event.GetEventObject() is self.source else 'sink'
        getattr(self,role+'_pins').SetValue(False)
        self._invalidate(event)

    def _unit_ids(self,role):
        control=getattr(self,role);index=control.GetSelection()
        if not 0<=index<len(self._terminals):return []
        ids=[self._terminals[index]['id']]
        checkbox=getattr(self,role+'_pins',None)
        if checkbox is not None and checkbox.GetValue():
            ids.extend(getattr(self,'_pin_peer_ids',{}).get(role,[]))
        return list(dict.fromkeys(ids))

    def _sync_pin_recommendations(self):
        from .pin_units import peers
        from .terminals import pad_names
        supported=(not self._series_request and self.model_dimension.GetSelection()==0
                   and self.load_mode.GetSelection() in (0,2) and not self._package_conduction)
        anchors={role:self._terminals[control.GetSelection()]['id']
                 for role,control in (('source',self.source),('sink',self.sink))
                 if 0<=control.GetSelection()<len(self._terminals)}
        reserved={identifier for spec in self._extra_sinks for identifier in pad_names(spec)}
        changed=False
        for role,other in (('source','sink'),('sink','source')):
            checkbox=getattr(self,role+'_pins')
            blocked=reserved|set(QuickPIFrame._unit_ids(self,other))
            rows=peers(self._terminals,anchors.get(role),blocked) if supported else []
            self._pin_peer_ids[role]=[row['id'] for row in rows]
            visible=bool(rows)
            label=f'Include {len(rows)} other same-net pin'+('s' if len(rows)!=1 else '')
            if checkbox.IsShown()!=visible or checkbox.GetLabel()!=label:changed=True
            checkbox.SetLabel(label);checkbox.Show(visible)
            if not visible:checkbox.SetValue(False)
            checkbox.SetToolTip('Also include '+', '.join(row.get('label',row['id']) for row in rows)+
                               '. One ideal equipotential endpoint; the specified current is the TOTAL for these pins. '
                               'Pins already assigned to another endpoint are excluded.')
        if changed:self.inputs.Layout();self.inputs.FitInside()

    def _apply_pin_units(self,request):
        """Translate the optional checkboxes to existing grouped solver inputs."""
        from .pin_units import unit,validate_units
        source_ids=QuickPIFrame._unit_ids(self,'source');sink_ids=QuickPIFrame._unit_ids(self,'sink')
        if not source_ids or not sink_ids:return request
        if len(source_ids)>1:
            request.pop('source_terminal',None);request['source_terminals']=source_ids
        if request.get('sinks'):
            request['sinks'][0]=unit(request['sinks'][0],sink_ids[1:])
            validate_units(source_ids,request['sinks'])
        elif 'sink_terminal' in request and len(sink_ids)>1:
            request.pop('sink_terminal',None);request['sinks']=[unit({'terminal':sink_ids[0]},sink_ids[1:])]
        return request

    def _set_layer_choices(self,rows):
        """Default to all copper; retain an explicit physical-layer selection."""
        current=self.layer.GetSelection()
        previous=self._layers[current]['id'] if 0<=current<len(self._layers) else None
        self._layers=[row for row in rows if row['id']!='all']
        if len(self._layers)>1:self._layers.append({'id':'all','name':'All copper layers (projected)'})
        self.layer.Set([row['name'] for row in self._layers])
        if self._layers:
            fallback=len(self._layers)-1 if len(self._layers)>1 else 0
            selected=next((i for i,row in enumerate(self._layers) if str(row['id'])==str(previous)),fallback)
            self.layer.SetSelection(selected)

    def _select_preview_layer(self):
        """Keep the current layer, or show an occupied layer for the chosen net."""
        occupied={row.get('layer') for row in self._board_scene.get('primitives',[])
                  if row.get('role') in ('track','pad','via','zone') and row.get('net')==self.net.GetValue()}
        current=self.layer.GetSelection()
        if 0<=current<len(self._layers) and (self._layers[current]['id']=='all' or self._layers[current]['id'] in occupied):return
        choice=next((i for i,row in enumerate(self._layers) if row['id'] in occupied),None)
        if choice is not None:self.layer.SetSelection(choice)

    def select_board_net(self,event=None):
        import pcbnew
        from wayricad_runtime.preview import GeometryPreview
        dialog=wx.Dialog(self,title='Select a net on the saved board',size=(850,620),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL);view=GeometryPreview(dialog);layout.Add(view,1,wx.EXPAND|wx.ALL,8)
        layout.Add(wx.StaticText(dialog,label='Click a pad, via or track to choose its net. Drag to pan; wheel to zoom.'),0,wx.ALL,8)
        layout.Add(dialog.CreateButtonSizer(wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,8);dialog.SetSizer(layout)
        view.set_board(self.decoupling.get_board() if self._snapshot_current() else pcbnew.LoadBoard(self.board_path),pcbnew)
        def selected(net,xy):
            self.net_search.ChangeValue('');self.net.Set(self.inventory.get('nets', []))
            self.net.SetValue(net);self._net_changed()
            dialog.EndModal(wx.ID_OK)
        view.on_net_select=selected
        dialog.ShowModal();dialog.Destroy()

    def _schedule_net_filter(self,event=None):
        pending=getattr(self,'_net_filter_timer',None)
        if pending:pending.Stop()
        self._net_filter_timer=wx.CallLater(180,self._filter_nets)

    def _visible_nets(self):
        geometry=self.bundle.get('geometry') or self.bundle.get('mesh',{}).get('geometry',{})
        return geometry.get('nets') or [geometry.get('net') or self.net.GetValue()]

    def _filter_nets(self,event=None):
        if self._closed or self._closing:return
        from wayricad_runtime.net_filter import filter_combo
        current=self.net.GetValue()
        filter_combo(self.net,self.inventory.get('nets',[]),self.net_search.GetValue())
        if self.net.GetValue()!=current:self._net_changed()

    def _net_changed(self,event=None):
        self._reset_live()
        self._input_revision=getattr(self,'_input_revision',0)+1
        if self._busy:self._cancel.set()
        self._inspection=None
        self._series_request=None;self._extra_sinks=[];self.loads_button.SetLabel('Additional sinks (0)…');self.operation_note.SetLabel('Source voltage → sink current')
        self.bundle={'board_scene':self._board_scene};self.volume_bundle={};self._set_terminals();self._select_preview_layer();self._plot_keys.clear();self._draw()
        self.status.SetLabel('Preview this net or run the analysis.')

    def _invalidate(self,event=None):
        if hasattr(self,'_reset_live'):self._reset_live()
        self._input_revision=getattr(self,'_input_revision',0)+1
        if hasattr(self,'source_pins'):self._sync_pin_recommendations()
        if self._busy:self._cancel.set()
        if event and event.GetEventObject() is self.load_mode:
            self.current_label.SetLabel(('Load · A','Load · Ω','Load · W')[self.load_mode.GetSelection()])
            self.operation_note.SetLabel(('Source voltage → specified sink current','Source voltage → resistive load to 0 V','Source voltage → constant-power operating point')[self.load_mode.GetSelection()])
        self._inspection=None
        self.bundle.pop('convergence',None)
        self.bundle.pop('result',None);self.volume_bundle={};self._buttons();self.summary.SetLabel('Inputs changed. Run again to update the electrical results.')
        if self.model_dimension.GetSelection()==1 and self.load_mode.GetSelection()!=0:
            self.status.SetLabel('3D copper supports a specified sink current. Set Mode to Specified sink current (A).')
        request=self.bundle.setdefault('request',{})
        for key in ('source_terminal','source_terminals','sink_terminal','sinks'):request.pop(key,None)
        for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
            if control.GetSelection()>=0:request[key]=self._terminals[control.GetSelection()]['id']
        if not self._series_request:
            request['sinks']=([{'terminal':request['sink_terminal']}] if request.get('sink_terminal') else [])+list(self._extra_sinks)
            QuickPIFrame._apply_pin_units(self,request)
        metric_index=max(0,self.metric.GetSelection())
        self.metric.Set([metric_name(self.bundle,key) for key in METRICS]);self.metric.SetSelection(metric_index)
        self._draw(preserve=True)
        if event:event.Skip()

    def _model_changed(self,event=None):
        if self.model_dimension.GetSelection()==1:self.auto_mesh.SetValue(False)
        self._invalidate(event)
        if self.model_dimension.GetSelection()==1:
            self.status.SetLabel('3D copper needs a specified sink current; switch Mode from resistive load before running.'
                                 if self.load_mode.GetSelection()!=0 else
                                 '3D DC copper needs Gmsh in the private runtime, one net, two pads and a specified current. First setup may download Gmsh.')
        else:
            self.status.SetLabel('2.5D layered copper is the default model. Choose two pads and run the analysis.')

    def on_run(self,event=None):
        if getattr(self,'joule_feedback',None) and self.joule_feedback.GetValue():
            self.on_electrothermal(feedback=True);return
        if self.model_dimension.GetSelection()==1:self.on_3d_analysis()
        else:self._analyze('solve')

    def _request(self,action,require_terminals=True):
        def number(control,label,positive=False):
            try:value=float(control.GetValue())
            except ValueError:raise ValueError(label+' must be a number.')
            if not math.isfinite(value) or positive and value<=0:raise ValueError(label+' must be finite'+(' and positive.' if positive else '.'))
            return value
        request={'action':action,'board_path':self.board_path,'net':self.net.GetValue(),
                 'edge_mm':number(self.edge,'Mesh edge',True),'plating_mm':number(self.plating,'Via plating',True)}
        if getattr(self,'auto_mesh',None) and self.auto_mesh.GetValue():request['mesh_sizing']='auto'
        if require_terminals and not request['net']:raise ValueError('Choose a net.')
        if action=='solve':
            a,b=self.source.GetSelection(),self.sink.GetSelection()
            if require_terminals and (min(a,b)<0 or a==b):raise ValueError('Choose two different source and sink pads on this net.')
            if min(a,b)>=0:request.update(source_terminal=self._terminals[a]['id'],sink_terminal=self._terminals[b]['id'])
            options={'temperature_c':number(self.temperature,'Copper temperature')}
            if self.model_dimension.GetSelection()==0:
                options.update(ambient_c=number(self.ambient,'Ambient temperature'),
                               temperature_limit_c=number(self.limit,'Temperature limit'),
                               pulse_duration_s=number(self.pulse,'Pulse duration',True))
                options.update(melting_temperature_c=number(self.melting,'Copper melting temperature'),
                               latent_heat_J_kg=number(self.latent,'Latent heat',True))
            request.update(source_voltage=number(self.voltage,'Source voltage'),options=options)
            if self.load_mode.GetSelection()==1:request['load_resistance_ohm']=number(self.current,'Load resistance',True)
            elif self.load_mode.GetSelection()==2:request['load_power_W']=number(self.current,'Load power',True)
            else:request['sink_current']=number(self.current,'Sink current',True)
            if self.source_current_limit.GetValue().strip():
                limit=number(self.source_current_limit,'Source current limit')
                if limit<0:raise ValueError('Source current limit must be nonnegative.')
                request['source_current_limit']=limit
            primary=load_values(request.get('sink_terminal'),1 if self.load_mode.GetSelection()==1 else self.current.GetValue(),self.sink_min_voltage.GetValue(),self.sink_max_voltage.GetValue(),power=self.load_mode.GetSelection()==2)
            if require_terminals and not self._series_request and self.load_mode.GetSelection() in (0,2) and self.model_dimension.GetSelection()==0:
                sinks=[primary,*[dict(row) for row in self._extra_sinks]]
                from .pin_units import validate_units
                validate_units([request['source_terminal']],sinks)
                request.pop('sink_terminal',None);request.pop('sink_current',None);request.pop('load_power_W',None);request['sinks']=sinks
            else:
                if self._extra_sinks:raise ValueError('Additional sinks require 2.5D constant-current mode without a console/series path.')
                for source,target in [('min_voltage_V','sink_min_voltage'),('max_voltage_V','sink_max_voltage')]:
                    if source in primary:request[target]=primary[source]
            if self.model_dimension.GetSelection()==1 and any(request.get(key) is not None for key in ('source_current_limit','sink_min_voltage','sink_max_voltage')):
                raise ValueError('3D does not evaluate source budgets or sink voltage limits. Clear those fields or use 2.5D.')
        else:
            for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
                if control.GetSelection()>=0:request[key]=self._terminals[control.GetSelection()]['id']
            request['sinks']=([{'terminal':request['sink_terminal']}] if request.get('sink_terminal') else [])+list(self._extra_sinks)
        if require_terminals and self._series_request and action=='solve':
            for key in ('series','net','source_terminal','sink_terminal'):request[key]=self._series_request[key]
        if require_terminals and not self._series_request:QuickPIFrame._apply_pin_units(self,request)
        if getattr(self,'_package_conduction',[]):
            request['package_conduction']=self._package_conduction
            from .package_contacts import guard_request
            guard_request(request)
        return request

    def on_package_contacts(self,event=None):
        if self._busy:return
        try:
            if self._series_request or self.load_mode.GetSelection()!=0 or self.model_dimension.GetSelection()!=0:
                raise ValueError('Package contacts require a 2.5D constant-current net solve.')
            request=self._request('solve')
            if any('power_W' in row for row in request.get('sinks',[])) or 'load_power_W' in request:
                raise ValueError('Package contacts currently require current loads, not constant-power operating points.')
            if 'source_terminals' in request or any('terminals' in spec for spec in request.get('sinks',[])):
                raise ValueError('Package contacts currently require single-pad endpoints. Uncheck the extra-pin options first.')
            from wayricad_runtime.package_contact_editor import edit_package_contacts
            sink_ids=[row['terminal'] for row in request.get('sinks',[])]
            if request.get('sink_terminal'):sink_ids.append(request['sink_terminal'])
            rows=edit_package_contacts(self,self._package_conduction,physics='electrical',
                ports=['source']+['sink:'+value for value in sink_ids],
                references=sorted({t.get('reference',t['label'].rsplit('.',1)[0]) for t in self._terminals}),
                layers=self.inventory.get('layers',[]))
            if rows is not None:
                self._package_conduction=rows
                self.package_button.SetLabel(f'Package contacts ({len(rows)})…')
                self._invalidate()
        except ValueError as exc:self.status.SetLabel(str(exc))

    def on_loads(self,event=None):
        """Edit additional constant-current sinks on the currently selected net."""
        if self._busy or self._series_request:return
        from .pin_units import anchor,peers,unit,validate_units
        from .terminals import pad_names
        dialog=wx.Dialog(self,title='Quick PI · Additional sinks',size=(820,490),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        rows=[dict(row) for row in self._extra_sinks];labels={row['id']:row.get('label',row['id']) for row in self._terminals}
        layout=wx.BoxSizer(wx.VERTICAL)
        layout.Add(wx.StaticText(dialog,label='The primary sink remains in the main window. All demands run together at the source voltage.'),0,wx.EXPAND|wx.ALL,10)
        table=wx.ListCtrl(dialog,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for index,(name,width) in enumerate([('Pad',210),('Demand A / W',130),('Min V',110),('Max V',110)]):table.InsertColumn(index,name,width=width)
        layout.Add(table,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        grid=wx.FlexGridSizer(2,5,6,10)
        for name in ('Sink pad','Load kind','Demand A / W','Minimum V (blank = 0)','Maximum V (blank = none)'):grid.Add(wx.StaticText(dialog,label=name))
        pad=ReadableChoice(dialog,choices=[labels[row['id']] for row in self._terminals]);current=wx.TextCtrl(dialog,value='1')
        kind=ReadableChoice(dialog,choices=['Current · A','Constant power · W']);kind.SetSelection(0)
        minimum=wx.TextCtrl(dialog);minimum.SetHint('0 V');maximum=wx.TextCtrl(dialog);maximum.SetHint('Unbounded')
        for control in (pad,kind,current,minimum,maximum):grid.Add(control,1,wx.EXPAND)
        for column in range(5):grid.AddGrowableCol(column)
        layout.Add(grid,0,wx.EXPAND|wx.ALL,10)
        include=wx.CheckBox(dialog,label='Include other same-net pins');include.Hide()
        layout.Add(include,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        peer_ids=[]
        main_ids=set(QuickPIFrame._unit_ids(self,'source')+QuickPIFrame._unit_ids(self,'sink'))
        def recommend():
            index=table.GetFirstSelected();choice=pad.GetSelection()
            blocked=main_ids|{identifier for i,spec in enumerate(rows) if i!=index for identifier in pad_names(spec)}
            supported=(hasattr(self,'model_dimension') and self.model_dimension.GetSelection()==0
                       and self.load_mode.GetSelection() in (0,2) and not getattr(self,'_package_conduction',[]))
            available=peers(self._terminals,self._terminals[choice]['id'],blocked) if choice>=0 and supported else []
            peer_ids[:]=[row['id'] for row in available]
            include.SetLabel(f'Include {len(available)} other same-net pin'+('s' if len(available)!=1 else ''))
            include.Show(bool(available))
            if not available:include.SetValue(False)
            include.SetToolTip('Also include '+', '.join(row.get('label',row['id']) for row in available)+
                               '. The entered current is the TOTAL across these ideal equipotential pins.')
            dialog.Layout()
        def pad_changed(event):
            include.SetValue(False);recommend()
        pad.Bind(wx.EVT_CHOICE,pad_changed)
        message=wx.StaticText(dialog,label='Select a row to edit it, or choose a pad and add a new sink.');layout.Add(message,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        add=wx.Button(dialog,label='Add sink');update=wx.Button(dialog,label='Update selected');remove=wx.Button(dialog,label='Remove selected')
        for button in (add,update,remove):buttons.Add(button,0,wx.RIGHT,8)
        layout.Add(buttons,0,wx.ALL,10);layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        def refresh():
            table.DeleteAllItems()
            for row in rows:
                identifier=anchor(row);count=len(pad_names(row))
                label=labels.get(identifier,identifier)+(f' (+{count-1} pins)' if count>1 else '')
                index=table.InsertItem(table.GetItemCount(),label)
                demand='power_W' if 'power_W' in row else 'current_A'
                table.SetItem(index,1,str(row[demand])+(' W' if demand=='power_W' else ' A'))
                for column,key in enumerate(('min_voltage_V','max_voltage_V'),2):
                    table.SetItem(index,column,str(row.get(key,0 if key=='min_voltage_V' else 'Unbounded')))
        def selected(event):
            row=rows[event.GetIndex()];index=next((i for i,item in enumerate(self._terminals) if item['id']==anchor(row)),-1)
            pad.SetSelection(index);kind.SetSelection(1 if 'power_W' in row else 0);current.ChangeValue(str(row.get('power_W',row.get('current_A'))));minimum.ChangeValue(str(row.get('min_voltage_V','')));maximum.ChangeValue(str(row.get('max_voltage_V','')))
            recommend();include.SetValue(len(pad_names(row))>1 and bool(peer_ids))
        def save(edit=False):
            try:
                choice=pad.GetSelection();index=table.GetFirstSelected() if edit else -1
                if choice<0:raise ValueError('Choose a sink pad.')
                if edit and index<0:raise ValueError('Select a row to update.')
                identifier=self._terminals[choice]['id']
                if identifier in main_ids:raise ValueError('Choose a pad outside the source and primary sink units.')
                row=unit(load_values(identifier,current.GetValue(),minimum.GetValue(),maximum.GetValue(),power=kind.GetSelection()==1),peer_ids if include.GetValue() else [])
                validate_units(list(main_ids),[spec for i,spec in enumerate(rows) if i!=index]+[row])
                if edit:rows[index]=row
                else:rows.append(row)
                refresh();include.SetValue(False);recommend();message.SetLabel('Sink demand updated. Apply with OK.');dialog.Layout()
            except ValueError as exc:message.SetLabel(str(exc));dialog.Layout()
        def delete(event):
            index=table.GetFirstSelected()
            if index>=0:rows.pop(index);refresh();include.SetValue(False);recommend()
        add.Bind(wx.EVT_BUTTON,lambda event:save());update.Bind(wx.EVT_BUTTON,lambda event:save(True));remove.Bind(wx.EVT_BUTTON,delete)
        table.Bind(wx.EVT_LIST_ITEM_SELECTED,selected);refresh()
        if dialog.ShowModal()==wx.ID_OK:
            self._extra_sinks=rows;self.loads_button.SetLabel(f'Additional sinks ({len(rows)})…');self._invalidate()
        dialog.Destroy()

    def preview_geometry(self,event=None):self._analyze('geometry')

    def _analyze(self,action):
        if self._series_request and action in ('geometry','mesh'):
            if self.bundle.get('geometry'):
                self.book.SetSelection(0 if action=='geometry' else 1);self._draw()
            return
        try:request=self._request(action)
        except Exception as exc:self.status.SetLabel(str(exc));return
        def finished(result):self._accept_result(result,request,action)
        self._job(request,finished,{'geometry':'Reading actual copper geometry…','mesh':'Building and validating the copper mesh…','solve':'Meshing copper and solving DC current flow…'}[action])

    def _accept_result(self,result,request,action):
        self._reset_live()
        self._inspection=None
        self.bundle=result;self.bundle.setdefault('request',request)
        from .display_ids import prepare_display_ids
        prepare_display_ids(self.bundle)
        geometry=result.get('geometry') or result.get('mesh',{}).get('geometry',{})
        expected=geometry.get('source_sha256')
        if result.get('board_scene'):
            from wayricad_runtime.board_render import prepare_scene
            self._board_scene=prepare_scene(result.pop('board_scene'));self._board_scene_hash=expected
        required=set(geometry.get('nets') or [geometry.get('net')])
        scope=self._board_scene.get('net_scope')
        if expected and (expected!=self._board_scene_hash or scope is not None and not required.issubset(scope)):
            self._board_scene={};self._board_scene_hash=None
            wx.CallAfter(self._load_result_scene,result,expected,sorted(net for net in required if net))
        self.bundle['board_scene']=self._board_scene
        self._set_layer_choices(layer_rows(result))
        mesh=result.get('mesh',{});self.mesh_count.SetLabel(f"{len(mesh.get('points_mm',[])):,} nodes · {len(mesh.get('triangles',[])):,} triangles" if mesh else '')
        for warning in result.get('geometry',{}).get('warnings',[]):self._console_write('Geometry: '+str(warning))
        self._plot_keys.clear();self.book.SetSelection(2 if action=='solve' else 1 if action=='mesh' else 0)
        if result.get('result'):
            r=result['result'];scope='Board + package' if r.get('package_contacts') else 'Circuit' if request.get('series') else 'Copper'
            multisink=len(r.get('sinks',[]))>1
            ratio='Worst drop / total demand' if multisink else scope+' ΔV/I'+(' (apparent)' if r.get('contains_forward_drop') else '')
            state=r.get('feasibility',{}).get('status','Solved')
            demand=r.get('total_sink_current_A',r.get('sink_current_A',0))
            self.summary.SetLabel(f"{state} · {len(r.get('sinks',[])) or 1} sink(s), {demand:.4g} A total   |   ΔV {r['voltage_drop_V']*1000:.4g} mV   |   {ratio} {r['drop_over_current_ohm']*1000:.4g} mΩ   |   Loss {r['total_power_W']:.4g} W")
            self.status.SetLabel('Mesh convergence not verified. Pulse risk is an adiabatic screen; peaks depend on mesh size and exclude cooling/fuse-opening physics.')
            if r.get('package_contacts'):
                from .package_contacts import details_text as package_text
                self._console_write(package_text(r))
            self._console_write(f"{state}: drop={r['voltage_drop_V']:.8g} V; {ratio}={r['drop_over_current_ohm']:.8g} ohm; power={r['total_power_W']:.8g} W; requested-load source V/I={r['V_over_I_ohm']:.8g} ohm")
            self._console_write(feasibility_text(r));self._console_write(sink_results_text(r))
            for branch in r.get('components',[]):
                if branch.get('model') in ('diode','fixed_drop'):
                    self._console_write(f"{branch['id']}: {branch['model']} at {branch['current_A']:.6g} A, Vf={branch['forward_drop_V']:.6g} V, before={branch['voltage_before_V']:.6g} V, after={branch['voltage_after_V']:.6g} V")
            if r.get('negative_sink_voltage'):
                self.status.SetLabel('Requested current makes the sink voltage negative. Review source voltage and load. Mesh convergence is not verified.')
                self._console_write('Warning: the requested sink current exceeds the available source voltage for this path; the DC operating point may be infeasible.')
            if result.get('convergence'):
                from .convergence import summary
                self.status.SetLabel(summary(result['convergence'])+(' Sink voltage is negative; review the load.' if r.get('negative_sink_voltage') else ''))
                self.edge.ChangeValue(str(result['request']['edge_mm']))
                self._console_write(summary(result['convergence']))
            if r.get('feasibility',{}).get('feasible') is False:
                self.status.SetLabel(feasibility_text(r)+'\nMesh convergence does not establish load feasibility. See Layers / losses for every sink voltage and limit.')
            metric_index=max(0,self.metric.GetSelection())
            self.metric.Set([metric_name(self.bundle,key) for key in METRICS]);self.metric.SetSelection(metric_index)
        else:self.summary.SetLabel('Actual filled copper, pad contacts and via barrels. Pan and zoom to inspect the selected layer.');self.status.SetLabel('Preview ready.')
        sizing=result.get('mesh_sizing_recommendation')
        if sizing:
            message=f"Recommended background: {sizing['background_edge_mm']:.4g} mm\nLocal target: {sizing['minimum_local_target_mm']:.4g} mm · {sizing['feature_count']} features\nHeuristic only; check convergence."
            self.mesh_count.SetLabel(self.mesh_count.GetLabel()+'\n'+message)
            self.mesh_count.SetToolTip(message+' '+('Estimated background exceeds budget; review scope or explicit budget.' if sizing['budget_warning'] else 'Local refinement can still exceed the budget.'))
            if not mesh:self.status.SetLabel('Preview ready. '+message.replace('\n',' · '))
        if result.get('convergence'):
            self.auto_mesh.SetValue(False);self.edge.Enable(not self._busy)
        self._update_inspector(True);self._draw()
        self._prepare_live()


    def _console_write(self,text):
        if not hasattr(self,'console_log') or self._closed:return
        self.console_log.AppendText(str(text).rstrip()+'\n')
        if self.console_log.GetLastPosition()>120000:
            self.console_log.SetValue(self.console_log.GetValue()[-90000:])
        self.console_log.ShowPosition(self.console_log.GetLastPosition())

    def _console_key(self,event):
        code=event.GetKeyCode()
        if code==wx.WXK_TAB:
            from .console import suggestions
            text=self.console_input.GetValue()
            if text not in self._completions:
                self._completion_prefix=text;self._completions=list(suggestions(text,self.inventory));self._completion_index=0
                if self._completions:self._console_write('Complete: '+' | '.join(self._completions[:12]))
            if self._completions:
                self.console_input.ChangeValue(self._completions[self._completion_index%len(self._completions)])
                self.console_input.SetInsertionPointEnd();self._completion_index+=1
            return
        if code in (wx.WXK_UP,wx.WXK_DOWN) and self._history:
            self._history_index=max(0,min(len(self._history),self._history_index+(-1 if code==wx.WXK_UP else 1)))
            self.console_input.ChangeValue(self._history[self._history_index] if self._history_index<len(self._history) else '')
            self.console_input.SetInsertionPointEnd();return
        event.Skip()

    def on_console(self,event=None):
        if self._busy:return
        line=self.console_input.GetValue().strip()
        if not line:return
        self._console_write('> '+line);self._history.append(line);self._history=self._history[-100:];self._history_index=len(self._history)
        self.console_input.ChangeValue('');self._completions=[]
        try:
            from .console import parse_command
            parsed=parse_command(line,self.inventory)
            if 'console_output' in parsed:self._console_write(parsed['console_output']);return
            self._start_parsed_path(parsed,'Running the console circuit in the isolated solver…')
        except Exception as exc:self._console_write('Error: '+str(exc));return

    def _start_parsed_path(self,parsed,message):
        request=self._request(parsed.get('action','solve'),require_terminals=False);request.update(parsed)
        request['board_path']=self.board_path
        self._series_request=request.copy() if request.get('series') else None
        if request.get('net') in self.inventory.get('nets',[]):
            self.net.SetValue(request['net']);self._set_terminals()
        if self._series_request:
            self._terminals=[next(t for t in self.inventory['terminals'] if request[key] in (t['id'],t.get('label')))
                             for key in ('source_terminal','sink_terminal')]
            labels=[t['label'] for t in self._terminals]
            self.source.Set(labels);self.sink.Set(labels);self.source.SetSelection(0);self.sink.SetSelection(1)
        else:
            for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
                index=next((i for i,t in enumerate(self._terminals) if request.get(key) in (t['id'],t.get('label'))),None)
                if index is not None:control.SetSelection(index)
        self.operation_note.SetLabel('Series path · '+('resistive load' if request.get('load_resistance_ohm') else 'specified current'))
        self.bundle={}
        self._job(request,lambda result:self._accept_result(result,request,request.get('action','solve')),message)

    def on_series_editor(self,event=None):
        if self._busy or not self.inventory.get('terminals'):return
        from .series_editor import SeriesPathDialog
        parsed=SeriesPathDialog(self,self.inventory,self.board_path).show()
        if parsed:
            try:self._start_parsed_path(parsed,'Solving selected series components and saved copper…')
            except Exception as exc:self.status.SetLabel(str(exc))

    def _page_changed(self,event):
        self._draw();self._buttons();event.Skip()

    def _draw(self,preserve=False):
        if self._closed or not self.views:return
        index=max(0,self.book.GetSelection())
        if index>=len(self.views):return
        figure,canvas,toolbar=self.views[index]
        selected=self.layer.GetSelection();layer=self._layers[selected]['id'] if 0<=selected<len(self._layers) else None
        metric=list(METRICS)[max(0,self.metric.GetSelection())]
        self.bundle.setdefault('view_settings',{})['scale_mode']=self.scale_mode.GetSelection()
        key=(index,str(layer));limits=None
        self.bundle['view_settings']['visible_nets']=self._visible_nets()
        self.bundle['view_settings']['isolate_nets']=self.isolate_nets.GetValue()
        self.bundle['view_settings']['field_style']='cells' if self.field_style.GetSelection()==1 else 'smooth'
        if preserve and self._plot_keys.get(index)==key and figure.axes:limits=(figure.axes[0].get_xlim(),figure.axes[0].get_ylim())
        if self.scale_mode.GetSelection()==2:
            setting=self.bundle.get('view_settings',{}).get('manual',{})
            if setting.get('metric')!=metric:
                defaults=result_scale(self.bundle,metric)
                if defaults:
                    self.scale_min.ChangeValue(f'{defaults[0]:.8g}');self.scale_max.ChangeValue(f'{defaults[1]:.8g}')
                    self.bundle.setdefault('view_settings',{})['manual']={'metric':metric,'limits':list(defaults)}
        self._update_inspector()
        render_key=(id(self.bundle),id(self.bundle.get('result')),id(self.bundle.get('mesh')),
                    id(self.bundle.get('geometry')),id(self.bundle.get('board_scene')),key,metric,
                    repr(self.bundle['view_settings']),repr(self._inspection),repr(self.bundle.get('differential_probes')),self._saved_source_current,
                    self.show_context.GetValue(),self.show_copper.GetValue(),self.show_overlay.GetValue(),
                    self.show_silkscreen.GetValue(),
                    tuple(self._visible_nets()),repr(self._scale_limits(metric)))
        if getattr(figure,'_wayricad_render_key',None)==render_key and figure.axes:
            self.color_legend.set_scale(getattr(figure.axes[0],'_wayricad_color_scale',None))
            canvas.draw_idle();return
        if not self._saved_source_current:
            self.color_legend.set_scale(None)
            figure._wayricad_render_key=None
            figure.clear();ax=figure.add_subplot(111)
            ax.text(.5,.5,'Saved PCB changed. Reload and rerun before viewing results.',ha='center',va='center',transform=ax.transAxes)
            ax.set_axis_off();toolbar.update();canvas.draw_idle();return
        ax=draw_view(figure,self.bundle,('Net','Mesh','Results')[index],layer,metric,self._scale_limits(metric),self._inspection,
                     show_context=self.show_context.GetValue(),show_copper=self.show_copper.GetValue(),show_overlay=self.show_overlay.GetValue(),show_silkscreen=self.show_silkscreen.GetValue(),board_view=True,visible_nets=self._visible_nets())
        self.color_legend.set_scale(getattr(ax,'_wayricad_color_scale',None))
        result=self.bundle.get('result',{});analysis=result.get('analytics',{})
        row=next((item for item in analysis.get('layers',[]) if str(item['layer'])==str(layer)),None)
        if row:
            from .analytics import thickness_label
            losses=analysis['losses']
            state=result.get('feasibility',{}).get('status','Solved')
            contacts=f" · Contacts {losses.get('package_W',0):.4g} W" if result.get('package_contacts') else ''
            self.summary.SetLabel(f"{state} · ΔV {result['voltage_drop_V']*1000:.4g} mV\nSheets {losses['planar_W']:.4g} W · Vias {losses['via_W']:.4g} W · Components {losses['component_W']:.4g} W{contacts}\n"
                                  f"{row['name']}: {thickness_label(row)} copper | {row['area_mm2']:.4g} mm² | Layer loss {row['planar_power_W']:.4g} W · More → Layer details")
            self.summary.GetParent().Layout()
        if limits:ax.set_xlim(*limits[0]);ax.set_ylim(*limits[1])
        controller=self._probe_controllers.pop(index,None)
        if controller:controller['disconnect']()
        if index==2 and layer!='all' and self.bundle.get('result') and self.bundle.get('mesh'):
            import numpy as np
            from .report import cell_values
            from wayricad_runtime.plot_probe import attach_probes
            mesh=self.bundle['mesh'];points=np.asarray(mesh['points_mm']);indices=[i for i,v in enumerate(mesh['triangle_layer']) if str(v)==str(layer)]
            polygons=points[np.asarray(mesh['triangles'],dtype=int)[indices],:2];centers=polygons.mean(axis=1);values=cell_values(mesh,self.bundle['result'],metric)
            samples=[[float(x),float(y),float(values[i]),'C'+str(i+1)] for (x,y),i in zip(centers,indices)]
            self._probe_controllers[index]=attach_probes(canvas,ax,samples,METRICS[metric][1],polygons=polygons)
        self._live_scene_ready(index,ax)
        figure._wayricad_render_key=render_key
        self._plot_keys[index]=key;toolbar.update();canvas.draw_idle()











    def on_return_path(self,event=None):
        if self._busy:return
        signal=self.return_signal.GetStringSelection()
        returns=[self.return_nets.GetString(i) for i in range(self.return_nets.GetCount()) if self.return_nets.IsChecked(i)]
        if not signal or not returns or signal in returns:
            self.return_status.SetLabel('Choose one routed signal and different, explicit return net(s).');return
        try:
            request={'action':'return_path','board_path':self.board_path,'signal_net':signal,'return_nets':returns,
                     'sample_pitch_mm':float(self.return_pitch.GetValue()),
                     'return_via_radius_mm':float(self.return_radius.GetValue()),
                     'return_terminal_ids':[self._return_pad_ids[c.GetStringSelection()] for c in (self.return_source,self.return_sink) if c.GetSelection()>0],
                     'return_terminal_roles':{role:self._return_pad_ids[c.GetStringSelection()] for role,c in [('source',self.return_source),('load',self.return_sink)] if c.GetSelection()>0}}
        except ValueError as exc:self.return_status.SetLabel(str(exc));return
        self.return_bundle={};self.return_table.DeleteAllItems();self.return_status.SetLabel('Checking saved filled return copper and transitions…')
        self._job(request,self._accept_return,'Screening the saved-board return path…')

    def _accept_return(self,bundle):
        self.return_bundle=bundle;result=bundle['return_path'];evidence=bundle['evidence']
        from wayricad_runtime.return_path import summary_text
        self.return_details.SetValue(summary_text(result))
        self.return_table.DeleteAllItems()
        for row in result['findings']:
            index=self.return_table.InsertItem(self.return_table.GetItemCount(),row['level'])
            position=', '.join(f'{v:.4g}' for v in row['position_mm']) if row['position_mm'] else '—'
            for col,value in enumerate((row['code'],row['layer'],position,row['detail']),1):self.return_table.SetItem(index,col,str(value))
        self.return_figure.clear();ax=self.return_figure.add_subplot(111)
        from .report import _polygon_patch
        for zone in evidence.get('reference_regions',[]):
            if len(zone['outer'])>=3:
                patch=_polygon_patch(zone);patch.set_alpha(.35);ax.add_patch(patch)
        layer_colors={name:f'C{i%10}' for i,name in enumerate(evidence.get('layer_order',[]))}
        for segment in evidence.get('segments',[]):
            a,b=segment['start'],segment['end']
            ax.plot([a[0],b[0]],[a[1],b[1]],color=layer_colors.get(segment['layer'],'#174c75'),linewidth=2.5)
        for via in evidence.get('return_vias',[]):ax.plot(*via['position'],marker='.',color='#27864a',markersize=5)
        for pad in result.get('selected_return_terminals',[]):
            ax.plot(*pad['position_mm'],marker='s',color='#7b3f9a',markersize=7);ax.annotate(pad['label'],pad['position_mm'],xytext=(5,5),textcoords='offset points',fontsize=8)
        for row in result['findings']:
            if row['position_mm']:
                ax.plot(*row['position_mm'],marker='x' if row['level']=='warning' else 'o',
                        color='#b63b32' if row['level']=='warning' else '#bd8b30',markersize=8)
        ax.autoscale_view();ax.set_aspect('equal',adjustable='box');ax.invert_yaxis();ax.set_xlabel('X mm');ax.set_ylabel('Y mm')
        ax.set_title(signal if (signal:=result.get('signal_net')) else 'Signal return path')
        self.return_figure.tight_layout();self.return_canvas.draw_idle()
        self.return_status.SetLabel(f"{result['checked_segment_count']} straight tracks; {result['warning_count']} warnings, {result['unknown_count']} unknowns. Sampled geometry only; review the actual return path.")
        self._buttons()

    def on_export_diagnostic(self,kind):
        bundle=self.return_bundle
        if kind not in bundle:return
        name=Path(self.board_path).stem+'-return-path.html'
        with wx.FileDialog(self,'Export analysis',defaultDir=str(Path(self.board_path).parent),defaultFile=name,
                           wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        from .report import write_diagnostic_report
        self._task(lambda:write_diagnostic_report(path,bundle,pocket_kivi=True),
            lambda result:self.return_status.SetLabel('Exported '+result['html']),
            'Writing local HTML and JSON evidence…')

    def on_help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('help.html'),'Quick PI · Help')

    def on_more(self,event):
        if self.book.GetSelection()>=len(self.views):self._inspect();return
        menu=wx.Menu();mesh=menu.Append(wx.ID_ANY,'Generate mesh only');self.Bind(wx.EVT_MENU,lambda e:self._analyze('mesh'),mesh)
        volume=menu.Append(wx.ID_ANY,'Select 3D copper analysis')
        volume.Enable(len(self._terminals)>1)
        self.Bind(wx.EVT_MENU,lambda e:(self.model_dimension.SetSelection(1),self._model_changed()),volume)
        transient=menu.Append(wx.ID_ANY,'Transient load-step study…')
        self.Bind(wx.EVT_MENU,self.on_transient,transient);transient.Enable(not self._busy)
        electrothermal=menu.Append(wx.ID_ANY,'Electrothermal study…')
        self.Bind(wx.EVT_MENU,self.on_electrothermal,electrothermal);electrothermal.Enable(not self._busy)
        ac=menu.Append(wx.ID_ANY,'AC / SMPS copper study…')
        self.Bind(wx.EVT_MENU,self.on_ac,ac);ac.Enable(not self._busy)
        details=menu.Append(wx.ID_ANY,'Layer thickness, losses and hotspots…');details.Enable(bool(self.bundle.get('result',{}).get('analytics')))
        self.Bind(wx.EVT_MENU,self.on_details,details)
        focus=menu.Append(wx.ID_ANY,'Zoom to circuit terminals');self.Bind(wx.EVT_MENU,self._focus_terminals,focus)
        refine=menu.Append(wx.ID_ANY,'Refine mesh and rerun (half edge length)')
        self.Bind(wx.EVT_MENU,self._refine,refine)
        study=menu.Append(wx.ID_ANY,'Check mesh convergence…');self.Bind(wx.EVT_MENU,self.on_convergence,study)
        study.Enable(len(self._terminals)>1 and self.model_dimension.GetSelection()==0
                     and self.load_mode.GetSelection()!=2 and not any('power_W' in row for row in self._extra_sinks))
        ladder=menu.Append(wx.ID_ANY,'Series voltage ladder…');ladder.Enable(bool(self.bundle.get('result',{}).get('components')))
        self.Bind(wx.EVT_MENU,self.on_series_details,ladder)
        sweep=menu.Append(wx.ID_ANY,'DC current sweep…');sweep.Enable(len(self._terminals)>1)
        self.Bind(wx.EVT_MENU,self.on_sweep,sweep)
        sweep_view=menu.Append(wx.ID_ANY,'View last current sweep…');sweep_view.Enable(bool(self.sweep_bundle.get('sweep')))
        self.Bind(wx.EVT_MENU,self.on_sweep_details,sweep_view)
        history=menu.Append(wx.ID_ANY,'View convergence plots…');history.Enable(bool(self.bundle.get('convergence')))
        self.Bind(wx.EVT_MENU,self.on_convergence_details,history)
        refresh=menu.Append(wx.ID_ANY,'Reload saved board');self.Bind(wx.EVT_MENU,lambda e:self._inspect(),refresh)
        self.PopupMenu(menu);menu.Destroy()

    def on_3d_analysis(self,event=None):
        """Run the separate volumetric DC model and show its sampled cell field."""
        if self._series_request or self.load_mode.GetSelection()!=0:
            self.status.SetLabel('3D analysis needs two pads on one net and a specified sink current.')
            return
        try:
            request=self._request('solve')
            request['model_dimension']='3d'
            request['options']={'temperature_c':float(self.temperature.GetValue())}
            if not math.isfinite(request['options']['temperature_c']):
                raise ValueError('Copper temperature must be finite.')
            try:budget=int(self.max_tetrahedra.GetValue())
            except ValueError:raise ValueError('3D tetrahedron budget must be a whole number.')
            if not 1<=budget<=1_000_000:
                raise ValueError('3D tetrahedron budget must be between 1 and 1,000,000.')
            request['max_tetrahedra']=budget
        except Exception as exc:
            self.status.SetLabel(str(exc));return
        from .service import run_job
        self.volume_bundle={};self._buttons()
        self._task(lambda:run_job(request,cancelled=self._cancel.is_set,timeout=300),
                   self._show_3d_analysis,'Preparing Gmsh runtime; meshing and solving saved 3D copper…')

    def _show_3d_analysis(self,bundle):
        from .volume_view import QUANTITIES,layer_names,sampled_cells
        result=bundle['result'];mesh=bundle['mesh']
        if not sampled_cells(bundle,limit=1)[2]:
            raise ValueError('3D solve returned no connected copper cells.')
        self.volume_bundle=bundle
        dialog=wx.Dialog(self,title='Quick PI · 3D copper current density',size=(1050,780),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        summary=(f"3D DC copper  |  ΔV {result['voltage_drop_V']*1000:.4g} mV  |  "
                 f"R {result['drop_over_current_ohm']*1000:.4g} mΩ  |  "
                 f"Loss {result['total_power_W']:.4g} W  |  "
                 f"{mesh['tetrahedron_count']:,} tetrahedra")
        layout.Add(wx.StaticText(dialog,label=summary),0,wx.EXPAND|wx.ALL,10)
        audit=(f"Current residual {result['current_balance_error_A']:.3g} A  |  "
               f"Power balance {result['energy_relative_error']*100:.3g}%  |  "
               f"Volume check {mesh['volume_relative_error']*100:.3g}%")
        layout.Add(wx.StaticText(dialog,label=audit),0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        selectors=wx.BoxSizer(wx.HORIZONTAL)
        selectors.Add(wx.StaticText(dialog,label='View'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        projection=ReadableChoice(dialog,choices=['Board top view','3D copper']);projection.SetSelection(0)
        selectors.Add(projection,0,wx.RIGHT,16)
        selectors.Add(wx.StaticText(dialog,label='Layer'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        layers=ReadableChoice(dialog,choices=layer_names(bundle));layers.SetSelection(0)
        selectors.Add(layers,0,wx.RIGHT,16)
        selectors.Add(wx.StaticText(dialog,label='Field'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
        quantities=ReadableChoice(dialog,choices=list(QUANTITIES));quantities.SetSelection(0)
        selectors.Add(quantities,0)
        layout.Add(selectors,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10)
        figure=Figure(figsize=(9,6),dpi=100,facecolor='white')
        canvas=FigureCanvasWxAgg(dialog,wx.ID_ANY,figure)
        toolbar=NavigationToolbar2WxAgg(canvas);toolbar.Realize()
        layout.Add(canvas,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        layout.Add(toolbar,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        note=wx.StaticText(dialog,label='Ideal pad electrodes · fixed-temperature DC · plotted cells are sampled; JSON includes every tetrahedron.')
        layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        probe_state={}
        def draw(event=None):
            if probe_state.get('controller'):probe_state['controller']['disconnect']()
            layer=layers.GetStringSelection()
            field=quantities.GetStringSelection()
            xyz,values,total=sampled_cells(bundle,layer,QUANTITIES[field])
            figure.clear()
            axes=figure.add_subplot(111,projection='3d' if projection.GetSelection()==1 else None)
            if len(values):
                if projection.GetSelection()==1:
                    artist=axes.scatter(xyz[:,0],xyz[:,1],xyz[:,2],c=values,cmap='inferno',
                                        s=5,alpha=.85,rasterized=True)
                    axes.set_zlabel('Z (mm)')
                    from matplotlib.ticker import MaxNLocator
                    axes.xaxis.set_major_locator(MaxNLocator(nbins=5))
                    axes.yaxis.set_major_locator(MaxNLocator(nbins=5))
                    axes.zaxis.set_major_locator(MaxNLocator(nbins=3))
                    axes.tick_params(labelsize=8)
                    extent=xyz.max(axis=0)-xyz.min(axis=0)
                    axes.set_box_aspect((max(extent[0],.01),max(extent[1],.01),
                                         max(extent[2],.01)),zoom=.85)
                else:
                    artist=axes.scatter(xyz[:,0],xyz[:,1],c=values,cmap='inferno',
                                        s=8,alpha=.9,rasterized=True)
                    axes.set_aspect('equal',adjustable='datalim');axes.invert_yaxis()
                figure.colorbar(artist,ax=axes,label=field,shrink=.75)
                note.SetLabel(f'{total:,} connected cells on {layer}; {len(values):,} plotted. '+
                              'Ideal pad electrodes · fixed-temperature DC; JSON contains the complete field.')
            else:
                axes.text(.1,.5,'No connected copper cells in this view.',transform=axes.transAxes)
                note.SetLabel(f'No connected cells on {layer}. Floating copper does not carry this solved current.')
            axes.set_xlabel('X (mm)');axes.set_ylabel('Y (mm)')
            axes.set_title(f'{layer} · {field}')
            from wayricad_runtime.plot_probe import attach_probes
            samples=[[float(p[0]),float(p[1]),float(v),'Sampled cell',float(p[2])] for p,v in zip(xyz,values)]
            probe_state['controller']=attach_probes(canvas,axes,samples,field)
            figure.tight_layout();canvas.draw_idle()
        for choice in (projection,layers,quantities):choice.Bind(wx.EVT_CHOICE,draw)
        buttons=wx.BoxSizer(wx.HORIZONTAL);save=wx.Button(dialog,label='Save 3D results / Pocket KiVi…')
        buttons.Add(save,0,wx.RIGHT,8);buttons.Add(dialog.CreateButtonSizer(wx.CLOSE),0)
        layout.Add(buttons,0,wx.ALIGN_RIGHT|wx.ALL,10)
        save.Bind(wx.EVT_BUTTON,lambda e:self._export_3d(dialog,bundle))
        dialog.Bind(wx.EVT_BUTTON,lambda e:dialog.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        dialog.SetSizer(layout);draw();dialog.ShowModal();dialog.Destroy()
        self.status.SetLabel('3D DC solve complete. Export an interactive HTML report and paired complete JSON from this window.')
        self._buttons()

    def _export_3d(self,parent,bundle):
        if not bundle.get('result'):return
        name=Path(self.board_path).stem+'-quick-pi-3d.html'
        with wx.FileDialog(parent,'Export 3D field',defaultDir=str(Path(self.board_path).parent),
                           defaultFile=name,wildcard='HTML (*.html)|*.html',
                           style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as picker:
            if picker.ShowModal()!=wx.ID_OK:return
            target=Path(picker.GetPath())
        try:
            from .volume_view import write_volume_report
            write_volume_report(target,bundle,pocket_kivi=True)
        except (OSError,ValueError) as exc:
            wx.MessageBox('Could not export the 3D result: '+str(exc),'Quick PI',wx.OK|wx.ICON_ERROR,parent)
            return
        self.status.SetLabel('Exported complete 3D field: '+str(target))

    def on_series_details(self,event=None):
        components=self.bundle.get('result',{}).get('components',[])
        if not components:return
        dialog=wx.Dialog(self,title='Quick PI · Voltage along series path',size=self.FromDIP((920,650)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        figure=Figure(figsize=(8,3),dpi=100);canvas=FigureCanvasWxAgg(dialog,wx.ID_ANY,figure)
        axes=figure.add_subplot(111)
        xs=list(range(len(components)+1))
        values=[components[0].get('voltage_before_V')]+[row.get('voltage_after_V') for row in components]
        if all(value is not None for value in values):
            axes.plot(xs,values,'o-',color='#147c86',linewidth=2)
            axes.set_xticks(xs,['Source',*[str(row['id']) for row in components]])
            axes.set_ylabel('Voltage (V)');axes.grid(True,alpha=.25)
        else:axes.text(.05,.5,'Component voltage is unavailable for this path.',transform=axes.transAxes)
        from wayricad_runtime.plot_probe import attach_probes
        attach_probes(canvas,axes,[[x,v,v,'Component boundary'] for x,v in zip(xs,values) if v is not None],'V')
        figure.tight_layout();layout.Add(canvas,1,wx.EXPAND|wx.ALL,10)
        table=wx.ListCtrl(dialog,style=wx.LC_REPORT,size=(-1,170))
        for col,(name,width) in enumerate([('Component',160),('Model',100),('Current A',110),('Before V',110),('Drop V',110),('After V',110),('Power W',110)]):
            table.InsertColumn(col,name,width=width)
        for row in components:
            index=table.InsertItem(table.GetItemCount(),str(row['id']))
            for col,key in enumerate(('model','current_A','voltage_before_V','voltage_drop_V','voltage_after_V','power_W'),1):
                value=row.get(key);table.SetItem(index,col,f'{value:.6g}' if isinstance(value,(float,int)) else str(value or '—'))
        layout.Add(table,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,10)
        dialog.SetSizer(layout);canvas.draw();dialog.ShowModal();dialog.Destroy()

    def on_sweep(self,event=None):
        if self._busy:return
        dialog=wx.Dialog(self,title='Quick PI · DC current sweep',size=self.FromDIP((480,290)))
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='Sweep DC current through the saved path. Copper temperature and geometry stay fixed; this is not a transient waveform.')
        note.Wrap(self.FromDIP(440));layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        grid=wx.FlexGridSizer(3,2,8,10)
        fields=[]
        for label,initial in [('Start A','0.1'),('Stop A','2'),('Points','21')]:
            grid.Add(wx.StaticText(dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            ctrl=wx.TextCtrl(dialog,value=initial);grid.Add(ctrl,1,wx.EXPAND);fields.append(ctrl)
        grid.AddGrowableCol(1,1);layout.Add(grid,0,wx.EXPAND|wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            request=self._request('solve')
            request.pop('load_resistance_ohm',None)
            if 'load_power_W' in request or any('power_W' in row for row in request.get('sinks',[])):
                raise ValueError('A current sweep cannot reinterpret a constant-power load. Select current mode first.')
            if 'source_terminals' in request or any('terminals' in row for row in request.get('sinks',[])):
                raise ValueError('Current sweeps currently require single-pad endpoints. Uncheck extra-pin options first.')
            if self._extra_sinks:
                raise ValueError('Current sweeps require a single sink. Remove additional sinks first.')
            if 'sinks' in request:
                sink=request.pop('sinks')[0]
                request.update(sink_terminal=sink['terminal'],sink_current=sink['current_A'])
                for key,target in [('min_voltage_V','sink_min_voltage'),('max_voltage_V','sink_max_voltage')]:
                    if key in sink:request[target]=sink[key]
            request['action']='sweep';request['sweep']={'start_A':float(fields[0].GetValue()),
                'stop_A':float(fields[1].GetValue()),'points':int(fields[2].GetValue())}
        except (ValueError,KeyError) as exc:self.status.SetLabel(str(exc));return
        finally:dialog.Destroy()
        self._job(request,self._accept_sweep,'Calculating DC path sweep from one verified mesh…')

    def _accept_sweep(self,bundle):
        self.sweep_bundle=bundle
        self.status.SetLabel(f"Current sweep: {len(bundle['sweep']['rows'])} operating points. Mesh temperature held fixed.")
        self.on_sweep_details()

    def on_sweep_details(self,event=None):
        sweep=self.sweep_bundle.get('sweep')
        if not sweep:return
        rows=sweep['rows'];dialog=wx.Dialog(self,title='Quick PI · Current sweep',size=self.FromDIP((930,660)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL);figure=Figure(figsize=(8,4),dpi=100);canvas=FigureCanvasWxAgg(dialog,wx.ID_ANY,figure)
        axes=figure.add_subplot(111);current=[row['current_A'] for row in rows]
        axes.plot(current,[row['path_drop_V'] for row in rows],label='Path drop',color='#b45134')
        axes.plot(current,[row['sink_voltage_V'] for row in rows],label='Sink voltage',color='#17657c')
        axes.axhline(0,color='#455',linewidth=.7);axes.set_xlabel('Prescribed DC current (A)');axes.set_ylabel('Voltage (V)')
        from wayricad_runtime.plot_probe import attach_probes
        attach_probes(canvas,axes,[[row['current_A'],row[key],row[key],key] for row in rows for key in ('path_drop_V','sink_voltage_V')],'V')
        axes.grid(True,alpha=.25);axes.legend();figure.tight_layout();layout.Add(canvas,1,wx.EXPAND|wx.ALL,10)
        note=wx.StaticText(dialog,label='One fixed-temperature FEM mesh supplies copper resistance. Diode Vf is reevaluated at each current; negative sink voltage flags an infeasible requested point.')
        note.Wrap(self.FromDIP(880));layout.Add(note,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,10)
        dialog.SetSizer(layout);canvas.draw();dialog.ShowModal();dialog.Destroy()

    def on_batch(self,event=None):
        if self._busy:return
        if not self._snapshot_current():self.status.SetLabel('Saved PCB changed. Reload before running batch cases.');return
        try:
            import hashlib
            from .batch import initial_study
            from .batch_ui import BatchStudyDialog
            from .service import run_job
            selected=self._request('solve')
            if selected.get('series'):raise ValueError('Batch cases use explicit per-net terminals; clear the series path first.')
            sha=hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()
            dialog=BatchStudyDialog(self,initial_study(selected),self.inventory,
                lambda payload,cancel:run_job(payload,cancelled=cancel,timeout=1800),self.board_path,sha)
            from wayricad_runtime.project_results_ui import add_study_results
            add_study_results(dialog,'quick-pi',self.board_path)
            try:dialog.ShowModal()
            finally:dialog.Destroy()
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def on_ac(self,event=None):
        if self._busy:return
        if not self._snapshot_current():self.status.SetLabel('Saved PCB changed. Reload before opening an AC study.');return
        try:
            import hashlib
            from .ac_ui import ACStudyDialog
            from .service import run_job
            sha=hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()
            dialog=ACStudyDialog(self,lambda payload,cancel:run_job(payload,cancelled=cancel,timeout=600),
                (FigureCanvasWxAgg,NavigationToolbar2WxAgg),self.board_path,sha)
            from wayricad_runtime.project_results_ui import add_study_results
            add_study_results(dialog,'quick-pi',self.board_path)
            try:dialog.ShowModal()
            finally:dialog.Destroy()
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def on_electrothermal(self,event=None,feedback=False):
        if self._busy:return
        if not self._snapshot_current():self.status.SetLabel('Saved PCB changed. Reload before opening electrothermal coupling.');return
        try:
            if self.model_dimension.GetSelection()!=0 or self.load_mode.GetSelection()!=0:
                raise ValueError('Seed electrothermal studies from 2.5D specified-current loads. 3D and resistive-load modes are separate models.')
            import hashlib
            from .electrothermal_ui import ElectrothermalStudyDialog,initial_studies,feedback_studies
            from .service import run_job
            request=self._request('solve')
            if request.get('package_conduction'):raise ValueError('Package contacts are unsupported in electrothermal coupling.')
            if request.get('series'):
                raise ValueError('Saved-board Joule feedback supports one copper net. Series branch heat contacts require an explicit prepared electrothermal model.')
            if 'load_power_W' in request or any('power_W' in row for row in request.get('sinks',[])):
                raise ValueError('Electrothermal studies currently require current profiles; constant-power regulation dynamics are not modeled.')
            sha=hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()
            dialog=ElectrothermalStudyDialog(self,(feedback_studies if feedback else initial_studies)(request,self._terminals),
                lambda payload,cancel:run_job(payload,cancelled=cancel),
                (FigureCanvasWxAgg,NavigationToolbar2WxAgg),self.board_path,sha,steady_only=feedback)
            from wayricad_runtime.project_results_ui import add_study_results
            add_study_results(dialog,'quick-pi',self.board_path)
            try:dialog.ShowModal()
            finally:dialog.Destroy()
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def on_transient(self,event=None):
        if self._busy:return
        if not self._snapshot_current():self.status.SetLabel('Saved board changed. Reload before opening a transient study.');return
        try:
            if self.model_dimension.GetSelection()!=0 or self.load_mode.GetSelection()!=0:
                raise ValueError('Seed transient studies from 2.5D specified-current loads, then enter explicit circuit R/L/C values.')
            import hashlib
            from .transient_inputs import initial_study
            from .service import run_job
            from .transient_setup import PITransientStudyDialog
            request=self._request('solve')
            if request.get('package_conduction'):raise ValueError('Package contacts are unsupported in rail transient studies.')
            if request.get('series'):raise ValueError('Select a net source and sinks for the transient setup; enter the explicit path R/L in the study.')
            sha=hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()
            dialog=PITransientStudyDialog(self,'pi',initial_study(request,self._terminals,bundle=self.bundle),
                lambda payload,cancel:run_job(payload,cancelled=cancel),
                (FigureCanvasWxAgg,NavigationToolbar2WxAgg),self.board_path,sha,
                terminals=self._terminals,signal_net=request.get('net',''),return_nets=self._return_selected_nets())
            from wayricad_runtime.project_results_ui import add_study_results
            add_study_results(dialog,'quick-pi',self.board_path)
            try:dialog.ShowModal()
            finally:dialog.Destroy()
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def on_convergence(self,event=None):
        if self._busy:return
        try:
            request=self._request('solve')
            from .constant_power import requested
            if requested(request):raise ValueError('Automatic convergence currently compares fixed-current cases. Constant-power points need separately reviewed mesh refinement.')
        except (ValueError,KeyError) as exc:self.status.SetLabel(str(exc));return
        dialog=wx.Dialog(self,title='Check mesh convergence',size=self.FromDIP((510,280)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL)
        start=('Fix the recommended background once, then use uniform manual meshes' if request.get('mesh_sizing')=='auto' else f"Start at {request['edge_mm']:g} mm")
        note=wx.StaticText(dialog,label=start+" and halve mesh edge each level. Contacts and material inputs stay fixed. Cancellation and mesh limits remain active.");note.Wrap(self.FromDIP(465));box.Add(note,0,wx.ALL,12)
        form=wx.FlexGridSizer(2,2,10,12);form.Add(wx.StaticText(dialog,label='Refinement levels'))
        levels=wx.SpinCtrl(dialog,min=3,max=5,initial=4);form.Add(levels)
        form.Add(wx.StaticText(dialog,label='Final two changes, maximum %'));tolerance=wx.TextCtrl(dialog,value='1');form.Add(tolerance)
        box.Add(form,0,wx.ALL,12);box.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,12);dialog.SetSizer(box)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            from .convergence import assess
            value=float(tolerance.GetValue());assess([],value)
            request.update(action='converge',convergence_levels=levels.GetValue(),convergence_tolerance_percent=value)
        except ValueError as exc:self.status.SetLabel(str(exc));return
        finally:dialog.Destroy()
        def finished(bundle):
            self._accept_result(bundle,request,'solve')
            self.on_convergence_details()
        self._job(request,finished,'Running fixed-input refinement study; this takes several solves…')

    def on_convergence_details(self,event=None):
        study=self.bundle.get('convergence')
        if not study:return
        from .convergence import summary
        dialog=wx.Dialog(self,title='Quick PI · Mesh refinement evidence',size=self.FromDIP((1100,800)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL);label=wx.StaticText(dialog,label=summary(study));label.Wrap(self.FromDIP(1020));box.Add(label,0,wx.ALL,12)
        figure=Figure(figsize=(10,4),dpi=100);canvas=FigureCanvasWxAgg(dialog,wx.ID_ANY,figure)
        canvas.SetMinSize(self.FromDIP((-1,220)))
        samples=study['samples'];edges=[row['edge_mm'] for row in samples]
        for index,key,scale,title,unit in [(1,'voltage_drop_V',1000,'Terminal drop','mV'),(2,'peak_J_A_mm2',1,'Local peak — not certified','A/mm²')]:
            ax=figure.add_subplot(1,2,index);ax.plot(edges,[row[key]*scale for row in samples],'o-');ax.set_xscale('log',base=2);ax.invert_xaxis();ax.set_xlabel('Mesh edge (mm), finer →');ax.set_ylabel(unit);ax.set_title(title);ax.grid(True,alpha=.25)
        figure.tight_layout();box.Add(canvas,1,wx.EXPAND|wx.ALL,8)
        table=wx.ListCtrl(dialog,style=wx.LC_REPORT,size=self.FromDIP((-1,130)))
        for col,(name,width) in enumerate([('Edge mm',100),('Triangles',100),('Drop mV',120),('R mΩ',120),('Loss mW',120),('Sheet loss mW',130),('Peak J A/mm²',145)]):table.InsertColumn(col,name,width=self.FromDIP(width))
        for row in samples:
            values=[row['edge_mm'],row['triangles'],row['voltage_drop_V']*1000,row['resistance_ohm']*1000,row['power_W']*1000,row['sheet_power_W']*1000,row['peak_J_A_mm2']]
            i=table.InsertItem(table.GetItemCount(),f'{values[0]:.6g}')
            for col,value in enumerate(values[1:],1):table.SetItem(i,col,f'{value:.7g}')
        box.Add(table,0,wx.EXPAND|wx.ALL,8)
        evidence=study['criteria']+'\n'+'\n'.join(study['limitations'])
        if study.get('failure'):evidence+='\nStopped: '+str(study['failure'])
        box.Add(wx.TextCtrl(dialog,value=evidence,style=wx.TE_MULTILINE|wx.TE_READONLY,size=self.FromDIP((-1,110))),0,wx.EXPAND|wx.ALL,8)
        box.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,8);dialog.SetSizer(box)
        dialog.Bind(wx.EVT_BUTTON,lambda e:dialog.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        canvas.draw();dialog.ShowModal();dialog.Destroy()

    def on_details(self,event=None):
        self.book.SetSelection(2);self._update_inspector(True)
        self.inspector_views.SetSelection(1);self.losses_book.SetSelection(0);self.loss_table.SetFocus();self.inspector.Scroll(0,0)

    def _focus_terminals(self,event=None):
        request=self.bundle.get('request',{});mesh=self.bundle.get('mesh',{})
        chosen=terminal_ids(request)
        for branch in request.get('series',[]):chosen.update((branch.get('from_pad'),branch.get('to_pad')))
        points=[]
        for terminal in self.bundle.get('geometry',{}).get('terminals',[]):
            if terminal.get('id') not in chosen and terminal.get('label') not in chosen:continue
            for polygons in terminal.get('polygons',{}).values():
                for polygon in polygons:points.extend(polygon['outer'])
        if not points:return
        xs=[p[0] for p in points];ys=[p[1] for p in points]
        pad=max(.5,max(max(xs)-min(xs),max(ys)-min(ys))*.2)
        if self.book.GetSelection()>=len(self.views):return
        figure,canvas,_=self.views[max(0,self.book.GetSelection())]
        if figure.axes:
            figure.axes[0].set_xlim(min(xs)-pad,max(xs)+pad)
            figure.axes[0].set_ylim(max(ys)+pad,min(ys)-pad);canvas.draw_idle()

    def _refine(self,event=None):
        try:
            value=float(self.bundle.get('mesh',{}).get('edge_mm',self.edge.GetValue()))/2
            if not math.isfinite(value) or value<=0:raise ValueError('Mesh edge must be positive.')
            if self.model_dimension.GetSelection()==1:
                value=float(self.edge.GetValue())/2
                if not math.isfinite(value) or value<=0:raise ValueError('Mesh edge must be positive.')
                self.edge.SetValue(f'{value:g}')
                self.on_3d_analysis()
                return
            if getattr(self,'auto_mesh',None):self.auto_mesh.SetValue(False)
            self.edge.SetValue(f'{value:g}');self._analyze('solve')
        except Exception as exc:self.status.SetLabel(str(exc))

    def on_power_flow(self,event=None):
        if not self._snapshot_current():
            self.status.SetLabel('Saved board changed. Reload and rerun before viewing power flow.');return
        bundle=self.volume_bundle if self.model_dimension.GetSelection()==1 else self.bundle
        if not bundle.get('result'):return
        try:
            from .sankey import open_sankey
            open_sankey(bundle)
            self.status.SetLabel('Opened offline source-to-sink power flow. Hover each ribbon for watts.')
        except Exception as exc:self.status.SetLabel('Power flow: '+str(exc))

    def on_export(self,event=None):
        if getattr(self,'_live_running',False) or getattr(self,'_live_pending',None) is not None:
            self.status.SetLabel('Wait for the latest live-current update before exporting.');return
        if self.model_dimension.GetSelection()==1:
            self._export_3d(self,self.volume_bundle)
            return
        if not self.bundle.get('result'):return
        if not self._snapshot_current():
            self.status.SetLabel('Saved board changed. Reload and rerun before exporting.');return
        with wx.FileDialog(self,'Export self-contained results',defaultDir=str(Path(self.board_path).parent),defaultFile=Path(self.board_path).stem+'-quick-pi.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        selected=self.layer.GetSelection();layer=self._layers[selected]['id'] if selected>=0 else None
        bundle=self.bundle
        self._task(lambda:write_report(path,bundle,layer,pocket_kivi=True),lambda result:self.status.SetLabel('Saved HTML, full numerical JSON and Pocket KiVi JSON: '+result['html']),
                   'Saving the report and all-layer numerical results for Pocket KiVi…')

    def on_blender(self,event=None):
        if self._busy or getattr(self,'_live_running',False) or getattr(self,'_live_pending',None) is not None:
            self.status.SetLabel('Wait for the current calculation before exporting to Blender.');return
        if not self._snapshot_current():
            self.status.SetLabel('Saved board changed. Reload and rerun before exporting to Blender.');return
        bundle=self.volume_bundle if self.model_dimension.GetSelection()==1 else self.bundle
        if not bundle.get('result'):return
        from wayricad_runtime.blender_ui import choose_export
        choose_export(self,bundle,'pi',self._task,self.status.SetLabel)

    def on_cancel(self,event=None):
        pending=getattr(self,'_net_filter_timer',None)
        if pending:pending.Stop()
        self._cancel.set();self.status.SetLabel('Stopping the isolated worker…')

    def on_close(self,event):
        pending=getattr(self,'_net_filter_timer',None)
        if pending:pending.Stop()
        if self._busy:
            self._closing=True;self.on_cancel()
            if event.CanVeto():event.Veto()
            return
        self._end()

    def _end(self):
        self._reset_live()
        self._closed=True;self.timer.Stop();self.Destroy()


MainFrame=QuickPIFrame
