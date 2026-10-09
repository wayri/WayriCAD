"""Hardware-accelerated native conflict explorer with exact contact overlays."""
import math
import time
import ctypes
import threading
import wx
from wx import glcanvas
from OpenGL import GL as gl
from OpenGL import GLU as glu
from .inspection_picking import SceneIndex, pack_mesh
from .inspection_state import InspectionState, measurement_text, length_text


class Scene(glcanvas.GLCanvas):
    def __init__(self,parent):
        attrs=[glcanvas.WX_GL_RGBA,glcanvas.WX_GL_DOUBLEBUFFER,glcanvas.WX_GL_DEPTH_SIZE,24,
               glcanvas.WX_GL_SAMPLE_BUFFERS,1,glcanvas.WX_GL_SAMPLES,4,0]
        if not glcanvas.GLCanvas.IsDisplaySupported(attrs):
            attrs=[glcanvas.WX_GL_RGBA,glcanvas.WX_GL_DOUBLEBUFFER,glcanvas.WX_GL_DEPTH_SIZE,24,0]
        super().__init__(parent,attribList=attrs)
        self.context=glcanvas.GLContext(self)
        self.SetMinSize((360,280))
        self.bodies=[];self.refs=set();self.issue=None;self.drag=None
        self.center=[0,0,0];self.span=100;self.zoom=1
        self.yaw=-1.0;self.pitch=.75
        self.isolate=False;self.ghost=True;self.section=False
        self.orthographic=False;self.grid=True;self.labels=True
        self.board_outline=None
        self.section_normal=[0,1,0];self.section_offset=0.0
        self.buffers={};self.initialized=False
        self.inspection=InspectionState();self.index=SceneIndex([])
        self.report_generation=0;self.disposed=False;self.text_cache={}
        self.on_measure=None;self.on_hover=None;self.on_ruler=None
        self.hover_measurement=None
        self.hover_hit=None;self.probes=[];self.on_pick=None;self.click_start=None;self.last_hover=0
        self.SetCursor(wx.Cursor(wx.CURSOR_CROSS))
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda e:self.Refresh())
        self.Bind(wx.EVT_LEFT_DOWN,self.down);self.Bind(wx.EVT_RIGHT_DOWN,self.down)
        self.Bind(wx.EVT_LEFT_UP,self.up);self.Bind(wx.EVT_RIGHT_UP,self.up)
        self.Bind(wx.EVT_MOTION,self.motion);self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))
        self.Bind(wx.EVT_LEAVE_WINDOW,self.leave)
        self.Bind(wx.EVT_WINDOW_DESTROY,self.dispose)
        self.SetToolTip('Drag to orbit Â· Right-drag to pan Â· Wheel to zoom.\nRed shows the intersecting volume in X-ray; grey shows actual STEP surfaces.')

    def release_buffers(self):
        if self.initialized and not self.disposed:
            self.SetCurrent(self.context)
            for buffer,count in self.buffers.values():gl.glDeleteBuffers(1,[buffer])
        self.buffers.clear();self.text_cache.clear()

    def dispose(self,event):
        if event.GetEventObject() is self:
            self.index.cancel.set();self.release_buffers();self.disposed=True
        event.Skip()

    def set_report(self,report):
        self.index.cancel.set();self.release_buffers()
        self.report_generation+=1;generation=self.report_generation
        self.bodies=report['bodies'];self.board_outline=report.get('board_outline')
        self.issue=None;self.probes=[];self.hover_hit=None
        self.hover_measurement=None;self.inspection.reset(report)
        self.index=SceneIndex(self.bodies);index=self.index
        def prepare():
            index.prepare()
            if not self.disposed and generation==self.report_generation:
                wx.CallAfter(self.prepared,generation)
        threading.Thread(target=prepare,daemon=True).start()
        self.fit()

    def prepared(self,generation):
        if not self.disposed and generation==self.report_generation:self.Refresh(False)

    def set_mode(self,mode):
        self.inspection.set_mode(mode);self.refs=set();self.Refresh(False)

    def set_view(self,name):
        self.yaw=-math.pi/2 if name!='iso' else -1.0
        self.pitch={'top':math.pi/2-.0001,'bottom':-math.pi/2+.0001,'side':0,'iso':.75}[name]
        self.orthographic=name!='iso';self.Refresh(False)

    def set_measurement(self,record):
        self.inspection.set_measurement(record)
        self.refs=set(record.get('refs',[]));self.Refresh(False)

    def clear_measurements(self):
        self.inspection.clear();self.probes=[];self.hover_measurement=None;self.refs=set();self.Refresh(False)

    def leave(self,event):
        if self.drag is None:
            self.hover_hit=None;self.hover_measurement=None;self.Refresh(False)
        event.Skip()

    def select(self,issue):
        self.issue=issue;self.fit(issue['refs'])

    def fit(self,refs=None):
        self.refs=set(refs or [])
        if not refs:self.issue=None
        bodies=[b for b in self.bodies if not refs or b['ref'] in refs]
        boxes=[b['bounds'] for b in bodies]
        outline=(self.board_outline or {}).get('bounds')
        if not refs and outline:boxes.append(outline)
        if not boxes:return
        lo=[min(b[i] for b in boxes) for i in range(3)]
        hi=[max(b[i+3] for b in boxes) for i in range(3)]
        self.center=[(a+b)/2 for a,b in zip(lo,hi)]
        self.span=max(4,math.sqrt(sum((b-a)**2 for a,b in zip(lo,hi))))
        self.zoom=1;self.Refresh()

    def focus_contact(self):
        if not self.issue:return
        bounds=self.issue.get('conflict_bounds')
        if bounds:
            self.center=[(bounds[i]+bounds[i+3])/2 for i in range(3)]
            self.span=max(2,math.sqrt(sum((bounds[i+3]-bounds[i])**2 for i in range(3))))
        elif self.issue.get('points'):
            points=self.issue['points'][0]
            self.center=[sum(p[i] for p in points)/len(points) for i in range(3)]
            self.span=max(3,math.dist(*points)*4)
        self.zoom=1.4;self.Refresh()

    def down(self,event):
        self.click_start=tuple(event.GetPosition())
        self.drag=(event.GetPosition(),event.RightDown() or event.ShiftDown())
        if not self.HasCapture():self.CaptureMouse()

    def up(self,event):
        moved=math.dist(tuple(event.GetPosition()),self.click_start) if self.click_start else math.inf
        if event.LeftUp() and moved<4:
            hit=self.pick(event.GetPosition())
            if hit:
                if event.ControlDown():self.probes.append(hit)
                else:
                    action=self.inspection.click(hit)
                    self.refs=set(self.inspection.pair) if self.inspection.mode=='parts' else {hit['reference']}
                    if isinstance(action,tuple) and callable(self.on_measure):self.on_measure(*action)
                    elif isinstance(action,dict) and callable(self.on_ruler):self.on_ruler(action)
                    if callable(self.on_pick):self.on_pick(hit)
                self.Refresh()
        self.click_start=None
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()

    def pick(self, position):
        if not self.initialized:return None
        self.SetCurrent(self.context)
        factor=self.GetContentScaleFactor()
        x,y=position.x*factor,(self.GetClientSize().height-position.y)*factor
        model=gl.glGetDoublev(gl.GL_MODELVIEW_MATRIX)
        projection=gl.glGetDoublev(gl.GL_PROJECTION_MATRIX)
        viewport=gl.glGetIntegerv(gl.GL_VIEWPORT)
        a=glu.gluUnProject(x,y,0,model,projection,viewport)
        b=glu.gluUnProject(x,y,1,model,projection,viewport)
        visible=lambda body:not self.refs or not self.isolate or body['ref'] in self.refs or body['kind'] in ('board','comparison_board')
        accept=None
        if self.section:
            origin=(self.issue or {}).get('section_origin',self.center)
            offset=sum(n*v for n,v in zip(self.section_normal,origin))+self.section_offset
            accept=lambda point:sum(n*v for n,v in zip(self.section_normal,point))>=offset-1e-9
        return self.index.pick(a,[end-start for start,end in zip(a,b)],visible,accept)

    def motion(self,event):
        if self.drag is None:
            if time.monotonic()-self.last_hover>.1:
                self.last_hover=time.monotonic();self.hover_hit=self.pick(event.GetPosition())
                self.hover_measurement=self.inspection.nearest.get(self.hover_hit['reference']) if self.hover_hit else None
                if self.hover_hit:
                    point=self.hover_hit['position']
                    gap='\n'+measurement_text(self.hover_measurement) if self.hover_measurement else '\nNearest-part distance unavailable for this geometry.'
                    self.SetToolTip(f"{self.hover_hit['reference']} · {point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f} mm{gap}")
                else:self.SetToolTip('Drag: orbit · Shift/right-drag: pan · Wheel: zoom. Choose a measurement tool below.')
                if callable(self.on_hover):self.on_hover(self.hover_hit,self.hover_measurement)
                self.Refresh(False)
            return
        previous,pan=self.drag;pos=event.GetPosition();dx,dy=pos.x-previous.x,pos.y-previous.y
        if pan:
            amount=self.span/max(self.GetClientSize().height,1)/self.zoom
            self.center[0]+=(-math.sin(self.yaw)*dx+math.cos(self.yaw)*math.sin(self.pitch)*dy)*amount
            self.center[1]+=(math.cos(self.yaw)*dx+math.sin(self.yaw)*math.sin(self.pitch)*dy)*amount
            self.center[2]+=math.cos(self.pitch)*dy*amount
        else:
            self.yaw-=dx*.008;self.pitch=max(-1.5,min(1.5,self.pitch+dy*.008))
        self.drag=(pos,pan);self.Refresh()

    def wheel(self,event):
        self.zoom=max(.1,min(30,self.zoom*math.exp(event.GetWheelRotation()*.001)))
        self.Refresh()

    def draw_mesh(self,key,mesh,packed=None):
        if key not in self.buffers:
            packed=pack_mesh(mesh) if packed is None else packed
            if not packed:return
            buffer=gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER,buffer)
            gl.glBufferData(gl.GL_ARRAY_BUFFER,len(packed)*packed.itemsize,packed.tobytes(),gl.GL_STATIC_DRAW)
            self.buffers[key]=(buffer,len(packed)//6)
        buffer,count=self.buffers[key]
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,buffer)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY);gl.glEnableClientState(gl.GL_NORMAL_ARRAY)
        gl.glVertexPointer(3,gl.GL_FLOAT,24,ctypes.c_void_p(0))
        gl.glNormalPointer(gl.GL_FLOAT,24,ctypes.c_void_p(12))
        gl.glDrawArrays(gl.GL_TRIANGLES,0,count)
        gl.glDisableClientState(gl.GL_NORMAL_ARRAY);gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,0)

    def draw_body(self,index,body,alpha=1):
        if not body.get('mesh'):return
        prepared=self.index.prepared.get(index)
        if prepared is None:return
        kind=body['kind'];active=body['ref'] in self.refs
        color=(.17,.48,.39) if kind=='board' else (.23,.43,.73) if kind=='comparison_board' else (.86,.56,.29) if kind=='comparison_component' else (.1,.72,.63) if active else (.55,.62,.68)
        if kind in ('hardware envelope','hole allowance'):color=(.94,.65,.22)
        gl.glColor4f(*color,alpha)
        self.draw_mesh(('body',index),body['mesh'],prepared[1])

    def paint(self,event):
        dc=wx.PaintDC(self)
        if not self.IsShownOnScreen():return
        self.SetCurrent(self.context);self.initialized=True
        factor=self.GetContentScaleFactor();size=self.GetClientSize();width,height=int(size.width*factor),int(size.height*factor)
        if width<=0 or height<=0:return
        gl.glViewport(0,0,width,height)
        gl.glClearColor(*((.10,.14,.17,1) if wx.SystemSettings.GetAppearance().IsDark() else (.97,.97,.97,1)))
        gl.glClear(gl.GL_COLOR_BUFFER_BIT|gl.GL_DEPTH_BUFFER_BIT)
        gl.glEnable(gl.GL_MULTISAMPLE);gl.glEnable(gl.GL_DEPTH_TEST);gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glEnable(gl.GL_BLEND);gl.glBlendFunc(gl.GL_SRC_ALPHA,gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glMatrixMode(gl.GL_PROJECTION);gl.glLoadIdentity()
        distance=self.span*1.8/self.zoom
        if self.orthographic:
            half=distance*math.tan(math.radians(18))
            gl.glOrtho(-half*width/height,half*width/height,-half,half,-100000,100000)
        else:glu.gluPerspective(36,width/height,max(.001,distance/1000),max(10000,distance*100))
        gl.glMatrixMode(gl.GL_MODELVIEW);gl.glLoadIdentity()
        direction=[math.cos(self.yaw)*math.cos(self.pitch),math.sin(self.yaw)*math.cos(self.pitch),math.sin(self.pitch)]
        eye=[self.center[i]+direction[i]*distance for i in range(3)]
        glu.gluLookAt(*eye,*self.center,0,0,1)
        self.draw_grid()
        self.draw_board_outline()
        gl.glEnable(gl.GL_LIGHTING);gl.glEnable(gl.GL_LIGHT0);gl.glEnable(gl.GL_LIGHT1)
        gl.glLightfv(gl.GL_LIGHT0,gl.GL_POSITION,[.2,-.4,1,0]);gl.glLightfv(gl.GL_LIGHT0,gl.GL_DIFFUSE,[.82,.85,.9,1])
        gl.glLightfv(gl.GL_LIGHT1,gl.GL_POSITION,[-.8,.3,.3,0]);gl.glLightfv(gl.GL_LIGHT1,gl.GL_DIFFUSE,[.38,.42,.46,1])
        gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT,[.28,.28,.30,1]);gl.glLightModeli(gl.GL_LIGHT_MODEL_TWO_SIDE,gl.GL_TRUE)
        gl.glEnable(gl.GL_NORMALIZE);gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glColorMaterial(gl.GL_FRONT_AND_BACK,gl.GL_AMBIENT_AND_DIFFUSE)
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK,gl.GL_SPECULAR,[.4,.4,.4,1]);gl.glMaterialf(gl.GL_FRONT_AND_BACK,gl.GL_SHININESS,45)
        if self.section:
            normal=self.section_normal
            length=math.sqrt(sum(value*value for value in normal)) or 1.0
            normal=[value/length for value in normal]
            origin=(self.issue or {}).get('section_origin',self.center)
            d=-sum(normal[i]*origin[i] for i in range(3))-self.section_offset
            gl.glClipPlane(gl.GL_CLIP_PLANE0,[*normal,d]);gl.glEnable(gl.GL_CLIP_PLANE0)
        boards=[]
        for i,body in enumerate(self.bodies):
            if body['kind'] in ('board','comparison_board'):boards.append((i,body));continue
            if self.refs and self.isolate and body['ref'] not in self.refs:continue
            self.draw_body(i,body)
        for i,body in boards:
            gl.glDepthMask(not self.ghost)
            self.draw_body(i,body,.24 if self.ghost else 1)
            gl.glDepthMask(True)
        gl.glDisable(gl.GL_CLIP_PLANE0)
        if self.issue:
            gl.glDisable(gl.GL_LIGHTING)
            contact=self.issue.get('conflict_mesh')
            if contact and contact['faces']:
                gl.glDisable(gl.GL_DEPTH_TEST);gl.glColor4f(.96,.12,.10,.95)
                self.draw_mesh(('issue',self.issue['id']),contact)
                gl.glEnable(gl.GL_DEPTH_TEST)
            points=self.issue.get('points')
            if points:
                gl.glDisable(gl.GL_DEPTH_TEST);gl.glColor3f(.85,.15,.08);gl.glLineWidth(3)
                gl.glBegin(gl.GL_LINES)
                for point in points[0]:gl.glVertex3f(*point)
                gl.glEnd();gl.glPointSize(8);gl.glBegin(gl.GL_POINTS)
                for point in points[0]:gl.glVertex3f(*point)
                gl.glEnd();gl.glEnable(gl.GL_DEPTH_TEST)
        markers=[*self.probes,*([self.hover_hit] if self.hover_hit else [])]
        if markers:
            gl.glDisable(gl.GL_LIGHTING);gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glColor3f(.95,.2,.48);gl.glPointSize(8);gl.glBegin(gl.GL_POINTS)
            for marker in markers:gl.glVertex3f(*marker['position'])
            gl.glEnd();gl.glEnable(gl.GL_DEPTH_TEST)
        self.draw_rulers(width,height,distance,factor)
        gl.glFlush();self.SwapBuffers()

    @staticmethod
    def nice_length(value):
        exponent=10**math.floor(math.log10(max(value,1e-9)))
        return next(v*exponent for v in (1,2,5,10) if v*exponent>=value)

    def draw_grid(self):
        if not self.grid:return
        extent=self.span/self.zoom
        spacing=self.nice_length(extent/16)
        gl.glDisable(gl.GL_LIGHTING);gl.glColor4f(.5,.58,.62,.24);gl.glLineWidth(1)
        gl.glBegin(gl.GL_LINES)
        for axis in range(2):
            low=math.floor((self.center[axis]-extent)/spacing)
            high=math.ceil((self.center[axis]+extent)/spacing)
            for index in range(low,high+1):
                point=[self.center[0],self.center[1],0]
                point[axis]=index*spacing;other=1-axis
                point[other]=self.center[other]-extent;gl.glVertex3f(*point)
                point[other]=self.center[other]+extent;gl.glVertex3f(*point)
        gl.glEnd()

    def draw_board_outline(self):
        outline=self.board_outline or {}
        gl.glDisable(gl.GL_LIGHTING);gl.glColor3f(.17,.48,.39);gl.glLineWidth(2)
        for contour in outline.get('polylines',[]):
            gl.glBegin(gl.GL_LINE_LOOP if contour.get('closed') else gl.GL_LINE_STRIP)
            for point in contour.get('points',[]):gl.glVertex3f(*point)
            gl.glEnd()

    def text_pixels(self,text,factor):
        if not text:return
        key=(text,round(factor,2))
        if key not in self.text_cache:
            font=wx.Font(max(9,round(10*factor)),wx.FONTFAMILY_DEFAULT,wx.FONTSTYLE_NORMAL,wx.FONTWEIGHT_NORMAL)
            dc=wx.MemoryDC(wx.Bitmap(1,1));dc.SetFont(font)
            w,h=dc.GetTextExtent(text);dc.SelectObject(wx.NullBitmap)
            bitmap=wx.Bitmap(w+12,h+8);dc.SelectObject(bitmap);dc.SetFont(font)
            dc.SetBackground(wx.Brush('#243444'));dc.Clear();dc.SetTextForeground('#ffffff')
            dc.DrawText(text,6,4);dc.SelectObject(wx.NullBitmap)
            # OpenGL pixel rows run from the bottom upward.
            raw=bytes(bitmap.ConvertToImage().GetData());stride=bitmap.GetWidth()*3
            pixels=b''.join(raw[i:i+stride] for i in range(len(raw)-stride,-1,-stride))
            self.text_cache[key]=(bitmap.GetWidth(),bitmap.GetHeight(),pixels)
            if len(self.text_cache)>512:self.text_cache.pop(next(iter(self.text_cache)))
        return self.text_cache[key]

    def draw_text(self,text,x,y,factor,occupied=None,optional=False):
        if not text:return
        w,h,pixels=self.text_pixels(text,factor)
        x=max(0,min(x,self.viewport_width-w));y=max(0,min(y,self.viewport_height-h))
        if occupied is not None:
            position=None
            for offset in (0,1,-1,2,-2,3,-3,4,-4):
                cy=max(0,min(y+offset*(h+3*factor),self.viewport_height-h))
                if all(x+w+3*factor<=a or x>=c+3*factor or cy+h+3*factor<=b or cy>=d+3*factor
                       for a,b,c,d in occupied):
                    position=(x,cy);break
            if position is None:
                if optional:return
            else:x,y=position
            occupied.append((x,y,x+w,y+h))
        gl.glRasterPos2f(x,y)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT,1)
        gl.glDrawPixels(w,h,gl.GL_RGB,gl.GL_UNSIGNED_BYTE,pixels)

    def draw_rulers(self,width,height,distance,factor):
        self.viewport_width=width;self.viewport_height=height
        records=list(self.inspection.rulers)
        if self.hover_measurement and self.hover_measurement not in records:records.append(self.hover_measurement)
        model=gl.glGetDoublev(gl.GL_MODELVIEW_MATRIX)
        projection=gl.glGetDoublev(gl.GL_PROJECTION_MATRIX)
        viewport=gl.glGetIntegerv(gl.GL_VIEWPORT)
        labels=[]
        gl.glDisable(gl.GL_LIGHTING);gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glLineWidth(2);gl.glPointSize(7*factor)
        for record in records:
            points=record['points'];gl.glColor3f(.97,.6,.08) if record is self.hover_measurement else gl.glColor3f(.1,.85,.73)
            gl.glBegin(gl.GL_LINES)
            for point in points:gl.glVertex3f(*point)
            gl.glEnd();gl.glBegin(gl.GL_POINTS)
            for point in points:gl.glVertex3f(*point)
            gl.glEnd()
            projected=[glu.gluProject(*point,model,projection,viewport) for point in points]
            labels.append((record,projected))
        gl.glMatrixMode(gl.GL_PROJECTION);gl.glPushMatrix();gl.glLoadIdentity();gl.glOrtho(0,width,0,height,-1,1)
        gl.glMatrixMode(gl.GL_MODELVIEW);gl.glPushMatrix();gl.glLoadIdentity()
        occupied=[]
        for record,points in labels:
            if not any(0<=p[2]<=1 for p in points):continue
            gl.glColor3f(.1,.85,.73);gl.glBegin(gl.GL_LINES)
            for x,y,z in points:
                gl.glVertex2f(x-5*factor,y-5*factor);gl.glVertex2f(x+5*factor,y+5*factor)
                gl.glVertex2f(x-5*factor,y+5*factor);gl.glVertex2f(x+5*factor,y-5*factor)
            gl.glEnd()
            text=' ↔ '.join(record.get('refs',[]))+': '+length_text(record['distance_mm'])
            prefix='Points ' if record.get('type')=='point_ruler' else 'Gap '
            self.draw_text(prefix+text,sum(p[0] for p in points)/2+8*factor,sum(p[1] for p in points)/2+8*factor,factor,occupied)
        if self.labels:
            references=[]
            for body in self.bodies:
                if body['kind'] not in ('component','comparison_component'):continue
                if self.refs and self.isolate and body['ref'] not in self.refs:continue
                bounds=body['bounds'];point=[(bounds[i]+bounds[i+3])/2 for i in range(3)]
                x,y,z=glu.gluProject(*point,model,projection,viewport)
                if 0<=z<=1 and 0<x<width and 0<y<height:
                    important=body['ref'] in self.refs or body['ref']==(self.hover_hit or {}).get('reference')
                    references.append((not important,(x-width/2)**2+(y-height/2)**2,body['ref'],x,y))
            # Bound text rasterization on dense boards; selected/hovered parts
            # and references near the view center take priority.
            for _,_,ref,x,y in sorted(references)[:80]:
                self.draw_text(ref,x+5*factor,y+5*factor,factor,occupied,optional=True)
        ppm=height/(2*distance*math.tan(math.radians(18)))
        length=self.nice_length(70*factor/ppm);pixels=length*ppm
        gl.glColor3f(.15,.55,.55);gl.glBegin(gl.GL_LINES)
        gl.glVertex2f(18*factor,23*factor);gl.glVertex2f(18*factor+pixels,23*factor)
        for x in (18*factor,18*factor+pixels):gl.glVertex2f(x,18*factor);gl.glVertex2f(x,28*factor)
        gl.glEnd()
        self.draw_text(length_text(length)+('' if self.orthographic else ' at view center'),18*factor,32*factor,factor)
        if not self.index.ready:self.draw_text('Preparing indexed geometry…',18*factor,height-40*factor,factor)
        gl.glPopMatrix();gl.glMatrixMode(gl.GL_PROJECTION);gl.glPopMatrix();gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glEnable(gl.GL_DEPTH_TEST)
