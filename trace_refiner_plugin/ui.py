"""Small scope, preview, validate and apply interface for native KiCad tracks."""
from copy import deepcopy
from pathlib import Path
import math
from collections import defaultdict
import pcbnew
import wx
from .refiner import DEFAULTS, propose, validate_detached, Transaction
from . import refiner
try:
    from .wayricad_runtime.editor_refresh import SavedBoardRefresh, source_stamp
except ImportError:
    from wayricad_runtime.editor_refresh import SavedBoardRefresh, source_stamp


class Preview(wx.Panel):
    DISPLAY_MODES=('Overlay','Before','After','Side by side')
    def __init__(self,parent,board,guard):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.board,self.guard=board,guard;self.plan=None;self.zoom=1.;self.pan=[0,0];self.drag=None
        self.context=();self.context_bounds=(0,0,1,1);self.context_generation=0
        self.overlays=();self.active_change=None;self.focus_bounds=None
        self.display_mode='Overlay';self.affected_segments=set()
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetToolTip('Amber: before. Teal: proposed. Overlay adds an amber comparison outline so coincident paths remain visible; the outline is not copper width. Choose Before, After or Side by side for separate views. Wheel zooms; drag pans; double-click fits.')
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL,self.wheel);self.Bind(wx.EVT_LEFT_DOWN,self.down);self.Bind(wx.EVT_LEFT_UP,self.up)
        self.Bind(wx.EVT_MOTION,self.motion);self.Bind(wx.EVT_LEFT_DCLICK,self.fit)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))
        self.capture_context()
    def capture_context(self):
        """Copy native geometry on the UI thread, outside the paint handler.

        Cached coordinates are context only: proposal, validation and apply keep
        their independent fresh source checks. Native arcs are tessellated at
        approximately 1 micrometre chord error, never drawn as straight chords.
        """
        if not self.guard():raise ValueError('Originating board closed or replaced. Reopen Trace Refiner.')
        records=[]
        for item in self.board.GetTracks():
            via=isinstance(item,pcbnew.PCB_VIA)
            width=int(item.GetWidth(item.TopLayer()) if via else item.GetWidth())
            if via:
                p=item.GetPosition();points=((int(p.x),int(p.y)),);kind='via'
            elif type(item) is pcbnew.PCB_TRACK:
                a=item.GetStart();b=item.GetEnd();points=((int(a.x),int(a.y)),(int(b.x),int(b.y)));kind='line'
            elif isinstance(item,pcbnew.PCB_ARC):
                a=item.GetStart();b=item.GetEnd();m=item.GetMid();center=item.GetCenter()
                cx,cy=int(center.x),int(center.y);radius=float(item.GetRadius())
                start=math.atan2(a.y-cy,a.x-cx);end=math.atan2(b.y-cy,b.x-cx);mid=math.atan2(m.y-cy,m.x-cx)
                ccw=(end-start)%(2*math.pi)
                sweep=ccw if (mid-start)%(2*math.pi)<=ccw else ccw-2*math.pi
                if a.x==b.x and a.y==b.y:sweep=2*math.pi
                if radius<=0:continue
                step=min(math.pi/36,2*math.acos(max(-1.,1.-min(1000./radius,2.))))
                count=max(2,math.ceil(abs(sweep)/max(step,1e-9)))
                # KiCad board-scale arcs stay comfortably below this bound.
                # For extreme geometry retain the curve with a bounded count.
                count=min(count,8192)
                points=((int(a.x),int(a.y)),)+tuple((round(cx+radius*math.cos(start+sweep*i/count)),round(cy+radius*math.sin(start+sweep*i/count))) for i in range(1,count))+((int(b.x),int(b.y)),)
                kind='arc'
            else:continue
            radius=width/2
            bounds=(min(p[0] for p in points)-radius,min(p[1] for p in points)-radius,
                    max(p[0] for p in points)+radius,max(p[1] for p in points)+radius)
            records.append((kind,width,points,bounds))
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                shape=pcbnew.SHAPE_POLY_SET()
                pad.TransformShapeToPolygon(shape,pad.GetLayer(),0,pcbnew.FromMM(.01),pcbnew.ERROR_OUTSIDE)
                for index in range(shape.OutlineCount()):
                    ring=shape.COutline(index)
                    points=tuple((int(ring.CPoint(i).x),int(ring.CPoint(i).y)) for i in range(ring.PointCount()))
                    if not points:continue
                    bounds=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
                    records.append(('pad',0,points,bounds))
        box=self.board.GetBoardEdgesBoundingBox()
        if box.GetWidth()<=0 or box.GetHeight()<=0:box=self.board.GetBoundingBox()
        bounds=(int(box.GetLeft()),int(box.GetTop()),int(box.GetRight()),int(box.GetBottom()))
        self.context=tuple(records);self.context_bounds=bounds;self.context_generation+=1

    def draw_context(self,dc,project,scale,view):
        """Render only plain cached values; group straight strokes by pixel width."""
        lines=defaultdict(list);vias=defaultdict(list)
        left,top,right,bottom=view
        for kind,width,points,bounds in self.context:
            if bounds[2]<left or bounds[0]>right or bounds[3]<top or bounds[1]>bottom:continue
            if kind=='pad':
                dc.SetPen(wx.Pen('#b89a55',1));dc.SetBrush(wx.Brush('#796c47'))
                dc.DrawPolygon([project(*point) for point in points]);continue
            pixels=max(1,round(width*scale))
            if kind=='via':vias[pixels].append(project(*points[0]))
            else:
                if kind=='line' and (width,tuple(sorted(points))) in self.affected_segments:continue
                projected=[project(*point) for point in points]
                lines[pixels].extend((*a,*b) for a,b in zip(projected,projected[1:]))
        for width,segments in lines.items():
            dc.SetPen(wx.Pen('#546a73',width));dc.DrawLineList(segments)
        dc.SetBrush(wx.Brush('#9e8c4c'))
        for width,positions in vias.items():
            dc.SetPen(wx.Pen('#546a73',1))
            for x,y in positions:dc.DrawCircle(x,y,max(2,round(width/2)))
    def set_plan(self,plan):
        """Cache review geometry and bounds before any repaint or focus action."""
        self.plan=plan;self.active_change=None;self.focus_bounds=None;records=[]
        self.affected_segments=set()
        for index,change in enumerate(plan.changes if plan else ()):
            before=tuple(tuple(point) for point in change.before);after=tuple(tuple(point) for point in change.after)
            points=before+after
            bounds=(min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
            records.append((index,change.width,before,after,bounds))
            self.affected_segments.update((change.width,tuple(sorted((a,b))))
                                          for points in (before,after) for a,b in zip(points,points[1:]))
        self.overlays=tuple(records);self.Refresh()

    def set_display_mode(self,mode):
        """Change only cached presentation; retain the reviewed proposal."""
        if mode not in self.DISPLAY_MODES:raise ValueError('Choose a supported comparison view.')
        self.display_mode=mode;self.Refresh()

    def focus_change(self,index):
        """Move only the cached viewport; never change native item selection."""
        record=next((row for row in self.overlays if row[0]==index),None)
        if record is None:return False
        _,width,_,_,bounds=record
        margin=max(width*4,max(bounds[2]-bounds[0],bounds[3]-bounds[1])*.2,1)
        self.focus_bounds=(bounds[0]-margin,bounds[1]-margin,bounds[2]+margin,bounds[3]+margin)
        self.active_change=index;self.zoom=1.;self.pan=[0,0];self.Refresh();return True

    def fit(self,event=None):self.zoom=1.;self.pan=[0,0];self.focus_bounds=None;self.Refresh()
    def wheel(self,event):self.zoom=max(.25,min(50,self.zoom*(1.25 if event.GetWheelRotation()>0 else .8)));self.Refresh()
    def down(self,event):self.drag=event.GetPosition();self.CaptureMouse()
    def up(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()
    def motion(self,event):
        if self.drag is not None and event.Dragging():
            p=event.GetPosition();self.pan[0]+=p.x-self.drag.x;self.pan[1]+=p.y-self.drag.y;self.drag=p;self.Refresh()
    def paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        self.draw(dc,self.GetClientSize())

    def draw(self,dc,size):
        """Draw cached geometry in linked comparison views, without native reads."""
        dc.SetBackground(wx.Brush('#162f3a'));dc.Clear()
        if not self.guard():return
        w,h=size
        if self.display_mode=='Side by side':
            half=w//2
            for origin,width,mode in ((0,half,'Before'),(half,w-half,'After')):
                dc.SetClippingRegion(origin,0,width,h)
                self.draw_view(dc,origin,width,h,mode)
                dc.DestroyClippingRegion()
            dc.SetPen(wx.Pen('#8aa5af',1));dc.DrawLine(half,0,half,h)
        else:self.draw_view(dc,0,w,h,self.display_mode)

    def draw_view(self,dc,origin,w,h,mode):
        bounds=self.focus_bounds or self.context_bounds
        scale=max(1e-12,min(max(1,w-40)/max(1,bounds[2]-bounds[0]),max(1,h-40)/max(1,bounds[3]-bounds[1]))*self.zoom)
        cx=(bounds[0]+bounds[2])/2;cy=(bounds[1]+bounds[3])/2
        def p(x,y):return round(origin+w/2+(x-cx)*scale+self.pan[0]),round(h/2+(y-cy)*scale+self.pan[1])
        view=(cx+(-w/2-self.pan[0])/scale,cy+(-h/2-self.pan[1])/scale,
              cx+(w/2-self.pan[0])/scale,cy+(h/2-self.pan[1])/scale)
        self.draw_context(dc,p,scale,view)
        for index,width,before,after,_ in self.overlays:
            paths=((before,'#e6a44a'),) if mode=='Before' else ((after,'#4bdebe'),) if mode=='After' else ((before,'#e6a44a'),(after,'#4bdebe'))
            pixels=max(2,round(width*scale))
            if index==self.active_change:
                dc.SetPen(wx.Pen('#eff9ff',pixels+8))
                for points,_ in paths:dc.DrawLines([p(*a) for a in points])
            for points,colour in paths:
                outline=4 if mode=='Overlay' and colour=='#e6a44a' else 0
                dc.SetPen(wx.Pen(colour,pixels+outline));dc.DrawLines([p(*a) for a in points])
        label='Overlay · Amber outline: before · Teal: proposed' if mode=='Overlay' else 'Before · Amber: original' if mode=='Before' else 'After · Teal: proposed'
        dc.SetTextForeground('#f1f6f7');dc.DrawText(label,origin+12,12)


class RefinerFrame(wx.Frame):
    def __init__(self,parent,board,guard=None):
        super().__init__(parent,title='WayriCAD Trace Refiner',size=(1150,780))
        self.SetMinSize((950,650));self.board=board;self.guard=guard or (lambda:True);self.review=None;self.transactions=[];self.redos=[];self._table_rows=[];self._excluded_notices=[];self._last_tooltip=None
        self._busy=False
        self._last_editor_selection=None
        self._proposal_source_ids=[]
        self.checked=set();self.nets=sorted({t.GetNetname() for t in board.GetTracks() if t.GetNetname()})
        panel=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(panel,label='Repair existing routing');title.SetFont(title.GetFont().Bold().Larger());root.Add(title,0,wx.ALL,12)
        self.operation=wx.Notebook(panel)
        for label,hint in [('Routing jogs','Remove small kinks and redundant segments; preserve contact endpoints.'),
                           ('Pad / via centering','Center off-center track ends already touching a same-net pad or via. Preview, validate, then apply.')]:
            page=wx.Panel(self.operation);layout=wx.BoxSizer(wx.VERTICAL)
            text=wx.StaticText(page,label=hint);text.Wrap(800);layout.Add(text,0,wx.ALL,8);page.SetSizer(layout)
            self.operation.AddPage(page,label)
        root.Add(self.operation,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.settings_splitter=wx.SplitterWindow(panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D);right_panel=wx.Panel(self.settings_splitter)
        left=wx.ScrolledWindow(self.settings_splitter,size=(290,-1));left.SetMinSize((250,100));left.SetScrollRate(12,15);setup=wx.BoxSizer(wx.VERTICAL)
        setup.Add(wx.StaticText(left,label='Scope'),0,wx.BOTTOM,5)
        self.scope=wx.Choice(left,choices=['Selected tracks','Selected nets','Whole board','Net filters','Net groups (net classes)']);self.scope.SetSelection(0);setup.Add(self.scope,0,wx.EXPAND|wx.BOTTOM,10)
        self.search=wx.SearchCtrl(left);self.search.SetDescriptiveText('Search net names');setup.Add(self.search,0,wx.EXPAND|wx.BOTTOM,5)
        self.netlist=wx.CheckListBox(left,choices=self.nets,size=(270,150),style=wx.LB_HSCROLL);setup.Add(self.netlist,0,wx.EXPAND|wx.BOTTOM,8)
        setup.Add(wx.StaticText(left,label='Net groups: select net classes'),0,wx.BOTTOM,5)
        self.groups=wx.CheckListBox(left,choices=sorted({t.GetNetClassName() for t in board.GetTracks()}),size=(270,65),style=wx.LB_HSCROLL);setup.Add(self.groups,0,wx.EXPAND|wx.BOTTOM,8)
        setup.Add(wx.StaticText(left,label='Layers (none checked = all)'),0,wx.BOTTOM,5)
        self.layers=wx.CheckListBox(left,choices=[board.GetLayerName(layer) for layer in board.GetEnabledLayers().CuStack()],size=(270,75),style=wx.LB_HSCROLL);setup.Add(self.layers,0,wx.EXPAND|wx.BOTTOM,8)
        self.deviation=wx.TextCtrl(left,value='.10');self.shortening=wx.TextCtrl(left,value='.10');self.jog_controls=[];self.setup_window=left
        for label,control in [('Maximum displacement (mm)',self.deviation),('Maximum shortening / chain (mm)',self.shortening)]:
            caption=wx.StaticText(left,label=label);self.jog_controls.extend((caption,control))
            setup.Add(caption,0,wx.TOP,5);setup.Add(control,0,wx.EXPAND|wx.BOTTOM,5)
        self.center_caption=wx.StaticText(left,label='Maximum contact centering shift (mm)');setup.Add(self.center_caption,0,wx.TOP,5)
        self.center_shift=wx.TextCtrl(left,value='.25');self.center_shift.SetToolTip('Pad / via centering only. Maximum endpoint movement; does not bridge gaps or move pads/vias. Native DRC is still required.')
        setup.Add(self.center_shift,0,wx.EXPAND|wx.BOTTOM,5)
        self.protected=wx.TextCtrl(left,value=DEFAULTS['protected']);self.protected.SetToolTip('Comma-separated protected net wildcards. Native differential-pair names are always protected. Add any other tuned or critical nets.');setup.Add(wx.StaticText(left,label='Protected nets (wildcards)'),0,wx.TOP,5);setup.Add(self.protected,0,wx.EXPAND|wx.BOTTOM,5)
        left.SetSizer(setup);left.FitInside()
        right=wx.BoxSizer(wx.VERTICAL)
        comparison=wx.BoxSizer(wx.HORIZONTAL);comparison.Add(wx.StaticText(right_panel,label='Compare'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.view_mode=wx.Choice(right_panel,choices=list(Preview.DISPLAY_MODES));self.view_mode.SetSelection(0)
        self.view_mode.SetToolTip('Presentation only; switching views keeps the current preview and native validation.')
        self.view_mode.Bind(wx.EVT_CHOICE,lambda e:self.canvas.set_display_mode(self.view_mode.GetStringSelection()))
        comparison.Add(self.view_mode,0);right.Add(comparison,0,wx.EXPAND|wx.BOTTOM,6)
        self.results_splitter=wx.SplitterWindow(right_panel,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        self.canvas=Preview(self.results_splitter,board,self.guard);self.canvas.SetMinSize((250,160))
        self.details=wx.ListCtrl(self.results_splitter,style=wx.LC_REPORT)
        for index,(label,width) in enumerate([('Net',230),('Layer',75),('Before mm',90),('After mm',90),('Shorter mm',95),('Segments',110),('Review / preserved',330)]):self.details.InsertColumn(index,label,width=width)
        self.details.SetMinSize((180,100))
        self.results_splitter.SetMinimumPaneSize(100);self.results_splitter.SplitHorizontally(self.canvas,self.details,-170);self.results_splitter.SetSashGravity(1)
        right.Add(self.results_splitter,1,wx.EXPAND)
        actions=wx.BoxSizer(wx.HORIZONTAL);self.exclude_button=wx.Button(right_panel,label='Exclude selected proposals');self.exclude_button.Disable();actions.Add(self.exclude_button,0,wx.RIGHT,8)
        self.locate_button=wx.Button(right_panel,label='Locate in PCB');self.locate_button.Disable();actions.Add(self.locate_button,0,wx.RIGHT,8)
        hint=wx.StaticText(right_panel,label='Click to focus. Ctrl/Shift selects several.');hint.Wrap(250);actions.Add(hint,1,wx.ALIGN_CENTER_VERTICAL)
        right.Add(actions,0,wx.EXPAND|wx.TOP,5)
        self.details.Bind(wx.EVT_LIST_ITEM_SELECTED,self._review_selected);self.details.Bind(wx.EVT_LIST_ITEM_DESELECTED,self._review_selection_changed)
        self.details.Bind(wx.EVT_MOTION,self._review_tooltip);self.exclude_button.Bind(wx.EVT_BUTTON,self.exclude_selected)
        self.locate_button.Bind(wx.EVT_BUTTON,self.locate_in_editor)
        right_panel.SetSizer(right)
        self.settings_splitter.SetMinimumPaneSize(250);self.settings_splitter.SplitVertically(left,right_panel,300);self.settings_splitter.SetSashGravity(0)
        root.Add(self.settings_splitter,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.status=wx.StaticText(panel,label='Select tracks or choose another scope. Preview is read-only; native DRC is required before Apply.');root.Add(self.status,0,wx.EXPAND|wx.ALL,12)
        row=wx.BoxSizer(wx.HORIZONTAL)
        help_button=wx.Button(panel,label='Help');row.Add(help_button);self.undo_button=wx.Button(panel,label='Undo');self.redo_button=wx.Button(panel,label='Redo');row.Add(self.undo_button,0,wx.LEFT,8);row.Add(self.redo_button,0,wx.LEFT,8);row.AddStretchSpacer()
        preview=wx.Button(panel,label='Preview');self.validate_button=wx.Button(panel,label='Validate candidate');self.apply_button=wx.Button(panel,label='Apply refinement')
        for button in (preview,self.validate_button,self.apply_button):row.Add(button,0,wx.LEFT,8)
        root.Add(row,0,wx.EXPAND|wx.ALL,12);panel.SetSizer(root)
        for button in (self.validate_button,self.apply_button,self.undo_button,self.redo_button):button.Disable()
        self.search.Bind(wx.EVT_TEXT,self.filter_nets)
        self.operation.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,self._operation_changed)
        for control in (self.scope,self.netlist,self.groups,self.layers,self.deviation,self.shortening,self.center_shift,self.protected):
            control.Bind(wx.EVT_CHOICE if control is self.scope else wx.EVT_CHECKLISTBOX if isinstance(control,wx.CheckListBox) else wx.EVT_TEXT,self.invalidate)
        preview.Bind(wx.EVT_BUTTON,self.on_preview);self.validate_button.Bind(wx.EVT_BUTTON,self.on_validate);self.apply_button.Bind(wx.EVT_BUTTON,self.on_apply)
        self.undo_button.Bind(wx.EVT_BUTTON,self.undo);self.redo_button.Bind(wx.EVT_BUTTON,self.redo)
        help_button.Bind(wx.EVT_BUTTON,lambda e:wx.LaunchDefaultBrowser(Path(__file__).with_name('help.html').as_uri()))
        self.Bind(wx.EVT_HELP,lambda e:wx.LaunchDefaultBrowser(Path(__file__).with_name('help.html').as_uri()))
        area=wx.Display(self).GetClientArea()
        self.SetSize((min(self.GetSize().width,area.width-24),min(self.GetSize().height,area.height-32)))
        self.CentreOnScreen()
        self._operation_changed()
        self.saved_refresh=SavedBoardRefresh(self,board.GetFileName(),self._invalidate_saved,
                                             self._refresh_saved,lambda:not self._busy)
        self.editor_timer=wx.Timer(self)
        self.Bind(wx.EVT_TIMER,self._follow_editor_selection,self.editor_timer)
        self.Bind(wx.EVT_ACTIVATE,self._check_live_board)
        self.Bind(wx.EVT_WINDOW_DESTROY,self._stop_editor_timer)
        self.editor_timer.Start(500)
    def _operation_changed(self,event=None):
        center=self.operation.GetSelection()==1
        self.deviation.Enable(not center);self.shortening.Enable(not center);self.center_shift.Enable(center)
        for control in self.jog_controls:control.Show(not center)
        self.center_caption.Show(center);self.center_shift.Show(center)
        self.apply_button.SetLabel('Apply contact centering' if center else 'Apply refinement')
        self.apply_button.SetMinSize(self.apply_button.GetBestSize())
        self.setup_window.Layout();self.setup_window.FitInside();self.apply_button.GetParent().Layout()
        self.invalidate()
        self.status.SetLabel('Center contacts: only unambiguous, already touching same-net pads/vias are eligible. Preview first.' if center else 'Select routing, then Preview. Validate before Apply.')
        if event:event.Skip()
    def _populate_review(self):
        self.details.DeleteAllItems();self._table_rows=[];self._last_tooltip=None
        self._proposal_source_ids=[]
        self.canvas.set_plan(self.review)
        if self.review is None:return
        by_proposal={}
        unattributed=[]
        for finding in self.review.evidence.get('finding_delta',[]):
            description=f"{finding['reason']} · "+', '.join(finding['item_uuids'])
            if not finding['proposal_indices']:
                unattributed.append(description)
            for proposal in finding['proposal_indices']:
                by_proposal.setdefault(proposal,[]).append(description)
        for index,change in enumerate(self.review.changes):
            self._proposal_source_ids.append(frozenset(refiner.uid(item) for item in change.originals))
            metrics=refiner.change_metrics(change,pcbnew)
            row=self.details.InsertItem(self.details.GetItemCount(),change.net);self._table_rows.append(index)
            reason='Proposed contact centering; pads/vias stay fixed' if self.review.settings.get('mode')=='center contacts' else f"Proposed; {metrics['removed_segments']} segments removed"
            if index in by_proposal:
                reason='Native DRC: '+' | '.join(by_proposal[index])
            cells=[self.board.GetLayerName(change.layer),f"{metrics['before_mm']:.4f}",f"{metrics['after_mm']:.4f}",f"{metrics['shortening_mm']:.4f}",f'{len(change.before)-1} → {len(change.after)-1}',reason]
            for column,value in enumerate(cells,1):self.details.SetItem(row,column,value)
        notes=list(self.review.skipped)+self._excluded_notices
        notes.extend(('Unattributed native finding',description) for description in unattributed)
        evidence=self.review.evidence
        if evidence.get('connectivity')=='changed':
            for partition in evidence['removed_partitions']:
                notes.append(('Connectivity before',', '.join(partition)))
            for partition in evidence['added_partitions']:
                notes.append(('Connectivity after',', '.join(partition)))
        for net,reason in notes:
            row=self.details.InsertItem(self.details.GetItemCount(),net);self._table_rows.append(None)
            self.details.SetItem(row,6,reason)
        self._last_editor_selection=None
        self._review_selection_changed()

    def _review_summary(self):
        changes=self.review.changes if self.review else ()
        metrics=[refiner.change_metrics(change,pcbnew) for change in changes]
        if self.review and self.review.settings.get('mode')=='center contacts':
            return (f"{len(changes)} proposed contact repairs · {sum(row['after_mm']-row['before_mm'] for row in metrics):+.4f} mm length change · "
                    f"{len(self.review.skipped)} preserved · {len(self._excluded_notices)} excluded.")
        return (f"{len(changes)} proposed chains · {sum(row['shortening_mm'] for row in metrics):.4f} mm shorter · "
                f"{sum(row['removed_segments'] for row in metrics)} segments removed · "
                f"{len(self.review.skipped) if self.review else 0} preserved · {len(self._excluded_notices)} excluded.")

    def _selected_changes(self):
        result=set();row=self.details.GetNextItem(-1,wx.LIST_NEXT_ALL,wx.LIST_STATE_SELECTED)
        while row!=-1:
            if row<len(self._table_rows) and self._table_rows[row] is not None:result.add(self._table_rows[row])
            row=self.details.GetNextItem(row,wx.LIST_NEXT_ALL,wx.LIST_STATE_SELECTED)
        return result

    def _review_selection_changed(self,event=None):
        selected=self._selected_changes() if self.review else set()
        self.exclude_button.Enable(bool(selected))
        self.locate_button.Enable(len(selected)==1)
        if event:event.Skip()

    def _editor_board(self):
        '''Return the hosting editor board only when it still owns this window.'''
        if not self.guard():
            return None
        editor=pcbnew.GetBoard()
        if editor is not None and refiner.board_identity(editor)==refiner.board_identity(self.board):
            return editor
        return None

    def locate_in_editor(self,event=None):
        try:
            if self._editor_board() is None:
                raise ValueError('Open Trace Refiner from PCB Editor to locate items on the board.')
            if not self.review or len(indices:=self._selected_changes())!=1:
                raise ValueError('Select one proposal to locate its original track.')
            if not self._review_is_current():
                raise ValueError('PCB or rules changed. Preview again before locating a proposal.')
            index=next(iter(indices))
            change=self.review.changes[index]
            wanted=self._proposal_source_ids[index]
            current=[item for item in self.board.GetTracks() if refiner.uid(item) in wanted]
            if len(current)!=len(wanted):
                raise ValueError('Original tracks no longer resolve uniquely. Preview again.')
            pcbnew.FocusOnItem(current[0])
            self.status.SetLabel(f'Located original {change.net} route in the originating PCB Editor.')
        except Exception as exc:self.error(exc)

    def _follow_editor_selection(self,event=None):
        if self._busy or not self.review or self._editor_board() is None:
            return
        selected=frozenset(refiner.uid(item) for item in pcbnew.GetCurrentSelection())
        if selected==self._last_editor_selection:
            return
        self._last_editor_selection=selected
        matches=[index for index,identifiers in enumerate(self._proposal_source_ids)
                 if selected & identifiers]
        if len(matches)==1:
            self.canvas.focus_change(matches[0])
        elif self.canvas.active_change is not None:
            self.canvas.active_change=None
            self.canvas.Refresh()

    def _review_is_current(self):
        return (self.review.fingerprint==refiner.snapshot(self.board,pcbnew)
                and self.review.rules==refiner.rule_hash(self.board))

    def _invalidate_saved(self):
        self.invalidate()
        self.status.SetLabel('Saved PCB or rules changed. Refreshing board context…')

    def _refresh_saved(self):
        # A detached test/CLI window has no live editor source to inspect.
        if self._editor_board() is None:
            self.status.SetLabel('Saved sources changed. Reopen Trace Refiner from PCB Editor.')
            return
        self._refresh_board_context()

    def _refresh_board_context(self):
        self.canvas.capture_context()
        self.remember_nets()
        self.nets=sorted({t.GetNetname() for t in self.board.GetTracks() if t.GetNetname()})
        self._show_filtered_nets()
        options=((self.groups,sorted({t.GetNetClassName() for t in self.board.GetTracks()})),
                 (self.layers,[self.board.GetLayerName(layer) for layer in self.board.GetEnabledLayers().CuStack()]))
        for control,values in options:
            checked=set(control.GetCheckedStrings())
            if list(control.GetStrings())!=values:
                # Retain stale checks until explicit user review. Losing a
                # checked layer would silently broaden scope to all layers.
                control.Set([*values,*sorted(checked-set(values))])
                control.SetCheckedStrings(list(checked))
        self.canvas.Refresh()
        self.status.SetLabel('PCB context refreshed. Preview again with the existing settings.')

    def _check_live_board(self,event):
        event.Skip()
        if not event.GetActive() or self._busy or self._editor_board() is None:
            return
        if self.review is not None and not self._review_is_current():
            self.invalidate()
            self._refresh_board_context()

    def _stop_editor_timer(self,event):
        if event.GetEventObject() is self:
            self.editor_timer.Stop()
        event.Skip()

    def _review_selected(self,event):
        row=event.GetIndex()
        if row<len(self._table_rows) and self._table_rows[row] is not None:self.canvas.focus_change(self._table_rows[row])
        self._review_selection_changed(event)

    def _review_tooltip(self,event):
        row,_=self.details.HitTest(event.GetPosition())
        value=(self.details.GetItemText(row)+'\n'+self.details.GetItemText(row,6)) if row>=0 else None
        if value!=self._last_tooltip:
            self.details.SetToolTip(value or 'Select proposals to inspect or exclude. Preserved notices are not proposals.');self._last_tooltip=value
        event.Skip()

    def exclude_selected(self,event=None):
        if self.review is None:return
        selected=self._selected_changes()
        if not selected:return
        try:
            self.require_board()
            excluded=[self.review.changes[index] for index in sorted(selected)]
            self.review=refiner.subset_plan(self.review,[index for index in range(len(self.review.changes)) if index not in selected])
            self._excluded_notices.extend((change.net,'Excluded by review; original copper retained.') for change in excluded)
            self._populate_review();self.apply_button.Disable();self.validate_button.Enable(bool(self.review.changes))
            self.status.SetLabel(self._review_summary()+(' Validate this subset again before Apply.' if self.review.changes else 'No proposals remain. Preview again to start a new review.'))
        except Exception as exc:self.error(exc)

    def require_board(self):
        if not self.guard():raise ValueError('Originating board closed or replaced. Reopen Trace Refiner.')
    def remember_nets(self):
        visible=set(self.netlist.GetStrings());self.checked.difference_update(visible);self.checked.update(self.netlist.GetCheckedStrings())
    def filter_nets(self,event):
        self.remember_nets()
        self._show_filtered_nets()

    def _show_filtered_nets(self):
        query=self.search.GetValue().casefold()
        values=[name for name in self.nets if query in name.casefold()]
        self.netlist.Set(values)
        self.netlist.SetCheckedStrings([name for name in values if name in self.checked])
    def settings(self):
        self.remember_nets()
        return dict(scope=['selected tracks','selected nets','whole board','net filters','groups'][self.scope.GetSelection()],nets=sorted(self.checked),layers=list(self.layers.GetCheckedStrings()),groups=list(self.groups.GetCheckedStrings()),max_deviation=float(self.deviation.GetValue()),max_shortening=float(self.shortening.GetValue()),protected=self.protected.GetValue(),mode='center contacts' if self.operation.GetSelection()==1 else 'refine',max_center_shift=float(self.center_shift.GetValue()))
    def invalidate(self,event=None):
        self.review=None;self.canvas.set_plan(None);self.details.DeleteAllItems();self._table_rows=[];self._proposal_source_ids=[];self._excluded_notices=[];self.validate_button.Disable();self.apply_button.Disable();self.exclude_button.Disable();self.locate_button.Disable()
        self.status.SetLabel('Inputs changed. Preview again.')
    def error(self,exc):self.status.SetLabel(str(exc));wx.MessageBox(str(exc),'Trace Refiner',wx.OK|wx.ICON_ERROR,parent=self)
    def on_preview(self,event=None):
        self.invalidate();self.details.DeleteAllItems()
        # Generic progress avoids native task-dialog teardown during wx repaints.
        self._busy=True
        progress=wx.GenericProgressDialog('Preview trace refinement','Inspecting native routing…',parent=self,style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
        try:
            self.require_board()
            def pulse(label):
                return self.guard() and progress.Pulse(label)[0]
            stamp=source_stamp(self.board.GetFileName())
            review=propose(self.board,pcbnew,self.settings(),progress=pulse)
            self.require_board()
            if source_stamp(self.board.GetFileName())!=stamp:
                raise ValueError('Saved PCB or rules changed during preview. Preview again.')
            self.review=review
            self.canvas.capture_context()
            self._populate_review()
            self.validate_button.Enable(bool(self.review.changes));self.canvas.Refresh()
            self.status.SetLabel(self._review_summary()+' Validate before Apply. Protected/locked/grouped items are untouched.')
        except Exception as exc:self.error(exc)
        finally:
            progress.Destroy()
            self._busy=False
    def on_validate(self,event=None):
        if self.review is None or not self.review.changes:return
        self._busy=True
        progress=wx.GenericProgressDialog('Validate trace refinement','Preparing native snapshot…',parent=self,style=wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
        try:
            self.require_board();review=self.review
            def pulse(label):
                if not self.guard():return False
                return progress.Pulse(label)[0]
            validate_detached(self.board,pcbnew,review,progress=pulse)
            if self.review is not review:
                raise ValueError('The old preview was cleared during validation. Preview again.')
            self.apply_button.Enable(True);self.status.SetLabel(f'{len(review.changes)} chains validated: native terminal connectivity unchanged; no new DRC findings. Review, then Apply.')
        except Exception as exc:
            self.apply_button.Disable()
            self._populate_review()
            self.error(exc)
        finally:
            progress.Destroy()
            self._busy=False
    def on_apply(self,event=None):
        try:
            self.require_board()
            if self.review is None or self.review.settings!=self.settings():raise ValueError('Preview changed. Validate again.')
            tx=Transaction(self.board,pcbnew,self.review).redo();self.transactions.append(tx);self.redos=[];self.invalidate();self.canvas.capture_context();self.undo_button.Enable();self.redo_button.Disable();pcbnew.Refresh()
            self.status.SetLabel('Refinement applied. Inspect the board, refill zones and run final DRC before saving. Undo is available in this window.')
        except Exception as exc:self.error(exc)
    def undo(self,event=None):
        if not self.transactions:return
        try:
            self.require_board();tx=self.transactions[-1];tx.undo();self.transactions.pop();self.redos.append(tx);self.invalidate();self.canvas.capture_context();self.undo_button.Enable(bool(self.transactions));self.redo_button.Enable();pcbnew.Refresh()
        except Exception as exc:self.error(exc)
    def redo(self,event=None):
        if not self.redos:return
        try:
            self.require_board();tx=self.redos[-1];tx.redo();self.redos.pop();self.transactions.append(tx);self.invalidate();self.canvas.capture_context();self.undo_button.Enable();self.redo_button.Enable(bool(self.redos));pcbnew.Refresh()
        except Exception as exc:self.error(exc)
