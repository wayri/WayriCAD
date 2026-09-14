"""Offline bounded mesh conversion. No model scripts or remote resources execute.

STEP/IGES/BREP conversion runs in a killable worker process. The stored original
is never replaced by this disposable tessellation. Browser rendering uses the
returned triangle buffer; no project-provided JavaScript or shaders are loaded.
"""
from __future__ import annotations
import gzip
import io
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from .assetbundle import MAX_ASSET

MAX_TRIANGLES=100000
MAX_VERTICES=300000
IDENTITY=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]

def multiply(a,b):return [sum(a[i*4+k]*b[k*4+j] for k in range(4)) for i in range(4) for j in range(4)]
def point(p,m):return [sum(m[i*4+j]*p[j] for j in range(3))+m[i*4+3] for i in range(3)]
def translate(v):
    m=IDENTITY.copy()
    for i in range(3):m[i*4+3]=v[i]
    return m

def rotate(v):
    x,y,z,angle=v;l=math.sqrt(x*x+y*y+z*z)
    if l<1e-12:return IDENTITY.copy()
    x/=l;y/=l;z/=l;c=math.cos(angle);s=math.sin(angle);d=1-c
    return [c+x*x*d,x*y*d-z*s,x*z*d+y*s,0,y*x*d+z*s,c+y*y*d,y*z*d-x*s,0,z*x*d-y*s,z*y*d+x*s,c+z*z*d,0,0,0,0,1]

def transform(node):
    vals=node.get('fields',{});t=vals.get('translation',[0,0,0]);c=vals.get('center',[0,0,0]);r=vals.get('rotation',[0,0,1,0]);sr=vals.get('scaleOrientation',[0,0,1,0]);s=vals.get('scale',[1,1,1]);sm=IDENTITY.copy()
    for i in range(3):sm[i*5]=s[i]
    m=IDENTITY.copy()
    for x in (translate(t),translate(c),rotate(r),rotate(sr),sm,rotate(sr[:3]+[-sr[3]]),translate([-x for x in c])):m=multiply(m,x)
    return m

class Mesh:
    def __init__(self):self.vertices=[];self.triangles=[];self.colors=[];self.warnings=[]
    def triangle(self,a,b,c,color):
        if len(self.triangles)>=MAX_TRIANGLES:raise ValueError('Preview exceeds 100,000 triangles; original model is still stored.')
        points=[a,b,c]
        if any(len(p)!=3 or any(not math.isfinite(float(x)) or abs(float(x))>1e9 for x in p) for p in points):raise ValueError('Invalid model coordinates.')
        start=len(self.vertices);self.vertices+=points;self.triangles.append([start,start+1,start+2]);self.colors.append([max(0,min(1,float(x))) for x in color[:3]])
    def polygon(self,coords,indices,color,matrix=IDENTITY):
        if len(indices)>256:raise ValueError('Face has more than 256 vertices; original retained.')
        if len(indices)>1 and indices[0]==indices[-1]:indices=indices[:-1]
        if len(indices)<3:return
        if any(not isinstance(i,int) or i<0 or i>=len(coords) for i in indices):raise ValueError('Invalid face coordinate index.')
        p=[point(coords[i],matrix) for i in indices]
        # Ear clipping in the dominant plane, not fan-triangulating concave faces.
        normal=[0.,0.,0.]
        for i,a in enumerate(p):
            b=p[(i+1)%len(p)];normal[0]+=(a[1]-b[1])*(a[2]+b[2]);normal[1]+=(a[2]-b[2])*(a[0]+b[0]);normal[2]+=(a[0]-b[0])*(a[1]+b[1])
        axis=max(range(3),key=lambda i:abs(normal[i]));plane=[i for i in range(3) if i!=axis];q=[(x[plane[0]],x[plane[1]]) for x in p]
        cross=lambda a,b,c:(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        area=sum(q[i][0]*q[(i+1)%len(q)][1]-q[(i+1)%len(q)][0]*q[i][1] for i in range(len(q)));sign=1 if area>=0 else -1
        if abs(area)<1e-15:return
        live=list(range(len(p)))
        while len(live)>3:
            found=False
            for pos,i in enumerate(live):
                j=live[pos-1];k=live[(pos+1)%len(live)]
                if sign*cross(q[j],q[i],q[k])<=1e-12:continue
                if any(all(sign*cross(a,b,q[z])>=-1e-12 for a,b in ((q[j],q[i]),(q[i],q[k]),(q[k],q[j]))) for z in live if z not in (j,i,k)):continue
                self.triangle(p[j],p[i],p[k],color);live.pop(pos);found=True;break
            if not found:raise ValueError('Degenerate/self-intersecting or unsupported nonplanar face; preview refused.')
        self.triangle(*(p[i] for i in live),color)
    def result(self,format_):
        if not self.triangles:raise ValueError('No supported triangle geometry in model; original remains downloadable.')
        lo=[min(p[i] for p in self.vertices) for i in range(3)];hi=[max(p[i] for p in self.vertices) for i in range(3)]
        return {'schema':'wayricad-mesh-preview-1','format':format_,'vertices':self.vertices,'triangles':self.triangles,'colors':self.colors,'bounds':[lo,hi],
                'triangle_count':len(self.triangles),'warnings':list(dict.fromkeys(self.warnings)),
                'notice':'Auto-fit model-local geometry. Footprint transforms are retained separately, not applied in this standalone view. Not dimensional qualification.'}

# VRML97 value arities. Unknown node/field syntax refuses parsing rather than
# executing Script/Inline/PROTO code or importing an external URL.
ARITY={k:3 for k in ('translation','center','scale','diffuseColor','emissiveColor','specularColor','bboxCenter','bboxSize','size','attenuation','direction','location','position')}
ARITY.update({k:4 for k in ('rotation','scaleOrientation','orientation')})
ARITY.update({k:1 for k in ('ambientIntensity','shininess','transparency','creaseAngle','solid','ccw','convex','colorPerVertex','normalPerVertex','radius','height','bottomRadius','top','bottom','side','whichChoice','repeatS','repeatT','headlight','fieldOfView','visibilityLimit','enabled','on','intensity')})
NODEFIELDS={'children','appearance','material','geometry','coord','normal','color','texCoord','texture','textureTransform','choice'}
class VRML:
    def __init__(self,text):
        if not text.lstrip().startswith('#VRML V2.0'):raise ValueError('Only VRML 2.0 / VRML97 is supported for preview; original is retained.')
        text=re.sub(r'#[^\n\r]*','',text)
        pattern=r'"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_+:.\-]*|[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[{}\[\]]'
        self.tokens=re.findall(pattern,text);self.i=0;self.defs={}
        if len(self.tokens)>4000000:raise ValueError('VRML token limit exceeded.')
    def pop(self):
        if self.i>=len(self.tokens):raise ValueError('Truncated VRML.')
        x=self.tokens[self.i];self.i+=1;return x
    def peek(self):return self.tokens[self.i] if self.i<len(self.tokens) else ''
    def take(self,token):
        if self.pop()!=token:raise ValueError('Unexpected VRML syntax; expected '+token)
    def scalar(self):
        s=self.pop()
        if s=='TRUE':return True
        if s=='FALSE':return False
        if s.startswith('"'):return json.loads(s)
        try:x=float(s)
        except ValueError:raise ValueError('Unsupported VRML value: '+s)
        if not math.isfinite(x) or abs(x)>1e9:raise ValueError('VRML coordinate/value outside bounds.')
        return x
    def value(self,depth):
        if self.peek()=='[':
            self.pop();items=[]
            while self.peek()!=']':
                if self.peek() in ('DEF','USE','NULL') or (self.i+1<len(self.tokens) and self.tokens[self.i+1]=='{'):items.append(self.node(depth+1))
                else:items.append(self.scalar())
            self.pop();return items
        return self.node(depth+1)
    def node(self,depth=0):
        if depth>64:raise ValueError('VRML nesting limit.')
        tag=self.pop()
        if tag=='NULL':return None
        if tag=='USE':
            name=self.pop()
            if name not in self.defs:raise ValueError('Unresolved VRML USE name.')
            return self.defs[name]
        name=None
        if tag=='DEF':name=self.pop();tag=self.pop()
        if tag in ('Script','Inline','PROTO','EXTERNPROTO','ROUTE'):raise ValueError('Executable or external VRML nodes are not previewed: '+tag)
        self.take('{');fields={}
        while self.peek()!='}':
            key=self.pop()
            if key in ARITY:
                n=ARITY[key];value=[self.scalar() for _ in range(n)];fields[key]=value if n>1 else value[0]
            elif key in NODEFIELDS or self.peek()=='[':fields[key]=self.value(depth+1)
            elif key in ('description','name'):fields[key]=self.scalar()
            else:raise ValueError('Unsupported VRML field: '+key+'. Original file is preserved.')
        self.pop();node={'type':tag,'fields':fields}
        if name:self.defs[name]=node
        return node
    def parse(self):
        nodes=[]
        while self.peek():nodes.append(self.node())
        return nodes

def vrml(raw):
    nodes=VRML(raw.decode('utf-8-sig')).parse();mesh=Mesh()
    def draw(n,matrix,depth=0):
        if not n:return
        if depth>64:raise ValueError('VRML scene nesting limit.')
        kind=n['type'];f=n['fields']
        if kind in ('Transform','Group','Collision','Anchor'):
            mat=multiply(matrix,transform(n)) if kind=='Transform' else matrix
            children=f.get('children',[]);children=children if isinstance(children,list) else [children]
            for c in children:draw(c,mat,depth+1)
        elif kind=='Switch':
            choice=int(f.get('whichChoice',-1));children=f.get('choice',[])
            if 0<=choice<len(children):draw(children[choice],matrix,depth+1)
        elif kind=='Shape':
            geo=f.get('geometry');app=f.get('appearance') or {};material=app.get('fields',{}).get('material') or {};mf=material.get('fields',{});color=mf.get('diffuseColor',[.66,.68,.73])
            if app.get('fields',{}).get('texture'):mesh.warnings.append('External textures are not loaded; material color is used.')
            if mf.get('transparency'):mesh.warnings.append('Transparency is not rendered; geometry shown opaque.')
            if not geo:return
            g=geo['fields'];gkind=geo['type']
            if gkind=='IndexedFaceSet':
                coord=g.get('coord') or {};points=coord.get('fields',{}).get('point',[])
                if len(points)%3:raise ValueError('Invalid VRML coordinate array.')
                coords=[points[i:i+3] for i in range(0,len(points),3)];face=[]
                if g.get('color') or g.get('normal'):mesh.warnings.append('Per-vertex colors/normals simplified to material color and flat shading.')
                for value in g.get('coordIndex',[]):
                    if int(value)!=value:raise ValueError('Noninteger VRML index.')
                    i=int(value)
                    if i==-1:
                        mesh.polygon(coords,face if g.get('ccw',True) else list(reversed(face)),color,matrix);face=[]
                    else:face.append(i)
                if face:mesh.polygon(coords,face,color,matrix)
            elif gkind=='Box':
                sx,sy,sz=[v/2 for v in g.get('size',[2,2,2])];coords=[[x,y,z] for x in (-sx,sx) for y in (-sy,sy) for z in (-sz,sz)]
                for face in ([0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]):mesh.polygon(coords,face,color,matrix)
            elif gkind in ('Cylinder','Cone','Sphere'):
                mesh.warnings.append(gkind+' tessellated with a fixed 32-segment inspection mesh.')
                segments=32;r=g.get('radius',g.get('bottomRadius',1));h=g.get('height',2)
                if gkind=='Sphere':
                    rings=16
                    for j in range(rings):
                        for i in range(segments):
                            coords=[]
                            for lat,lon in ((j,i),(j+1,i),(j+1,i+1),(j,i+1)):
                                a=math.pi*lat/rings;b=2*math.pi*lon/segments;coords.append(point([r*math.sin(a)*math.cos(b),r*math.cos(a),r*math.sin(a)*math.sin(b)],matrix))
                            mesh.triangle(coords[0],coords[1],coords[2],color);mesh.triangle(coords[0],coords[2],coords[3],color)
                else:
                    for i in range(segments):
                        a=i*2*math.pi/segments;b=(i+1)*2*math.pi/segments
                        bottom=[[r*math.cos(a),-h/2,r*math.sin(a)],[r*math.cos(b),-h/2,r*math.sin(b)]];top=[[0,h/2,0],[0,h/2,0]] if gkind=='Cone' else [[x,h/2,z] for x,y,z in bottom]
                        if g.get('side',True):mesh.polygon(bottom+list(reversed(top)) if gkind!='Cone' else bottom+[top[0]],list(range(4 if gkind!='Cone' else 3)),color,matrix)
                        if g.get('bottom',True):mesh.triangle(point([0,-h/2,0],matrix),point(bottom[1],matrix),point(bottom[0],matrix),color)
                        if gkind=='Cylinder' and g.get('top',True):mesh.triangle(point([0,h/2,0],matrix),point(top[0],matrix),point(top[1],matrix),color)
            else:mesh.warnings.append('Unsupported VRML geometry omitted: '+gkind)
        elif kind not in ('WorldInfo','NavigationInfo','Viewpoint','Background','DirectionalLight','PointLight'):
            mesh.warnings.append('Unsupported VRML scene node omitted: '+kind)
    for n in nodes:draw(n,IDENTITY)
    return mesh.result('VRML97')

def stl(raw):
    mesh=Mesh();color=[.66,.69,.75]
    if len(raw)>=84 and 84+struct.unpack_from('<I',raw,80)[0]*50==len(raw):
        count=struct.unpack_from('<I',raw,80)[0]
        if count>MAX_TRIANGLES:raise ValueError('STL triangle limit exceeded.')
        for i in range(count):
            v=struct.unpack_from('<12fH',raw,84+i*50);mesh.triangle(v[3:6],v[6:9],v[9:12],color)
    else:
        text=raw.decode('ascii');vertices=re.findall(r'\bvertex\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)',text)
        if len(vertices)%3:raise ValueError('Invalid ASCII STL.')
        for i in range(0,len(vertices),3):mesh.triangle(*[[float(x) for x in p] for p in vertices[i:i+3]],color)
    return mesh.result('STL')

def obj(raw):
    mesh=Mesh();coords=[]
    for line in raw.decode('utf-8-sig').splitlines():
        values=line.split()
        if not values:continue
        if values[0]=='v':
            if len(values)!=4:raise ValueError('OBJ homogeneous/color vertices are unsupported.')
            coords.append([float(x) for x in values[1:]])
            if len(coords)>MAX_VERTICES:raise ValueError('OBJ vertex limit exceeded.')
        elif values[0]=='f':
            ind=[int(x.split('/')[0]) for x in values[1:]];ind=[i-1 if i>0 else len(coords)+i for i in ind];mesh.polygon(coords,ind,[.66,.69,.75])
        elif values[0] in ('mtllib','usemtl'):mesh.warnings.append('OBJ material files/textures are not read. Neutral material used.')
    return mesh.result('OBJ')

def unpack(raw,ext):
    if ext in ('.wrz','.stpz','.stepz'):
        if raw[:2]==b'PK':
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                files=[i for i in z.infolist() if not i.is_dir()]
                if len(files)!=1 or files[0].file_size>MAX_ASSET or files[0].flag_bits&1:raise ValueError('Compressed model must contain exactly one bounded unencrypted file.')
                with z.open(files[0]) as f:data=f.read(MAX_ASSET+1)
        elif raw[:2]==b'\x1f\x8b':
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:data=f.read(MAX_ASSET+1)
        else:raise ValueError('Unsupported compressed model container.')
        if len(data)>MAX_ASSET:raise ValueError('Unpacked model exceeds 64 MiB.')
        return data,'.wrl' if ext=='.wrz' else '.step'
    return raw,ext

def convert(raw,ext,cancel=None):
    if ext not in ('.wrl','.wrz','.stl','.obj','.step','.stp','.stpz','.stepz','.iges','.igs','.brep'):raise ValueError('No preview converter for '+ext+'. Original retained.')
    if cancel and cancel():raise InterruptedError('3D preview canceled; stored originals unchanged.')
    # No shell command or model-supplied path. Parser isolated and time bounded.
    with tempfile.TemporaryDirectory(prefix='wayricad-preview-') as temp:
        inp=Path(temp)/('model'+ext);out=Path(temp)/'mesh.json';inp.write_bytes(raw)
        proc=subprocess.Popen([sys.executable,'-m','bomstudio.meshworker',str(inp),str(out)],cwd=str(Path(__file__).resolve().parent.parent),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            start=time.monotonic()
            while proc.poll() is None:
                if cancel and cancel():raise InterruptedError('3D preview canceled; stored originals unchanged.')
                if time.monotonic()-start>60:raise ValueError('3D conversion exceeded 60-second limit; original remains stored.')
                time.sleep(.08)
            if not out.exists():raise ValueError('3D worker failed. STEP/IGES/BREP previews need the optional requirements-preview.txt installed in this interpreter; original files remain stored.')
            if out.stat().st_size>64*1024*1024:raise ValueError('Generated mesh exceeds preview memory limit.')
            result=json.loads(out.read_text())
            if 'error' in result:raise ValueError(result['error'])
            return result
        finally:
            if proc.poll() is None:proc.kill()
            proc.wait()
