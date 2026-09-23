"""Hardware-accelerated native conflict explorer with exact contact overlays."""
import math
import wx
from wx import glcanvas
from OpenGL import GL as gl
from OpenGL import GLU as glu


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
        self.isolate=True;self.ghost=True;self.section=False
        self.lists={};self.initialized=False
        self.Bind(wx.EVT_PAINT,self.paint)
        self.Bind(wx.EVT_SIZE,lambda e:self.Refresh())
        self.Bind(wx.EVT_LEFT_DOWN,self.down);self.Bind(wx.EVT_RIGHT_DOWN,self.down)
        self.Bind(wx.EVT_LEFT_UP,self.up);self.Bind(wx.EVT_RIGHT_UP,self.up)
        self.Bind(wx.EVT_MOTION,self.motion);self.Bind(wx.EVT_MOUSEWHEEL,self.wheel)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST,lambda e:setattr(self,'drag',None))
        self.Bind(wx.EVT_WINDOW_DESTROY,self.dispose)
        self.SetToolTip('Drag to orbit · Right-drag to pan · Wheel to zoom.\nRed shows the intersecting volume in X-ray; grey shows actual STEP surfaces.')

    def dispose(self,event):
        if event.GetEventObject() is self and self.initialized:
            self.SetCurrent(self.context)
            for display in self.lists.values():gl.glDeleteLists(display,1)
            self.lists.clear()
        event.Skip()

    def set_report(self,report):
        if self.initialized:
            self.SetCurrent(self.context)
            for display in self.lists.values():gl.glDeleteLists(display,1)
        self.lists={};self.bodies=report['bodies'];self.issue=None;self.fit()

    def select(self,issue):
        self.issue=issue;self.fit(issue['refs'])

    def fit(self,refs=None):
        self.refs=set(refs or [])
        if not refs:self.issue=None
        bodies=[b for b in self.bodies if not refs or b['ref'] in refs]
        if not bodies:return
        lo=[min(b['bounds'][i] for b in bodies) for i in range(3)]
        hi=[max(b['bounds'][i+3] for b in bodies) for i in range(3)]
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
        self.drag=(event.GetPosition(),event.RightDown() or event.ShiftDown())
        if not self.HasCapture():self.CaptureMouse()

    def up(self,event):
        self.drag=None
        if self.HasCapture():self.ReleaseMouse()

    def motion(self,event):
        if self.drag is None:return
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

    def display_list(self,key,mesh):
        if key in self.lists:return self.lists[key]
        display=gl.glGenLists(1);self.lists[key]=display
        gl.glNewList(display,gl.GL_COMPILE);gl.glBegin(gl.GL_TRIANGLES)
        vertices=mesh['vertices']
        for face in mesh['faces']:
            a,b,c=[vertices[i] for i in face]
            u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
            n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            length=math.sqrt(sum(x*x for x in n))
            if length<1e-15:continue
            gl.glNormal3f(*(x/length for x in n))
            for point in (a,b,c):gl.glVertex3f(*point)
        gl.glEnd();gl.glEndList();return display

    def draw_body(self,index,body,alpha=1):
        if not body.get('mesh'):return
        kind=body['kind'];active=body['ref'] in self.refs
        color=(.17,.48,.39) if kind=='board' else (.64,.68,.74) if active else (.55,.62,.68)
        if kind in ('hardware envelope','hole allowance'):color=(.94,.65,.22)
        gl.glColor4f(*color,alpha)
        gl.glCallList(self.display_list(('body',index),body['mesh']))

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
        glu.gluPerspective(36,width/height,max(.001,distance/1000),max(10000,distance*100))
        gl.glMatrixMode(gl.GL_MODELVIEW);gl.glLoadIdentity()
        direction=[math.cos(self.yaw)*math.cos(self.pitch),math.sin(self.yaw)*math.cos(self.pitch),math.sin(self.pitch)]
        eye=[self.center[i]+direction[i]*distance for i in range(3)]
        glu.gluLookAt(*eye,*self.center,0,0,1)
        gl.glEnable(gl.GL_LIGHTING);gl.glEnable(gl.GL_LIGHT0);gl.glEnable(gl.GL_LIGHT1)
        gl.glLightfv(gl.GL_LIGHT0,gl.GL_POSITION,[.2,-.4,1,0]);gl.glLightfv(gl.GL_LIGHT0,gl.GL_DIFFUSE,[.82,.85,.9,1])
        gl.glLightfv(gl.GL_LIGHT1,gl.GL_POSITION,[-.8,.3,.3,0]);gl.glLightfv(gl.GL_LIGHT1,gl.GL_DIFFUSE,[.38,.42,.46,1])
        gl.glLightModelfv(gl.GL_LIGHT_MODEL_AMBIENT,[.28,.28,.30,1]);gl.glLightModeli(gl.GL_LIGHT_MODEL_TWO_SIDE,gl.GL_TRUE)
        gl.glEnable(gl.GL_NORMALIZE);gl.glEnable(gl.GL_COLOR_MATERIAL)
        gl.glColorMaterial(gl.GL_FRONT_AND_BACK,gl.GL_AMBIENT_AND_DIFFUSE)
        gl.glMaterialfv(gl.GL_FRONT_AND_BACK,gl.GL_SPECULAR,[.4,.4,.4,1]);gl.glMaterialf(gl.GL_FRONT_AND_BACK,gl.GL_SHININESS,45)
        boards=[]
        for i,body in enumerate(self.bodies):
            if body['kind']=='board':boards.append((i,body));continue
            if self.refs and self.isolate and body['ref'] not in self.refs:continue
            self.draw_body(i,body)
        for i,body in boards:
            if self.section:
                gl.glClipPlane(gl.GL_CLIP_PLANE0,[0,1,0,-self.center[1]]);gl.glEnable(gl.GL_CLIP_PLANE0)
            gl.glDepthMask(not self.ghost)
            self.draw_body(i,body,.24 if self.ghost else 1)
            gl.glDepthMask(True);gl.glDisable(gl.GL_CLIP_PLANE0)
        if self.issue:
            gl.glDisable(gl.GL_LIGHTING)
            contact=self.issue.get('conflict_mesh')
            if contact and contact['faces']:
                gl.glDisable(gl.GL_DEPTH_TEST);gl.glColor4f(.96,.12,.10,.95)
                gl.glCallList(self.display_list(('issue',self.issue['id']),contact))
                gl.glEnable(gl.GL_DEPTH_TEST)
            points=self.issue.get('points')
            if points:
                gl.glDisable(gl.GL_DEPTH_TEST);gl.glColor3f(.85,.15,.08);gl.glLineWidth(3)
                gl.glBegin(gl.GL_LINES)
                for point in points[0]:gl.glVertex3f(*point)
                gl.glEnd();gl.glPointSize(8);gl.glBegin(gl.GL_POINTS)
                for point in points[0]:gl.glVertex3f(*point)
                gl.glEnd();gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glFlush();self.SwapBuffers()
