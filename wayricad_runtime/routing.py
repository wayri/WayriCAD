"""Shared headless routing planners. Settings use millimetres; board objects use native units.

Conservative bounding-box obstacle checks supplement, but do not replace, KiCad DRC.
No wx import, file writes, or board mutation occurs during planning.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, List, Tuple, Set, Dict
import math
import fnmatch
from .geometry import (dimensions, positive, inside_native, segment_hits_box,
                       segment_segment_distance, segment_inside_native, item_id)


def _coord(value): return float(value) / 1_000_000.0

@dataclass
class FanoutPlan:
    footprint: Any
    pad: Any
    end: Any
    width: int
    via_diameter: int
    via_drill: int
    add_track: bool = True
    add_via: bool = False
    pattern: str = "Radial outward"
    start: Any = None
    layer: int = 0
    net_code: int = 0
    start_via: bool = False



def project_netclasses(board):
    """Read saved project class declarations, explicit assignments and glob patterns."""
    import json
    from pathlib import Path
    filename=getattr(board,'GetFileName',lambda:'')()
    if not filename:return {}
    project=Path(filename).with_suffix('.kicad_pro')
    if not project.exists():return {}
    try:return json.loads(project.read_text(encoding='utf-8-sig')).get('net_settings',{})
    except (OSError,ValueError) as exc:raise ValueError('Cannot read project netclasses: '+str(exc)) from exc


def netclass_names(board):
    names={'Default'}
    getter=getattr(board,'GetAllNetClasses',None)
    if getter:names.update(str(name) for name in getter())
    settings=project_netclasses(board)
    names.update(row['name'] for row in settings.get('classes',[]) if row.get('name'))
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            getter=getattr(pad,'GetNetClassName',None)
            if getter:
                name=str(getter())
                if name:names.add(name)
    return sorted(names,key=lambda name:(name!='Default',name.casefold()))


def pad_in_netclass(pad,choice,settings):
    if choice=='All netclasses':return True
    names=set()
    getter=getattr(pad,'GetEffectiveNetClass',None)
    if getter:
        effective=getter()
        if hasattr(effective,"ContainsNetclassWithName") and effective.ContainsNetclassWithName(choice):names.add(choice)
    getter=getattr(pad,'GetNetClassName',None)
    if getter:names.add(str(getter()))
    net=pad.GetNetname()
    assigned=settings.get('netclass_assignments',{}).get(net,[])
    names.update([assigned] if isinstance(assigned,str) else assigned)
    for row in settings.get('netclass_patterns',[]):
        if fnmatch.fnmatchcase(net,row.get('pattern','')):names.add(row.get('netclass','Default'))
    for row in settings.get('classes',[]):
        if net in row.get('nets',[]):names.add(row['name'])
    if len(names)>1:names.discard('Default')
    return choice in (names or {'Default'})


def copper_layer_names(board):
    return [board.GetLayerName(layer) for layer in board.GetEnabledLayers().CuStack()]


class FanoutPlanner:
    defaults = {'scope': 'All SMD pads', 'ref': '*', 'width': 0.2, 'length': 1.5, 'via_diameter': 0.6, 'via_drill': 0.3, 'pattern': 'Dogbone outward', 'angle_offset': 0, 'offset_x': 0, 'offset_y': 0, 'clearance': 0.2, 'add_vias': True, 'escape_layer': 'Pad layer', 'output_mode': 'Escape traces', 'netclass_filter': 'All netclasses'}
    def __init__(self, board, api, settings):
        unknown = set(settings) - set(self.defaults)
        if unknown: raise ValueError('Unknown routing settings: ' + ', '.join(sorted(unknown)))
        self.board, self.api = board, api
        self.settings = dict(self.defaults, **settings)

    def _layer(self, pad: Any) -> int:
        choice = self.settings["escape_layer"]
        target = {"F.Cu":self.api.F_Cu,"B.Cu":self.api.B_Cu}.get(choice,pad.GetLayer())
        layers={self.board.GetLayerName(layer):layer for layer in self.board.GetEnabledLayers().CuStack()}
        if choice=='Pad layer':return pad.GetLayer()
        if choice not in layers:raise ValueError('Choose an enabled copper layer.')
        return layers[choice]


    def _selected_pad_keys(self) -> set[Tuple[str, str]]:
        return {
            (str(fp.GetReference()), str(pad.GetNumber()))
            for fp in self.board.GetFootprints()
            for pad in fp.Pads()
            if bool(getattr(pad, "IsSelected", lambda: False)())
        }


    def _selected_footprint_refs(self) -> set[str]:
        refs = {
            str(fp.GetReference()) for fp in self.board.GetFootprints()
            if bool(getattr(fp, "IsSelected", lambda: False)())
        }
        refs.update(ref for ref, _pin in self._selected_pad_keys())
        return refs


    def _eligible_pads(self) -> List[Tuple[Any, Any]]:
        scope = self.settings["scope"]
        selected_pads = self._selected_pad_keys()
        selected_refs = self._selected_footprint_refs()
        patterns = [item.strip().upper() for item in self.settings["ref"].split(",") if item.strip()]
        result = []
        classes=project_netclasses(self.board)
        for fp in self.board.GetFootprints():
            ref = str(fp.GetReference())
            if scope == "Selected footprints" and ref not in selected_refs:
                continue
            if scope == "Reference wildcard" and not any(fnmatch.fnmatchcase(ref.upper(), pattern) for pattern in patterns):
                continue
            for pad in fp.Pads():
                if not pad_in_netclass(pad,self.settings["netclass_filter"],classes):
                    continue
                if pad.GetAttribute() != self.api.PAD_ATTRIB_SMD:
                    continue
                if scope == "Selected pads" and (ref, str(pad.GetNumber())) not in selected_pads:
                    continue
                result.append((fp, pad))
        return result


    def _escape_angle(self, pattern: str, fp: Any, pad: Any) -> float:
        pos = pad.GetPosition()
        center = fp.GetPosition()
        dx = _coord(pos.x) - _coord(center.x)
        dy = _coord(pos.y) - _coord(center.y)
        rotation = -math.radians(float(getattr(fp,"GetOrientationDegrees",lambda:0)()))
        dx,dy=math.cos(rotation)*dx+math.sin(rotation)*dy,-math.sin(rotation)*dx+math.cos(rotation)*dy
        radial = math.atan2(dy, dx) if dx or dy else 0.0
        inward = "inward" in pattern.lower()
        if pattern.startswith("Dogbone"):
            angle = round(radial/(math.pi/4))*(math.pi/4)
        elif pattern.startswith("Quadrant"):
            angle = math.atan2(1.0 if dy >= 0 else -1.0, 1.0 if dx >= 0 else -1.0)
        elif pattern.startswith("Four-corner"):
            box = fp.GetBoundingBox()
            corner_x = box.GetRight() if dx >= 0 else box.GetLeft()
            corner_y = box.GetBottom() if dy >= 0 else box.GetTop()
            angle = math.atan2(_coord(corner_y) - _coord(pos.y), _coord(corner_x) - _coord(pos.x))
        elif pattern.startswith("BGA/LGA"):
            angle = math.atan2(1 if dy>=0 else -1,1 if dx>=0 else -1)
        elif pattern.startswith("Perimeter"):
            if abs(dx) >= abs(dy):
                angle = 0.0 if dx >= 0 else math.pi
            else:
                angle = math.pi / 2 if dy >= 0 else -math.pi / 2
        else:
            angle = radial
        # Bounding-box corner angles are already in world coordinates.
        return angle + (0 if pattern.startswith("Four-corner") else rotation) + (math.pi if inward else 0.0)


    def _plan(self) -> List[FanoutPlan]:
        try:
            dimensions(self.settings["width"],self.settings["length"],self.settings["via_diameter"],self.settings["via_drill"])
            width = self.api.FromMM(float(self.settings["width"]))
            length = self.api.FromMM(float(self.settings["length"]))
            via_diameter = self.api.FromMM(float(self.settings["via_diameter"]))
            via_drill = self.api.FromMM(float(self.settings["via_drill"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        result: List[FanoutPlan] = []
        if self.settings["output_mode"] not in ("Escape traces","Via-in-pad"):raise ValueError("Unknown output mode.")
        pattern = "Via-in-pad" if self.settings["output_mode"]=="Via-in-pad" else self.settings["pattern"]
        offsets=[float(self.settings[name]) for name in ('angle_offset','offset_x','offset_y','clearance')]
        if not all(math.isfinite(x) for x in offsets) or offsets[3]<0:raise ValueError("Offsets must be finite and clearance must be non-negative.")
        self.plan_rejections=[]
        margin=self.api.FromMM(offsets[3])
        if width<=0 or via_drill<=0 or via_diameter<=via_drill or length<=0:
            raise ValueError('Dimensions are below the board coordinate resolution.')
        patterns=('Dogbone outward','Dogbone inward','BGA/LGA grid outward','Quadrant outward','Quadrant inward',
                  'Four-corner outward','Four-corner inward','Perimeter outward','Radial outward','Via-in-pad')
        if pattern not in patterns:raise ValueError('Unknown fanout pattern: '+str(pattern))
        if self.settings['scope'] not in ('All SMD pads','Selected pads','Selected footprints','Reference wildcard'):
            raise ValueError('Unknown pad scope.')
        outline=None
        if hasattr(self.api,'SHAPE_POLY_SET'):
            outline=self.api.SHAPE_POLY_SET()
            if not self.board.GetBoardPolygonOutlines(outline,False):raise ValueError('A closed, valid Edge.Cuts outline is required.')
        elif hasattr(self.board,'wayricad_outline'):outline=self.board.wayricad_outline()
        else:raise ValueError('This runtime cannot validate the board outline for fanout.')
        pads=[p for f in self.board.GetFootprints() for p in f.Pads()]
        tracks=list(self.board.GetTracks())
        zones=list(self.board.Zones())
        for fp, pad in self._eligible_pads():
            if not pad.GetNetCode():
                self.plan_rejections.append(f"{fp.GetReference()}.{pad.GetNumber()}: no net")
                continue
            pos = pad.GetPosition()
            via_in_pad = pattern == "Via-in-pad"
            angle = self._escape_angle(pattern, fp, pad)+math.radians(offsets[0])
            end = self.api.VECTOR2I(pos.x, pos.y) if via_in_pad else self.api.VECTOR2I(
                pos.x + int(math.cos(angle) * length)+self.api.FromMM(offsets[1]),
                pos.y + int(math.sin(angle) * length)+self.api.FromMM(offsets[2]),
            )
            target_layer=self._layer(pad)
            start_via=not via_in_pad and target_layer!=pad.GetLayer()
            forced_via = via_in_pad or pattern.startswith("Dogbone")
            add_via=forced_via or self.settings["add_vias"]
            obstacles=[p for p in pads if p.GetNetCode()!=pad.GetNetCode()]
            obstacles.extend(t for t in tracks if t.GetNetCode()!=pad.GetNetCode())
            reason=next(("other-net copper" for obstacle in obstacles if segment_hits_box(pos,end,obstacle.GetBoundingBox(),width/2+margin) or (add_via and segment_hits_box(end,end,obstacle.GetBoundingBox(),via_diameter/2+margin))),"")
            if not reason and start_via:
                reason=next(('source via clearance' for obstacle in obstacles if segment_hits_box(pos,pos,obstacle.GetBoundingBox(),via_diameter/2+margin)), '')
            if not reason and start_via and not inside_native(pos,via_diameter/2+margin,outline):reason='source via near board edge'
            if not reason and not segment_inside_native(pos,end,width/2+margin,outline):reason='board edge/cutout'
            if not reason and add_via and not inside_native(end,via_diameter/2+margin,outline):reason='via near board edge/cutout'
            if not reason:
                for zone in zones:
                    blocked = (zone.GetIsRuleArea() and ((add_via and zone.GetDoNotAllowVias()) or (not via_in_pad and zone.GetDoNotAllowTracks()))) or (not zone.GetIsRuleArea() and zone.GetNetCode()!=pad.GetNetCode())
                    if blocked and segment_hits_box(pos,end,zone.GetBoundingBox(),max(width,via_diameter if add_via else 0)/2+margin):
                        reason='zone/keepout';break
            if not reason:
                for other in result:
                    if other.start_via and segment_segment_distance((other.start.x,other.start.y),(other.start.x,other.start.y),(pos.x,pos.y),(end.x,end.y))<(via_diameter+width)/2+margin and other.net_code!=pad.GetNetCode():
                        reason='generated source via collision';break
                    if other.net_code==pad.GetNetCode():continue
                    a,b=(pos.x,pos.y),(end.x,end.y)
                    c,d=(other.start.x,other.start.y),(other.end.x,other.end.y)
                    if (other.add_track and not via_in_pad and segment_segment_distance(a,b,c,d)<width+margin
                        or add_via and other.add_track and segment_segment_distance(b,b,c,d)<(via_diameter+width)/2+margin
                        or other.add_via and not via_in_pad and segment_segment_distance(d,d,a,b)<(via_diameter+width)/2+margin):
                        reason='generated copper collision';break
            if not reason and start_via:
                a=(pos.x,pos.y)
                for other in result:
                    if other.start_via and math.hypot(other.start.x-pos.x,other.start.y-pos.y)<via_diameter+margin:
                        reason='generated source via overlap';break
                    if other.add_via and math.hypot(other.end.x-pos.x,other.end.y-pos.y)<via_diameter+margin:
                        reason='generated source via overlap';break
                    if other.net_code!=pad.GetNetCode() and other.add_track and segment_segment_distance(a,a,(other.start.x,other.start.y),(other.end.x,other.end.y))<(via_diameter+width)/2+margin:
                        reason='generated source via collision';break
            if not reason and add_via:
                reason=next(("generated via overlap" for p in result if p.add_via and math.hypot(p.end.x-end.x,p.end.y-end.y)<via_diameter+margin),"")
            if reason:
                self.plan_rejections.append(f"{fp.GetReference()}.{pad.GetNumber()}: {reason}")
                continue
            result.append(FanoutPlan(
                fp, pad, end, width, via_diameter, via_drill,
                add_track=not via_in_pad,
                add_via=bool(pad.GetNetCode()) and (forced_via or self.settings["add_vias"]),
                pattern=pattern,start=self.api.VECTOR2I(pos.x,pos.y),layer=target_layer,net_code=pad.GetNetCode(),start_via=start_via,
            ))
        return result


class StitchingPlanner:
    defaults = {'spacing': 2.5, 'drill': 0.3, 'diameter': 0.6, 'edge': 1.0, 'clearance': 0.2, 'density': 'Uniform', 'net_choice': 'GND', 'universal': True, 'x_min': 0, 'y_min': 0, 'x_max': 100, 'y_max': 100, 'require_target_zone': True, 'pattern': 'Square grid', 'skip_refs': '', 'skip_parts': True, 'skip_tracks': True, 'skip_zones': True, 'skip_keepouts': True}
    def __init__(self, board, api, settings):
        unknown = set(settings) - set(self.defaults)
        if unknown: raise ValueError('Unknown routing settings: ' + ', '.join(sorted(unknown)))
        self.board, self.api = board, api
        self.settings = dict(self.defaults, **settings)

    def _selected_net(self) -> tuple[str, int]:
        name = self.settings["net_choice"]
        if not name or name == "<No net>":
            return "", 0
        find_net = getattr(self.board, "FindNet", None)
        if callable(find_net):
            net = find_net(name)
            if net is not None:
                return name, int(net.GetNetCode())
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() == name:
                    return name, int(pad.GetNetCode())
        return name, 0


    def _excluded_refs(self) -> Set[str]:
        return {item.strip().upper() for item in self.settings["skip_refs"].split(",") if item.strip()}


    @staticmethod
    def _net_code(item: Any) -> int:
        try:
            return int(item.GetNetCode())
        except Exception:
            return 0


    def _target_zones(self, net_code: int) -> List[Any]:
        return [zone for zone in getattr(self.board, "Zones", lambda: [])() if self._net_code(zone) == net_code and not zone.GetIsRuleArea()]


    def _inside_zone(self, zone: Any, position: Any) -> bool:
        # Require actual filled copper with room for the entire via; no HitTestFilledArea fallback to outlines.
        layers=list(zone.GetLayerSet().Seq())
        return any(inside_native(position,self._radius,zone.GetFilledPolysList(layer)) for layer in layers)


    def _blocked_reason(self, position: Any, net_code: int) -> str:
        excluded = self._excluded_refs()
        for fp in self._obstacle_footprints:
            if self.settings["skip_parts"] or fp.GetReference().upper() in excluded:
                if segment_hits_box(position,position,fp.GetBoundingBox(),self._margin):
                    return "footprint"
            for pad in fp.Pads():
                if pad.GetNetCode()!=net_code and segment_hits_box(position,position,pad.GetBoundingBox(),self._margin):
                    return 'other-net pad'
        if True:  # Electrical clearance is always enforced.
            tracks = self._obstacle_tracks
            if any((self._net_code(track) != net_code or 'VIA' in track.GetClass() or self.settings["skip_tracks"]) and segment_hits_box(position,position,track.GetBoundingBox(),self._margin) for track in tracks):
                return "other-net track/via"
        if True:  # Other-net copper is always excluded.
            zones = self._obstacle_zones
            if any(not zone.GetIsRuleArea() and self._net_code(zone) != net_code and segment_hits_box(position,position,zone.GetBoundingBox(),self._margin) for zone in zones):
                return "other-net zone"
        if True:  # Via keepouts cannot be disabled.
            if any(zone.GetIsRuleArea() and zone.GetDoNotAllowVias() and segment_hits_box(position,position,zone.GetBoundingBox(),self._margin) for zone in self._obstacle_zones):
                return "keepout/drawing"
        return ""


    def _bounds(self) -> Tuple[int, int, int, int]:
        if self.settings["universal"]:
            box = self.board.GetBoardEdgesBoundingBox()
            return box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()
        return tuple(int(self.api.FromMM(float(value))) for value in (self.settings["x_min"], self.settings["y_min"], self.settings["x_max"], self.settings["y_max"]))


    def _plan(self) -> List[Any]:
        if self.settings['pattern'] not in ('Square grid','Staggered grid'):raise ValueError('Unknown stitching pattern.')
        if self.settings['density'] not in ('Uniform','Dense perimeter / sparse interior','Dense selected area'):raise ValueError('Unknown density profile.')
        for control,label in ((self.settings["spacing"],'Spacing'),(self.settings["drill"],'Drill'),(self.settings["diameter"],'Diameter')):positive(control,label)
        positive(self.settings["edge"],'Edge inset',True)
        positive(self.settings["clearance"],'Clearance',True)
        if float(self.settings["drill"])>=float(self.settings["diameter"]):raise ValueError('Drill must be smaller than via diameter.')
        spacing = self.api.FromMM(float(self.settings["spacing"]))
        inset = self.api.FromMM(float(self.settings["edge"]))
        drill = self.api.FromMM(float(self.settings["drill"]))
        diameter = self.api.FromMM(float(self.settings["diameter"]))
        if spacing <= 0:
            raise ValueError("Grid spacing must be greater than zero.")
        step = max(1, spacing // 2) if self.settings["density"] == "Dense selected area" else spacing
        self._radius=diameter/2
        self._margin=self._radius+self.api.FromMM(float(self.settings["clearance"]))
        if step < diameter+self.api.FromMM(float(self.settings["clearance"])):raise ValueError('Spacing is smaller than the via diameter plus clearance.')
        _net_name, net_code = self._selected_net()
        if not net_code:
            raise ValueError("Choose a real PCB net before previewing stitching vias.")
        left, top, right, bottom = self._bounds()
        left, right = sorted((left, right))
        top, bottom = sorted((top, bottom))
        if right - left <= 2 * inset or bottom - top <= 2 * inset:
            raise ValueError("The selected bounds are smaller than twice the edge inset.")
        target_zones = self._target_zones(net_code)
        require_zone = self.settings["require_target_zone"]
        if require_zone and not target_zones:raise ValueError('No copper zones match the selected net. Create and fill a target-net zone first.')
        if require_zone and not any(zone.IsFilled() for zone in target_zones):raise ValueError('Fill the target-net copper zones before generating vias.')
        self._obstacle_footprints=list(self.board.GetFootprints())
        self._obstacle_tracks=list(self.board.GetTracks())
        self._obstacle_zones=list(self.board.Zones())
        self._board_outline=None
        if hasattr(self.api,'SHAPE_POLY_SET'):
            self._board_outline=self.api.SHAPE_POLY_SET()
            if not self.board.GetBoardPolygonOutlines(self._board_outline,False):raise ValueError('A closed, valid Edge.Cuts outline is required.')
        elif hasattr(self.board,"wayricad_outline"):
            self._board_outline=self.board.wayricad_outline()
        elif not require_zone:
            raise ValueError('This runtime needs a filled target-net zone to constrain stitching geometry.')
        candidate_count=(1+(right-left)//step)*(1+(bottom-top)//step)
        if candidate_count>50000:raise ValueError(f'{candidate_count:,} candidates exceed the 50,000 limit. Increase spacing or reduce the selected area.')
        rejected: Dict[str, int] = {}
        result = []
        x = left + inset
        x_index = 0
        while x <= right - inset:
            y = top + inset + (step//2 if self.settings["pattern"]=='Staggered grid' and x_index%2 else 0)
            y_index = 0
            while y <= bottom - inset:
                profile = self.settings["density"]
                perimeter_distance = min(x - left, right - x, y - top, bottom - y)
                if profile == "Dense perimeter / sparse interior" and perimeter_distance > 3 * spacing and (x_index % 2 or y_index % 2):
                    y += step; y_index += 1; continue
                position = self.api.VECTOR2I(int(x), int(y))
                if self._board_outline is not None and not inside_native(position,max(inset,self._margin),self._board_outline):
                    rejected['board edge/cutout']=rejected.get('board edge/cutout',0)+1
                    y+=step;y_index+=1;continue
                if require_zone and not any(self._inside_zone(zone, position) for zone in target_zones):
                    rejected["outside target copper"] = rejected.get("outside target copper", 0) + 1
                    y += step
                    y_index += 1
                    continue
                reason = self._blocked_reason(position, net_code)
                if reason:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    y += step
                    y_index += 1
                    continue
                via = self.api.PCB_VIA(self.board)
                via.SetPosition(position)
                via.SetViaType(self.api.VIATYPE_THROUGH)
                via.SetLayerPair(self.api.F_Cu,self.api.B_Cu)
                via.SetDrill(int(drill))
                via.SetWidth(int(diameter))
                via.SetNetCode(net_code)
                result.append(via)
                y += step
                y_index += 1
            x += step
            x_index += 1
        self.plan_rejections = rejected
        return result


def plan_fanout(board, api, settings=None):
    planner = FanoutPlanner(board, api, settings or {})
    return planner._plan(), planner.plan_rejections


def plan_stitching(board, api, settings=None):
    planner = StitchingPlanner(board, api, settings or {})
    return planner._plan(), planner.plan_rejections


def fanout_items(board, api, plans):
    items = []
    for plan in plans:
        if plan.add_track:
            track=api.PCB_TRACK(board)
            track.SetStart(plan.start); track.SetEnd(plan.end)
            track.SetWidth(plan.width); track.SetLayer(plan.layer); track.SetNetCode(plan.net_code)
            items.append(track)
        for position in ([plan.start] if plan.start_via else []) + ([plan.end] if plan.add_via else []):
            via=api.PCB_VIA(board)
            via.SetPosition(position); via.SetWidth(plan.via_diameter); via.SetDrill(plan.via_drill)
            via.SetViaType(api.VIATYPE_THROUGH); via.SetLayerPair(api.F_Cu,api.B_Cu)
            via.SetNetCode(plan.net_code); items.append(via)
    return items


def plan_document(kind, board, api, settings=None):
    """JSON-ready review data; never modifies the board."""
    from .geometry import board_fingerprint
    if kind == 'fanout':
        plans, rejected = plan_fanout(board, api, settings)
        records=[dict(reference=p.footprint.GetReference(),pad=p.pad.GetNumber(),net=p.pad.GetNetname(),
                      start_mm=[api.ToMM(p.start.x),api.ToMM(p.start.y)],end_mm=[api.ToMM(p.end.x),api.ToMM(p.end.y)],
                      width_mm=api.ToMM(p.width),via_diameter_mm=api.ToMM(p.via_diameter),via_drill_mm=api.ToMM(p.via_drill),
                      add_track=p.add_track,add_via=p.add_via,start_via=p.start_via,layer=board.GetLayerName(p.layer)) for p in plans]
    elif kind == 'stitching':
        plans, rejected = plan_stitching(board, api, settings)
        records=[dict(position_mm=[api.ToMM(p.GetPosition().x),api.ToMM(p.GetPosition().y)],
                      diameter_mm=api.ToMM(p.GetWidth(api.F_Cu)),drill_mm=api.ToMM(p.GetDrillValue()),net=p.GetNetname()) for p in plans]
    else: raise ValueError('Routing kind must be fanout or stitching.')
    return dict(schema=1,kind=kind,settings=settings or {},board_fingerprint=board_fingerprint(board),
                candidates=records,rejected=rejected,warning='Conservative geometry checks; run KiCad DRC before manufacturing.')
