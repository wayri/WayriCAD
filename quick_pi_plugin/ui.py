"""Native Quick PI window: saved copper, mesh and DC results in one workflow."""
from __future__ import annotations
import math
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
        self.SetMinSize((940,680));self.board_path=str(Path(board_path).resolve())
        self.bundle={};self.inventory={};self._busy=False;self._closed=False;self._closing=False
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
        self.operation_note=wx.StaticText(panel,label='Source voltage → sink current')
        for name,control in [('Net',self.net),('Source pad',self.source),('Sink pad',self.sink),
                             ('Source V',self.voltage),('Sink A',self.current),('',self.operation_note)]:
            form.Add(wx.StaticText(panel,label=name),0,wx.ALIGN_CENTER_VERTICAL);form.Add(control,1,wx.EXPAND)
        self.dc_form=form
        root.Add(form,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
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
        self.console_input.SetHint('help   ·   run pi <net> <source pad> <sink pad>   ·   Tab completes names')
        console_layout.Add(self.console_log,1,wx.EXPAND|wx.BOTTOM,5);console_layout.Add(self.console_input,0,wx.EXPAND)
        console_panel.SetSizer(console_layout);root.Add(self.console,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.status=wx.StaticText(panel,label='Reading the saved board…');root.Add(self.status,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        self.help_button=wx.Button(panel,wx.ID_HELP,label='Help')
        self.help_button.Bind(wx.EVT_BUTTON,self.on_help)
        footer.Add(self.help_button,0,wx.RIGHT,8)
        self.more=wx.Button(panel,label='More…');self.preview=wx.Button(panel,label='Preview copper');self.run=wx.Button(panel,label='Run analysis')
        self.export=wx.Button(panel,label='Export report…');self.cancel=wx.Button(panel,label='Cancel')
        self.gauge=wx.Gauge(panel,range=100,size=(140,-1))
        for control in (self.more,self.preview):footer.Add(control,0,wx.RIGHT,8)
        footer.Add(self.gauge,0,wx.ALIGN_CENTER_VERTICAL);footer.AddStretchSpacer()
        for control in (self.run,self.export,self.cancel):footer.Add(control,0,wx.LEFT,8)
        root.Add(footer,0,wx.EXPAND|wx.ALL,12);panel.SetSizer(root)
        self._controls=[self.net,self.source,self.sink,self.voltage,self.current,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit,self.more,self.layer,self.metric,self.console_input]
        self.net.Bind(wx.EVT_COMBOBOX,self._net_changed)
        for control in (self.source,self.sink):control.Bind(wx.EVT_CHOICE,self._invalidate)
        for control in (self.voltage,self.current,self.edge,self.plating,self.temperature,self.ambient,self.pulse,self.limit):control.Bind(wx.EVT_TEXT,self._invalidate)
        self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:panel.Layout())
        self.console.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:panel.Layout())
        self.console_input.Bind(wx.EVT_TEXT_ENTER,self.on_console)
        self.console_input.Bind(wx.EVT_KEY_DOWN,self._console_key)
        self.layer.Bind(wx.EVT_CHOICE,lambda event:self._draw());self.metric.Bind(wx.EVT_CHOICE,lambda event:self._draw(preserve=True))
        self.book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,self._page_changed)
        self.preview.Bind(wx.EVT_BUTTON,self.preview_geometry);self.run.Bind(wx.EVT_BUTTON,lambda event:self._analyze('solve'))
        self.more.Bind(wx.EVT_BUTTON,self.on_more);self.export.Bind(wx.EVT_BUTTON,self.on_export)
        self.cancel.Bind(wx.EVT_BUTTON,self.on_cancel);self.Bind(wx.EVT_CLOSE,self.on_close)
        self.timer=wx.Timer(self);self.Bind(wx.EVT_TIMER,lambda event:self.gauge.Pulse() if self._busy else None,self.timer);self.timer.Start(120)
        self._buttons();self._draw();self.Centre();wx.CallAfter(self._inspect)

    def _buttons(self):
        placement=self.book.GetSelection()>=len(self.views)
        self.dc_form.ShowItems(not placement);self.dc_viewer.ShowItems(not placement)
        for window in (self.options,self.console,self.summary,self.preview,self.run,self.export,self.status):window.Show(not placement)
        self.main_panel.Layout()
        for control in self._controls:control.Enable(not self._busy)
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
            self._console_write('Error: '+str(error))
            self.status.Wrap(max(600,self.GetClientSize().width-32))
        else:finished(result)
        self._buttons();self.Layout()
        if self._closing:self._end()

    def _job(self,request,finished,message):
        from .service import run_job
        if request.get('action') in ('geometry','mesh','solve'):
            self.bundle.pop('result',None)
            self.summary.SetLabel('Waiting for the current request. No current electrical result is available.')
            self._draw(preserve=True)
        self._console_write('Job: '+json.dumps(request,ensure_ascii=False))
        self._task(lambda:run_job(request,cancelled=self._cancel.is_set,timeout=300),finished,message)

    def _inspect(self):
        self._series_request=None;self.bundle={}
        def finished(result):
            import pcbnew
            self.decoupling.board=pcbnew.LoadBoard(self.board_path)
            self.decoupling.invalidate()
            self.decoupling.summary.SetLabel('Saved board reloaded; run a fresh placement check.')
            self.inventory=result;names=result.get('nets',[]);self.net.Set(names)
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
            request.update(source_voltage=number(self.voltage,'Source voltage'),sink_current=number(self.current,'Sink current',True),
                options={'temperature_c':number(self.temperature,'Copper temperature'),'ambient_c':number(self.ambient,'Ambient temperature'),
                         'temperature_limit_c':number(self.limit,'Temperature limit'),'pulse_duration_s':number(self.pulse,'Pulse duration',True)})
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
            self.summary.SetLabel(f"ΔV {r['voltage_drop_V']*1000:.4g} mV   |   {scope} ΔV/I {r['drop_over_current_ohm']*1000:.4g} mΩ   |   Total loss {r['total_power_W']:.4g} W   |   Peak sheet J {r['max_current_density_A_mm2']:.4g} A/mm²")
            self.status.SetLabel('Mesh convergence not verified. Pulse risk is an adiabatic screen; peaks depend on mesh size and exclude cooling/fuse-opening physics.')
            self._console_write(f"Solved: drop={r['voltage_drop_V']:.8g} V; {scope.lower()} R={r['drop_over_current_ohm']:.8g} ohm; power={r['total_power_W']:.8g} W; source V/I={r['V_over_I_ohm']:.8g} ohm")
            if r.get('negative_sink_voltage'):
                self.status.SetLabel('Requested current makes the sink voltage negative. Review source voltage and load. Mesh convergence is not verified.')
                self._console_write('Warning: the requested sink current exceeds the available source voltage for this resistive path.')
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
            request=self._request(parsed.get('action','solve'),require_terminals=False);request.update(parsed)
            request['board_path']=self.board_path
            self._series_request=request.copy() if request.get('series') else None
            if request.get('net') in self.inventory.get('nets',[]):
                self.net.SetValue(request['net']);self._set_terminals()
                for control,key in ((self.source,'source_terminal'),(self.sink,'sink_terminal')):
                    index=next((i for i,t in enumerate(self._terminals) if request.get(key) in (t['id'],t.get('label'))),None)
                    if index is not None:control.SetSelection(index)
            if self._series_request:
                self._terminals=[next(t for t in self.inventory['terminals'] if request[key] in (t['id'],t.get('label')))
                                 for key in ('source_terminal','sink_terminal')]
                labels=[t['label'] for t in self._terminals]
                self.source.Set(labels);self.sink.Set(labels);self.source.SetSelection(0);self.sink.SetSelection(1)
            self.operation_note.SetLabel('Console series circuit' if request.get('series') else 'Source voltage → sink current')
        except Exception as exc:self._console_write('Error: '+str(exc));return
        self.bundle={}
        self._job(request,lambda result:self._accept_result(result,request,request.get('action','solve')),'Running the console circuit in the isolated solver…')

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
        refresh=menu.Append(wx.ID_ANY,'Reload saved board');self.Bind(wx.EVT_MENU,lambda e:self._inspect(),refresh)
        self.PopupMenu(menu);menu.Destroy()

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
        with wx.FileDialog(self,'Export self-contained results',defaultFile='WayriCAD-Quick-PI.html',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
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
