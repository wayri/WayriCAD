"""Shared headless routing planners. Settings use millimetres; board objects use native units.

Conservative bounding-box obstacle checks supplement, but do not replace, KiCad DRC.
No wx import, file writes, or board mutation occurs during planning.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Tuple, Set, Dict
import math
import fnmatch
import re
from .fanout_profiles import FANOUT_PATTERNS, SIGNAL_PROFILES, ANGLE_MODES, PAIR_MODES, profile_defaults
from .geometry import (dimensions, positive, inside_native, segment_hits_box,
                       segment_segment_distance, segment_inside_native, item_id, segment_hits_pad)


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
    path: list = field(default_factory=list)
    pair_id: str = ""
    length_mm: float = 0.0
    group_name: str = "Defaults"
    group_index: int = -1
    clearance: int = 0



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
    defaults = {'scope': 'All SMD pads', 'ref': '*', 'width': 0.2, 'length': 1.5, 'via_diameter': 0.6, 'via_drill': 0.3, 'pattern': 'Perimeter pitch expansion', 'angle_offset': 0, 'offset_x': 0, 'offset_y': 0, 'clearance': 0.2, 'add_vias': True, 'escape_layer': 'Pad layer', 'output_mode': 'Escape traces', 'netclass_filter': 'All netclasses', 'escape_angle': 45.0, 'angle_mode': 'Pattern', 'launch_length': 0.5, 'stagger_pitch': 0.5, 'spread_pitch': 0.0, 'routing_mode': 'Fixed', 'adaptive_radius': 3.0, 'adaptive_step': 0.25, 'signal_profile': 'Generic', 'net_filter': '*', 'pair_mode': 'Independent', 'pair_gap': 0.2, 'max_pair_skew': 0.1, 'use_netclass_rules': False, 'groups': [], 'unmatched': 'defaults'}
    def __init__(self, board, api, settings):
        unknown = set(settings) - set(self.defaults)
        if unknown: raise ValueError('Unknown routing settings: ' + ', '.join(sorted(unknown)))
        self.board, self.api = board, api
        self.settings = dict(self.defaults)
        if "signal_profile" in settings:
            self.settings.update(profile_defaults(settings["signal_profile"]))
        self.settings.update(settings)

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
                if not any(fnmatch.fnmatchcase(str(pad.GetNetname()), pattern.strip()) for pattern in str(self.settings["net_filter"]).split(",") if pattern.strip()):
                    continue
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
            corner_x = box.GetRight() if pos.x >= center.x else box.GetLeft()
            corner_y = box.GetBottom() if pos.y >= center.y else box.GetTop()
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


    def _outward(self, fp, pad):
        """Dominant footprint-local edge normal and signed tangent."""
        rotation = -math.radians(float(getattr(fp, 'GetOrientationDegrees', lambda: 0)()))
        pos, center = pad.GetPosition(), fp.GetPosition()
        dx, dy = pos.x-center.x, pos.y-center.y
        x = math.cos(rotation)*dx + math.sin(rotation)*dy
        y = -math.sin(rotation)*dx + math.cos(rotation)*dy
        # Native rotation rounds positions to integer units; stabilize edge
        # tangent choice for pads on the footprint's local centerline.
        if abs(x) < 1: x = 0.0
        if abs(y) < 1: y = 0.0
        if abs(x) >= abs(y):
            normal = 0.0 if x >= 0 else math.pi
            tangent = (1 if y >= 0 else -1) * (1 if x >= 0 else -1)
        else:
            normal = math.pi/2 if y >= 0 else -math.pi/2
            tangent = (-1 if x >= 0 else 1) * (1 if y >= 0 else -1)
        return normal + rotation, tangent

    def _direction(self, fp, pad, pattern):
        normal, sign = self._outward(fp, pad)
        mode = self.settings['angle_mode']
        angle = math.radians(float(self.settings['escape_angle']))
        if mode == 'Board absolute':
            result = angle
        elif mode == 'Footprint relative':
            result = angle - math.radians(float(fp.GetOrientationDegrees()))
        elif pattern in ('45-degree spread', 'Custom-angle spread', 'Straight + angled escape'):
            result = normal + sign * (math.pi/4 if pattern == '45-degree spread' else angle)
        elif pattern == 'Staggered rows':
            result = normal
        else:
            result = self._escape_angle(pattern, fp, pad)
        return result + math.radians(float(self.settings['angle_offset']))

    @staticmethod
    def _pair_key(net):
        # Case and suffix style are significant, matching named PCB nets.
        # P/N and +/- are KiCad's naming convention; delimited T/C is an
        # explicit convenience for memory clocks/strobes.
        match = re.fullmatch(r'(.+?)([PN+-])', str(net))
        if match:
            stem,polarity=match.groups()
            return (stem, 'PN' if polarity in 'PN' else '+-'),polarity
        match = re.fullmatch(r'(.+[_./-])([TCtc])', str(net))
        if match:
            stem,polarity=match.groups()
            return (stem,'TC' if polarity in 'TC' else 'tc'),polarity
        return None

    def _groups(self, eligible):
        if self.settings['pair_mode'] == 'Independent':
            return [([entry], '') for entry in eligible]
        buckets = {}
        for fp, pad in eligible:
            parsed = self._pair_key(pad.GetNetname())
            if not parsed:
                self.plan_rejections.append(f'{fp.GetReference()}.{pad.GetNumber()}: no strict differential suffix (P/N, T/C or +/-)')
                continue
            key, polarity = parsed
            buckets.setdefault((item_id(fp), key), []).append((fp, pad, polarity))
        groups = []
        for (_fp_id, (stem, family)), members in buckets.items():
            pair_id = f'{members[0][0].GetReference()}:{stem}[{family}]'
            if len(members) != 2 or {row[2] for row in members} != set(family):
                for fp, pad, _ in members:
                    self.plan_rejections.append(f'{fp.GetReference()}.{pad.GetNumber()}: missing or ambiguous differential mate within filtered footprint')
                continue
            groups.append(([(fp, pad) for fp, pad, _ in members], pair_id))
        return groups

    def _dimensions(self):
        values = dict(self.settings)
        if values['use_netclass_rules']:
            choice = values['netclass_filter']
            if choice == 'All netclasses':
                raise ValueError('Choose one netclass before loading its routing dimensions.')
            classes = project_netclasses(self.board).get('classes', [])
            matches = [row for row in classes if row.get('name') == choice]
            if len(matches) != 1:
                raise ValueError('Selected netclass dimensions are unavailable in the saved project.')
            rule = matches[0]
            paired = values['pair_mode'] != 'Independent'
            for dest, source in [('width', 'diff_pair_width' if paired else 'track_width'),
                                 ('via_diameter', 'via_diameter'), ('via_drill', 'via_drill'),
                                 ('clearance', 'clearance')]:
                if source not in rule:
                    raise ValueError('Selected netclass lacks ' + source + '.')
                values[dest] = rule[source]
            if paired:
                if 'diff_pair_gap' not in rule:
                    raise ValueError('Selected netclass lacks diff_pair_gap.')
                values['pair_gap'] = rule['diff_pair_gap']
        dimensions(values['width'], values['length'], values['via_diameter'], values['via_drill'])
        for name in ('clearance', 'pair_gap', 'max_pair_skew', 'stagger_pitch', 'spread_pitch'):
            positive(values[name], name, True)
        positive(values['launch_length'], 'Launch length')
        positive(values['adaptive_radius'], 'Adaptive radius')
        positive(values['adaptive_step'], 'Adaptive step')
        if float(values['adaptive_radius'])/float(values['adaptive_step']) > 20:
            raise ValueError('Adaptive radius/step must not exceed 20; use a coarser search step.')
        for name in ('escape_angle', 'angle_offset', 'offset_x', 'offset_y'):
            if not math.isfinite(float(values[name])):
                raise ValueError(name + ' must be finite.')
        if not 0 <= float(values['escape_angle']) <= 360:
            raise ValueError('Escape angle must be between 0 and 360 degrees.')
        if values['angle_mode'] == 'Pattern' and values['pattern'] in ('Custom-angle spread', 'Straight + angled escape') and float(values['escape_angle']) >= 90:
            raise ValueError('Outward spread angle must be less than 90 degrees; use an absolute angle for other directions.')
        return values

    def _candidate(self, fp, pad, path, values, pattern, pair_id=''):
        via_in_pad = pattern == 'Via-in-pad'
        start = self.api.VECTOR2I(pad.GetPosition().x, pad.GetPosition().y)
        layer = self._layer(pad)
        return FanoutPlan(fp, pad, path[-1], self.api.FromMM(float(values['width'])),
                          self.api.FromMM(float(values['via_diameter'])), self.api.FromMM(float(values['via_drill'])),
                          add_track=not via_in_pad, add_via=via_in_pad or pattern.startswith('Dogbone') or bool(values['add_vias']),
                          pattern=pattern, start=start, layer=layer, net_code=pad.GetNetCode(),
                          start_via=not via_in_pad and layer != pad.GetLayer(), path=path, pair_id=pair_id,
                          clearance=self.api.FromMM(float(values['clearance'])),
                          length_mm=sum(math.hypot(b.x-a.x, b.y-a.y) for a,b in zip(path,path[1:])) / 1_000_000)

    def _paths(self, group, pair_id, values, pattern, row_index):
        def point(x, y): return self.api.VECTOR2I(int(round(x)), int(round(y)))
        length = self.api.FromMM(float(values['length']))
        launch = self.api.FromMM(float(values['launch_length']))
        ox, oy = (self.api.FromMM(float(values[name])) for name in ('offset_x','offset_y'))
        if pattern == 'Via-in-pad':
            return [[point(p.GetPosition().x,p.GetPosition().y)] for _,p in group]
        if pattern == 'Perimeter pitch expansion':
            if pair_id:
                raise ValueError('Use independent perimeter escapes or a paired style; pitch expansion does not infer differential coupling.')
            from .perimeter_escape import path
            return [path(fp, pad, self.api, values) for fp, pad in group]
        if pair_id:
            angles = [self._direction(fp,pad,pattern) for fp,pad in group]
            vx,vy = sum(math.cos(a) for a in angles),sum(math.sin(a) for a in angles)
            if math.hypot(vx,vy) < 1.0:
                raise ValueError('pair pads escape in opposing directions; choose a common absolute angle')
            if pattern in ('45-degree spread', 'Custom-angle spread', 'Straight + angled escape'):
                midpoint = point(sum(pad.GetPosition().x for _,pad in group)/2,
                                 sum(pad.GetPosition().y for _,pad in group)/2)
                class PairCenter:
                    def GetPosition(self):return midpoint
                angle = self._direction(group[0][0], PairCenter(), pattern)
            else:
                angle = math.atan2(vy,vx)
            ux,uy,nx,ny = math.cos(angle),math.sin(angle),-math.sin(angle),math.cos(angle)
            positions = [pad.GetPosition() for _,pad in group]
            cx,cy = sum(p.x for p in positions)/2,sum(p.y for p in positions)/2
            projections = [(p.x-cx)*nx+(p.y-cy)*ny for p in positions]
            if abs(projections[0]-projections[1]) < 1:
                raise ValueError('pair pads align with escape direction; choose a direction across the pad pair')
            gap = self.api.FromMM(float(values['width'])+float(values['pair_gap']))
            terminal_gap = max(gap, self.api.FromMM(float(values['via_diameter'])+float(values['clearance'])) + 2) if values['add_vias'] or pattern.startswith('Dogbone') else gap
            flare = (terminal_gap-gap)/2
            forward_launch = max((p.x-cx)*ux+(p.y-cy)*uy for p in positions)+launch
            if length <= forward_launch+flare:
                raise ValueError('pair escape length must exceed launch length plus via flare')
            paths=[]
            for pos, projection in zip(positions,projections):
                sign = -1 if projection == min(projections) else 1
                lane = sign*gap/2
                path=[point(pos.x,pos.y),point(cx+ux*forward_launch+nx*lane+ox,cy+uy*forward_launch+ny*lane+oy),
                      point(cx+ux*(length-flare)+nx*lane+ox,cy+uy*(length-flare)+ny*lane+oy)]
                if flare:
                    lane=sign*terminal_gap/2
                    path.append(point(cx+ux*length+nx*lane+ox,cy+uy*length+ny*lane+oy))
                paths.append(path)
            return paths
        fp,pad=group[0]
        pos=pad.GetPosition()
        angle=self._direction(fp,pad,pattern)
        path=[point(pos.x,pos.y)]
        x,y=pos.x,pos.y
        if pattern=='Straight + angled escape':
            if length <= launch:raise ValueError('Escape length must exceed launch length.')
            normal,_=self._outward(fp,pad)
            x,y=x+math.cos(normal)*launch,y+math.sin(normal)*launch
            path.append(point(x,y))
            length-=launch
        if pattern=='Staggered rows':
            length += self.api.FromMM(float(values['stagger_pitch']))*(row_index%2)
        path.append(point(x+math.cos(angle)*length+ox,y+math.sin(angle)*length+oy))
        return [path]

    @staticmethod
    def _segments(plan):
        points=plan.path or [plan.start,plan.end]
        return list(zip(points,points[1:])) if plan.add_track else []

    @staticmethod
    def _on_layer(item, layer):
        getter=getattr(item,'IsOnLayer',None)
        if getter:return bool(getter(layer))
        getter=getattr(item,'GetLayer',None)
        return getter() == layer if getter else True

    def _blocked(self, plan, accepted, pads, tracks, zones, outline, margin):
        segments=self._segments(plan)
        vias=([plan.start] if plan.start_via else [])+([plan.end] if plan.add_via else [])
        # Drill overlap is unsafe even when the existing via has the same net.
        for item in tracks:
            if 'VIA' in str(getattr(item,'GetClass',lambda:'')()):
                if any(segment_hits_box(v,v,item.GetBoundingBox(),plan.via_diameter/2+margin) for v in vias):
                    return 'existing via overlap'
        obstacles=[item for item in pads+tracks if item.GetNetCode()!=plan.net_code]
        for item in obstacles:
            box=item.GetBoundingBox()
            if any(segment_hits_pad(v,v,item,plan.via_diameter/2+margin,self.api) for v in vias):
                return 'via clearance to other-net copper'
            if self._on_layer(item,plan.layer) and any(segment_hits_pad(a,b,item,plan.width/2+margin,self.api) for a,b in segments):
                return 'other-net copper'
        if any(not segment_inside_native(a,b,plan.width/2+margin,outline) for a,b in segments):
            return 'board edge/cutout'
        if any(not inside_native(v,plan.via_diameter/2+margin,outline) for v in vias):
            return 'via near board edge/cutout'
        for zone in zones:
            rule=zone.GetIsRuleArea()
            blocked_via=zone.GetDoNotAllowVias() if rule else zone.GetNetCode()!=plan.net_code
            blocked_track=zone.GetDoNotAllowTracks() if rule else zone.GetNetCode()!=plan.net_code
            box=zone.GetBoundingBox()
            if blocked_via and any(segment_hits_box(v,v,box,plan.via_diameter/2+margin) for v in vias):return 'zone/keepout'
            if blocked_track and self._on_layer(zone,plan.layer) and any(segment_hits_box(a,b,box,plan.width/2+margin) for a,b in segments):return 'zone/keepout'
        def distance(a,b,c,d):return segment_segment_distance((a.x,a.y),(b.x,b.y),(c.x,c.y),(d.x,d.y))
        for other in accepted:
            pair_margin=max(margin, getattr(other, 'clearance', 0))
            other_vias=([other.start] if other.start_via else [])+([other.end] if other.add_via else [])
            if any(math.hypot(a.x-b.x,a.y-b.y)<(plan.via_diameter+other.via_diameter)/2+pair_margin for a in vias for b in other_vias):
                return 'generated via overlap'
            if other.net_code==plan.net_code:continue
            other_segments=self._segments(other)
            if plan.layer==other.layer and any(distance(a,b,c,d)<(plan.width+other.width)/2+pair_margin-2 for a,b in segments for c,d in other_segments):return 'generated copper collision'
            if any(distance(v,v,a,b)<(plan.via_diameter+other.width)/2+pair_margin-2 for v in vias for a,b in other_segments):return 'generated via/track collision'
            if any(distance(v,v,a,b)<(other.via_diameter+plan.width)/2+pair_margin-2 for v in other_vias for a,b in segments):return 'generated via/track collision'
        return ''

    def _plan(self, eligible_override=None, accepted_seed=()) -> List[FanoutPlan]:
        from .fanout_groups import validate_groups
        validate_groups(self.settings['groups'], self.settings['unmatched'], self.defaults)
        if self.settings['groups'] or self.settings['unmatched'] != 'defaults':
            return self._plan_grouped()
        values=self._dimensions()
        for key, choices in [('pattern',FANOUT_PATTERNS+('Via-in-pad',)),('signal_profile',SIGNAL_PROFILES),
                             ('angle_mode',ANGLE_MODES),('pair_mode',PAIR_MODES),('routing_mode',('Fixed','Adaptive')),
                             ('output_mode',('Escape traces','Via-in-pad')),
                             ('scope',('All SMD pads','Selected pads','Selected footprints','Reference wildcard'))]:
            if values[key] not in choices:raise ValueError('Unknown '+key+': '+str(values[key]))
        pattern='Via-in-pad' if values['output_mode']=='Via-in-pad' else values['pattern']
        if min(self.api.FromMM(float(values[name])) for name in ('width','length','via_drill'))<=0:
            raise ValueError('Dimensions are below the board coordinate resolution.')
        if self.api.FromMM(float(values['via_diameter']))<=self.api.FromMM(float(values['via_drill'])):
            raise ValueError('Via diameter must exceed drill at board coordinate resolution.')
        if hasattr(self.api,'SHAPE_POLY_SET'):
            outline=self.api.SHAPE_POLY_SET()
            if not self.board.GetBoardPolygonOutlines(outline,False):raise ValueError('A closed, valid Edge.Cuts outline is required.')
        elif hasattr(self.board,'wayricad_outline'):outline=self.board.wayricad_outline()
        else:raise ValueError('This runtime cannot validate the board outline for fanout.')
        self.plan_rejections=[]
        pads=[p for f in self.board.GetFootprints() for p in f.Pads()]
        tracks=list(self.board.GetTracks());zones=list(self.board.Zones())
        margin=self.api.FromMM(float(values['clearance']))
        eligible=sorted(self._eligible_pads() if eligible_override is None else eligible_override,key=lambda row:(str(row[0].GetReference()),row[1].GetPosition().x,row[1].GetPosition().y,str(row[1].GetNumber())))
        result=[]
        for index,(group,pair_id) in enumerate(self._groups(eligible)):
            reason=''
            candidates=[]
            if any(not pad.GetNetCode() for _,pad in group):reason='no net'
            if pair_id and len({self._layer(pad) for _,pad in group})!=1:reason='pair members must use the same copper layer'
            if not reason:
                try:
                    if values['routing_mode']=='Adaptive' and pattern!='Via-in-pad':
                        if pair_id:
                            raise ValueError('Adaptive search currently requires independent escapes; use Fixed for differential pairs.')
                        from .adaptive_fanout import adaptive_paths
                        candidate,reason=adaptive_paths(self,group[0][0],group[0][1],values,pattern,
                            list(accepted_seed)+result,pads,tracks,zones,outline,margin)
                        candidates=[candidate] if candidate is not None else []
                    else:
                        paths=self._paths(group,pair_id,values,pattern,index)
                        candidates=[self._candidate(fp,pad,path,values,pattern,pair_id) for (fp,pad),path in zip(group,paths)]
                except ValueError as exc:reason=str(exc)
            if not reason and pair_id:
                if len({p.start_via for p in candidates})!=1:reason='pair members must use the same via transitions'
                elif max(p.length_mm for p in candidates)-min(p.length_mm for p in candidates)>float(values['max_pair_skew'])+0.000002:
                    reason='pair escape skew exceeds max_pair_skew (mm)'
                elif self.api.FromMM(float(values['pair_gap'])) <= 0:
                    reason='pair gap must be positive at board coordinate resolution'
                elif float(values['pair_gap'])<float(values['clearance']):
                    reason='pair gap is below configured clearance'
            accepted=[]
            for candidate in candidates:
                if reason:break
                reason=self._blocked(candidate,list(accepted_seed)+result+accepted,pads,tracks,zones,outline,margin)
                if not reason:accepted.append(candidate)
            if reason:
                for fp,pad in group:self.plan_rejections.append(f'{fp.GetReference()}.{pad.GetNumber()}: '+('differential pair rejected: ' if pair_id else '')+reason)
            else:result.extend(accepted)
        self.group_report=[dict(name="Defaults",index=-1,matched=len(eligible),accepted=len(result),rejected=len(self.plan_rejections),skipped=0)]
        return result


    def _plan_grouped(self):
        from .fanout_groups import matches
        rules=self.settings['groups']
        classes=project_netclasses(self.board)
        eligible=self._eligible_pads()
        buckets=[[] for _ in rules]+[[]]
        owners={}
        for fp,pad in eligible:
            owner=next((i for i,rule in enumerate(rules) if matches(rule,fp,pad,classes,pad_in_netclass)),len(rules))
            buckets[owner].append((fp,pad));owners[item_id(pad)]=owner
        if buckets[-1] and self.settings['unmatched']=='error':
            names=', '.join(f'{fp.GetReference()}.{pad.GetNumber()}' for fp,pad in buckets[-1][:8])
            raise ValueError('Unmatched fanout pads: '+names)
        self.plan_rejections=[]
        self.group_report=[]
        planners=[]
        for index in range(len(buckets)):
            settings=dict(self.settings,groups=[],unmatched='defaults')
            if index<len(rules):
                settings.update(rules[index].get('settings',{}))
                # Netclass dimensions follow this rule's exact class, when set.
                if 'netclass' in rules[index].get('match',{}):
                    settings['netclass_filter']=rules[index]['match']['netclass']
            planner=FanoutPlanner(self.board,self.api,settings)
            # Validate even an empty rule; hidden invalid overrides must not wait
            # until a future board selection happens to match the rule.
            planner._dimensions()
            planners.append(planner)
        split=set()
        pairs={}
        for fp,pad in eligible:
            parsed=self._pair_key(pad.GetNetname())
            if parsed:pairs.setdefault((item_id(fp),parsed[0]),[]).append(pad)
        for pads in pairs.values():
            indices={owners[item_id(p)] for p in pads}
            if len(indices)>1 and any(planners[i].settings['pair_mode']=='Auto differential pairs' for i in indices):
                split.update(item_id(p) for p in pads)
        result=[]
        for index,entries in enumerate(buckets):
            name=rules[index]['name'] if index<len(rules) else 'Defaults'
            skipped=index==len(rules) and self.settings['unmatched']=='skip'
            usable=[]
            before=len(self.plan_rejections)
            for fp,pad in entries:
                reason='differential mates match different groups' if item_id(pad) in split else ('unmatched pad skipped' if skipped else '')
                if reason:self.plan_rejections.append(f'{fp.GetReference()}.{pad.GetNumber()} [{name}]: '+reason)
                else:usable.append((fp,pad))
            plans=planners[index]._plan(usable,result)
            for plan in plans:
                plan.group_name=name;plan.group_index=index if index<len(rules) else -1
            self.plan_rejections.extend(f'[{name}] '+r for r in planners[index].plan_rejections)
            result.extend(plans)
            self.group_report.append(dict(name=name,index=index if index<len(rules) else -1,matched=len(entries),accepted=len(plans),rejected=len(self.plan_rejections)-before,skipped=len(entries) if skipped else 0))
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
            points=plan.path or [plan.start,plan.end]
            for start,end in zip(points,points[1:]):
                if start.x==end.x and start.y==end.y:continue
                track=api.PCB_TRACK(board)
                track.SetStart(start); track.SetEnd(end)
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
    group_summary=[]
    if kind == 'fanout':
        planner=FanoutPlanner(board,api,settings or {})
        plans=planner._plan();rejected=planner.plan_rejections
        group_summary=getattr(planner,'group_report',[])
        records=[dict(reference=p.footprint.GetReference(),pad=p.pad.GetNumber(),net=p.pad.GetNetname(),
                      start_mm=[api.ToMM(p.start.x),api.ToMM(p.start.y)],end_mm=[api.ToMM(p.end.x),api.ToMM(p.end.y)],
                      path_mm=[[api.ToMM(point.x),api.ToMM(point.y)] for point in (p.path or [p.start,p.end])],
                      length_mm=p.length_mm,pair_id=p.pair_id,group_name=p.group_name,group_index=p.group_index,clearance_mm=api.ToMM(p.clearance),pattern=p.pattern,
                      width_mm=api.ToMM(p.width),via_diameter_mm=api.ToMM(p.via_diameter),via_drill_mm=api.ToMM(p.via_drill),
                      add_track=p.add_track,add_via=p.add_via,start_via=p.start_via,layer=board.GetLayerName(p.layer)) for p in plans]
    elif kind == 'stitching':
        plans, rejected = plan_stitching(board, api, settings)
        records=[dict(position_mm=[api.ToMM(p.GetPosition().x),api.ToMM(p.GetPosition().y)],
                      diameter_mm=api.ToMM(p.GetWidth(api.F_Cu)),drill_mm=api.ToMM(p.GetDrillValue()),net=p.GetNetname()) for p in plans]
    else: raise ValueError('Routing kind must be fanout or stitching.')
    return dict(schema=1,kind=kind,settings=settings or {},board_fingerprint=board_fingerprint(board),
                candidates=records,rejected=rejected,group_summary=group_summary,unmatched_count=sum(g['matched'] for g in group_summary if g['index']==-1),skipped_count=sum(g['skipped'] for g in group_summary),warning='Conservative geometry checks; run KiCad DRC before manufacturing.')
