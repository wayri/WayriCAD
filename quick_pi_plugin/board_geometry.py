"""Native KiCad copper geometry for a 2.5D sheet/barrel electrical model.

Copper curves are conservatively inscribed; holes are circumscribed. Native
integer Boolean unions retain filled-zone thermal spokes and disconnected
islands. No proximity snap, guessed fill or invented inter-layer bridge occurs.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path


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


def _copy(api,poly):return api.SHAPE_POLY_SET(poly)


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


def _bounds(poly):
    box=poly.BBox()
    return box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom()


def _intersects(a,b):
    return not (a[2]<b[0] or a[0]>b[2] or a[3]<b[1] or a[1]>b[3])


class _NativeContourIndex:
    """Index whole native contour bounds; never cut or rasterize geometry."""
    def __init__(self,api,polygons,cell_mm=2.):
        self.api=api;self.polygons=polygons;self.step=api.FromMM(cell_mm)
        self.records=[];self.grid={};self.large=[]
        for outer in range(polygons.OutlineCount()):
            for hole in [-1,*range(polygons.HoleCount(outer))]:
                chain=polygons.COutline(outer) if hole<0 else polygons.CHole(outer,hole)
                box=chain.BBox();bounds=(box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom())
                index=len(self.records);self.records.append((outer,hole,bounds))
                tiles=self._tiles(bounds)
                if tiles is None:self.large.append(index)
                else:
                    for tile in tiles:self.grid.setdefault(tile,[]).append(index)

    def _tiles(self,bounds):
        x0,y0,x1,y1=(int(value)//self.step for value in bounds)
        if (x1-x0+1)*(y1-y0+1)>1024:return None
        return ((x,y) for x in range(x0,x1+1) for y in range(y0,y1+1))

    def subset(self,bounds):
        """Keep relevant full outlines with their relevant full hole contours."""
        tiles=self._tiles(bounds)
        candidates=set(range(len(self.records))) if tiles is None else set(self.large)
        if tiles is not None:
            for tile in tiles:candidates.update(self.grid.get(tile,()))
        selected={}
        for index in sorted(candidates):
            outer,hole,box=self.records[index]
            if _intersects(bounds,box):selected.setdefault(outer,set()).add(hole)
        result=self.api.SHAPE_POLY_SET()
        for outer,holes in selected.items():
            if -1 not in holes:continue
            target=result.AddOutline(self.polygons.COutline(outer))
            for hole in sorted(holes-{-1}):result.AddHole(self.polygons.CHole(outer,hole),target)
        return result

    def subtract_from(self,contact):
        result=_copy(self.api,contact)
        local=self.subset(_bounds(contact))
        if local.OutlineCount():result.BooleanSubtract(local)
        return result


def _partition(api,copper,contacts,progress):
    """Split contact overlaps locally and subtract their union from copper once.

    Recutting the complete plane for every pad/via repeatedly copies thousands
    of drilled contours. Only the small contact regions need individual cuts;
    the background and all native contact boundaries retain the same domain.
    """
    if not contacts:return _polygons(copper,api)
    united=api.SHAPE_POLY_SET()
    for contact in contacts:united.Append(contact)
    united.Simplify()
    background=_copy(api,copper);background.BooleanSubtract(united)
    regions=[]
    for index,contact in enumerate(contacts):
        if progress and index%25==0 and progress('Partitioning contacts',index,len(contacts)) is False:
            raise ValueError('Geometry extraction cancelled; the board was not changed.')
        cut_bounds=_bounds(contact);next_regions=[];remaining=_copy(api,contact)
        for region,bounds in regions:
            if not _intersects(bounds,cut_bounds):
                next_regions.append((region,bounds));continue
            inside=_copy(api,region);inside.BooleanIntersection(contact)
            if not inside.OutlineCount():
                next_regions.append((region,bounds));continue
            outside=_copy(api,region);outside.BooleanSubtract(contact)
            next_regions.append((inside,_bounds(inside)))
            if outside.OutlineCount():next_regions.append((outside,_bounds(outside)))
            remaining.BooleanSubtract(region)
        if remaining.OutlineCount():next_regions.append((remaining,_bounds(remaining)))
        regions=next_regions
        if len(regions)>30000:
            raise ValueError('More than 30,000 contact regions; split the analysis scope before meshing.')
    return [polygon for region in [background,*[r for r,_ in regions]]
            for polygon in _polygons(region,api)]


def extract(board,net,*,source_path=None,stackup_override=None,curve_tolerance_mm=.005,progress=None):
    """Return JSON-compatible physical copper, pad electrodes and plated barrels.

    ``source_sha256`` hashes saved input bytes; ``geometry_sha256`` hashes this
    extracted geometry. A live board can differ from its saved source, so these
    identities are deliberately separate. Pads keep UUID IDs and ref.pad labels.
    """
    import pcbnew as api
    if getattr(api,'_wayricad_ipc',False) or not hasattr(api,'SHAPE_POLY_SET'):
        raise ValueError('Exact extraction requires the native KiCad polygon API.')
    net=str(net)
    if not net:raise ValueError('Choose a named electrical net.')
    error=api.FromMM(_positive(curve_tolerance_mm,'Curve tolerance'))
    if error<1:raise ValueError('Curve tolerance is smaller than KiCad integer geometry resolution.')
    path=Path(source_path or board.GetFileName()) if source_path or board.GetFileName() else None
    data=path.read_bytes() if path is not None else None
    layers=stackup(board,api,data.decode('utf-8-sig') if data else None,stackup_override)
    enabled=[row['id'] for row in layers]
    copper={layer:api.SHAPE_POLY_SET() for layer in enabled}
    holes={layer:api.SHAPE_POLY_SET() for layer in enabled}
    contacts={layer:[] for layer in enabled}
    terminals=[];barrels=[];counts={'tracks':0,'arcs':0,'pads':0,'zones':0,'vias':0,'plated_pads':0,'drilled_objects':0}
    warnings=['Copper curves use inscribed polygons and drills use circumscribed polygons at the stated tolerance; no geometric gap snapping is performed.']
    items=list(board.GetTracks())
    footprints=list(board.GetFootprints())
    pads=[pad for fp in footprints for pad in fp.Pads()]
    drawings=list(board.GetDrawings())+[item for fp in footprints for item in fp.GraphicalItems()]
    zones=list(board.Zones())+[zone for fp in footprints for zone in fp.Zones()]
    all_items=items+pads
    for index,item in enumerate(all_items):
        if progress and index%250==0 and progress('Reading copper',index,len(all_items)) is False:
            raise ValueError('Geometry extraction cancelled; the board was not changed.')
        via=isinstance(item,api.PCB_VIA);pad=isinstance(item,api.PAD)
        span=[layer for layer in enabled if item.IsOnLayer(layer)]
        if via:
            # Backdrills have different holes on different spans. A cylinder is
            # not a faithful substitute; reject until that model is supported.
            if any(getattr(item,name,lambda:None)() is not None for name in ('GetSecondaryDrillSize','GetTertiaryDrillSize')):
                raise ValueError('Backdrilled vias require an explicit stepped-barrel model: '+_uid(item))
            span=[layer for layer in enabled if enabled.index(item.TopLayer())<=enabled.index(layer)<=enabled.index(item.BottomLayer())]
        if pad or via:
            hole=_hole(api,item,error)
            hole_layers=span if via else enabled
            if hole.OutlineCount():
                counts['drilled_objects']+=1
                for layer in hole_layers:holes[layer].Append(hole)
        if item.GetNetname()!=net:continue
        terminal={'id':_uid(item),'pad_uuid':_uid(item),'reference':str(item.GetParentFootprint().GetReference()),
                  'pad_number':str(item.GetNumber()),'net':str(item.GetNetname()),
                  'label':item.GetParentFootprint().GetReference()+'.'+item.GetNumber(),'polygons':{}} if pad else None
        layer_diameters={};contact_polygons={}
        for layer in span:
            if (pad or via) and not item.FlashLayer(layer):continue
            poly=_shape(api,item,layer,error)
            if not poly.OutlineCount():continue
            copper[layer].Append(poly)
            if pad or via:
                contact=_copy(api,poly);contact.BooleanSubtract(_hole(api,item,error))
                if contact.OutlineCount():
                    contact_polygons[str(layer)]=_polygons(contact,api)
                    # Shared terminal/barrel list: clip once in native coordinates.
                    contacts[layer].append((contact,contact_polygons[str(layer)]))
                    if terminal is not None:terminal['polygons'][str(layer)]=contact_polygons[str(layer)]
            if via:layer_diameters[str(layer)]=api.ToMM(item.GetWidth(layer))
        if pad:
            counts['pads']+=1
            if terminal['polygons']:terminals.append(terminal)
        elif via:counts['vias']+=1
        else:counts['arcs' if isinstance(item,api.PCB_ARC) else 'tracks']+=1
        plated_pad=pad and item.GetAttribute()==api.PAD_ATTRIB_PTH
        if via or plated_pad:
            if plated_pad:
                size=item.GetDrillSize()
                if size.x<=0 or size.y<=0:raise ValueError('Plated pad has no valid drill: '+terminal['label'])
                if size.x!=size.y and item.GetDrillShape()!=api.PAD_DRILL_SHAPE_OBLONG:
                    raise ValueError('Only circular and obround plated drills are supported: '+terminal['label'])
                drill=min(api.ToMM(size.x),api.ToMM(size.y))
                drill_size=[api.ToMM(size.x),api.ToMM(size.y)]
                if item.GetSize().x<=size.x or item.GetSize().y<=size.y:
                    raise ValueError('Plated drill must fit within the copper land: '+terminal['label'])
                span=enabled[:]
                layer_diameters={str(layer):min(api.ToMM(item.GetSize().x),api.ToMM(item.GetSize().y)) for layer in span if str(layer) in contact_polygons}
                counts['plated_pads']+=1
            else:
                drill=api.ToMM(item.GetDrillValue());drill_size=[drill,drill]
            if not layer_diameters:raise ValueError('Plated barrel has no flashed copper contacts: '+_uid(item))
            if drill<=0 or any(d<=drill for d in layer_diameters.values()):
                raise ValueError('Barrel drill must be smaller than each copper land: '+_uid(item))
            position=item.GetPosition()
            for layer in span:contact_polygons.setdefault(str(layer),[])
            barrels.append({'id':_uid(item),'kind':'plated_pad' if plated_pad else 'via',
                            'layers':span,'x_mm':api.ToMM(position.x),'y_mm':api.ToMM(position.y),
                            'drill_mm':drill,'drill_size_mm':drill_size,
                            'drill_shape':'circle' if drill_size[0]==drill_size[1] else 'obround',
                            'drill_angle_deg':float(item.GetOrientationDegrees()) if plated_pad else 0.,
                            'diameter_mm':max(layer_diameters.values()),
                            'diameters_mm':layer_diameters,'polygons':contact_polygons})
    for item in drawings:
        if hasattr(item,'GetNetname') and item.GetNetname()==net:
            for layer in enabled:
                if item.IsOnLayer(layer):copper[layer].Append(_shape(api,item,layer,error))
    for zone in zones:
        if zone.GetIsRuleArea() or zone.GetNetname()!=net:continue
        for layer in enabled:
            if not zone.IsOnLayer(layer):continue
            if not zone.IsFilled() or not zone.HasFilledPolysForLayer(layer):
                raise ValueError('Selected-net zone is unfilled on '+board.GetLayerName(layer)+'. Fill zones in KiCad and save before extraction.')
            copper[layer].Append(zone.GetFilledPolysList(layer));counts['zones']+=1
    total_area=0.0
    for row in layers:
        layer=row['id'];cu=copper[layer]
        cu.Simplify();holes[layer].Simplify();cu.BooleanSubtract(holes[layer])
        row['polygons']=_polygons(cu,api)
        total_area+=abs(cu.Area())/(api.FromMM(1)**2)
        drill_index=_NativeContourIndex(api,holes[layer])
        clean_contacts=[]
        for index,(contact,records) in enumerate(contacts[layer]):
            if progress and index%250==0 and progress('Clipping contacts · '+row['name'],index,len(contacts[layer])) is False:
                raise ValueError('Geometry extraction cancelled; the board was not changed.')
            # Each contact is a subset of a selected-net shape appended to this
            # layer's copper. Intersecting final copper is exactly equivalent
            # to subtracting drilled voids from that contact. The spatial index
            # omits only whole native contours outside the contact bounding box.
            clipped=drill_index.subtract_from(contact)
            records[:]=_polygons(clipped,api)
            if clipped.OutlineCount():clean_contacts.append(clipped)
        row['mesh_regions']=_partition(api,cu,clean_contacts,progress) if cu.OutlineCount() else []
    if total_area<=0:raise ValueError('The selected net has no extractable copper.')
    pad_catalog=[{'id':_uid(p),'pad_uuid':_uid(p),'reference':str(p.GetParentFootprint().GetReference()),
                  'pad_number':str(p.GetNumber()),'net':str(p.GetNetname()),
                  'layer_ids':[int(layer) for layer in enabled if p.IsOnLayer(layer)]} for p in pads]
    result={'pad_catalog':pad_catalog,'schema_version':1,'net':net,'layers':layers,'terminals':terminals,'vias':barrels,
            'counts':counts,'warnings':warnings,'area_mm2':total_area,
            'curve_tolerance_mm':float(curve_tolerance_mm),'z_convention':'Copper midplanes; positive Z down from the top copper surface.',
            'stackup_source':'explicit_override' if stackup_override is not None else 'saved_board',
            'source_path':str(path.resolve()) if path is not None else None,
            'source_sha256':hashlib.sha256(data).hexdigest() if data is not None else None}
    result['geometry_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result
