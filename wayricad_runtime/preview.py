"""Local board-coordinate canvas with neutral styling and native pad geometry."""
import math
import wx
from .geometry import polygons


class GeometryPreview(wx.Panel):
    def __init__(self,parent,empty_text):
        super().__init__(parent,style=wx.BORDER_SIMPLE)
        self.empty_text=empty_text
        self.lines=[];self.points=[];self.pads=[];self.outlines=[]
        self.point_diameters=[];self.line_widths=[];self.pad_sizes=[];self.point_drills=[];self.rejected=[]
        self.context_lines=[];self.context_pads=[];self.context_rings=[];self.context_vias=[];self.footprint_lines=[];self.references=[]
        self.focus_points=[];self.show_grid=False
        self.zoom=1.;self.pan=[0.,0.];self.drag=None;self.pick=None;self.project=lambda p:(0,0)
        self.SetMinSize((320,280));self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetToolTip('Wheel: zoom. Drag: pan. Double-click: fit. Click a via: inspect coordinates. Arc tracks use conservative envelopes.')
        for event,handler in ((wx.EVT_PAINT,self.on_paint),(wx.EVT_MOUSEWHEEL,self.wheel),(wx.EVT_LEFT_DOWN,self.down),(wx.EVT_LEFT_UP,self.up),(wx.EVT_MOTION,self.motion),(wx.EVT_LEFT_DCLICK,self.fit)):
            self.Bind(event,handler)
        self.Bind(wx.EVT_SIZE,lambda event:(self.Refresh(),event.Skip()))
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda event:setattr(self,'drag',None))

    def set_geometry(self,lines=(),points=(),pads=(),outlines=(),point_diameters=(),line_widths=(),pad_sizes=(),point_drills=(),rejected=(),pad_shapes=()):
        for name,value in locals().copy().items():
            if name!='self':setattr(self,name,list(value))
        self.pick=None;self.Refresh()

    def set_board(self,board,api):
        mm=api.ToMM
        self.context_lines=[];self.context_pads=[];self.context_rings=[];self.context_vias=[];self.footprint_lines=[];self.references=[]
        self.focus_points=[]
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
                radius=mm(pad.GetRoundRectCornerRadius()) if shape=='roundrect' else 0
                drill=getattr(pad,'GetDrillSize',lambda:None)()
                drill=(mm(drill.x),mm(drill.y)) if drill is not None else (0,0)
                self.context_pads.append(dict(center=center,size=(mm(size.x),mm(size.y)),angle=-float(pad.GetOrientationDegrees()),shape=shape,rings=rings,radius=radius,number=str(pad.GetNumber()),drill=drill))
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
            if 'VIA' in track.GetClass():
                pos=track.GetPosition();self.context_vias.append((mm(pos.x),mm(pos.y),mm(track.GetWidth(track.TopLayer())),mm(track.GetDrillValue())))
            elif track.GetClass()=='PCB_TRACK':
                a,b=track.GetStart(),track.GetEnd();self.context_lines.append((mm(a.x),mm(a.y),mm(b.x),mm(b.y),mm(track.GetWidth())))
            else:
                box=track.GetBoundingBox();a,b,c,d=mm(box.GetLeft()),mm(box.GetTop()),mm(box.GetRight()),mm(box.GetBottom())
                self.context_rings.append(([(a,b),(c,b),(c,d),(a,d)],'envelope'))
        for zone in board.Zones():
            for outer,holes in polygons(zone.Outline()):
                self.context_rings.extend(([(mm(x),mm(y)) for x,y in ring],'zone') for ring in [outer,*holes])
        outline=None
        if hasattr(api,'SHAPE_POLY_SET'):
            outline=api.SHAPE_POLY_SET();board.GetBoardPolygonOutlines(outline,False)
        elif hasattr(board,'wayricad_outline'):
            try:outline=board.wayricad_outline()
            except RuntimeError:pass  # Planner reports unsupported board geometry before Apply.
        if outline is not None:
            for outer,holes in polygons(outline):self.context_rings.extend(([(mm(x),mm(y)) for x,y in ring],'edge') for ring in [outer,*holes])
        self.Refresh()

    def clear(self):
        self.lines=[];self.points=[];self.pads=[];self.outlines=[];self.rejected=[];self.pick=None;self.Refresh()

    def fit(self,_event=None):self.zoom=1.;self.pan=[0.,0.];self.pick=None;self.Refresh()

    def wheel(self,event):
        factor=1.2 if event.GetWheelRotation()>0 else 1/1.2
        new=max(.1,min(100.,self.zoom*factor));factor=new/self.zoom
        width,height=self.GetClientSize();x,y=event.GetPosition()
        self.pan=[(self.pan[0]-(x-width/2))*factor+(x-width/2),(self.pan[1]-(y-(height-48)/2))*factor+(y-(height-48)/2)]
        self.zoom=new;self.Refresh()

    def down(self,event):self.drag=event.GetPosition();self.CaptureMouse()
    def up(self,event):
        if self.HasCapture():self.ReleaseMouse()
        self.drag=None
        if self.points:
            x,y=event.GetPosition();index=min(range(len(self.points)),key=lambda i:math.dist((x,y),self.project(self.points[i])))
            if math.dist((x,y),self.project(self.points[index]))<14:self.pick=index
        self.Refresh()
    def motion(self,event):
        if self.drag is not None and event.Dragging():
            pos=event.GetPosition();self.pan[0]+=pos.x-self.drag.x;self.pan[1]+=pos.y-self.drag.y;self.drag=pos;self.Refresh()

    def on_paint(self,event):
        dc=wx.AutoBufferedPaintDC(self);dc.SetBackground(wx.Brush('#fbfcfd'));dc.Clear()
        width,height=self.GetClientSize();view_height=max(1,height-48)
        coordinates=[p for line in self.lines for p in (line[:2],line[2:4])]+self.points+self.pads+[p for r in self.outlines for p in (r[:2],r[2:4])]
        if not coordinates:coordinates=self.focus_points
        if not coordinates:
            dc.SetTextForeground('#65707c');dc.DrawLabel(self.empty_text,wx.Rect(20,20,max(1,width-40),max(1,view_height-40)),wx.ALIGN_CENTER);return
        # Keep nearby connected copper visible without fitting the entire board.
        left,right=min(p[0] for p in coordinates)-5,max(p[0] for p in coordinates)+5
        top,bottom=min(p[1] for p in coordinates)-5,max(p[1] for p in coordinates)+5
        nearby=[p for line in self.context_lines for p in (line[:2],line[2:4])]+[(x,y) for x,y,_,_ in self.context_vias]
        coordinates=coordinates+[p for p in nearby if left<=p[0]<=right and top<=p[1]<=bottom]
        padding=max([.5]+[d/2 for d in self.point_diameters]+[max(size[:2])/2 for size in self.pad_sizes])+.5
        minx=min(p[0] for p in coordinates)-padding;maxx=max(p[0] for p in coordinates)+padding
        miny=min(p[1] for p in coordinates)-padding;maxy=max(p[1] for p in coordinates)+padding
        scale=max(.01,min((width-60)/max(maxx-minx,1),(view_height-60)/max(maxy-miny,1)))*self.zoom
        cx,cy=(minx+maxx)/2,(miny+maxy)/2
        def project(p):return (round(width/2+self.pan[0]+(p[0]-cx)*scale),round(view_height/2+self.pan[1]+(p[1]-cy)*scale))
        self.project=project
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
        for ring,kind in self.context_rings:
            dc.SetPen(wx.Pen('#687582' if kind=='edge' else '#c3cbd2',2 if kind=='edge' else 1,wx.PENSTYLE_SOLID if kind=='edge' else wx.PENSTYLE_SHORT_DASH))
            dc.DrawPolygon([wx.Point(*project(p)) for p in ring])
        for x1,y1,x2,y2,stroke in self.context_lines:
            dc.SetPen(wx.Pen('#b47c6f',max(1,round(stroke*scale))));dc.DrawLine(*project((x1,y1)),*project((x2,y2)))
        dc.SetPen(wx.Pen('#596877',max(1,min(3,round(.12*scale)))))
        for line in self.footprint_lines:dc.DrawLine(*project(line[:2]),*project(line[2:4]))
        gc=wx.GraphicsContext.Create(dc)
        for pad in self.context_pads:
            x,y=project(pad['center']);w,h=[v*scale for v in pad['size']]
            gc.SetPen(wx.Pen('#9d793d',1));gc.SetBrush(wx.Brush('#d7b36c'))
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
            x,y=project(point);dc.SetPen(wx.Pen('#164e63' if selected else '#758d86' if existing else '#087f98',2));dc.SetBrush(wx.Brush('#cbd9d4' if existing else '#62c1c5'))
            dc.DrawCircle(x,y,max(3,round(diameter*scale/2)))
            dc.SetBrush(wx.Brush('#fbfcfd'));dc.SetPen(wx.Pen('#596877',1));dc.DrawCircle(x,y,max(1,round(drill*scale/2)))
        for x,y,d,drill in self.context_vias:via((x,y),d,drill,existing=True)
        for i,point in enumerate(self.points):via(point,self.point_diameters[i] if i<len(self.point_diameters) else .6,self.point_drills[i] if i<len(self.point_drills) else .3,i==self.pick)
        for pad in self.context_pads:
            x,y=project(pad['center']);w,h=[v*scale for v in pad['size']]
            if min(w,h)>12:
                dc.SetTextForeground('#56411e');tw,th=dc.GetTextExtent(pad['number'])
                dc.DrawText(pad['number'],x-round(w/2)-tw-4,y-th//2)
        dc.SetTextForeground('#495763')
        for x,y,reference in self.references:
            px,py=project((x,y));tw,th=dc.GetTextExtent(reference);dc.DrawText(reference,px-tw//2,py-th)
        dc.SetPen(wx.Pen('#dce2e7',1));dc.SetBrush(wx.Brush('#f3f6f8'));dc.DrawRectangle(0,view_height,width,48)
        dc.SetTextForeground('#596877');dc.DrawText('Pads / existing copper',12,view_height+8)
        dc.SetTextForeground('#087f98');dc.DrawText('New tracks / vias',175,view_height+8)
        text=f'{step:g} mm';bar=round(step*scale);dc.SetPen(wx.Pen('#596877',2));dc.DrawLine(12,view_height+35,12+bar,view_height+35);dc.DrawText(text,20+bar,view_height+26)
        detail='Wheel: zoom   Drag: pan'
        if self.pick is not None and self.pick<len(self.points):detail=f'Via {self.pick+1}: {self.points[self.pick][0]:.3f}, {self.points[self.pick][1]:.3f} mm'
        dc.SetTextForeground('#596877');dc.DrawText(detail,max(170,width-300),view_height+26)
        dc.DrawText('+X >',max(0,width-56),10);dc.DrawText('+Y v',max(0,width-56),27)
