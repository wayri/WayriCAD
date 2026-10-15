"""Small scope, preview, validate and apply interface for native KiCad tracks."""
from copy import deepcopy
from pathlib import Path
import pcbnew
import wx
from .refiner import DEFAULTS, propose, validate_detached, Transaction


class Preview(wx.Panel):
    def __init__(self,parent,board,guard):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.board,self.guard=board,guard;self.plan=None;self.zoom=1.;self.pan=[0,0];self.drag=None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetToolTip('Grey: existing tracks. Amber: original chains. Teal: proposed replacement. Wheel zooms; drag pans; double-click fits.')
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL,self.wheel);self.Bind(wx.EVT_LEFT_DOWN,self.down);self.Bind(wx.EVT_LEFT_UP,self.up)
        self.Bind(wx.EVT_MOTION,self.motion);self.Bind(wx.EVT_LEFT_DCLICK,self.fit)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))
    def fit(self,event=None):self.zoom=1.;self.pan=[0,0];self.Refresh()
    def wheel(self,event):self.zoom=max(.25,min(50,self.zoom*(1.25 if event.GetWheelRotation()>0 else .8)));self.Refresh()
    def down(self,event):self.drag=event.GetPosition();self.CaptureMouse()
    def up(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()
    def motion(self,event):
        if self.drag is not None and event.Dragging():
            p=event.GetPosition();self.pan[0]+=p.x-self.drag.x;self.pan[1]+=p.y-self.drag.y;self.drag=p;self.Refresh()
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('#162f3a'));dc.Clear()
        if not self.guard():return
        tracks=list(self.board.GetTracks());bounds=self.board.GetBoardEdgesBoundingBox();w,h=self.GetClientSize()
        if bounds.GetWidth()<=0 or bounds.GetHeight()<=0:bounds=self.board.GetBoundingBox()
        scale=min((w-40)/max(1,bounds.GetWidth()),(h-40)/max(1,bounds.GetHeight()))*self.zoom
        cx=(bounds.GetLeft()+bounds.GetRight())/2;cy=(bounds.GetTop()+bounds.GetBottom())/2
        def p(x,y):return round(w/2+(x-cx)*scale+self.pan[0]),round(h/2+(y-cy)*scale+self.pan[1])
        for t in tracks:
            width=t.GetWidth(t.TopLayer()) if isinstance(t,pcbnew.PCB_VIA) else t.GetWidth()
            dc.SetPen(wx.Pen('#546a73',max(1,round(width*scale))))
            if isinstance(t,pcbnew.PCB_VIA):
                v=t.GetPosition();dc.SetBrush(wx.Brush('#9e8c4c'));dc.DrawCircle(*p(v.x,v.y),max(2,round(width*scale/2)))
            elif type(t) is pcbnew.PCB_TRACK:dc.DrawLine(*p(t.GetStart().x,t.GetStart().y),*p(t.GetEnd().x,t.GetEnd().y))
        if self.plan:
            for c in self.plan.changes:
                for points,colour in ((c.before,'#e6a44a'),(c.after,'#4bdebe')):
                    dc.SetPen(wx.Pen(colour,max(2,round(c.width*scale))));dc.DrawLines([p(*a) for a in points])
        dc.SetTextForeground('#f1f6f7');dc.DrawText('Amber: before     Teal: proposed     Wheel: zoom · Drag: pan · Double-click: fit',12,12)


class RefinerFrame(wx.Frame):
    def __init__(self,parent,board,guard=None):
        super().__init__(parent,title='WayriCAD Trace Refiner',size=(1150,780))
        self.SetMinSize((950,650));self.board=board;self.guard=guard or (lambda:True);self.review=None;self.transactions=[];self.redos=[]
        self.checked=set();self.nets=sorted({t.GetNetname() for t in board.GetTracks() if t.GetNetname()})
        panel=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(panel,label='Refine small routing jogs');title.SetFont(title.GetFont().Bold().Larger());root.Add(title,0,wx.ALL,12)
        body=wx.BoxSizer(wx.HORIZONTAL);left=wx.ScrolledWindow(panel,size=(290,-1));left.SetMinSize((290,100));left.SetScrollRate(0,15);setup=wx.BoxSizer(wx.VERTICAL)
        setup.Add(wx.StaticText(left,label='Scope'),0,wx.BOTTOM,5)
        self.scope=wx.Choice(left,choices=['Selected tracks','Selected nets','Whole board','Net filters','Net groups (net classes)']);self.scope.SetSelection(0);setup.Add(self.scope,0,wx.EXPAND|wx.BOTTOM,10)
        self.search=wx.SearchCtrl(left);self.search.SetDescriptiveText('Search net names');setup.Add(self.search,0,wx.EXPAND|wx.BOTTOM,5)
        self.netlist=wx.CheckListBox(left,choices=self.nets,size=(270,150));setup.Add(self.netlist,0,wx.EXPAND|wx.BOTTOM,8)
        setup.Add(wx.StaticText(left,label='Net groups: select net classes'),0,wx.BOTTOM,5)
        self.groups=wx.CheckListBox(left,choices=sorted({t.GetNetClassName() for t in board.GetTracks()}),size=(270,65));setup.Add(self.groups,0,wx.EXPAND|wx.BOTTOM,8)
        setup.Add(wx.StaticText(left,label='Layers (none checked = all)'),0,wx.BOTTOM,5)
        self.layers=wx.CheckListBox(left,choices=[board.GetLayerName(layer) for layer in board.GetEnabledLayers().CuStack()],size=(270,75));setup.Add(self.layers,0,wx.EXPAND|wx.BOTTOM,8)
        self.deviation=wx.TextCtrl(left,value='.10');self.shortening=wx.TextCtrl(left,value='.10')
        for label,control in [('Maximum displacement (mm)',self.deviation),('Maximum shortening / chain (mm)',self.shortening)]:
            setup.Add(wx.StaticText(left,label=label),0,wx.TOP,5);setup.Add(control,0,wx.EXPAND|wx.BOTTOM,5)
        self.protected=wx.TextCtrl(left,value=DEFAULTS['protected']);self.protected.SetToolTip('Comma-separated protected net wildcards. Native differential-pair names are always protected. Add any other tuned or critical nets.');setup.Add(wx.StaticText(left,label='Protected nets (wildcards)'),0,wx.TOP,5);setup.Add(self.protected,0,wx.EXPAND|wx.BOTTOM,5)
        left.SetSizer(setup);left.FitInside();body.Add(left,0,wx.EXPAND|wx.RIGHT,12)
        right=wx.BoxSizer(wx.VERTICAL);self.canvas=Preview(panel,board,self.guard);right.Add(self.canvas,1,wx.EXPAND)
        self.details=wx.ListCtrl(panel,style=wx.LC_REPORT);self.details.InsertColumn(0,'Net',width=330);self.details.InsertColumn(1,'Change / preserved',width=430);self.details.SetMinSize((-1,130));right.Add(self.details,0,wx.EXPAND|wx.TOP,8)
        body.Add(right,1,wx.EXPAND);root.Add(body,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.status=wx.StaticText(panel,label='Select tracks or choose another scope. Preview is read-only; native DRC is required before Apply.');root.Add(self.status,0,wx.EXPAND|wx.ALL,12)
        row=wx.BoxSizer(wx.HORIZONTAL)
        help_button=wx.Button(panel,label='Help');row.Add(help_button);self.undo_button=wx.Button(panel,label='Undo');self.redo_button=wx.Button(panel,label='Redo');row.Add(self.undo_button,0,wx.LEFT,8);row.Add(self.redo_button,0,wx.LEFT,8);row.AddStretchSpacer()
        preview=wx.Button(panel,label='Preview');self.validate_button=wx.Button(panel,label='Validate candidate');self.apply_button=wx.Button(panel,label='Apply refinement')
        for button in (preview,self.validate_button,self.apply_button):row.Add(button,0,wx.LEFT,8)
        root.Add(row,0,wx.EXPAND|wx.ALL,12);panel.SetSizer(root)
        for button in (self.validate_button,self.apply_button,self.undo_button,self.redo_button):button.Disable()
        self.search.Bind(wx.EVT_TEXT,self.filter_nets)
        for control in (self.scope,self.netlist,self.groups,self.layers,self.deviation,self.shortening,self.protected):
            control.Bind(wx.EVT_CHOICE if control is self.scope else wx.EVT_CHECKLISTBOX if isinstance(control,wx.CheckListBox) else wx.EVT_TEXT,self.invalidate)
        preview.Bind(wx.EVT_BUTTON,self.on_preview);self.validate_button.Bind(wx.EVT_BUTTON,self.on_validate);self.apply_button.Bind(wx.EVT_BUTTON,self.on_apply)
        self.undo_button.Bind(wx.EVT_BUTTON,self.undo);self.redo_button.Bind(wx.EVT_BUTTON,self.redo)
        help_button.Bind(wx.EVT_BUTTON,lambda e:wx.LaunchDefaultBrowser(Path(__file__).with_name('help.html').as_uri()))
    def require_board(self):
        if not self.guard():raise ValueError('Originating board closed or replaced. Reopen Trace Refiner.')
    def remember_nets(self):
        visible=set(self.netlist.GetStrings());self.checked.difference_update(visible);self.checked.update(self.netlist.GetCheckedStrings())
    def filter_nets(self,event):
        self.remember_nets();query=self.search.GetValue().casefold();values=[n for n in self.nets if query in n.casefold()];self.netlist.Set(values)
        for i,n in enumerate(values):self.netlist.Check(i,n in self.checked)
    def settings(self):
        self.remember_nets()
        return dict(scope=['selected tracks','selected nets','whole board','net filters','groups'][self.scope.GetSelection()],nets=sorted(self.checked),layers=list(self.layers.GetCheckedStrings()),groups=list(self.groups.GetCheckedStrings()),max_deviation=float(self.deviation.GetValue()),max_shortening=float(self.shortening.GetValue()),protected=self.protected.GetValue())
    def invalidate(self,event=None):
        self.review=None;self.canvas.plan=None;self.canvas.Refresh();self.validate_button.Disable();self.apply_button.Disable()
        self.status.SetLabel('Inputs changed. Preview again.')
    def error(self,exc):self.status.SetLabel(str(exc));wx.MessageBox(str(exc),'Trace Refiner',wx.OK|wx.ICON_ERROR,parent=self)
    def on_preview(self,event=None):
        self.invalidate();self.details.DeleteAllItems()
        progress=wx.ProgressDialog('Preview trace refinement','Inspecting native routing…',parent=self,style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
        try:
            self.require_board()
            def pulse(label):
                return self.guard() and progress.Pulse(label)[0]
            self.review=propose(self.board,pcbnew,self.settings(),progress=pulse)
            self.canvas.plan=self.review
            for c in self.review.changes:
                row=self.details.InsertItem(self.details.GetItemCount(),c.net);self.details.SetItem(row,1,f'{self.board.GetLayerName(c.layer)} · {len(c.before)-1} → {len(c.after)-1} segments')
            for net,reason in self.review.skipped:
                row=self.details.InsertItem(self.details.GetItemCount(),net);self.details.SetItem(row,1,reason)
            self.validate_button.Enable(bool(self.review.changes));self.canvas.Refresh()
            self.status.SetLabel(f'{len(self.review.changes)} proposed chains · {len(self.review.skipped)} preserved. Validate before Apply. Protected/locked/grouped items are untouched.')
        except Exception as exc:self.error(exc)
        finally:progress.Destroy()
    def on_validate(self,event=None):
        if self.review is None:return
        progress=wx.ProgressDialog('Validate trace refinement','Preparing native snapshot…',parent=self,style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
        try:
            self.require_board();review=self.review
            def pulse(label):
                if not self.guard():return False
                return progress.Pulse(label)[0]
            validate_detached(self.board,pcbnew,review,progress=pulse)
            self.apply_button.Enable(True);self.status.SetLabel(f'{len(review.changes)} chains validated: native terminal connectivity unchanged; no new DRC findings. Review, then Apply.')
        except Exception as exc:self.apply_button.Disable();self.error(exc)
        finally:progress.Destroy()
    def on_apply(self,event=None):
        try:
            self.require_board()
            if self.review is None or self.review.settings!=self.settings():raise ValueError('Preview changed. Validate again.')
            tx=Transaction(self.board,pcbnew,self.review).redo();self.transactions.append(tx);self.redos=[];self.invalidate();self.undo_button.Enable();self.redo_button.Disable();pcbnew.Refresh()
            self.status.SetLabel('Refinement applied. Inspect the board, refill zones and run final DRC before saving. Undo is available in this window.')
        except Exception as exc:self.error(exc)
    def undo(self,event=None):
        if not self.transactions:return
        try:
            self.require_board();tx=self.transactions[-1];tx.undo();self.transactions.pop();self.redos.append(tx);self.invalidate();self.undo_button.Enable(bool(self.transactions));self.redo_button.Enable();pcbnew.Refresh()
        except Exception as exc:self.error(exc)
    def redo(self,event=None):
        if not self.redos:return
        try:
            self.require_board();tx=self.redos[-1];tx.redo();self.redos.pop();self.transactions.append(tx);self.invalidate();self.undo_button.Enable();self.redo_button.Enable(bool(self.redos));pcbnew.Refresh()
        except Exception as exc:self.error(exc)
