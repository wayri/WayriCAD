"""Minimal native UI: choose scope, preview, apply; details stay on demand."""
from pathlib import Path
from copy import deepcopy
from .options_ui import OptionsDialog
import pcbnew
import wx
from .placement import DEFAULTS, plan, apply, text_geometry, polygons, item_id


class LabelPreview(wx.Panel):
    def __init__(self,parent,board):
        self.source_guard=lambda:True
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self._geometry_plan=None;self._glyphs={};self.board=board;self.preview=None;self.back=False;self.zoom=1.;self.pan=[0.,0.];self.drag=None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetToolTip('Wheel: zoom. Drag: pan. Double-click: fit. Boxes show checked native text envelopes; teal marks proposed labels and guides.')
        self.Bind(wx.EVT_PAINT,self.paint);self.Bind(wx.EVT_SIZE,lambda e:(self.Refresh(),e.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL,self.wheel);self.Bind(wx.EVT_LEFT_DOWN,self.down)
        self.Bind(wx.EVT_LEFT_UP,self.up);self.Bind(wx.EVT_MOTION,self.motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))
        self.Bind(wx.EVT_LEFT_DCLICK,self.fit)
    def fit(self,event=None):self.zoom=1.;self.pan=[0.,0.];self.Refresh()
    def wheel(self,event):self.zoom=max(.2,min(20,self.zoom*(1.2 if event.GetWheelRotation()>0 else 1/1.2)));self.Refresh()
    def down(self,event):self.drag=event.GetPosition();self.CaptureMouse()
    def up(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()
    def motion(self,event):
        if self.drag is not None and event.Dragging():
            point=event.GetPosition();self.pan[0]+=point.x-self.drag.x;self.pan[1]+=point.y-self.drag.y;self.drag=point;self.Refresh()
    def paint(self,event):
        self.draw(wx.AutoBufferedPaintDC(self),self.GetClientSize())
    def draw(self,dc,size):
        dc.SetBackground(wx.Brush('#f3f7f8'));dc.Clear()
        if not self.source_guard():
            dc.DrawText('The originating board was closed or replaced. Reopen this plugin.',12,12);return
        box=self.board.GetBoardEdgesBoundingBox();w,h=size
        if box.GetWidth()<=0 or box.GetHeight()<=0:return
        scale=min((w-60)/box.GetWidth(),(h-60)/box.GetHeight())*self.zoom
        cx=(box.GetLeft()+box.GetRight())/2;cy=(box.GetTop()+box.GetBottom())/2
        def point(x,y):return (round(w/2+(-1 if self.back else 1)*(x-cx)*scale+self.pan[0]),round(h/2+(y-cy)*scale+self.pan[1]))
        def rectangle(b,colour,fill=None):
            a=point(b.GetLeft(),b.GetTop());z=point(b.GetRight(),b.GetBottom())
            dc.SetPen(wx.Pen(colour,1));dc.SetBrush(wx.Brush(fill) if fill else wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(min(a[0],z[0]),min(a[1],z[1]),max(1,abs(z[0]-a[0])),max(1,abs(z[1]-a[1])))
        outline=pcbnew.SHAPE_POLY_SET()
        if self.board.GetBoardPolygonOutlines(outline,False):
            dc.SetPen(wx.Pen('#405665',2));dc.SetBrush(wx.TRANSPARENT_BRUSH)
            for i in range(outline.OutlineCount()):
                ring=outline.COutline(i);dc.DrawLines([point(ring.CPoint(j).x,ring.CPoint(j).y) for j in range(ring.PointCount())]+[point(ring.CPoint(0).x,ring.CPoint(0).y)])
                for k in range(outline.HoleCount(i)):
                    ring=outline.CHole(i,k);dc.DrawLines([point(ring.CPoint(j).x,ring.CPoint(j).y) for j in range(ring.PointCount())]+[point(ring.CPoint(0).x,ring.CPoint(0).y)])
        silk=pcbnew.B_SilkS if self.back else pcbnew.F_SilkS
        mask=pcbnew.B_Mask if self.back else pcbnew.F_Mask
        moving={item_id(c.item) for c in self.preview.changes} if self.preview else set()
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer()==silk and isinstance(drawing,pcbnew.PCB_SHAPE) and drawing.GetShape()==pcbnew.SHAPE_T_SEGMENT:
                dc.SetPen(wx.Pen('#82969d',max(1,round(drawing.GetWidth()*scale))));a,b=drawing.GetStart(),drawing.GetEnd();dc.DrawLine(*point(a.x,a.y),*point(b.x,b.y))
            if drawing.GetLayer()==silk and isinstance(drawing,pcbnew.PCB_TEXT) and item_id(drawing) not in moving:rectangle(drawing.GetBoundingBox(),'#aab5be')
        for fp in self.board.GetFootprints():
            if fp.IsFlipped()==self.back:
                hull=fp.GetBoundingHull()
                dc.SetPen(wx.Pen('#9babb2'));dc.SetBrush(wx.TRANSPARENT_BRUSH)
                for i in range(hull.OutlineCount()):
                    ring=hull.COutline(i);pts=[point(ring.CPoint(j).x,ring.CPoint(j).y) for j in range(ring.PointCount())]
                    if pts:dc.DrawLines(pts+[pts[0]])
            for pad in fp.Pads():
                if pad.IsOnLayer(mask):rectangle(pad.GetBoundingBox(),'#ad8639','#e8d5a6')
            for text in fp.GetFields():
                if text.GetLayer()==silk and text.IsVisible() and item_id(text) not in moving:rectangle(text.GetBoundingBox(),'#aab5be')
        if self.preview:
            gc=wx.GraphicsContext.Create(dc)
            for change in self.preview.changes:
                if change.item.GetLayer()!=silk:continue
                rectangle(change.box,'#008a7d','#e2f4ef')
                if self._geometry_plan is not self.preview:
                    self._glyphs={};self._geometry_plan=self.preview
                key=item_id(change.item)
                if key not in self._glyphs:
                    _,shape=text_geometry(change.item,change.after,pcbnew)
                    self._glyphs[key]=polygons(shape)
                # Board-scale native glyph polygons retain rotation, mirroring,
                # font, stroke and knockout; never enlarge small screen labels.
                if gc:
                    gc.SetPen(wx.TRANSPARENT_PEN);gc.SetBrush(wx.Brush('#00685f'))
                    path=gc.CreatePath()
                    for outer,holes in self._glyphs[key]:
                        for ring in [outer,*holes]:
                            if not ring:continue
                            path.MoveToPoint(*point(*ring[0]))
                            for vertex in ring[1:]:path.AddLineToPoint(*point(*vertex))
                            path.CloseSubpath()
                    gc.DrawPath(path,wx.ODDEVEN_RULE)
                guide=getattr(change,'leader_path',())
                if not guide and change.leader:
                    x1,y1,x2,y2,stroke,layer=change.leader;guide=((x1,y1),(x2,y2))
                if guide:
                    stroke=change.leader[4] if change.leader else change.thickness
                    dc.SetPen(wx.Pen('#008a7d',max(1,round(stroke*scale))))
                    for a,b in zip(guide,guide[1:]):dc.DrawLine(*point(*a),*point(*b))
            if gc:gc.Flush()
        dc.SetFont(wx.Font(wx.FontInfo(10)));dc.SetTextForeground('#405665')
        dc.DrawText('Bottom view' if self.back else 'Top view',12,10)
        dc.DrawText('Teal: proposed labels / guides    Gold: pads    Grey: existing text envelopes',12,h-25)


class SilkscreenFrame(wx.Frame):
    def __init__(self,parent,board,board_guard=None):
        self.board_guard=board_guard or (lambda:True)
        super().__init__(parent,title='WayriCAD Silkscreen Label Placer',size=(1100,760))
        self.SetMinSize((850,600));self.board=board;self.settings=deepcopy(DEFAULTS);self.preview=None;self.transactions=[];self.redos=[]
        panel=wx.Panel(self);root=wx.BoxSizer(wx.VERTICAL)
        title=wx.StaticText(panel,label='Arrange silkscreen labels');title.SetFont(title.GetFont().Bold().Larger());root.Add(title,0,wx.ALL,12)
        row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(panel,label='Place labels for'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.scope=wx.Choice(panel,choices=['Selected parts / text','Whole board']);self.scope.SetSelection(0 if any(f.IsSelected() or any(p.IsSelected() for p in f.Pads()) for f in board.GetFootprints()) or any(isinstance(t,pcbnew.PCB_TEXT) and t.IsSelected() for t in board.GetDrawings()) else 1)
        self.scope.SetToolTip('Selected scope includes selected parts, parts containing selected pads, and selected board text. Whole board checks both sides.')
        row.Add(self.scope,0,wx.RIGHT,10);options=wx.Button(panel,label='Options…');row.Add(options,0)
        row.AddStretchSpacer();self.side=wx.Choice(panel,choices=['Top view','Bottom view']);self.side.SetSelection(0);row.Add(self.side,0,wx.RIGHT,8)
        fit=wx.Button(panel,label='Fit',size=(55,-1));row.Add(fit,0);root.Add(row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        self.canvas=LabelPreview(panel,board);self.canvas.source_guard=self.board_guard;root.Add(self.canvas,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.status=wx.StaticText(panel,label='Preview visible reference labels. Hidden and locked items stay untouched.');root.Add(self.status,0,wx.EXPAND|wx.ALL,12)
        self.details=wx.CollapsiblePane(panel,label='Review details');self.list=wx.ListCtrl(self.details.GetPane(),style=wx.LC_REPORT)
        self.list.InsertColumn(0,'Label',width=150);self.list.InsertColumn(1,'Result',width=730);self.list.SetMinSize((-1,140))
        ds=wx.BoxSizer(wx.VERTICAL);ds.Add(self.list,1,wx.EXPAND);self.details.GetPane().SetSizer(ds);root.Add(self.details,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.details.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda e:self.Layout())
        buttons=wx.BoxSizer(wx.HORIZONTAL);help_button=wx.Button(panel,label='Help');buttons.Add(help_button,0)
        self.undo_button=wx.Button(panel,label='Undo');self.redo_button=wx.Button(panel,label='Redo');buttons.Add(self.undo_button,0,wx.LEFT,8);buttons.Add(self.redo_button,0,wx.LEFT,8)
        buttons.AddStretchSpacer();preview_button=wx.Button(panel,label='Preview');self.apply_button=wx.Button(panel,label='Apply labels')
        buttons.Add(preview_button,0,wx.RIGHT,8);buttons.Add(self.apply_button,0);root.Add(buttons,0,wx.EXPAND|wx.ALL,12)
        panel.SetSizer(root);self.apply_button.Disable();self.undo_button.Disable();self.redo_button.Disable()
        options.Bind(wx.EVT_BUTTON,self.options);self.scope.Bind(wx.EVT_CHOICE,self.invalidate)
        self.side.Bind(wx.EVT_CHOICE,lambda e:(setattr(self.canvas,'back',self.side.GetSelection()==1),self.canvas.Refresh()))
        fit.Bind(wx.EVT_BUTTON,self.canvas.fit);preview_button.Bind(wx.EVT_BUTTON,self.on_preview)
        self.apply_button.Bind(wx.EVT_BUTTON,self.on_apply);self.undo_button.Bind(wx.EVT_BUTTON,self.undo);self.redo_button.Bind(wx.EVT_BUTTON,self.redo)
        help_button.Bind(wx.EVT_BUTTON,lambda e:wx.LaunchDefaultBrowser(Path(__file__).with_name('help.html').as_uri()))
    def require_board(self):
        if not self.board_guard():raise ValueError('The originating board was closed or replaced. Reopen this plugin.')
    def current_settings(self):return dict(self.settings,selected_only=self.scope.GetSelection()==0)
    def invalidate(self,event=None):
        self.preview=None;self.canvas.preview=None;self.apply_button.Disable();self.canvas.Refresh();self.status.SetLabel('Settings changed. Preview again before applying.')
    def options(self,event):
        dialog=OptionsDialog(self,self.settings)
        try:
            while dialog.ShowModal()==wx.ID_OK:
                try:
                    self.settings=dialog.result();self.invalidate();break
                except ValueError as exc:wx.MessageBox(str(exc),'Label options',wx.OK|wx.ICON_ERROR,parent=dialog)
        finally:dialog.Destroy()
    def on_preview(self,event=None):
        self.invalidate();self.list.DeleteAllItems()
        try:
            self.require_board()
            self.status.SetLabel('Checking text, pads, holes and guide lines…');self.status.Update()
            progress=wx.ProgressDialog('Arrange silkscreen labels','Preparing geometry…',maximum=100,parent=self,style=wx.PD_AUTO_HIDE|wx.PD_APP_MODAL|wx.PD_CAN_ABORT|wx.PD_ELAPSED_TIME)
            def advance(done,total,label):
                if not self.board_guard():return False
                keep_going,_=progress.Update(min(99,round(100*done/max(1,total))),str(label))
                return keep_going
            try:
                with wx.BusyCursor():self.preview=plan(self.board,pcbnew,self.current_settings(),progress=advance)
            finally:progress.Destroy()
            self.canvas.preview=self.preview
            for change in self.preview.changes:
                row=self.list.InsertItem(self.list.GetItemCount(),change.label);styles=', '.join(name for name,on in zip(('bold','italic','knockout'),change.after[7:10]) if on)
                self.list.SetItem(row,1,f'{pcbnew.ToMM(change.after[4]):.2f} mm · {change.after[2]:g}°'+(' · '+styles if styles else '')+(' · guide line' if change.leader else ''))
            for label in self.preview.rejected:
                row=self.list.InsertItem(self.list.GetItemCount(),'Unresolved');self.list.SetItem(row,0,str(label[0]));self.list.SetItem(row,1,str(label[1]))
            for label in self.preview.skipped:
                row=self.list.InsertItem(self.list.GetItemCount(),'Preserved');self.list.SetItem(row,0,str(label[0]));self.list.SetItem(row,1,str(label[1]))
            leaders=sum(bool(c.leader) for c in self.preview.changes)
            self.status.SetLabel(f"{self.preview.stats.get('placed',len(self.preview.changes))}/{self.preview.stats.get('eligible',len(self.preview.changes)+len(self.preview.rejected))} labels placed · {len(self.preview.changes)} changes · {leaders} guides · {len(self.preview.rejected)} unresolved. Review, then Apply.")
            self.apply_button.Enable(bool(self.preview.changes));self.canvas.Refresh()
        except Exception as exc:self.status.SetLabel(str(exc))
    def on_apply(self,event=None):
        try:
            self.require_board()
            if self.preview is None:raise ValueError('Create a preview first.')
            if self.preview.settings!=self.current_settings():raise ValueError('Settings changed. Preview again.')
            transaction=apply(self.board,pcbnew,self.preview);self.transactions.append(transaction);self.redos=[]
            count=len(self.preview.changes);self.invalidate();self.undo_button.Enable(True);self.redo_button.Disable()
            pcbnew.Refresh();self.status.SetLabel(f'Applied {count} labels. Run KiCad DRC and inspect the silkscreen before saving.')
        except Exception as exc:
            self.apply_button.Disable();self.status.SetLabel(str(exc));wx.MessageBox(str(exc),'Labels not applied',wx.OK|wx.ICON_ERROR)
    def undo(self,event=None):
        if not self.transactions:return
        try:
            self.require_board()
            transaction=self.transactions[-1];transaction.undo();self.transactions.pop();self.redos.append(transaction);self.invalidate()
            self.undo_button.Enable(bool(self.transactions));self.redo_button.Enable(True);pcbnew.Refresh();self.status.SetLabel('Restored the previous labels and removed their guide lines.')
        except Exception as exc:wx.MessageBox(str(exc),'Undo failed',wx.OK|wx.ICON_ERROR)
    def redo(self,event=None):
        if not self.redos:return
        try:
            self.require_board()
            transaction=self.redos[-1];transaction.redo();self.redos.pop();self.transactions.append(transaction);self.invalidate()
            self.undo_button.Enable(True);self.redo_button.Enable(bool(self.redos));pcbnew.Refresh();self.status.SetLabel('Reapplied the reviewed labels and guide lines.')
        except Exception as exc:wx.MessageBox(str(exc),'Redo failed',wx.OK|wx.ICON_ERROR)
