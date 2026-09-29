"""KiCad copper-layer and stackup helpers for QuickTherm."""
from __future__ import annotations
import math

def _positive(value,name):
    value=float(value)
    if not math.isfinite(value) or value<=0:
        raise ValueError(name+' must be finite and positive.')
    return value


def _top_level(text, tag):
    """Read one root child without materializing a multi-million-node PCB."""
    depth=0;quote=False;escape=False;comment=False;start=None;i=0
    while i<len(text):
        c=text[i]
        if comment:
            if c in '\r\n':comment=False
        elif quote:
            if escape:escape=False
            elif c=='\\':escape=True
            elif c=='"':quote=False
        elif c=='"':quote=True
        elif c in ';#':comment=True
        elif c=='(':
            if depth==1:
                j=i+1
                while j<len(text) and text[j].isspace():j+=1
                k=j
                while k<len(text) and not text[k].isspace() and text[k] not in '()':k+=1
                if text[j:k]==tag:start=i
            depth+=1
        elif c==')':
            depth-=1
            if start is not None and depth==1:return text[start:i+1]
        i+=1
    raise ValueError('Saved board has no '+tag+' section. Supply an explicit stackup override.')


def stackup(board,api,source_text=None,override=None):
    """Copper mid-plane Z in mm, increasing from the top copper surface down."""
    enabled=list(board.GetEnabledLayers().CuStack())
    canonical={int(layer):str(api.LayerName(layer)) for layer in enabled}
    display={int(layer):str(board.GetLayerName(layer)) for layer in enabled}
    names={name:layer for layer,name in canonical.items()}
    names.update({name:layer for layer,name in display.items()})
    result=[]
    if override is not None:
        if not isinstance(override,list):raise ValueError('Stackup override must be a list of copper layer records.')
        for row in override:
            layer=row.get('id',names.get(row.get('name','')))
            if layer is None or int(layer) not in canonical:raise ValueError('Stackup override names an unavailable copper layer.')
            z=float(row['z_mm']);thickness=_positive(row['thickness_mm'],'Copper thickness')
            if not math.isfinite(z):raise ValueError('Copper Z positions must be finite.')
            result.append({'id':int(layer),'name':canonical[int(layer)],'display_name':display[int(layer)],
                           'z_mm':z,'thickness_mm':thickness})
    else:
        if not source_text:raise ValueError('No saved stackup is available. Supply explicit layer Z positions and copper thicknesses.')
        from wayricad_runtime.schematic_sexpr import parse
        setup=parse(_top_level(source_text,'setup'))
        stacks=setup.nodes('stackup')
        if len(stacks)!=1:raise ValueError('Save an explicit board stackup or supply a stackup override; thicknesses are never guessed.')
        entries=stacks[0].nodes('layer')
        copper=[i for i,row in enumerate(entries) if row.get('type').lower()=='copper']
        if not copper:raise ValueError('The saved stackup contains no explicit copper layers.')
        z=0.0
        for row in entries[copper[0]:copper[-1]+1]:
            values=row.nodes('thickness')
            if len(values)!=1 or len(values[0].atoms)!=2:
                raise ValueError('Ambiguous or missing stackup thickness for '+row.val()+'. Supply an explicit override.')
            thickness=_positive(values[0].val(),'Stackup thickness for '+row.val())
            if row.get('type').lower()=='copper':
                layer=names.get(row.val())
                if layer is None:raise ValueError('Saved stackup has an unknown copper layer: '+row.val())
                result.append({'id':layer,'name':canonical[layer],'display_name':display[layer],
                               'z_mm':z+thickness/2,'thickness_mm':thickness})
            z+=thickness
    if len(result)!=len(enabled) or {r['id'] for r in result}!=set(canonical):
        raise ValueError('Stackup must specify each enabled copper layer exactly once.')
    order={int(layer):i for i,layer in enumerate(enabled)}
    result.sort(key=lambda row:order[row['id']])
    for left,right in zip(result,result[1:]):
        if right['z_mm']-right['thickness_mm']/2<=left['z_mm']+left['thickness_mm']/2:
            raise ValueError('Copper layers overlap or have no positive dielectric separation in the stackup.')
    return result


def _polygons(poly,api):
    def ring(chain):
        points=[[api.ToMM(chain.CPoint(i).x),api.ToMM(chain.CPoint(i).y)] for i in range(chain.PointCount())]
        if points and points[0]==points[-1]:points.pop()
        return points
    return [{'outer':ring(poly.COutline(i)),
             'holes':[ring(poly.CHole(i,h)) for h in range(poly.HoleCount(i))]}
            for i in range(poly.OutlineCount())]


def _uid(item):return item.m_Uuid.AsString()


def _shape(api,item,layer,error):
    poly=api.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(poly,layer,0,error,api.ERROR_INSIDE)
    return poly


def _hole(api,item,error):
    poly=api.SHAPE_POLY_SET()
    shape=item.GetEffectiveHoleShape()
    if shape and shape.GetWidth()>0:
        shape.TransformToPolygon(poly,error,api.ERROR_OUTSIDE)
    return poly
