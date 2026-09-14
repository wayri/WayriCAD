"""Dependency-free, non-executable SVG inspection of captured KiCad definitions.

Not KiCad's renderer: supported primitives are drawn, unsupported content gets a
visible warning. Raw source files are not injected as SVG/HTML or executed.
"""
from __future__ import annotations
import html
import math
import re
from .sexpr import parse

MAX_PRIMITIVES=20000

def num(v,default=0):
    if v in ('',None):v=default
    try:x=float(v)
    except (ValueError,TypeError) as exc:raise ValueError('Invalid numeric preview coordinate.') from exc
    if not math.isfinite(x) or abs(x)>1e6:raise ValueError('Preview coordinate outside finite bounds.')
    return x

def pt(n,default=(0,0)):
    return (num(n.val(1)),num(n.val(2))) if n else default

def fmt(n):return format(num(n),'.8g')
def esc(s):return html.escape(str(s),quote=True)

class Drawing:
    def __init__(self,title):self.title=title;self.parts=[];self.bounds=[];self.warnings=[];self.labels=[]
    def add(self,s,points=()):
        if len(self.parts)>MAX_PRIMITIVES:raise ValueError('Preview exceeds 20,000 primitives.')
        self.parts.append(s);self.bounds.extend(points)
    def line(self,a,b,color='#ac3638',width=.12):
        self.add(f'<line x1="{fmt(a[0])}" y1="{fmt(a[1])}" x2="{fmt(b[0])}" y2="{fmt(b[1])}" stroke="{color}" stroke-width="{fmt(width)}"/>',[a,b])
    def circle(self,c,r,color='#ac3638',fill='none',width=.12):
        r=abs(num(r));self.add(f'<circle cx="{fmt(c[0])}" cy="{fmt(c[1])}" r="{fmt(r)}" stroke="{color}" fill="{fill}" stroke-width="{fmt(width)}"/>',[(c[0]-r,c[1]-r),(c[0]+r,c[1]+r)])
    def poly(self,points,closed=False,color='#ac3638',fill='none',width=.12):
        if len(points)>10000:raise ValueError('Preview polygon too large.')
        tag='polygon' if closed else 'polyline';v=' '.join(f'{fmt(x)},{fmt(y)}' for x,y in points)
        self.add(f'<{tag} points="{v}" stroke="{color}" stroke-width="{fmt(width)}" stroke-linejoin="round" fill="{fill}"/>',points)
    def label(self,value,c,size=.8,color='#243a54',angle=0):
        value=str(value);size=max(.08,min(5,num(size)));angle=num(angle)
        # Never output asset-supplied styles, URLs, font data or markup.
        self.add(f'<text x="{fmt(c[0])}" y="{fmt(c[1])}" text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-size="{fmt(size)}" fill="{color}" transform="rotate({fmt(angle)} {fmt(c[0])} {fmt(c[1])})">{esc(value[:300])}</text>',[(c[0]-len(value[:80])*size*.32,c[1]-size),(c[0]+len(value[:80])*size*.32,c[1]+size)])
        if len(value)>300:self.warnings.append('Display label limited to 300 characters; full value retained in metadata.')
    def arc(self,a,m,b,color='#ac3638',width=.12):
        # Circle through 3 points; choose the sweep that includes the middle point.
        ax,ay=a;mx,my=m;bx,by=b;d=2*(ax*(my-by)+mx*(by-ay)+bx*(ay-my))
        if abs(d)<1e-10:self.poly([a,m,b],color=color,width=width);return
        aa=ax*ax+ay*ay;mm=mx*mx+my*my;bb=bx*bx+by*by
        cx=(aa*(my-by)+mm*(by-ay)+bb*(ay-my))/d;cy=(aa*(bx-mx)+mm*(ax-bx)+bb*(mx-ax))/d
        r=math.hypot(ax-cx,ay-cy);t0=math.atan2(ay-cy,ax-cx);tm=(math.atan2(my-cy,mx-cx)-t0)%(2*math.pi);tb=(math.atan2(by-cy,bx-cx)-t0)%(2*math.pi)
        sweep=tm<=tb;span=tb if sweep else 2*math.pi-tb
        self.add(f'<path d="M {fmt(ax)} {fmt(ay)} A {fmt(r)} {fmt(r)} 0 {int(span>math.pi)} {int(sweep)} {fmt(bx)} {fmt(by)}" fill="none" stroke="{color}" stroke-width="{fmt(width)}"/>',[(cx-r,cy-r),(cx+r,cy+r)])
    def finish(self):
        b=self.bounds or [(-5,-5),(5,5)];x0=min(x for x,y in b);x1=max(x for x,y in b);y0=min(y for x,y in b);y1=max(y for x,y in b);margin=max(.5,max(x1-x0,y1-y0)*.08)
        box=[x0-margin,y0-margin,max(1,x1-x0+2*margin),max(1,y1-y0+2*margin)]
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(self.title)}" viewBox="'+ ' '.join(fmt(v) for v in box)+'"><title>'+esc(self.title)+'</title><rect x="'+fmt(box[0])+'" y="'+fmt(box[1])+'" width="'+fmt(box[2])+'" height="'+fmt(box[3])+'" fill="#fbfcff"/>'+''.join(self.parts)+'</svg>'
        return {'svg':svg,'bounds':box,'warnings':list(dict.fromkeys(self.warnings)),'primitive_count':len(self.parts)}


def svg_preview(raw,kind,unit=1,style=1,layers=None,show_labels=True):
    if kind not in ('symbol','footprint'):raise ValueError('SVG preview requires symbol or footprint.')
    if not isinstance(unit,int) or isinstance(unit,bool) or unit<1 or unit>100:raise ValueError('Unit must be 1..100.')
    if style not in (1,2):raise ValueError('Choose normal (1) or alternate (2) body style.')
    text=raw.decode('utf-8-sig');t=parse(text)
    if t.tag!=kind:raise ValueError('Captured native asset type differs.')
    d=Drawing(kind.title()+' inspection: '+t.val());flip=-1 if kind=='symbol' else 1
    xy=lambda n:(pt(n)[0],flip*pt(n)[1]);pins=[];units=set();available_layers=set()
    if layers is not None and (not isinstance(layers,list) or any(not isinstance(x,str) for x in layers)):raise ValueError('Layers must be a string list.')
    board_angle=num(t.one('at').val(3,'0')) if kind=='footprint' and t.one('at') else 0
    if kind=='symbol':
        nodes=[]
        if t.one('extends'):d.warnings.append('Unflattened parent: inherited graphics are unavailable; re-harvest to resolve the parent.')
        for n in t.nodes('symbol'):
            m=re.search(r'_(\d+)_(\d+)$',n.val())
            if not m:d.warnings.append('Unrecognized symbol unit name: '+n.val());continue
            u,st=map(int,m.groups());units.add(u)
            if u in (0,unit) and st in (0,style):nodes.extend(n.children)
        if not nodes:d.warnings.append('No graphics in selected unit/body style.')
    else:nodes=t.children
    palettes={'F.Cu':'#bc6831','B.Cu':'#406db1','F.SilkS':'#21848b','B.SilkS':'#538b59','F.Fab':'#6e6f77','B.Fab':'#6e6f77','F.CrtYd':'#97418e','B.CrtYd':'#97418e','Edge.Cuts':'#9b8134'}
    for n in nodes:
        tag=n.tag;layer=n.get('layer');available_layers.add(layer) if layer else None
        if layer and layers is not None and layer not in layers:continue
        color=palettes.get(layer,'#ac3638' if kind=='symbol' else '#5f6878');stroke=n.one('stroke');w=num(stroke.get('width') if stroke else n.get('width'),.12) or .1
        fill=n.one('fill');filled=fill and fill.get('type') not in ('','none');fc='#edf0df' if filled else 'none'
        if tag in ('rectangle','fp_rect'):
            a=xy(n.one('start'));b=xy(n.one('end'));d.poly([a,(b[0],a[1]),b,(a[0],b[1])],True,color,fc,w)
        elif tag in ('polyline','fp_poly','fp_line'):
            points=[xy(c) for c in n.one('pts').nodes('xy')] if n.one('pts') else [xy(n.one('start')),xy(n.one('end'))]
            d.poly(points,tag=='fp_poly',color,fc,w)
        elif tag in ('circle','fp_circle'):
            c=xy(n.one('center'));r=num(n.get('radius')) if kind=='symbol' else math.dist(c,xy(n.one('end')));d.circle(c,r,color,fc,w)
        elif tag in ('arc','fp_arc'):
            if all(n.one(x) for x in ('start','mid','end')):d.arc(xy(n.one('start')),xy(n.one('mid')),xy(n.one('end')),color,w)
            else:d.warnings.append('Legacy arc syntax is not rendered.')
        elif tag=='pin':
            a=xy(n.one('at'));angle=math.radians(num(n.one('at').val(3,'0')));length=num(n.get('length'));b=(a[0]+math.cos(angle)*length,a[1]-math.sin(angle)*length)
            hidden=any(a.value=='hide' for a in n.atoms) or n.get('hide')=='yes';d.line(a,b,'#87949f' if hidden else '#99454b',.14);d.circle(a,.12,'#99454b',width=.07)
            name=n.get('name');number=n.get('number');pins.append({'number':number,'name':name,'electrical_type':n.val(),'shape':n.val(2),'hidden':hidden})
            if show_labels:
                d.label(number,((a[0]+b[0])/2,(a[1]+b[1])/2-.45),.65)
                if name not in ('','~'):d.label(name,(b[0]+math.cos(angle)*1.05,b[1]-math.sin(angle)*1.05),.65)
            if n.val(2) not in ('line',''):d.warnings.append('Pin decorative shapes are simplified; inspect electrical pin names/types and original symbol.')
        elif tag=='pad':
            layer_node=n.one('layers');pl=[a.value for a in layer_node.atoms[1:]] if layer_node else []
            available_layers.update(pl)
            if layers is not None and not any(x in layers or ('*.Cu' in pl and x.endswith('.Cu')) for x in pl):continue
            a=xy(n.one('at'));sx,sy=pt(n.one('size'));angle=-(num(n.one('at').val(3,'0'))-board_angle) if n.one('at') else board_angle
            if sx<=0 or sy<=0:d.warnings.append('Pad has invalid or missing size.');continue
            shape=n.val(3);r=math.radians(angle);trans=lambda x,y:(a[0]+x*math.cos(r)-y*math.sin(r),a[1]+x*math.sin(r)+y*math.cos(r))
            col='#bc6831' if 'F.Cu' in pl or '*.Cu' in pl else '#406db1';rr=min(sx,sy)/2 if shape in ('circle','oval') else min(sx,sy)*num(n.get('roundrect_rratio'),.25) if shape=='roundrect' else 0
            if shape not in ('circle','oval','rect','roundrect'):d.warnings.append('Pad '+n.val()+': unsupported '+shape+' shape shown by its declared size envelope, not exact copper.')
            d.add(f'<rect x="{fmt(a[0]-sx/2)}" y="{fmt(a[1]-sy/2)}" width="{fmt(sx)}" height="{fmt(sy)}" rx="{fmt(rr)}" fill="{col}" fill-opacity="0.85" stroke="{col}" stroke-width="0.04" transform="rotate({fmt(angle)} {fmt(a[0])} {fmt(a[1])})"/>',[trans(x,y) for x in (-sx/2,sx/2) for y in (-sy/2,sy/2)])
            drill=n.one('drill')
            if drill:
                vals=[num(x.value) for x in drill.atoms[1:] if x.value!='oval']
                if vals:
                    dx=vals[0];dy=vals[-1];d.add(f'<ellipse cx="{fmt(a[0])}" cy="{fmt(a[1])}" rx="{fmt(dx/2)}" ry="{fmt(dy/2)}" fill="#fbfcff" transform="rotate({fmt(angle)} {fmt(a[0])} {fmt(a[1])})"/>')
                if drill.one('offset'):d.warnings.append('Drill-offset preview is simplified; use declared qualification geometry.')
            if show_labels:d.label(n.val(),a,min(.65,min(sx,sy)*.55),'#ffffff')
        elif tag in ('text','fp_text','property'):
            if not show_labels:continue
            effects=n.one('effects');hidden=any(x.value=='hide' for x in n.atoms) or n.get('hide')=='yes' or (effects and (effects.get('hide')=='yes' or any(x.value=='hide' for x in effects.atoms)))
            if hidden:continue
            label=n.val(2) if tag in ('fp_text','property') else n.val();font=effects.one('font') if effects else None;size=pt(font.one('size'),(.8,.8))[1] if font else .8
            d.label(label,xy(n.one('at')),size,color,-(num(n.one('at').val(3,'0'))-(board_angle if kind=='footprint' else 0)) if n.one('at') else 0)
        elif tag in ('bezier','fp_curve','text_box','fp_text_box','image','zone'):
            d.warnings.append('Unsupported preview primitive: '+tag+'. Original retained.')
    if kind=='symbol' and show_labels:
        visible={n.val() for n in nodes if n.tag=='property'}
        for n in t.nodes('property'):
            if n.val() in ('Reference','Value') and n.val() not in visible:d.label(n.val(2),xy(n.one('at')),1)
    if board_angle:d.warnings.append('Saved board placement is normalized for this local footprint inspection.')
    return {'schema':'wayricad-native-preview-1','kind':kind,'name':t.val(),'unit':unit,'style':style,'units':sorted(units-{0}) or [1],
            'layers':sorted(available_layers),'pins':pins,'renderer':'WayriCAD bounded SVG inspection, not native KiCad',**d.finish()}
