"""Local board-coordinate canvas with neutral styling and native pad geometry."""
import math
import wx
from .geometry import polygons


class GeometryPreview(wx.Panel):
    def __init__(self,parent,empty_text="Click a pad, via or track to select its net.",compact=False):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.compact=bool(compact)
        self._scene_bitmap=None;self._scene_key=None;self._scene_revision=0
        self.empty_text=empty_text
        self.lines=[];self.points=[];self.pads=[];self.outlines=[]
        self.point_diameters=[];self.line_widths=[];self.pad_sizes=[];self.point_drills=[];self.rejected=[]
        self.context_lines=[];self.context_pads=[];self.context_rings=[];self.context_vias=[];self.footprint_lines=[];self.references=[]
        self.focus_points=[];self.show_grid=False
        self._context_identity={};self._highlight_nets=frozenset();self._highlight_ids=frozenset()
        self._highlight_indices={};self._highlight_bounds=[];self._view_bounds=None
        self.zoom=1.;self.pan=[0.,0.];self.drag=None;self.pick=None;self.project=lambda p:(0,0)
        self.on_net_select=None;self.net_targets=[];self.cursor=None;self.probes=[];self.click_start=None
        self.unproject=lambda p:None
        self.SetMinSize((180,140) if self.compact else (320,280));self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.SetToolTip('Wheel: zoom. Drag: pan. Double-click: fit. Click a via: inspect coordinates. Arc tracks use conservative envelopes.')
        for event,handler in ((wx.EVT_PAINT,self.on_paint),(wx.EVT_MOUSEWHEEL,self.wheel),(wx.EVT_LEFT_DOWN,self.down),(wx.EVT_LEFT_UP,self.up),(wx.EVT_MOTION,self.motion),(wx.EVT_LEFT_DCLICK,self.fit)):
            self.Bind(event,handler)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,self.capture_lost)

    def invalidate_scene(self):
        """Discard cached pixels after an in-place edit to preview geometry."""
        self._scene_revision+=1
        self._scene_bitmap=None
        self._scene_key=None

    def _cache_key(self):
        names=('lines','points','pads','outlines','point_diameters','line_widths',
               'pad_sizes','point_drills','rejected','context_lines','context_pads',
               'context_rings','context_vias','footprint_lines','references')
        return (tuple(self.GetClientSize()),self._scene_revision,self.zoom,
                tuple(self.pan),self.show_grid,self.pick,self.compact,self.empty_text,tuple(self.focus_points),
                self._highlight_nets,self._highlight_ids,tuple(self._view_bounds or ()),
                tuple((id(getattr(self,name)),len(getattr(self,name))) for name in names))

    def set_geometry(self,lines=(),points=(),pads=(),outlines=(),point_diameters=(),line_widths=(),pad_sizes=(),point_drills=(),rejected=(),pad_shapes=()):
        for name,value in locals().copy().items():
            if name!='self':setattr(self,name,list(value))
        self.pick=None;self.probes=[];self._view_bounds=None;self.invalidate_scene();self.Refresh()

    def set_board_context(self,other):
        """Reuse an extracted board snapshot without calling the native API again.

        Shared context lists are read-only snapshots; each view keeps its own
        fit, camera, candidate geometry and inspection state.
        """
        for name in ('context_lines','context_pads','context_rings','context_vias',
                     'footprint_lines','references','focus_points','net_targets','_context_identity'):
            setattr(self,name,getattr(other,name))
        self.set_highlight()
        self.probes=[];self.invalidate_scene();self.Refresh()

    def set_board(self,board,api):
        mm=api.ToMM
        self.context_lines=[];self.context_pads=[];self.context_rings=[];self.context_vias=[];self.footprint_lines=[];self.references=[]
        self.focus_points=[];self.net_targets=[];self.probes=[]
        self._context_identity={};self._view_bounds=None
        def identity(item):
            value=getattr(item,'m_Uuid',None)
            return str(value.AsString() if hasattr(value,'AsString') else value or '').casefold()
        def tag(kind,item,owner=None):
            self._context_identity.setdefault(kind,[]).append((str(getattr(item,'GetNetname',lambda:'')()),identity(item),identity(owner)))
        selected_points=[]
        for fp in board.GetFootprints():
            positions=[]
            for pad in fp.Pads():
                pos=pad.GetPosition();size=pad.GetSize();center=(mm(pos.x),mm(pos.y));positions.append(center)
                shape='circle' if pad.GetShape()==api.PAD_SHAPE_CIRCLE else 'oval' if pad.GetShape()==api.PAD_SHAPE_OVAL else 'roundrect' if pad.GetShape()==getattr(api,'PAD_SHAPE_ROUNDRECT',None) else 'rectangle'
                rings=[]
                if hasattr(pad,'GetEffectivePolygon'):
                    for outer,holes in polygons(pad.GetEffectivePolygon(pad.GetLayer())):
                        rings.extend([[(mm(x),mm(y)) for x,y in ring] for ring in [outer,*holes]])
                bounds=(min(p[0] for r in rings for p in r),min(p[1] for r in rings for p in r),max(p[0] for r in rings for p in r),max(p[1] for r in rings for p in r)) if any(rings) else None
                radius=mm(pad.GetRoundRectCornerRadius()) if shape=='roundrect' else 0
                drill=getattr(pad,'GetDrillSize',lambda:None)()
                drill=(mm(drill.x),mm(drill.y)) if drill is not None else (0,0)
                net=str(getattr(pad,"GetNetname",lambda:"")())
                if net:self.net_targets.append({"net":net,"start":center,"end":center,"radius":max(mm(size.x),mm(size.y))/2})
                self.context_pads.append(dict(bounds=bounds,center=center,size=(mm(size.x),mm(size.y)),angle=-float(pad.GetOrientationDegrees()),shape=shape,rings=rings,radius=radius,number=str(pad.GetNumber()),drill=drill))
                tag('context_pads',pad,fp)
            self.focus_points.extend(positions)
            if getattr(fp,"IsSelected",lambda:False)() or any(getattr(p,"IsSelected",lambda:False)() for p in fp.Pads()):selected_points.extend(positions)
            graphics=list(getattr(fp,'GraphicalItems',lambda:[])())
            for graphic in graphics:
                raw=getattr(graphic,'raw',None)
                if raw is not None:
                    # IPC returns board-space shape coordinates for footprint graphics.
                    if hasattr(raw,'start') and hasattr(raw,'end'):
                        a,b=raw.start,raw.end;self.footprint_lines.append((mm(a.x),mm(a.y),mm(b.x),mm(b.y)))
                    continue
                if not hasattr(graphic,'GetShape'):continue
                shape=graphic.GetShape()
                if shape==api.SHAPE_T_SEGMENT:
                    a,b=graphic.GetStart(),graphic.GetEnd();self.footprint_lines.append((mm(a.x),mm(a.y),mm(b.x),mm(b.y)))
                elif shape==getattr(api,'SHAPE_T_RECT',None):
                    a,b=graphic.GetStart(),graphic.GetEnd();x1,y1,x2,y2=mm(a.x),mm(a.y),mm(b.x),mm(b.y)
                    self.footprint_lines.extend(((x1,y1,x2,y1),(x2,y1,x2,y2),(x2,y2,x1,y2),(x1,y2,x1,y1)))
            if positions:
                self.references.append((sum(p[0] for p in positions)/len(positions),min(p[1] for p in positions)-1,str(fp.GetReference())))
        if selected_points:self.focus_points=selected_points
        for track in board.GetTracks():
            net=str(getattr(track,"GetNetname",lambda:"")())
            if net and ("VIA" in track.GetClass() or track.GetClass()=="PCB_TRACK"):
                if "VIA" in track.GetClass():
                    position=track.GetPosition();a=b=(mm(position.x),mm(position.y));radius=mm(track.GetWidth(track.TopLayer()))/2
                else:
                    start,end=track.GetStart(),track.GetEnd();a,b=(mm(start.x),mm(start.y)),(mm(end.x),mm(end.y));radius=mm(track.GetWidth())/2
                self.net_targets.append({"net":net,"start":a,"end":b,"radius":radius})
            if 'VIA' in track.GetClass():
                pos=track.GetPosition();self.context_vias.append((mm(pos.x),mm(pos.y),mm(track.GetWidth(track.TopLayer())),mm(track.GetDrillValue())))
                tag('context_vias',track)
            elif track.GetClass()=='PCB_TRACK':
                a,b=track.GetStart(),track.GetEnd();self.context_lines.append((mm(a.x),mm(a.y),mm(b.x),mm(b.y),mm(track.GetWidth())))
                tag('context_lines',track)
            else:
                box=track.GetBoundingBox();a,b,c,d=mm(box.GetLeft()),mm(box.GetTop()),mm(box.GetRight()),mm(box.GetBottom())
                self.context_rings.append(([(a,b),(c,b),(c,d),(a,d)],'envelope'))
                tag('context_rings',track)
        for zone in board.Zones():
            for outer,holes in polygons(zone.Outline()):
                for ring in [outer,*holes]:
                    self.context_rings.append(([(mm(x),mm(y)) for x,y in ring],'zone'))
                    tag('context_rings',zone)
        outline=None
        if hasattr(api,'SHAPE_POLY_SET'):
            outline=api.SHAPE_POLY_SET();board.GetBoardPolygonOutlines(outline,False)
        elif hasattr(board,'wayricad_outline'):
            try:outline=board.wayricad_outline()
            except RuntimeError:pass  # Planner reports unsupported board geometry before Apply.
        if outline is not None:
            for outer,holes in polygons(outline):
                for ring in [outer,*holes]:
                    self.context_rings.append(([(mm(x),mm(y)) for x,y in ring],'edge'))
                    self._context_identity.setdefault('context_rings',[]).append(('',''))
        self.set_highlight()
        self.invalidate_scene();self.Refresh()

    def set_highlight(self,nets=(),identifiers=()):
        """Accent exact saved copper identities without replacing candidate geometry.

        Zone borders and arc envelopes remain borders/envelopes, never invented
        filled copper. Selection changes retain the current camera until focused.
        """
        self._highlight_nets=frozenset(str(n) for n in nets if n)
        self._highlight_ids=frozenset(str(i).casefold() for i in identifiers if i)
        self._highlight_indices={kind:{i for i,row in enumerate(rows)
                                     if row[0] in self._highlight_nets or any(uid in self._highlight_ids for uid in row[1:] if uid)}
                                 for kind,rows in self._context_identity.items()}
        bounds=[]
        for kind,indices in self._highlight_indices.items():
            for i in indices:
                row=getattr(self,kind)[i]
                if kind=='context_lines':bounds.extend((row[:2],row[2:4]))
                elif kind=='context_pads':
                    if row.get('bounds'):
                        x1,y1,x2,y2=row['bounds'];bounds.extend(((x1,y1),(x2,y2)))
                    else:
                        x,y=row['center'];r=math.hypot(*row['size'])/2;bounds.extend(((x-r,y-r),(x+r,y+r)))
                elif kind=='context_vias':
                    x,y,d,_=row;bounds.extend(((x-d/2,y-d/2),(x+d/2,y+d/2)))
                else:bounds.extend(row[0])
        self._highlight_bounds=bounds
        self.invalidate_scene();self.Refresh()
        return sum(len(indices) for indices in self._highlight_indices.values())

    def focus_highlight(self):
        """Fit only the highlighted saved items; return False for no match."""
        if not self._highlight_bounds:return False
        self._view_bounds=list(self._highlight_bounds)
        self.zoom=1.;self.pan=[0.,0.];self.invalidate_scene();self.Refresh()
        return True

    def fit_board(self):
        """Fit the complete saved board context, including edge cuts and holes."""
        coordinates=[p for line in self.context_lines for p in (line[:2],line[2:4])]
        coordinates.extend(p for ring,_ in self.context_rings for p in ring)
        coordinates.extend(pad['center'] for pad in self.context_pads)
        coordinates.extend((x,y) for x,y,_,_ in self.context_vias)
        if not coordinates:return False
        self._view_bounds=coordinates;self.zoom=1.;self.pan=[0.,0.]
        self.invalidate_scene();self.Refresh()
        return True

    def _highlighted(self,kind,index):
        return index in self._highlight_indices.get(kind,())

    def clear(self):
        self.lines=[];self.points=[];self.pads=[];self.outlines=[];self.rejected=[];self.pick=None;self.probes=[];self.cursor=None;self._view_bounds=None;self.set_highlight();self.Refresh()

    def fit(self,_event=None):self.zoom=1.;self.pan=[0.,0.];self.pick=None;self._view_bounds=None;self.Refresh()

    def wheel(self,event):
        factor=1.2 if event.GetWheelRotation()>0 else 1/1.2
        new=max(.1,min(100.,self.zoom*factor));factor=new/self.zoom
        width,height=self.GetClientSize();x,y=event.GetPosition()
        self.pan=[(self.pan[0]-(x-width/2))*factor+(x-width/2),(self.pan[1]-(y-(height-(0 if self.compact else 48))/2))*factor+(y-(height-(0 if self.compact else 48))/2)]
        self.zoom=new;self.Refresh()

    def down(self,event):self.drag=event.GetPosition();self.click_start=tuple(event.GetPosition());self.CaptureMouse()
    def up(self,event):
        if self.HasCapture():self.ReleaseMouse()
        self.drag=None
        click=tuple(event.GetPosition())
        moved=math.dist(click,self.click_start) if self.click_start else math.inf
        self.click_start=None
        if moved<4:
            world=self.unproject(click)
            if event.ControlDown() and world is not None:
                self.probes.append(world)
            elif callable(self.on_net_select):
                target=self.pick_net(click)
                if target is not None:self.on_net_select(target['net'],world)
        if self.points:
            x,y=event.GetPosition();index=min(range(len(self.points)),key=lambda i:math.dist((x,y),self.project(self.points[i])))
            if math.dist((x,y),self.project(self.points[index]))<14:self.pick=index
        self.Refresh()
    def motion(self,event):
        self.cursor=tuple(event.GetPosition());self.Refresh(False)
        if self.drag is not None and event.Dragging():
            pos=event.GetPosition();self.pan[0]+=pos.x-self.drag.x;self.pan[1]+=pos.y-self.drag.y;self.drag=pos;self.Refresh()

    def capture_lost(self,event):
        self.drag=None;self.click_start=None;self.Refresh(False)

    def pick_net(self, screen):
        """Pick only visible copper/pads within a screen-space tolerance."""
        from .picking import segment_distance
        closest=None;distance=math.inf
        for target in self.net_targets:
            a,b=self.project(target['start']),self.project(target['end'])
            gap=segment_distance(screen,a,b)
            radius=math.dist(a,self.project((target['start'][0]+target['radius'],target['start'][1])))
            gap=max(0,gap-radius)
            if gap<=7 and gap<distance:closest=target;distance=gap
        return closest

    def on_paint(self,event):
        dc=wx.AutoBufferedPaintDC(self)
        offset=self._drag_bitmap_offset()
        if offset is None:
            dc.DrawBitmap(self._bitmap_for_view(),0,0)
        else:
            dc.SetBackground(wx.Brush('#fbfcfd'));dc.Clear()
            width,height=self.GetClientSize();footer=0 if self.compact else 48
            view_height=max(1,height-footer)
            dc.SetClippingRegion(0,0,width,view_height)
            dc.DrawBitmap(self._scene_bitmap,*offset)
            dc.DestroyClippingRegion()
            if footer:
                source_dc=wx.MemoryDC(self._scene_bitmap)
                try:dc.Blit(0,view_height,width,footer,source_dc,0,view_height)
                finally:source_dc.SelectObject(wx.NullBitmap)
        self._draw_inspection(dc)

    def _drag_bitmap_offset(self):
        """Translate accurate cached pixels during a drag; release renders afresh."""
        if self.drag is None or self._scene_bitmap is None or self._scene_key is None:return None
        key=self._cache_key()
        if key[:3]+key[4:]!=self._scene_key[:3]+self._scene_key[4:]:return None
        old_pan=self._scene_key[3]
        return (round(self.pan[0]-old_pan[0]),round(self.pan[1]-old_pan[1]))

    def _bitmap_for_view(self):
        key=self._cache_key()
        if self._scene_bitmap is None or key!=self._scene_key:
            width,height=self.GetClientSize()
            bitmap=wx.Bitmap(max(1,width),max(1,height))
            scene_dc=wx.MemoryDC(bitmap)
            try:self._render_scene(scene_dc)
            finally:scene_dc.SelectObject(wx.NullBitmap)
            self._scene_bitmap=bitmap;self._scene_key=key
        return self._scene_bitmap

    def _draw_inspection(self,dc):
        """Draw transient cursor/probe overlays without traversing board geometry."""
        if self.unproject((0,0)) is None:return
        view_height=max(1,self.GetClientSize()[1]-(0 if self.compact else 48))
        dc.SetClippingRegion(0,0,self.GetClientSize()[0],view_height)
        dc.SetPen(wx.Pen('#ae335a',1));dc.SetTextForeground('#5e263e')
        for index,position in enumerate(self.probes,1):
            x,y=self.project(position);dc.DrawLine(x-6,y,x+6,y);dc.DrawLine(x,y-6,x,y+6)
            dc.DrawText(f'P{index} {position[0]:.3f}, {position[1]:.3f} mm',x+8,y+5)
        if not self.compact and self.cursor is not None and 0<=self.cursor[1]<view_height:
            point=self.unproject(self.cursor)
            dc.DrawText(f'{point[0]:.3f}, {point[1]:.3f} mm | Ctrl-click: pin coordinates',12,12)
        dc.DestroyClippingRegion()

    def _render_scene(self,dc):
        dc.SetBackground(wx.Brush('#fbfcfd'));dc.Clear()
        width,height=self.GetClientSize();view_height=max(1,height-(0 if self.compact else 48))
        coordinates=[p for line in self.lines for p in (line[:2],line[2:4])]+self.points+self.pads+[p for r in self.outlines for p in (r[:2],r[2:4])]
        if not coordinates:coordinates=self.focus_points
        if self._view_bounds:coordinates=self._view_bounds
        if not coordinates:
            self.unproject=lambda p:None
            dc.SetTextForeground('#65707c');dc.DrawLabel(self.empty_text,wx.Rect(20,20,max(1,width-40),max(1,view_height-40)),wx.ALIGN_CENTER);return
        # Keep nearby connected copper visible without fitting the entire board.
        left,right=min(p[0] for p in coordinates)-5,max(p[0] for p in coordinates)+5
        top,bottom=min(p[1] for p in coordinates)-5,max(p[1] for p in coordinates)+5
        nearby=[p for line in self.context_lines for p in (line[:2],line[2:4])]+[(x,y) for x,y,_,_ in self.context_vias]
        if not self.compact:
            coordinates=coordinates+[p for p in nearby if left<=p[0]<=right and top<=p[1]<=bottom]
        padding=max([.5]+[d/2 for d in self.point_diameters]+[max(size[:2])/2 for size in self.pad_sizes])+.5
        minx=min(p[0] for p in coordinates)-padding;maxx=max(p[0] for p in coordinates)+padding
        miny=min(p[1] for p in coordinates)-padding;maxy=max(p[1] for p in coordinates)+padding
        inset=20 if self.compact else 60
        scale=max(.01,min((width-inset)/max(maxx-minx,1),(view_height-inset)/max(maxy-miny,1)))*self.zoom
        cx,cy=(minx+maxx)/2,(miny+maxy)/2
        def project(p):return (round(width/2+self.pan[0]+(p[0]-cx)*scale),round(view_height/2+self.pan[1]+(p[1]-cy)*scale))
        self.project=project
        self.unproject=lambda p:(cx+(p[0]-width/2-self.pan[0])/scale,cy+(p[1]-view_height/2-self.pan[1])/scale)
        low=self.unproject((-20,-20));high=self.unproject((width+20,view_height+20))
        def visible(x1,y1,x2,y2,margin=0):
            return (max(x1,x2)+margin>=low[0] and min(x1,x2)-margin<=high[0]
                    and max(y1,y2)+margin>=low[1] and min(y1,y2)-margin<=high[1])
        def pad_visible(pad):
            bounds=pad.get('bounds')
            return visible(*bounds) if bounds else visible(*pad['center'],*pad['center'],math.hypot(*pad['size'])/2)
        step=10**math.floor(math.log10(60/scale))
        if step*scale<30:step*=5
        if self.show_grid:
            dc.SetPen(wx.Pen('#e9edf1',1))
            for axis,limit,center in ((0,width,cx),(1,view_height,cy)):
                low=center-(limit/2+self.pan[axis])/scale;high=low+limit/scale
                for i in range(math.floor(low/step),math.ceil(high/step)+1):
                    p=project((i*step,cy) if axis==0 else (cx,i*step))
                    dc.DrawLine(p[0],0,p[0],view_height) if axis==0 else dc.DrawLine(0,p[1],width,p[1])
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        highlighting=bool(self._highlight_bounds)
        for ri,(ring,kind) in enumerate(self.context_rings):
            if not ring or not visible(min(p[0] for p in ring),min(p[1] for p in ring),max(p[0] for p in ring),max(p[1] for p in ring)):continue
            selected=self._highlighted('context_rings',ri)
            dc.SetPen(wx.Pen('#007f89' if selected else '#687582' if kind=='edge' else '#c3cbd2',3 if selected else 2 if kind=='edge' else 1,wx.PENSTYLE_SOLID if kind=='edge' or selected else wx.PENSTYLE_SHORT_DASH))
            dc.DrawPolygon([wx.Point(*project(p)) for p in ring])
        for ti,(x1,y1,x2,y2,stroke) in enumerate(self.context_lines):
            if not visible(x1,y1,x2,y2,stroke/2):continue
            selected=self._highlighted('context_lines',ti)
            dc.SetPen(wx.Pen('#007f89' if selected else '#d1d7dc' if highlighting else '#b47c6f',max(3 if selected else 1,round(stroke*scale))));dc.DrawLine(*project((x1,y1)),*project((x2,y2)))
        dc.SetPen(wx.Pen('#596877',max(1,min(3,round(.12*scale)))))
        for line in self.footprint_lines:
            if visible(*line[:4]):dc.DrawLine(*project(line[:2]),*project(line[2:4]))
        gc=wx.GraphicsContext.Create(dc)
        for pi,pad in enumerate(self.context_pads):
            if not pad_visible(pad):continue
            x,y=project(pad['center']);w,h=[v*scale for v in pad['size']]
            selected=self._highlighted('context_pads',pi)
            gc.SetPen(wx.Pen('#00575e' if selected else '#b8bdc1' if highlighting else '#9d793d',2 if selected else 1));gc.SetBrush(wx.Brush('#4fd9d4' if selected else '#e1e4e6' if highlighting else '#d7b36c'))
            if pad['rings']:
                for ring in pad['rings']:
                    path=gc.CreatePath();first=project(ring[0]);path.MoveToPoint(*first)
                    for point in ring[1:]:path.AddLineToPoint(*project(point))
                    path.CloseSubpath();gc.DrawPath(path)
            else:
                gc.PushState();gc.Translate(x,y);gc.Rotate(math.radians(pad['angle']))
                if pad['shape']=='circle':gc.DrawEllipse(-w/2,-h/2,w,h)
                elif pad['shape'] in ('oval','roundrect'):gc.DrawRoundedRectangle(-w/2,-h/2,w,h,min(w,h)/2 if pad['shape']=='oval' else pad['radius']*scale)
                else:gc.DrawRectangle(-w/2,-h/2,w,h)
                gc.PopState()
            dx,dy=pad['drill']
            if dx>0 and dy>0:
                gc.SetBrush(wx.Brush('#fbfcfd'));gc.SetPen(wx.Pen('#8d8e8f',1));gc.DrawEllipse(x-dx*scale/2,y-dy*scale/2,dx*scale,dy*scale)
        gc.Flush()
        for i,line in enumerate(self.lines):
            stroke=self.line_widths[i] if i<len(self.line_widths) else .2
            dc.SetPen(wx.Pen('#087f98',max(2,round(stroke*scale))));dc.DrawLine(*project(line[:2]),*project(line[2:4]))
        def via(point,diameter,drill,selected=False,existing=False):
            x,y=project(point);dc.SetPen(wx.Pen('#00575e' if selected else '#c4cbd0' if existing and highlighting else '#758d86' if existing else '#087f98',2));dc.SetBrush(wx.Brush('#4fd9d4' if selected else '#e5e8eb' if existing and highlighting else '#cbd9d4' if existing else '#62c1c5'))
            dc.DrawCircle(x,y,max(3,round(diameter*scale/2)))
            dc.SetBrush(wx.Brush('#fbfcfd'));dc.SetPen(wx.Pen('#596877',1));dc.DrawCircle(x,y,max(1,round(drill*scale/2)))
        for vi,(x,y,d,drill) in enumerate(self.context_vias):
            if visible(x,y,x,y,d/2):via((x,y),d,drill,selected=self._highlighted('context_vias',vi),existing=not self._highlighted('context_vias',vi))
        for i,point in enumerate(self.points):via(point,self.point_diameters[i] if i<len(self.point_diameters) else .6,self.point_drills[i] if i<len(self.point_drills) else .3,i==self.pick)
        for pi,pad in enumerate(self.context_pads):
            if highlighting and not self._highlighted('context_pads',pi):continue
            if not pad_visible(pad):continue
            x,y=project(pad['center']);w,h=[v*scale for v in pad['size']]
            if min(w,h)>12:
                dc.SetTextForeground('#56411e');tw,th=dc.GetTextExtent(pad['number'])
                dc.DrawText(pad['number'],x-round(w/2)-tw-4,y-th//2)
        dc.SetTextForeground('#495763')
        for x,y,reference in self.references:
            if not visible(x,y,x,y,5):continue
            px,py=project((x,y));tw,th=dc.GetTextExtent(reference);dc.DrawText(reference,px-tw//2,py-th)
        if self.compact:return
        dc.SetPen(wx.Pen('#dce2e7',1));dc.SetBrush(wx.Brush('#f3f6f8'));dc.DrawRectangle(0,view_height,width,48)
        dc.SetTextForeground('#596877');dc.DrawText('Pads / existing copper',12,view_height+8)
        dc.SetTextForeground('#087f98');dc.DrawText('Selected copper' if highlighting and not self.lines and not self.points else 'New tracks / vias',175,view_height+8)
        text=f'{step:g} mm';bar=round(step*scale);dc.SetPen(wx.Pen('#596877',2));dc.DrawLine(12,view_height+35,12+bar,view_height+35);dc.DrawText(text,20+bar,view_height+26)
        detail='Wheel: zoom   Drag: pan'
        if self.pick is not None and self.pick<len(self.points):detail=f'Via {self.pick+1}: {self.points[self.pick][0]:.3f}, {self.points[self.pick][1]:.3f} mm'
        dc.SetTextForeground('#596877');dc.DrawText(detail,max(170,width-300),view_height+26)
        dc.DrawText('+X >',max(0,width-56),10);dc.DrawText('+Y v',max(0,width-56),27)
