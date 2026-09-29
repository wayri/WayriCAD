"""Native Quick PI window: saved copper, mesh and DC results in one workflow."""
from __future__ import annotations
from pathlib import Path
import threading
import wx
from matplotlib.figure import Figure
from .plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg

from .report import METRICS,draw_view,layer_rows,write_report,via_markers
import json




class QuickPIFrame(wx.Frame):
    def __init__(self,parent,board_path):
        super().__init__(parent,title='WayriCAD Quick PI',size=(1180,800))
        icon_prefix='icon-'
        icon_dir=Path(__file__).with_name('resources')
        icons=wx.IconBundle()
        for size in (24,48,96):
            icon_path=icon_dir/f'{icon_prefix}{size}.png'
            if icon_path.is_file():icons.AddIcon(wx.Icon(str(icon_path),wx.BITMAP_TYPE_PNG))
        if icons.GetIcon(wx.Size(48,48)).IsOk():self.SetIcons(icons)
        self.SetMinSize((940,680));self.board_path=str(Path(board_path).resolve())
        self.bundle={};self.inventory={};self.return_bundle={};self.sweep_bundle={}
        self._busy=False;self._closed=False;self._closing=False
        self._series_request=None
        self._cancel=threading.Event();self._terminals=[];self._layers=[];self._plot_keys={}
        self._history=[];self._history_index=0;self._completions=[];self._completion_prefix=None;self._completion_index=0
        panel=wx.Panel(self);self.main_panel=panel;root=wx.BoxSizer(wx.VERTICAL)
        title=wx.BoxSizer(wx.HORIZONTAL)
        label=wx.StaticText(panel,label='Quick PI · Copper and decoupling')
        font=label.GetFont();font.SetWeight(wx.FONTWEIGHT_BOLD);label.SetFont(font)
        title.Add(label,1,wx.ALIGN_CENTER_VERTICAL)
        filename=wx.StaticText(panel,label=Path(self.board_path).name);filename.SetToolTip(self.board_path)
        title.Add(filename,0,wx.ALIGN_CENTER_VERTICAL);root.Add(title,0,wx.EXPAND|wx.ALL,12)
        form=wx.FlexGridSizer(2,6,7,10);form.AddGrowableCol(1,1);form.AddGrowableCol(3,1);form.AddGrowableCol(5,1)
        self.net=wx.ComboBox(panel,style=wx.CB_READONLY)
        self.source=wx.Choice(panel);self.sink=wx.Choice(panel)
        self.voltage=wx.TextCtrl(panel,value='1');self.current=wx.TextCtrl(panel,value='1')
        self.load_mode=wx.Choice(panel,choices=['Specified sink current (A)','Resistive load to 0 V (Ω)'])
        self.load_mode.SetSelection(0)
        self.operation_note=wx.StaticText(panel,label='Source voltage → sink current')
        for name,control in [('Net',self.net),('Source pad',self.source),('Sink pad',self.sink),
                             ('Source V',self.voltage),('Current / load',self.current),('Mode',self.load_mode)]:
            form.Add(wx.StaticText(panel,label=name),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        self.dc_form=form
        root.Add(form,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        root.Add(self.operation_note,0,wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.options=wx.CollapsiblePane(panel,label='Mesh and material options',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        pane=self.options.GetPane();grid=wx.FlexGridSizer(2,6,6,10)
        for col in (1,3,5):grid.AddGrowableCol(col,1)
        self.edge=wx.TextCtrl(pane,value='0.5');self.plating=wx.TextCtrl(pane,value='0.025')
        self.temperature=wx.TextCtrl(pane,value='20');self.ambient=wx.TextCtrl(pane,value='20')
        self.pulse=wx.TextCtrl(pane,value='1');self.limit=wx.TextCtrl(pane,value='150')
        for name,control in [('Mesh edge mm',self.edge),('Via plating mm',self.plating),('Copper °C',self.temperature),
                             ('Ambient °C',self.ambient),('Pulse seconds',self.pulse),('Screen limit °C',self.limit)]:
            grid.Add(wx.StaticText(pane,label=name),0,wx.ALIGN_CENTER_VERTICAL);grid.Add(control,1,wx.EXPAND)
        pane.SetSizer(grid);root.Add(self.options,0,wx.EXPAND|wx.ALL,12)
        viewer=wx.BoxSizer(wx.HORIZONTAL)
        viewer.Add(wx.StaticText(panel,label='Layer'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.layer=wx.Choice(panel);viewer.Add(self.layer,0,wx.RIGHT,16)
        viewer.Add(wx.StaticText(panel,label='Result'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.metric=wx.Choice(panel,choices=[value[0] for value in METRICS.values()]);self.metric.SetSelection(1)
        viewer.Add(self.metric,0,wx.RIGHT,12);self.mesh_count=wx.StaticText(panel,label='');viewer.Add(self.mesh_count,1,wx.ALIGN_CENTER_VERTICAL)
        self.dc_viewer=viewer
        root.Add(viewer,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.book=wx.Notebook(panel);self.views=[]
        for name in ('Net','Mesh','Results'):
            page=wx.Panel(self.book);layout=wx.BoxSizer(wx.VERTICAL)
            figure=Figure(figsize=(9,5),dpi=100,facecolor='white');canvas=FigureCanvasWxAgg(page,wx.ID_ANY,figure)
            toolbar=NavigationToolbar2WxAgg(canvas);toolbar.Realize()
            layout.Add(canvas,1,wx.EXPAND);layout.Add(toolbar,0,wx.EXPAND);page.SetSizer(layout)
            self.book.AddPage(page,name);self.views.append((figure,canvas,toolbar))
        self._build_return_page()
        from .decoupling.pdn_decoupling_plugin import PdnFrame
        import pcbnew
        self.decoupling=PdnFrame(self.book,pcbnew.LoadBoard(self.board_path))
        self.book.AddPage(self.decoupling,"Decoupling placement")
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.summary=wx.StaticText(panel,label='Choose two pads on one net. Run creates the mesh and solves the DC current path.')
        root.Add(self.summary,0,wx.EXPAND|wx.ALL,12)
        self.console=wx.CollapsiblePane(panel,label='Console',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        console_panel=self.console.GetPane();console_layout=wx.BoxSizer(wx.VERTICAL)
        self.console_log=wx.TextCtrl(console_panel,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,95))
        self.console_input=wx.TextCtrl(console_panel,style=wx.TE_PROCESS_ENTER)
        self.console_input.SetHint('help · run pi START D1.1 1V D1.2 END · diode(Vf=0.7V,Iref=1A,n=2,T=25C)')
        console_layout.Add(self.console_log,1,wx.EXPAND|wx.BOTTOM,5);console_layout.Add(self.console_input,0,wx.EXPAND)
        console_panel.SetSizer(console_layout);root.Add(self.console,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.status=wx.StaticText(panel,label='Reading the saved board…');root.Add(self.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.help_button=wx.Button(panel,wx.ID_HELP,label='Help')
        self.help_button.Bind(wx.EVT_BUTTON,self.on_help)
        footer.Add(self.help_button,0,wx.RIGHT,8)
        self.more=wx.Button(panel,label='More…');self.preview=wx.Button(panel,label='Preview copper');self.run=wx.Button(panel,label='Run analysis')
        self.series_button=wx.Button(panel,label='Build series path…')
        self.export=wx.Button(panel,label='Export report…');self.cancel=wx.Button(panel,label='Cancel')
        self.gauge=wx.Gauge(panel,range=100,size=(140,-1))
        for control in (self.more,self.series_button,self.preview):footer.Add(control,0,wx.RIGHT,8)
        footer.Add(self.gauge,0,wx.ALIGN_CENTER_VERTICAL);footer.AddStretchSpacer()
        for control in (self.run,self.export,self.cancel):footer.Add(control,0,wx.LEFT,8)
        root.Add(footer,0,wx.EXPAND|wx.ALL,12);panel.SetSizer(root)
        self._controls=[self.net,self.source,self.sink,self.voltage,self.current,self.load_mode,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit,self.more,self.series_button,self.layer,self.metric,self.console_input]
        self.net.Bind(wx.EVT_COMBOBOX,self._net_changed)
        for control in (self.source,self.sink):control.Bind(wx.EVT_CHOICE,self._invalidate)
        for control in (self.voltage,self.current,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit):control.Bind(wx.EVT_TEXT,self._invalidate)
        self.load_mode.Bind(wx.EVT_CHOICE,self._invalidate)
        self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:panel.Layout())
        self.console.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:panel.Layout())
        self.console_input.Bind(wx.EVT_TEXT_ENTER,self.on_console)
        self.console_input.Bind(wx.EVT_KEY_DOWN,self._console_key)
        self.layer.Bind(wx.EVT_CHOICE,lambda event:self._draw());self.metric.Bind(wx.EVT_CHOICE,lambda event:self._draw(preserve=True))
        self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,self._page_changed)
        self.preview.Bind(wx.EVT_BUTTON,self.preview_geometry);self.run.Bind(wx.EVT_BUTTON,lambda event:self._analyze('solve'))
        self.more.Bind(wx.EVT_BUTTON,self.on_more);self.export.Bind(wx.EVT_BUTTON,self.on_export)
        self.series_button.Bind(wx.EVT_BUTTON,self.on_series_editor)
        self.cancel.Bind(wx.EVT_BUTTON,self.on_cancel);self.Bind(wx.EVT_CLOSE,self.on_close)
        self.timer=wx.Timer(self);self.Bind(wx.EVT_TIMER,lambda event:self.gauge.Pulse() if self._busy else None,self.timer);self.timer.Start(120)
        self._buttons();self._draw();self.Centre();wx.CallAfter(self._inspect)


    def _build_return_page(self):
        page=wx.Panel(self.book);layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(page,label='Return-path screen · choose the routed signal and its actual return net(s). The map checks saved filled zones and nearby return vias; it cannot prove current loops or impedance.')
        note.Wrap(1050);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        settings=wx.BoxSizer(wx.HORIZONTAL)
        self.return_signal=wx.Choice(page)
        self.return_pitch=wx.TextCtrl(page,value='0.25',size=(75,-1))
        self.return_radius=wx.TextCtrl(page,value='2',size=(75,-1))
        for label,ctrl in [('Signal net',self.return_signal),('Sample pitch mm',self.return_pitch),('Return via radius mm',self.return_radius)]:
            settings.Add(wx.StaticText(page,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
            settings.Add(ctrl,1 if ctrl is self.return_signal else 0,wx.RIGHT,12)
        self.return_run=wx.Button(page,label='Review return path');self.return_run.Bind(wx.EVT_BUTTON,self.on_return_path)
        self.return_export=wx.Button(page,label='Export report…');self.return_export.Bind(wx.EVT_BUTTON,lambda e:self.on_export_diagnostic('return_path'))
        settings.Add(self.return_run,0,wx.RIGHT,7);settings.Add(self.return_export,0);layout.Add(settings,0,wx.EXPAND|wx.ALL,10)
        body=wx.BoxSizer(wx.HORIZONTAL)
        side=wx.BoxSizer(wx.VERTICAL);side.Add(wx.StaticText(page,label='Return nets'),0,wx.BOTTOM,5)
        self.return_nets=wx.CheckListBox(page,size=(180,-1));side.Add(self.return_nets,1,wx.EXPAND)
        body.Add(side,0,wx.EXPAND|wx.RIGHT,10)
        self.return_figure=Figure(figsize=(8,4),dpi=100);self.return_canvas=FigureCanvasWxAgg(page,wx.ID_ANY,self.return_figure)
        body.Add(self.return_canvas,1,wx.EXPAND);layout.Add(body,1,wx.EXPAND|wx.ALL,10)
        self.return_table=wx.ListCtrl(page,style=wx.LC_REPORT,size=(-1,145))
        for i,(name,width) in enumerate([('Level',90),('Finding',210),('Layer',100),('Position mm',120),('Detail',510)]):
            self.return_table.InsertColumn(i,name,width=width)
        layout.Add(self.return_table,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.return_status=wx.StaticText(page,label='Choose explicit return net(s), then run the saved-board review.')
        layout.Add(self.return_status,0,wx.EXPAND|wx.ALL,10)
        self.return_signal.Bind(wx.EVT_CHOICE,self._invalidate_return)
        for ctrl in (self.return_pitch,self.return_radius):ctrl.Bind(wx.EVT_TEXT,self._invalidate_return)
        self.return_nets.Bind(wx.EVT_CHECKLISTBOX,self._invalidate_return)
        page.SetSizer(layout);self.book.AddPage(page,'Return path')






    def _invalidate_return(self,event=None):
        self.return_bundle={};self.return_table.DeleteAllItems();self.return_figure.clear()
        self.return_canvas.draw_idle();self.return_status.SetLabel('Inputs changed. Review the saved return path again.')
        self._buttons()
        if event:event.Skip()

    def _buttons(self):
        placement=self.book.GetSelection()>=len(self.views)
        self.dc_form.ShowItems(not placement);self.dc_viewer.ShowItems(not placement)
        for window in (self.options,self.console,self.summary,self.series_button,self.preview,self.run,self.export,self.status):window.Show(not placement)
        self.main_panel.Layout()
        for control in self._controls:control.Enable(not self._busy)
        for control in (self.return_signal,self.return_pitch,self.return_radius,self.return_nets):
            control.Enable(not self._busy)
        self.return_run.Enable(not self._busy)
        self.return_export.Enable(not self._busy and bool(self.return_bundle.get('return_path')))
        self.preview.Enable(not self._busy and bool(self.net.GetValue()))
        self.run.Enable(not self._busy and len(self._terminals)>1)
        self.export.Enable(not self._busy and bool(self.bundle.get('result')))
        self.cancel.Enable(self._busy);self.cancel.Show(not placement);self.gauge.Show(self._busy and not placement)
        self.more.SetLabel("Reload saved board" if placement else "More…")
        self.more.InvalidateBestSize();self.more.SetMinSize(self.more.GetBestSize());self.main_panel.Layout()
        if not self._busy:self.metric.Enable(self.book.GetSelection()==2)
        if self._series_request:
            self.source.Disable();self.sink.Disable()
            self.preview.Enable(not self._busy and bool(self.bundle.get('geometry')))
        if self.book.GetSelection()>=len(self.views):
            for control in (self.net,self.source,self.sink,self.voltage,self.current,self.layer,self.metric,self.preview,self.run,self.export):control.Disable()

    def _task(self,operation,finished,message):
        if self._busy:return
        self._busy=True;self._cancel.clear();self.status.SetLabel(message);self._buttons();self.Layout()
        def worker():
            try:result=operation();error=None
            except Exception as exc:result=None;error=exc
            wx.CallAfter(self._finish,finished,result,error)
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
        else:finished(result)
        self._buttons();self.Layout()
        if self._closing:self._end()

    def _job(self,request,finished,message):
        if self._closed or self._closing:return
        from .service import run_job
        if request.get('action') in ('geometry','mesh','solve','converge'):
            self.bundle.pop('result',None)
            self.bundle.pop('convergence',None)
            self.summary.SetLabel('Waiting for the current request. No current electrical result is available.')
            self._draw(preserve=True)
        self._console_write('Job: '+json.dumps(request,ensure_ascii=False))
        self._task(lambda:run_job(request,cancelled=self._cancel.is_set,timeout=300),finished,message)

    def _inspect(self):
        if self._closed or self._closing:return
        self._series_request=None;self.bundle={};self.return_bundle={}
        self.sweep_bundle={};self.return_table.DeleteAllItems()
        self.return_figure.clear();self.return_canvas.draw_idle()
        def finished(result):
            import pcbnew
            self.decoupling.board=pcbnew.LoadBoard(self.board_path)
            self.decoupling.invalidate()
            self.decoupling.summary.SetLabel('Saved board reloaded; run a fresh placement check.')
            self.inventory=result;names=result.get('nets',[]);self.net.Set(names)
            self.return_signal.Set(names);self.return_nets.Set(names)
            if names:self.return_signal.SetSelection(0)
            if names:
                choice=next((n for n in names if n.startswith(('+','VCC','VDD'))),names[0]);self.net.SetValue(choice)
            self._set_terminals();self.status.SetLabel(f'{len(names)} saved nets. Choose source and sink terminals.')
            if names:wx.CallAfter(self.preview_geometry)
        self._job({'action':'inspect','board_path':self.board_path},finished,'Reading saved net names and pad terminals…')

    def _set_terminals(self):
        net=self.net.GetValue();self._terminals=[t for t in self.inventory.get('terminals',[]) if t.get('net')==net]
        labels=[t.get('label',t['id']) for t in self._terminals]
        for control in (self.source,self.sink):control.Set(labels)
        if labels:self.source.SetSelection(0);self.sink.SetSelection(min(1,len(labels)-1))
        self._buttons()

    def _net_changed(self,event=None):
        self._series_request=None;self.operation_note.SetLabel('Source voltage → sink current')
        self.bundle={};self._set_terminals();self._plot_keys.clear();self._draw()
        self.status.SetLabel('Preview this net or run the analysis.')

    def _invalidate(self,event=None):
        if event and event.GetEventObject() is self.load_mode:
            self.operation_note.SetLabel('Source voltage → resistive load to 0 V' if self.load_mode.GetSelection()==1 else 'Source voltage → specified sink current')
        self.bundle.pop('convergence',None)
        self.bundle.pop('result',None);self._buttons();self.summary.SetLabel('Inputs changed. Run again to update the electrical results.')
        request=self.bundle.setdefault('request',{})
        for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
            if control.GetSelection()>=0:request[key]=self._terminals[control.GetSelection()]['id']
        self._draw(preserve=True)
        if event:event.Skip()

    def _request(self,action,require_terminals=True):
        def number(control,label,positive=False):
            try:value=float(control.GetValue())
            except ValueError:raise ValueError(label+' must be a number.')
            if not math.isfinite(value) or positive and value<=0:raise ValueError(label+' must be finite'+(' and positive.' if positive else '.'))
            return value
        request={'action':action,'board_path':self.board_path,'net':self.net.GetValue(),
                 'edge_mm':number(self.edge,'Mesh edge',True),'plating_mm':number(self.plating,'Via plating',True)}
        if require_terminals and not request['net']:raise ValueError('Choose a net.')
        if action=='solve':
            a,b=self.source.GetSelection(),self.sink.GetSelection()
            if require_terminals and (min(a,b)<0 or a==b):raise ValueError('Choose two different source and sink pads on this net.')
            if min(a,b)>=0:request.update(source_terminal=self._terminals[a]['id'],sink_terminal=self._terminals[b]['id'])
            request.update(source_voltage=number(self.voltage,'Source voltage'),
                options={'temperature_c':number(self.temperature,'Copper temperature'),'ambient_c':number(self.ambient,'Ambient temperature'),
                         'temperature_limit_c':number(self.limit,'Temperature limit'),'pulse_duration_s':number(self.pulse,'Pulse duration',True)})
            if self.load_mode.GetSelection()==1:request['load_resistance_ohm']=number(self.current,'Load resistance',True)
            else:request['sink_current']=number(self.current,'Sink current',True)
        else:
            for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
                if control.GetSelection()>=0:request[key]=self._terminals[control.GetSelection()]['id']
        if require_terminals and self._series_request and action=='solve':
            for key in ('series','net','source_terminal','sink_terminal'):request[key]=self._series_request[key]
        return request

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
        self.bundle=result;self.bundle.setdefault('request',request)
        self._layers=[row for row in layer_rows(result) if row.get('polygons') or
                      via_markers(result.get('mesh',{}),result.get('result',{}),result.get('geometry',{}),row['id'],'density')]
        self.layer.Set([row['name'] for row in self._layers])
        if self._layers:self.layer.SetSelection(0)
        mesh=result.get('mesh',{});self.mesh_count.SetLabel(f"{len(mesh.get('points_mm',[])):,} nodes · {len(mesh.get('triangles',[])):,} triangles" if mesh else '')
        for warning in result.get('geometry',{}).get('warnings',[]):self._console_write('Geometry: '+str(warning))
        self._plot_keys.clear();self.book.SetSelection(2 if action=='solve' else 1 if action=='mesh' else 0)
        if result.get('result'):
            r=result['result'];scope='Circuit' if request.get('series') else 'Copper'
            ratio_label=f'{scope} ΔV/I'+(' (apparent)' if r.get('contains_forward_drop') else '')
            self.summary.SetLabel(f"ΔV {r['voltage_drop_V']*1000:.4g} mV   |   {ratio_label} {r['drop_over_current_ohm']*1000:.4g} mΩ   |   Total loss {r['total_power_W']:.4g} W   |   Peak sheet J {r['max_current_density_A_mm2']:.4g} A/mm²")
            self.status.SetLabel('Mesh convergence not verified. Pulse risk is an adiabatic screen; peaks depend on mesh size and exclude cooling/fuse-opening physics.')
            self._console_write(f"Solved: drop={r['voltage_drop_V']:.8g} V; {ratio_label}={r['drop_over_current_ohm']:.8g} ohm; power={r['total_power_W']:.8g} W; source V/I={r['V_over_I_ohm']:.8g} ohm")
            for branch in r.get('components',[]):
                if branch.get('model') in ('diode','fixed_drop'):
                    self._console_write(f"{branch['id']}: {branch['model']} at {branch['current_A']:.6g} A, Vf={branch['forward_drop_V']:.6g} V, before={branch['voltage_before_V']:.6g} V, after={branch['voltage_after_V']:.6g} V")
            if r.get('negative_sink_voltage'):
                self.status.SetLabel('Requested current makes the sink voltage negative. Review source voltage and load. Mesh convergence is not verified.')
                self._console_write('Warning: the requested sink current exceeds the available source voltage for this path; the DC operating point may be infeasible.')
            if result.get('convergence'):
                from .convergence import summary
                self.status.SetLabel(summary(result['convergence'])+(' Sink voltage is negative; review the load.' if r.get('negative_sink_voltage') else ''))
                self.status.Wrap(max(600,self.GetClientSize().width-32))
                self.edge.ChangeValue(str(result['request']['edge_mm']))
                self._console_write(summary(result['convergence']))
        else:self.summary.SetLabel('Actual filled copper, pad contacts and via barrels. Pan and zoom to inspect the selected layer.');self.status.SetLabel('Preview ready.')
        self._draw()


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
        key=(index,str(layer));limits=None
        if preserve and self._plot_keys.get(index)==key and figure.axes:limits=(figure.axes[0].get_xlim(),figure.axes[0].get_ylim())
        ax=draw_view(figure,self.bundle,('Net','Mesh','Results')[index],layer,metric)
        result=self.bundle.get('result',{});analysis=result.get('analytics',{})
        row=next((item for item in analysis.get('layers',[]) if str(item['layer'])==str(layer)),None)
        if row:
            from .analytics import thickness_label
            losses=analysis['losses']
            self.summary.SetLabel(f"ΔV {result['voltage_drop_V']*1000:.4g} mV | Sheets {losses['planar_W']:.4g} W | Vias {losses['via_W']:.4g} W | Components {losses['component_W']:.4g} W\n"
                                  f"{row['name']}: {thickness_label(row)} copper | {row['area_mm2']:.4g} mm² | Layer loss {row['planar_power_W']:.4g} W · More → Layer details")
            self.summary.GetParent().Layout()
        if limits:ax.set_xlim(*limits[0]);ax.set_ylim(*limits[1])
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
                     'return_via_radius_mm':float(self.return_radius.GetValue())}
        except ValueError as exc:self.return_status.SetLabel(str(exc));return
        self.return_bundle={};self.return_table.DeleteAllItems();self.return_status.SetLabel('Checking saved filled return copper and transitions…')
        self._job(request,self._accept_return,'Screening the saved-board return path…')

    def _accept_return(self,bundle):
        self.return_bundle=bundle;result=bundle['return_path'];evidence=bundle['evidence']
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
        for row in result['findings']:
            if row['position_mm']:
                ax.plot(*row['position_mm'],marker='x' if row['level']=='warning' else 'o',
                        color='#b63b32' if row['level']=='warning' else '#bd8b30',markersize=8)
        ax.set_aspect('equal',adjustable='datalim');ax.invert_yaxis();ax.set_xlabel('X mm');ax.set_ylabel('Y mm')
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
        self._task(lambda:write_diagnostic_report(path,bundle),
            lambda result:self.return_status.SetLabel('Exported '+result['html']),
            'Writing local HTML and JSON evidence…')

    def on_help(self,event=None):
        import wx.html
        dialog=wx.Dialog(self,title='Quick PI · Help',size=(960,740),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        html=wx.html.HtmlWindow(dialog)
        html.LoadPage(str(Path(__file__).with_name('help.html')))
        layout=wx.BoxSizer(wx.VERTICAL);layout.Add(html,1,wx.EXPAND|wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,10)
        dialog.SetSizer(layout);dialog.Bind(wx.EVT_BUTTON,lambda e:dialog.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        dialog.ShowModal();dialog.Destroy()

    def on_more(self,event):
        if self.book.GetSelection()>=len(self.views):self._inspect();return
        menu=wx.Menu();mesh=menu.Append(wx.ID_ANY,'Generate mesh only');self.Bind(wx.EVT_MENU,lambda e:self._analyze('mesh'),mesh)
        details=menu.Append(wx.ID_ANY,'Layer thickness, losses and hotspots…');details.Enable(bool(self.bundle.get('result',{}).get('analytics')))
        self.Bind(wx.EVT_MENU,self.on_details,details)
        focus=menu.Append(wx.ID_ANY,'Zoom to circuit terminals');self.Bind(wx.EVT_MENU,self._focus_terminals,focus)
        refine=menu.Append(wx.ID_ANY,'Refine mesh and rerun (half edge length)')
        self.Bind(wx.EVT_MENU,self._refine,refine)
        study=menu.Append(wx.ID_ANY,'Check mesh convergence…');self.Bind(wx.EVT_MENU,self.on_convergence,study)
        study.Enable(len(self._terminals)>1)
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
        axes.grid(True,alpha=.25);axes.legend();figure.tight_layout();layout.Add(canvas,1,wx.EXPAND|wx.ALL,10)
        note=wx.StaticText(dialog,label='One fixed-temperature FEM mesh supplies copper resistance. Diode Vf is reevaluated at each current; negative sink voltage flags an infeasible requested point.')
        note.Wrap(self.FromDIP(880));layout.Add(note,0,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,10)
        dialog.SetSizer(layout);canvas.draw();dialog.ShowModal();dialog.Destroy()

    def on_convergence(self,event=None):
        if self._busy:return
        try:request=self._request('solve')
        except (ValueError,KeyError) as exc:self.status.SetLabel(str(exc));return
        dialog=wx.Dialog(self,title='Check mesh convergence',size=self.FromDIP((510,280)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label=f"Start at {request['edge_mm']:g} mm and halve mesh edge each level. The board, contacts and material inputs stay fixed. Cancellation and mesh limits remain active.");note.Wrap(self.FromDIP(465));box.Add(note,0,wx.ALL,12)
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
        from .analytics import details_text
        dialog=wx.Dialog(self,title='Quick PI · Layer details',size=(940,660),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        text=wx.TextCtrl(dialog,value=details_text(self.bundle.get('result',{})),style=wx.TE_MULTILINE|wx.TE_READONLY)
        layout=wx.BoxSizer(wx.VERTICAL);layout.Add(text,1,wx.EXPAND|wx.ALL,12)
        layout.Add(dialog.CreateButtonSizer(wx.CLOSE),0,wx.ALIGN_RIGHT|wx.ALL,12)
        dialog.SetSizer(layout);dialog.Bind(wx.EVT_BUTTON,lambda e:dialog.EndModal(wx.ID_CLOSE),id=wx.ID_CLOSE)
        dialog.ShowModal();dialog.Destroy()

    def _focus_terminals(self,event=None):
        request=self.bundle.get('request',{});mesh=self.bundle.get('mesh',{})
        chosen={request.get('source_terminal'),request.get('sink_terminal')}
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
            value=float(self.edge.GetValue())/2
            if not math.isfinite(value) or value<=0:raise ValueError('Mesh edge must be positive.')
            prior=dict(self.bundle.get('request',{}));self.edge.SetValue(f'{value:g}')
            if prior.get('series'):
                prior['edge_mm']=value
                self._job(prior,lambda result:self._accept_result(result,prior,'solve'),'Refining the console circuit mesh…')
            else:self._analyze('solve')
        except Exception as exc:self.status.SetLabel(str(exc))

    def on_export(self,event=None):
        if not self.bundle.get('result'):return
        with wx.FileDialog(self,'Export self-contained results',defaultDir=str(Path(self.board_path).parent),defaultFile=Path(self.board_path).stem+'-quick-pi.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        selected=self.layer.GetSelection();layer=self._layers[selected]['id'] if selected>=0 else None
        bundle=self.bundle
        self._task(lambda:write_report(path,bundle,layer),lambda result:self.status.SetLabel('Exported HTML maps and all-layer JSON: '+result['html']),
                   'Rendering the selected layer’s seven maps and exporting all numerical results…')

    def on_cancel(self,event=None):
        self._cancel.set();self.status.SetLabel('Stopping the isolated worker…')

    def on_close(self,event):
        if self._busy:
            self._closing=True;self.on_cancel()
            if event.CanVeto():event.Veto()
            return
        self._end()

    def _end(self):
        self._closed=True;self.timer.Stop();self.Destroy()


MainFrame=QuickPIFrame
