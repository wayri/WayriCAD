"""Explicit PCB compatibility boundary backed by the official IPC API.

No SWIG import. Stable net names are mapped to session-local comparison IDs;
these IDs are never sent to KiCad as deprecated native net codes.
"""
from pathlib import Path
from types import ModuleType, SimpleNamespace
import hashlib
import math
import uuid


class UnsupportedCapability(RuntimeError):
    pass


class Box:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
    def GetLeft(self): return self.left
    def GetTop(self): return self.top
    def GetRight(self): return self.right
    def GetBottom(self): return self.bottom
    def GetWidth(self): return self.right-self.left
    def GetHeight(self): return self.bottom-self.top
    def Contains(self, point): return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom
    def Inflate(self, amount):
        self.left -= amount; self.top -= amount; self.right += amount; self.bottom += amount
        return self


def uid(raw):
    # Footprint fields have FieldId rather than KIID. Their text owns the UUID.
    identity = raw.id
    return str(identity.value if hasattr(identity, 'value') else raw.text.id.value)


class LibraryID:
    def __init__(self, raw): self.raw = raw
    def GetLibItemName(self): return self.raw.name
    def GetLibNickname(self): return self.raw.library
    def Format(self): return str(self.raw)
    def __str__(self): return str(self.raw)


class Net:
    def __init__(self, board, name): self.board, self.name = board, name
    def GetNetname(self): return self.name
    def GetNetCode(self): return self.board.net_id(self.name)
    def GetNetClassName(self):
        if not self.name:return ''
        classes=self.board.raw.get_netclass_for_nets(self.board.types.Net(name=self.name))
        if self.name not in classes:raise UnsupportedCapability('KiCad did not return the net class for '+self.name+'.')
        return classes[self.name].name


class Item:
    def __init__(self, board, raw, parent=None, existing=True):
        self.board, self.raw, self.parent, self.existing = board, raw, parent, existing
        self.m_Uuid = SimpleNamespace(AsString=lambda: uid(self.raw))
    def GetUuid(self): return self.m_Uuid
    def GetClass(self):
        names={'FootprintInstance':'FOOTPRINT','Pad':'PAD','Track':'PCB_TRACK','ArcTrack':'PCB_ARC','Via':'PCB_VIA','Group':'PCB_GROUP'}
        return names.get(type(self.raw).__name__,type(self.raw).__name__)
    def IsSelected(self): return uid(self.raw) in self.board.selected_ids()
    def SetSelected(self): self.board.raw.add_to_selection([self.raw])
    def ClearSelected(self): self.board.raw.remove_from_selection([self.raw])
    def HasSelectedAncestorGroup(self): return self.IsSelected()
    def IsLocked(self): return bool(getattr(self.raw,'locked',False))
    def GetParent(self): return self.parent or self.board
    def GetParentFootprint(self): return self.parent
    def GetPosition(self):
        if isinstance(self.raw,self.board.types.Field):return self.raw.text.position
        if isinstance(self.raw,(self.board.types.Track,self.board.types.ArcTrack)):return self.raw.start
        return self.raw.position
    def SetPosition(self,p): self.raw.position=p
    def GetLayer(self):
        if hasattr(self.raw,'layer'): return self.raw.layer
        layers=self.GetLayerSet().Seq()
        if not layers: raise UnsupportedCapability('Item has no copper layers.')
        return layers[0]
    def SetLayer(self,layer): self.raw.layer=layer
    def GetLayerName(self): return self.board.GetLayerName(self.GetLayer())
    def GetLayerSet(self):
        layers = list(self.raw.padstack.layers) if hasattr(self.raw,'padstack') else list(self.raw.layers) if hasattr(self.raw,'layers') else [self.raw.layer]
        if isinstance(self.raw,self.board.types.Via):
            copper = self.board.GetEnabledLayers().CuStack()
            start, end = self.TopLayer(), self.BottomLayer()
            if start not in copper or end not in copper:
                raise UnsupportedCapability('Via span contains a disabled copper layer.')
            a,b=sorted((copper.index(start),copper.index(end)))
            layers=copper[a:b+1]
        from kipy.util.board_layer import is_copper_layer
        return SimpleNamespace(Seq=lambda: layers, Contains=lambda layer: layer in layers,
                               CuStack=lambda: [layer for layer in layers if is_copper_layer(layer)])
    def IsOnLayer(self,layer): return self.GetLayerSet().Contains(layer)
    def GetNetname(self): return getattr(getattr(self.raw,'net',None),'name','')
    def GetNetCode(self): return self.board.net_id(self.GetNetname())
    def GetNet(self): return Net(self.board,self.GetNetname())
    def GetNetClassName(self):return self.GetNet().GetNetClassName()
    def SetNetCode(self,code): self.raw.net=self.board.types.Net(name=self.board.net_names[code])
    def SetNet(self,net): self.SetNetCode(net.GetNetCode())
    def GetReference(self): return self.raw.reference_field.text.value
    def GetValue(self): return self.raw.value_field.text.value
    def GetLibDescription(self): return self.raw.description_field.text.value
    def SetReference(self,value): self.raw.reference_field.text.value=value; self.flush()
    def SetValue(self,value): self.raw.value_field.text.value=value; self.flush()
    def GetFPID(self):
        return LibraryID(self.raw.definition.id)
    def GetPath(self): return SimpleNamespace(AsString=lambda:'/'+'/'.join(p.value for p in self.raw.sheet_path.path))
    def GetSheetname(self): return self.raw.sheet_path.path_human_readable
    def GetSheetfile(self):
        raise UnsupportedCapability('The board IPC API does not expose the schematic sheet filename.')
    def GetAttributes(self):
        attrs=self.raw.attributes
        return ((1 if attrs.exclude_from_bill_of_materials else 0) |
                (2 if attrs.exclude_from_position_files else 0) |
                (4 if attrs.do_not_populate else 0))
    def IsDNP(self): return self.raw.attributes.do_not_populate
    def Pads(self): return [self.board.wrap(p,self) for p in self.raw.definition.pads]
    def GraphicalItems(self):return [self.board.wrap(p,self) for p in self.raw.definition.shapes]
    def GetFields(self): return [self.board.wrap(f,self) for f in self.raw.texts_and_fields if isinstance(f,self.board.types.Field)]
    def GetProperties(self): return {f.GetName():f.GetText() for f in self.GetFields()}
    def GetName(self): return self.raw.name
    def GetText(self): return self.raw.text.value if isinstance(self.raw,self.board.types.Field) else self.raw.value
    def SetText(self,value):
        if isinstance(self.raw,self.board.types.Field): self.raw.text.value=value
        else: self.raw.value=value
        self.flush()
    def flush(self):
        if self.existing:
            target=self.parent.raw if self.parent else self.raw
            result=self.board.raw.update_items([target])
            if len(result)!=1 or uid(result[0])!=uid(target):
                raise RuntimeError('KiCad did not acknowledge the item update; inspect the board before retrying.')
    def GetNumber(self): return self.raw.number
    def GetPadName(self): return self.raw.number
    def GetAttribute(self): return 1 if self.raw.pad_type==self.board.types.PadType.PT_SMD else 0
    def GetOrientationDegrees(self):
        return self.raw.padstack.angle.degrees if hasattr(self.raw,'padstack') else self.raw.orientation.degrees
    def GetOrientation(self): return SimpleNamespace(AsDegrees=self.GetOrientationDegrees)
    def GetSize(self): return self.raw.padstack.copper_layers[0].size
    def GetShape(self): return self.raw.padstack.copper_layers[0].shape
    def GetRoundRectCornerRadius(self):
        copper=self.raw.padstack.copper_layers[0]
        return round(min(copper.size.x,copper.size.y)*copper.corner_rounding_ratio)
    def GetStart(self): return self.raw.position if isinstance(self.raw,self.board.types.Via) else self.raw.start
    def GetEnd(self): return self.raw.position if isinstance(self.raw,self.board.types.Via) else self.raw.end
    def SetStart(self,p): self.raw.start=p
    def SetEnd(self,p): self.raw.end=p
    def GetLength(self): return int(self.raw.length()) if callable(getattr(self.raw,'length',None)) else int(math.hypot(self.raw.end.x-self.raw.start.x,self.raw.end.y-self.raw.start.y))
    def GetWidth(self,layer=None):
        if isinstance(self.raw,self.board.types.Via):
            if layer is not None:
                copper=self.raw.padstack.copper_layer(layer)
                if copper is not None:return max(copper.size.x,copper.size.y)
            # Safety/overview callers without a layer need the largest copper extent.
            return max(max(c.size.x,c.size.y) for c in self.raw.padstack.copper_layers)
        return self.raw.width
    def SetWidth(self,value):
        if isinstance(self.raw,self.board.types.Via): self.raw.diameter=int(value)
        else: self.raw.width=int(value)
    def GetDrillValue(self): return self.raw.drill_diameter
    def GetDrillSize(self): return self.raw.padstack.drill.diameter
    def SetDrill(self,value): self.raw.drill_diameter=int(value)
    def SetViaType(self,value): self.raw.type=value
    def SetLayerPair(self,start,end): self.raw.padstack.drill.start_layer=start; self.raw.padstack.drill.end_layer=end
    def TopLayer(self): return self.raw.padstack.drill.start_layer
    def BottomLayer(self): return self.raw.padstack.drill.end_layer
    def SetName(self,value): self.raw.proto.name=value; self.flush()
    def GetItems(self):
        ids=list(self.raw.proto.items)
        return [self.board.wrap(x) for x in self.board.raw.get_items_by_id(ids)] if ids else []
    def AddItem(self,item):
        if not any(i.value==item.raw.id.value for i in self.raw.proto.items): self.raw.proto.items.append(item.raw.id)
        self.flush()
    def RemoveItem(self,item):
        ids=[x for x in self.raw.proto.items if x.value!=item.raw.id.value]
        del self.raw.proto.items[:];self.raw.proto.items.extend(ids);self.flush()
    def GetBoundingBox(self):
        box=self.board.raw.get_item_bounding_box(self.raw)
        if box is None: raise UnsupportedCapability('KiCad did not return geometry for this item.')
        return Box(box.pos.x,box.pos.y,box.pos.x+box.size.x,box.pos.y+box.size.y)
    def HitTest(self,position): return self.board.raw.hit_test(self.raw,position)
    def GetIsRuleArea(self): return self.raw.is_rule_area()
    def GetDoNotAllowVias(self): return self.raw.is_rule_area() and self.raw.proto.rule_area_settings.keepout_vias
    def GetDoNotAllowTracks(self): return self.raw.is_rule_area() and self.raw.proto.rule_area_settings.keepout_tracks
    def IsFilled(self): return self.raw.filled
    def HitTestFilledArea(self,layer,position):
        from .geometry import inside_polygon
        for poly in self.raw.filled_polygons.get(layer,[]):
            outline,holes=polygon_points(poly)
            if inside_polygon((position.x,position.y),outline,holes): return True
        return False
    def Outline(self): return IPCPolySet([self.raw.outline])
    def GetFilledPolysList(self,layer): return IPCPolySet(self.raw.filled_polygons.get(layer,[]))


def polygon_points(poly):
    def ring(line):
        if any(node.has_arc for node in line.nodes):
            raise UnsupportedCapability('Curved polygon boundaries require polygon tessellation before geometry generation.')
        return [(node.point.x,node.point.y) for node in line.nodes]
    return ring(poly.outline),[ring(h) for h in poly.holes]


class IPCPolySet:
    def __init__(self,polygons): self.polygons=[polygon_points(p) for p in polygons]
    @classmethod
    def from_rings(cls, rings):
        """Build material islands and cutouts from disjoint, simple closed rings."""
        from .geometry import inside_polygon, segment_segment_distance
        cleaned=[]
        for ring in rings:
            ring=list(ring)
            if ring and ring[-1]==ring[0]: ring.pop()
            if len(ring)<3 or len(set(ring))!=len(ring):
                raise UnsupportedCapability('Edge.Cuts contains a degenerate boundary.')
            cleaned.append(ring)
        edges=[(r,i,a,ring[(i+1)%len(ring)]) for r,ring in enumerate(cleaned) for i,a in enumerate(ring)]
        for index,(r,i,a,b) in enumerate(edges):
            for s,j,c,d in edges[index+1:]:
                if r==s and ((i-j)%len(cleaned[r]) in (1,len(cleaned[r])-1)):
                    continue
                if segment_segment_distance(a,b,c,d)==0:
                    raise UnsupportedCapability('Edge.Cuts boundaries intersect or touch. Repair the outline in KiCad.')
        containers=[[j for j,other in enumerate(cleaned) if j!=i and inside_polygon(ring[0],other)]
                    for i,ring in enumerate(cleaned)]
        result=cls([])
        for i,ring in enumerate(cleaned):
            if len(containers[i])%2==0:
                holes=[other for j,other in enumerate(cleaned)
                       if i in containers[j] and len(containers[j])==len(containers[i])+1]
                result.polygons.append((ring,holes))
        return result
    def OutlineCount(self): return len(self.polygons)
    def HoleCount(self,index): return len(self.polygons[index][1])
    def COutline(self,index): return self.chain(self.polygons[index][0])
    def CHole(self,index,hole): return self.chain(self.polygons[index][1][hole])
    @staticmethod
    def chain(points):
        return SimpleNamespace(PointCount=lambda:len(points),CPoint=lambda i:SimpleNamespace(x=points[i][0],y=points[i][1]))


class Board:
    def __init__(self,raw,types):
        self.raw,self.types=raw,types
        self.net_names={0:''};self.cache={}
        for net in raw.get_nets(): self.net_id(net.name)
    def net_id(self,name):
        for code,value in self.net_names.items():
            if value==name:return code
        code=len(self.net_names);self.net_names[code]=name;return code
    def wrap(self,raw,parent=None,existing=True):
        key=uid(raw)
        if key and key in self.cache:
            item=self.cache[key];item.raw=raw
            if parent is not None:item.parent=parent
            return item
        item=Item(self,raw,parent,existing)
        if key:self.cache[key]=item
        return item
    def selected_ids(self): return {uid(x) for x in self.raw.get_selection()}
    def GetSelection(self): return [self.wrap(x) for x in self.raw.get_selection()]
    def GetFootprints(self): return [self.wrap(x) for x in self.raw.get_footprints()]
    def FindFootprintByReference(self,reference):
        return next((fp for fp in self.GetFootprints() if fp.GetReference()==reference),None)
    def GetTracks(self): return [self.wrap(x) for x in [*self.raw.get_tracks(),*self.raw.get_vias()]]
    def GetDrawings(self): return [self.wrap(x) for x in [*self.raw.get_shapes(),*self.raw.get_text()]]
    def Zones(self): return [self.wrap(x) for x in self.raw.get_zones()]
    def Groups(self): return [self.wrap(x) for x in self.raw.get_groups()]
    def GetFileName(self):
        name=Path(self.raw.name)
        return str(name if name.is_absolute() else Path(self.raw.get_project().path)/name)
    def GetCopperLayerCount(self): return self.raw.get_copper_layer_count()
    def GetLayerName(self,layer): return self.raw.get_layer_name(layer)
    def GetEnabledLayers(self):
        from kipy.util.board_layer import is_copper_layer, iter_copper_layers
        layers=list(self.raw.get_enabled_layers())
        copper=[layer for layer in iter_copper_layers() if layer in layers]
        return SimpleNamespace(Seq=lambda:layers,CuStack=lambda:copper)
    def FindNet(self,name): return Net(self,str(name)) if str(name) in self.net_names.values() else None
    def GetNetsByName(self): return {name:Net(self,name) for name in self.net_names.values()}
    def GetDesignSettings(self):
        # Read actual project rules; never invent a fabricator clearance.
        import json
        source=Path(self.GetFileName()).with_suffix('.kicad_pro')
        try:
            data=json.loads(source.read_text(encoding='utf-8-sig')) if source.exists() else {}
            if not isinstance(data,dict):raise ValueError('project root must be a JSON object')
        except (OSError,ValueError) as exc:
            raise UnsupportedCapability(f'Cannot read project design rules from {source}: {exc}. Repair or resave the project in KiCad before analysis.') from exc
        rules=data.get('board',{}).get('design_settings',{}).get('rules',{})
        clearance=rules.get('min_clearance')
        def minimum():
            if clearance is None:raise UnsupportedCapability('Save project design rules before running this analysis.')
            return round(float(clearance)*1e6)
        return SimpleNamespace(GetSmallestClearanceValue=minimum,GetBoardThickness=lambda:sum(layer.thickness for layer in self.raw.get_stackup().layers))
    def GetBoardEdgesBoundingBox(self):
        shapes=[x for x in self.GetDrawings() if x.GetLayerName()=='Edge.Cuts']
        if not shapes:raise ValueError('The board has no Edge.Cuts outline.')
        boxes=[x.GetBoundingBox() for x in shapes]
        return Box(min(x.left for x in boxes),min(x.top for x in boxes),max(x.right for x in boxes),max(x.bottom for x in boxes))
    def wayricad_outline(self):
        """Live straight Edge.Cuts geometry; unsupported curves fail closed.

        kicad-python 0.8 exposes shapes but no native board-outline command.
        Exact endpoint joining deliberately does not guess across outline gaps.
        """
        from kipy.proto.board.board_types_pb2 import BL_Edge_Cuts
        rings=[]; segments=[]
        point=lambda p:(p.x,p.y)
        for shape in self.raw.get_shapes():
            if shape.layer!=BL_Edge_Cuts: continue
            if isinstance(shape,self.types.BoardSegment):
                segments.append((point(shape.start),point(shape.end)))
            elif isinstance(shape,self.types.BoardRectangle):
                x,y=point(shape.top_left);u,v=point(shape.bottom_right)
                rings.append([(x,y),(u,y),(u,v),(x,v)])
            elif isinstance(shape,self.types.BoardPolygon):
                for poly in shape.polygons:
                    outer,holes=polygon_points(poly);rings.extend([outer,*holes])
            else:
                raise UnsupportedCapability('This IPC planner supports straight Edge.Cuts boundaries. Curves require native outline tessellation, which this API does not expose.')
        adjacency={}
        for a,b in segments:
            if a==b:raise UnsupportedCapability('Edge.Cuts contains a zero-length segment.')
            adjacency.setdefault(a,[]).append(b);adjacency.setdefault(b,[]).append(a)
        if any(len(neighbours)!=2 for neighbours in adjacency.values()):
            raise UnsupportedCapability('Edge.Cuts is open or branches. Close the outline exactly before generating copper.')
        unused=set(adjacency)
        while unused:
            start=min(unused);previous=None;current=start;ring=[]
            while current in unused:
                unused.remove(current);ring.append(current)
                candidates=adjacency[current]
                following=candidates[0] if candidates[0]!=previous else candidates[1]
                previous,current=current,following
            if current!=start:raise UnsupportedCapability('Edge.Cuts contains an invalid joined boundary.')
            rings.append(ring)
        if not rings:raise UnsupportedCapability('The board has no closed Edge.Cuts outline.')
        return IPCPolySet.from_rings(rings)
    def Add(self,item):
        result=self.raw.create_items([item.raw])
        if len(result)!=1:raise RuntimeError('KiCad did not create the requested item.')
        item.raw=result[0];item.existing=True;self.cache[uid(item.raw)]=item
    def Remove(self,item): self.raw.remove_items([item.raw]);item.existing=False
    def SetHighLightNet(self,code):
        self.raw.clear_selection()
        items=[x.raw for fp in self.GetFootprints() for x in fp.Pads() if x.GetNetCode()==code]
        if items:self.raw.add_to_selection(items)
    def fingerprint(self):
        blobs=[]
        for getter in (self.raw.get_footprints,self.raw.get_tracks,self.raw.get_vias,self.raw.get_zones,self.raw.get_shapes):
            blobs.extend(x.proto.SerializeToString(deterministic=True) for x in getter())
        return hashlib.sha256(b''.join(sorted(blobs))).hexdigest()


def module(client=None):
    """Build the narrowly scoped facade used by existing UI controllers."""
    from kipy import KiCad
    from kipy import board_types as types
    from kipy.geometry import Vector2
    from kipy.proto.board.board_types_pb2 import BoardLayer,ViaType
    if client is None:
        from .context import connect
        client=connect()
    version=client.get_version()
    if version.major < 10:
        raise UnsupportedCapability('WayriCAD IPC plugins require KiCad 10 or later; detected '+str(version)+'.')
    board=Board(client.get_board(),types)
    result=ModuleType('pcbnew')
    result._wayricad_ipc=True
    result.GetBoard=lambda:board
    result.FromMM=lambda v:round(float(v)*1e6)
    result.ToMM=lambda v:float(v)/1e6
    result.VECTOR2I=lambda x,y:Vector2.from_xy(int(x),int(y))
    result.VECTOR2D=result.VECTOR2I
    result.Refresh=lambda:None
    result.Version=lambda:version.full_version
    result.GetBuildVersion=result.Version
    result.LayerName=board.GetLayerName
    result.PAD_ATTRIB_SMD=1;result.PAD_ATTRIB_PTH=0
    result.FP_EXCLUDE_FROM_BOM=1;result.FP_EXCLUDE_FROM_POS_FILES=2;result.FP_DNP=4
    for name,value in types.PadStackShape.items():
        if name.startswith('PSS_'):setattr(result,'PAD_SHAPE_'+name[4:],value)
    result.VIATYPE_THROUGH=ViaType.VT_THROUGH
    result.VIATYPE_BLIND_BURIED=ViaType.VT_BLIND_BURIED
    result.VIATYPE_BLIND=ViaType.VT_BLIND
    result.VIATYPE_BURIED=ViaType.VT_BURIED
    result.VIATYPE_MICROVIA=ViaType.VT_MICRO
    for name,value in BoardLayer.items():
        if name.startswith('BL_'):setattr(result,name[3:],value)
    class ActionPlugin:
        def __init__(self): self.defaults()
        def register(self): pass
    result.ActionPlugin=ActionPlugin
    def create(cls,parent):
        raw=cls();raw.id.value=str(uuid.uuid4())
        if isinstance(raw,types.Via):raw.type=ViaType.VT_THROUGH
        return Item(parent,raw,existing=False)
    result.PCB_TRACK=lambda parent:create(types.Track,parent)
    result.PCB_VIA=lambda parent:create(types.Via,parent)
    result.PCB_GROUP=lambda parent:create(types.Group,parent)
    result.FOOTPRINT=Item
    result.BOARD=Board
    return result
