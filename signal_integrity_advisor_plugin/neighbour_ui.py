"""Native saved-board neighbour map; all geometry work stays in an owned child."""
from pathlib import Path
import json
import math
import threading
import wx
from .neighbour_report import colour, pair_text, html_report


class NeighbourCanvas(wx.Panel):
    def __init__(self,parent,selected):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.pairs=[];self.current=None;self.selected=selected;self.zoom=1.;self.pan=[0.,0.];self.drag=None;self.strokes=[]
        self.SetMinSize((250,200));self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_MOTION,self.motion)
        self.Bind(wx.EVT_LEFT_DOWN,self.down);self.Bind(wx.EVT_LEFT_UP,self.up)
        self.Bind(wx.EVT_LEFT_DCLICK,self.fit);self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))

    def show_pairs(self,pairs):
        self.pairs=pairs;self.current=None;self.fit()

    def fit(self,event=None):
        self.zoom=1.;self.pan=[0.,0.];self.Refresh()

    def paint(self,event=None):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('#f6f9fa'));dc.Clear();self.strokes=[]
        if not self.pairs:
            dc.DrawLabel('Run a neighbour search, then select a pair.\nNo empty view establishes zero interference.',self.GetClientRect(),wx.ALIGN_CENTER);return
        points=[p for row in self.pairs for side in ('a','b') for p in (row[side]['start_mm'],row[side]['end_mm'])]
        low=[min(p[k] for p in points) for k in (0,1)];high=[max(p[k] for p in points) for k in (0,1)]
        width,height=self.GetClientSize();scale=max(.01,min(max(1,width-45)/max(.1,high[0]-low[0]),max(1,height-45)/max(.1,high[1]-low[1])))*self.zoom
        project=lambda p:(round(23+(p[0]-low[0])*scale+self.pan[0]),round(23+(p[1]-low[1])*scale+self.pan[1]))
        for row in reversed(self.pairs):
            for side in ('a','b'):
                track=row[side];a,b=project(track['start_mm']),project(track['end_mm'])
                if row['id']==self.current:
                    dc.SetPen(wx.Pen('#183e47',max(6,round(track['width_mm']*scale)+5)));dc.DrawLine(*a,*b)
                dc.SetPen(wx.Pen(colour(row['closeness']),max(2,min(80,round(track['width_mm']*scale)))));dc.DrawLine(*a,*b)
                self.strokes.append((a,b,row))
            x,y=project(row['location_mm']);dc.SetPen(wx.Pen('#183e47',1));dc.SetBrush(wx.Brush('white'));dc.DrawCircle(x,y,4)

    def hit(self,point):
        from .neighbours import _closest
        best=None;distance=9.
        for a,b,row in self.strokes:
            if a==b:continue
            d=math.dist(point,_closest(point,a,b))
            if d<distance:distance=d;best=row
        return best

    def motion(self,event):
        if self.drag and event.Dragging() and event.LeftIsDown():
            point=event.GetPosition();self.pan=[self.drag[1][k]+point[k]-self.drag[0][k] for k in (0,1)];self.Refresh();return
        row=self.hit(event.GetPosition());text=pair_text(row) if row else 'Geometric gap map · wheel zoom · drag pan · double-click fit'
        if self.GetToolTipText()!=text:self.SetToolTip(text)

    def down(self,event):
        row=self.hit(event.GetPosition())
        if row:self.selected(row['id']);return
        self.drag=(tuple(event.GetPosition()),list(self.pan));self.CaptureMouse()

    def up(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()

    def wheel(self,event):
        self.zoom=max(.1,min(100.,self.zoom*(1.2 if event.GetWheelRotation()>0 else 1/1.2)));self.Refresh()


class NeighbourPanel(wx.Panel):
    def __init__(self,parent,board,saved_board=False,study_panel=None):
        super().__init__(parent);self.board=board;self.saved_board=saved_board;self.report=None;self.closed=False;self.serial=0;self.cancel=threading.Event();self.visible=[]
        self.fingerprints=None;self.study_panel=study_panel
        if saved_board:
            from .service import source_fingerprints
            self.fingerprints=source_fingerprints(board.GetFileName())
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Neighbour interference map · geometric exposure, not solved field intensity. Colour shows edge gap in mm; local NEXT stays UNKNOWN unless an explicit hypothetical model is enabled.');note.Wrap(950);root.Add(note,0,wx.EXPAND|wx.ALL,8)
        controls=wx.BoxSizer(wx.HORIZONTAL)
        self.search=wx.SearchCtrl(self,size=(220,-1));self.search.SetHint('Search mapped net names / evidence')
        names=getattr(study_panel,'_net_names',None)
        if names is None:names=sorted({str(t.GetNetname()) for t in board.GetTracks() if t.GetNetname()})
        self.net=wx.ComboBox(self,value='',choices=names,size=(200,-1));self.net.SetHint('Choose/type exact net; blank = all')
        self.layer=wx.Choice(self,choices=['All copper layers']+[str(board.GetLayerName(v)) for v in board.GetEnabledLayers().CuStack()]);self.layer.SetSelection(0)
        self.radius=wx.TextCtrl(self,value='1',size=(60,-1))
        self.run_button=wx.Button(self,label='Map neighbours');self.cancel_button=wx.Button(self,label='Cancel');self.cancel_button.Disable()
        self.export_button=wx.Button(self,label='Export HTML + JSON');self.export_button.Disable()
        self.study_button=wx.Button(self,label='Link current study sections');self.study_button.Disable()
        for label,control in [('Target net',self.net),('Layer',self.layer),('Radius mm',self.radius)]:
            controls.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.LEFT,7);controls.Add(control,0,wx.LEFT,4)
        root.Add(controls,0,wx.EXPAND|wx.ALL,5)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        for control in (self.run_button,self.cancel_button,self.export_button,self.study_button):actions.Add(control,0,wx.LEFT|wx.BOTTOM,6)
        fit=wx.Button(self,label='Fit map');fit.Bind(wx.EVT_BUTTON,lambda e:self.canvas.fit());actions.Add(fit,0,wx.LEFT|wx.BOTTOM,6)
        root.Add(actions,0,wx.EXPAND|wx.ALL,5)
        assumptions=wx.CollapsiblePane(self,label='Optional isolated local NEXT model · explicit what-if inputs',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        host=assumptions.GetPane();form=wx.BoxSizer(wx.VERTICAL);self.model_enabled=wx.CheckBox(host,label='Use ideal homogeneous-plane model');form.Add(self.model_enabled,0,wx.BOTTOM,8)
        grid=wx.FlexGridSizer(cols=6,hgap=6,vgap=6)
        self.model_fields={}
        for key,label,value in [('reference_layer','Reference layer','B.Cu'),('height_mm','Height mm','0.2'),('epsilon_r','Er','4'),('copper_mm','Copper mm','0.035'),('rise_ns','Rise ns','1'),('swing_v','Swing V','1')]:
            grid.Add(wx.StaticText(host,label=label),0,wx.ALIGN_CENTER_VERTICAL);control=wx.TextCtrl(host,value=value,size=(75,-1));self.model_fields[key]=control;grid.Add(control,0);control.Bind(wx.EVT_TEXT,self.invalidate)
        form.Add(grid,0,wx.EXPAND)
        host.SetSizer(form);root.Add(assumptions,0,wx.EXPAND|wx.ALL,5)
        assumptions.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:self.Layout())
        legend=wx.BoxSizer(wx.HORIZONTAL)
        self.legend_labels=[]
        for text,bg in [('Contact / 0 mm','#c5313d'),('0.5 mm gap','#e6a52c'),('1 mm radius','#22878e'),('UNKNOWN coupling: not solved','#6b7780')]:
            tag=wx.StaticText(self,label='  '+text+'  ');tag.SetBackgroundColour(bg);tag.SetForegroundColour('white');legend.Add(tag,0,wx.RIGHT,8)
            self.legend_labels.append(tag)
        legend.Add(self.search,1,wx.LEFT,8);root.Add(legend,0,wx.EXPAND|wx.ALL,6)
        self.split=wx.SplitterWindow(self,style=wx.SP_LIVE_UPDATE);self.split.SetMinimumPaneSize(100)
        self.canvas=NeighbourCanvas(self.split,self.select_pair);self.table=wx.ListCtrl(self.split,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(name,width) in enumerate([('Trace net',180),('Neighbour',180),('Layer',90),('Gap mm',100),('Overlap mm',110),('Local NEXT mV',145),('Study section NEXT mV',180)]):self.table.InsertColumn(i,name,width=width)
        self.split.SplitHorizontally(self.canvas,self.table,360);root.Add(self.split,1,wx.EXPAND|wx.ALL,5)
        self.detail=wx.TextCtrl(self,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,76));root.Add(self.detail,0,wx.EXPAND|wx.ALL,5)
        self.status=wx.StaticText(self,label='Saved-board read-only search. Arcs, vias, pads, zones and other layers are not coupling-solved.');root.Add(self.status,0,wx.EXPAND|wx.ALL,6)
        self.SetSizer(root)
        self.run_button.Bind(wx.EVT_BUTTON,self.run);self.cancel_button.Bind(wx.EVT_BUTTON,lambda e:self.invalidate())
        self.export_button.Bind(wx.EVT_BUTTON,self.export);self.search.Bind(wx.EVT_TEXT,self.filter)
        self.study_button.Bind(wx.EVT_BUTTON,self.link_study)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED,lambda e:self.select_pair(self.visible[e.GetIndex()]['id'],False))
        for control,event in ((self.net,wx.EVT_TEXT),(self.radius,wx.EVT_TEXT),(self.layer,wx.EVT_CHOICE),(self.model_enabled,wx.EVT_CHECKBOX)):control.Bind(event,self.invalidate)
        self.net.Bind(wx.EVT_COMBOBOX,self.invalidate)
        self.Bind(wx.EVT_WINDOW_DESTROY,self.destroyed)
        if not saved_board:self.run_button.Disable();self.status.SetLabel('Open the normal saved-board Quick SI sidecar for this cancellable map; unsaved live geometry is not substituted.')

    def destroyed(self,event):
        if event.GetEventObject() is self:self.closed=True;self.cancel.set();self.serial+=1
        event.Skip()

    def invalidate(self,event=None):
        self.cancel.set();self.serial+=1;self.report=None;self.export_button.Disable();self.study_button.Disable();self.cancel_button.Disable();self.run_button.Enable(self.saved_board)
        self.table.DeleteAllItems();self.canvas.show_pairs([]);self.detail.SetValue('');self.status.SetLabel('Inputs changed or analysis cancelled; rerun the neighbour map.')

    def run(self,event=None):
        from .service import source_fingerprints,run_job
        from .neighbours import settings_checked
        self.invalidate();self.cancel=threading.Event();serial=self.serial
        try:
            if source_fingerprints(self.board.GetFileName())!=self.fingerprints:raise ValueError('Saved source changed; reopen Quick SI.')
            model={key:(control.GetValue() if key=='reference_layer' else float(control.GetValue())) for key,control in self.model_fields.items()} if self.model_enabled.GetValue() else None
            settings=settings_checked(dict(radius_mm=float(self.radius.GetValue()),nets=[self.net.GetValue().strip()] if self.net.GetValue().strip() else [],layers=[self.layer.GetStringSelection()] if self.layer.GetSelection()>0 else [],model=model))
            request=dict(mode='neighbours',board_path=self.board.GetFileName(),source_fingerprints=self.fingerprints,settings=settings)
        except Exception as error:self.status.SetLabel(str(error));return
        self.run_button.Disable();self.cancel_button.Enable();self.status.SetLabel('Indexing nearby traces in a bounded worker…')
        cancelled=self.cancel
        def work():
            try:payload=run_job(request,cancelled=cancelled.is_set,timeout=90);error=None
            except Exception as caught:payload=None;error=str(caught)
            if self.closed:return
            wx.CallAfter(self.finished,serial,payload,error)
        # Reap the owned child before the broker exits on window close.
        threading.Thread(target=work,name='si-neighbour-map',daemon=False).start()

    def finished(self,serial,payload,error):
        if self.closed or serial!=self.serial:return
        self.cancel_button.Disable();self.run_button.Enable(self.saved_board)
        if error:self.status.SetLabel(error);return
        from .service import source_fingerprints
        try:
            if source_fingerprints(self.board.GetFileName())!=self.fingerprints or payload['source_fingerprints']!=self.fingerprints:raise ValueError('Source changed; reopen and rerun.')
            self.report=payload['neighbours'];self.filter();self.export_button.Enable();self.study_button.Enable(self.study_panel is not None)
            radius=self.report['settings']['radius_mm'];self.legend_labels[1].SetLabel(f'  {radius/2:.4g} mm gap  ');self.legend_labels[2].SetLabel(f'  {radius:.4g} mm radius  ');self.Layout()
            coverage=self.report['coverage'];self.status.SetLabel(f"{self.report['status']} · {coverage['pair_count']} pairs · {coverage['comparisons']} indexed comparisons · "+' '.join(self.report['warnings']))
        except Exception as caught:self.invalidate();self.status.SetLabel(str(caught))

    def filter(self,event=None):
        query=self.search.GetValue().casefold();self.visible=[row for row in self.report['pairs'] if query in pair_text(row).casefold()] if self.report else []
        self.table.DeleteAllItems()
        for row in self.visible:
            index=self.table.InsertItem(self.table.GetItemCount(),row['a']['net'])
            for col,value in enumerate((row['b']['net'],row['layer'],f"{row['gap_mm']:.6g}",f"{row['parallel_length_mm']:.6g}",'UNKNOWN' if row['next_peak_v'] is None else f"{row['next_peak_v']*1000:.6g}",', '.join(f"{r['next_peak_v']*1000:.5g}" for r in row.get('study_sections',[])) or 'UNKNOWN'),1):self.table.SetItem(index,col,value)
        self.canvas.show_pairs(self.visible)

    def link_study(self,event=None):
        if not self.report:return
        from .neighbours import attach_study
        from .service import source_fingerprints
        try:
            if source_fingerprints(self.board.GetFileName())!=self.fingerprints:raise ValueError('Saved source changed; reopen Quick SI.')
            study=getattr(self.study_panel,'study_report',None)
            if not study:raise ValueError('Run an explicit multi-net study with directed crosstalk pairs first.')
            attach_study(self.report,study);self.filter();self.status.SetLabel('Linked explicit study sections; select a pair for section scope and reference evidence. Peaks are not added.')
        except Exception as error:self.status.SetLabel(str(error))

    def select_pair(self,identifier,select_table=True):
        for index,row in enumerate(self.visible):
            if row['id']==identifier:
                self.canvas.current=identifier;self.canvas.Refresh();self.detail.SetValue(pair_text(row))
                if select_table:self.table.Select(index);self.table.EnsureVisible(index)
                return

    def export(self,event=None):
        if not self.report:return
        from .service import source_fingerprints
        from .cli import write_report
        try:
            source=Path(self.board.GetFileName())
            if source_fingerprints(source)!=self.fingerprints:raise ValueError('Source changed; reopen and rerun before export.')
            dialog=wx.FileDialog(self,'Export neighbour map',wildcard='HTML report (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
            try:
                if dialog.ShowModal()!=wx.ID_OK:return
                target=Path(dialog.GetPath());companion=target.with_suffix('.json')
                if companion.exists():raise ValueError('Companion JSON already exists; choose a new report name.')
                write_report(target,html_report(self.report),source,'.html');write_report(companion,json.dumps(self.report,indent=2,allow_nan=False),source,'.json')
            finally:dialog.Destroy()
            self.status.SetLabel('Saved neighbour map HTML and complete JSON.')
        except Exception as error:self.status.SetLabel(str(error))
