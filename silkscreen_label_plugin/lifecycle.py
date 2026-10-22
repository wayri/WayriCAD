"""Read-only generated-object audit and explicit reversible leader cleanup.

Legacy guide names and TP ownership groups are evidence for review, not enough
by themselves to authorize deletion. A versioned board-property manifest records
UUIDs and bounded generation settings. Cleanup removes only verified, exclusively
owned silk segments; it never changes annotation text or the underlying layout.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import uuid

from .placement import (GUIDE_PREFIX, NET_PREFIX, fingerprint, item_id, _texts,
                        _state, text_geometry, polygons, inside_polygon,
                        point_segment_distance, courtyard_envelopes)

MANIFEST_KEY = 'wayricad.silkscreen.generated.v1'
MAX_RECORDS = 4096
MAX_MEMBERS = 64
MAX_BYTES = 4194304
SETTING_KEYS = frozenset(('height', 'thickness', 'clearance', 'body_clearance',
    'guide_thickness', 'min_height', 'auto_size', 'size_step', 'edge_margin',
    'allowed_rotations', 'reading_direction', 'leaders', 'leader_distance',
    'max_radius', 'step', 'testpoint_net_names', 'protect_tented_drills',
    'preserve_acceptable', 'problem_only', 'orientation_preference',
    'normal_distance', 'min_width', 'min_width_ratio', 'repack_neighbours',
    'repack_displacement', 'leader_limit', 'leader_max_length'))


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Ownership identifiers must be canonical UUIDs.')
    return value


def _settings(settings):
    if not isinstance(settings, dict) or not set(settings) <= SETTING_KEYS:
        raise ValueError('Unsupported generated-object settings.')
    def valid(value):
        if isinstance(value, bool):return True
        if isinstance(value, (int, float)):return abs(value) <= 1000000 and math.isfinite(value)
        if isinstance(value, str):return len(value) <= 64 and not any(ord(c)<32 for c in value)
        return isinstance(value, (tuple, list)) and len(value)<=36 and all(
            isinstance(v, (int,float)) and not isinstance(v,bool) and abs(v)<=1000000 and math.isfinite(v) for v in value)
    if not all(valid(value) for value in settings.values()):
        raise ValueError('Generated-object settings exceed their bounded schema.')
    booleans={'auto_size','leaders','testpoint_net_names','protect_tented_drills','preserve_acceptable','problem_only'}
    for key,value in settings.items():
        if key=='reading_direction':
            if value not in ('Bottom/right','Top/left','Either'):raise ValueError('Unsupported reading direction.')
        elif key=='orientation_preference':
            if value not in ('Footprint axis','Common direction'):raise ValueError('Unsupported orientation preference.')
        elif key=='allowed_rotations':
            if not isinstance(value,(tuple,list)) or not value or any(not 0<=angle<180 for angle in value):raise ValueError('Allowed rotations must contain at most 36 finite angles in [0, 180).')
        elif key in ('repack_neighbours','leader_limit'):
            maximum=12 if key=='repack_neighbours' else 100000
            if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=maximum:raise ValueError('Generated-object count is outside its supported integer range.')
        elif key in booleans:
            if not isinstance(value,bool):raise ValueError('Generated-object switch must be Boolean.')
        elif not isinstance(value,(int,float)) or isinstance(value,bool):
            raise ValueError('Generated-object dimension must be numeric.')
        elif value<0 or value==0 and key not in ('body_clearance','edge_margin','repack_displacement'):
            raise ValueError('Generated-object dimension is outside its supported range.')
        elif key=='min_width_ratio' and value>1:
            raise ValueError('Minimum width ratio must not exceed 1.')
    return dict(settings)


def _records(records):
    if not isinstance(records, (list, tuple)) or len(records)>MAX_RECORDS:
        raise ValueError('Too many generated-object ownership records.')
    result=[];groups=set()
    for row in records:
        if not isinstance(row,dict) or set(row)!={'footprint','text','group','leaders','settings'}:
            raise ValueError('Unsupported generated-object ownership record.')
        record={key:_uuid(row[key]) for key in ('footprint','text')}
        record['group']=_uuid(row['group']) if row['group'] is not None else None
        leaders=row['leaders']
        if not isinstance(leaders,(list,tuple)) or len(leaders)>MAX_MEMBERS or bool(leaders)!=(record['group'] is not None):
            raise ValueError('Invalid generated leader count.')
        record['leaders']=sorted(_uuid(value) for value in leaders)
        identity=record['group'] or 'text:'+record['text']
        if len(set(record['leaders']))!=len(leaders) or identity in groups:
            raise ValueError('Duplicate ownership identifiers.')
        groups.add(identity);record['settings']=_settings(row['settings']);result.append(record)
    return sorted(result,key=lambda row:(row['text'],row['group'] or ''))


def manifest_value(records):
    """Return bounded persistent metadata; this function never writes the board."""
    value=json.dumps(dict(v=1,records=_records(records)),sort_keys=True,separators=(',',':'),allow_nan=False)
    if len(value.encode('utf-8'))>MAX_BYTES:raise ValueError('Ownership metadata is too large.')
    return value


def manifest_properties(board, records):
    """Copy native properties with reviewed records for a caller's transaction.

    Callers must journal their explicit ``board.SetProperties`` write alongside
    creation/replacement of the corresponding objects. Audit never adopts legacy
    objects or writes this property automatically.
    """
    source=board.GetProperties();properties=type(source)()
    for key,value in source.items():properties[key]=value
    properties[MANIFEST_KEY]=manifest_value(records)
    return properties


def _properties(board):
    return {str(key):str(value) for key,value in board.GetProperties().items()}


def _native_properties(api, values):
    result=api.MAP_STRING_STRING()
    for key,value in values.items():result[key]=value
    return result


def _fingerprint(board,api):
    groups=[(item_id(g),g.IsLocked(),g.GetParentGroupId().AsString(),
             sorted((item_id(i),i.IsLocked(),i.GetParentGroupId().AsString()) for i in g.GetItems())) for g in board.Groups()]
    return hashlib.sha256(json.dumps([fingerprint(board,api),_properties(board),sorted(groups)],sort_keys=True).encode()).hexdigest()


def _manifest(board):
    raw=_properties(board).get(MANIFEST_KEY)
    if raw is None:return [],None
    try:
        if len(raw.encode('utf-8'))>MAX_BYTES:raise ValueError('Ownership metadata is too large.')
        data=json.loads(raw)
        if not isinstance(data,dict) or set(data)!={'v','records'} or type(data['v']) is not int or data['v']!=1:
            raise ValueError('Unsupported ownership metadata version.')
        return _records(data['records']),None
    except (ValueError,TypeError,KeyError) as exc:return [],str(exc)


def _net_owner(group, footprints, drawings, api):
    """Validate the existing TP metadata without adopting arbitrary board text."""
    data=json.loads(group.GetName()[len(NET_PREFIX):])
    if not isinstance(data,dict) or set(data)!={'v','footprint','reference','visible'} or type(data['v']) is not int or data['v']!=1 or not isinstance(data['visible'],bool):
        raise ValueError('Unsupported TP ownership metadata.')
    fp=footprints[data['footprint']];members=list(group.GetItems())
    if data['reference']!=item_id(fp.Reference()) or len(members)!=1:
        raise ValueError('TP owner or text is missing.')
    text=members[0]
    if not isinstance(text,api.PCB_TEXT) or item_id(text) not in drawings or text.GetParentFootprint() is not None or text.GetParentGroupId().AsString()!=item_id(group):
        raise ValueError('TP ownership is not exclusive.')
    return data['footprint'],item_id(text)


def _point_box_gap(point, box):
    dx=max(box.GetLeft()-point[0],0,point[0]-box.GetRight())
    dy=max(box.GetTop()-point[1],0,point[1]-box.GetBottom())
    return math.hypot(dx,dy)


def _point_polyset_gap(point, polyset):
    shapes=polygons(polyset)
    if any(inside_polygon(point,outer,holes) for outer,holes in shapes):return 0.0
    return min((point_segment_distance(point,a,b)
                for outer,holes in shapes for ring in [outer,*holes]
                for a,b in zip(ring,ring[1:]+ring[:1])),default=math.inf)


def _guide_attached(board, members, owner, footprint, settings, api):
    """Check a manifest-owned guide against the current 2D planner envelopes.

    The planner places endpoints on inflated axis-aligned glyph and courtyard
    envelopes, including their corners. Use the same rectangular margins here,
    rather than Euclidean distance to a different polygon/body model. This is
    envelope attachment, not physical package contact. The finite tolerance is
    the recorded margin plus half the guide stroke and 0.02 mm; it does not
    grow with board size or label movement.
    """
    if owner is None or footprint is None or not members:return False
    layer=owner.GetLayer()
    if layer not in (api.F_SilkS,api.B_SilkS):return False
    if any(member.GetLayer()!=layer for member in members):return False
    # Current planner emits one direct segment. Treat a changed or branched
    # path as detached; ownership still makes explicit cleanup safe.
    if len(members)!=1:return False
    line=members[0]
    start,end=line.GetStart(),line.GetEnd()
    endpoints=((start.x,start.y),(end.x,end.y))
    _clone,glyphs=text_geometry(owner,_state(owner),api)
    if not glyphs.OutlineCount():return False
    glyph_box=glyphs.BBox()
    from .placement import DEFAULTS
    try:
        clearance=float(settings.get('clearance',DEFAULTS['clearance']))
        body_clearance=float(settings.get('body_clearance',DEFAULTS['body_clearance']))
        recorded_width=float(settings.get('guide_thickness',DEFAULTS['guide_thickness']))
    except (TypeError,ValueError):return False
    board_minimum=api.FromMM(recorded_width)
    try:board_minimum=max(board_minimum,board.GetDesignSettings().m_MinSilkTextThickness)
    except (AttributeError,TypeError):pass
    if abs(line.GetWidth()-board_minimum)>api.FromMM(.02):return False
    width=board_minimum
    floor=api.FromMM(.02)
    text_tolerance=api.FromMM(clearance)+width//2+floor
    body_tolerance=max(api.FromMM(clearance),api.FromMM(body_clearance))+width//2+floor
    def envelope_gap(point,box):
        return max(box.GetLeft()-point[0],0,point[0]-box.GetRight(),
                   box.GetTop()-point[1],point[1]-box.GetBottom())
    text_gaps=[envelope_gap(point,glyph_box) for point in endpoints]
    envelopes=courtyard_envelopes(footprint,api)
    owner_layer=api.B_SilkS if footprint.GetLayer()==api.B_Cu else api.F_SilkS
    body=envelopes.get(layer,envelopes.get(owner_layer))
    if body is None:return False
    footprint_gaps=[envelope_gap(point,body) for point in endpoints]
    return ((text_gaps[0]<=text_tolerance and footprint_gaps[1]<=body_tolerance)
            or (text_gaps[1]<=text_tolerance and footprint_gaps[0]<=body_tolerance))


def ownership_record(board,api,group,footprint,text,settings=None):
    """Describe explicitly generated leaders for the generation transaction.

    This does not adopt, rename, add or delete any object. ``group`` and its
    native members must already exist; save the returned record atomically with
    their creation. Ownerless or handmade artwork must not be passed here.
    """
    row=dict(footprint=item_id(footprint),text=item_id(text),group=item_id(group) if group is not None else None,
             leaders=[item_id(i) for i in group.GetItems()] if group is not None else [],settings=settings or {})
    return _records([row])[0]


@dataclass(frozen=True)
class Audit:
    source_fingerprint: str
    findings: tuple
    records: tuple

    def as_dict(self):
        return dict(source_fingerprint=self.source_fingerprint,findings=list(self.findings),
                    cleanup_group_ids=[r['group'] for r in self.findings if r.get('cleanup_eligible')])


def audit(board,api):
    """Report orphaned, duplicate and uncertain managed objects without writes."""
    source=_fingerprint(board,api);records,error=_manifest(board)
    groups={item_id(g):g for g in board.Groups()};footprints={item_id(fp):fp for fp in board.GetFootprints()}
    drawings={item_id(i):i for i in board.GetDrawings()};texts={item_id(t):(t,fp) for t,fp,_ in _texts(board,api)}
    memberships={};findings=[];nets={}
    for group in groups.values():
        for obj in group.GetItems():memberships.setdefault(item_id(obj),[]).append(item_id(group))
        if group.GetName().startswith(NET_PREFIX):
            try:
                owner,text=_net_owner(group,footprints,drawings,api)
                nets.setdefault(owner,[]).append((item_id(group),text))
                findings.append(dict(group=item_id(group),kind='annotation',status='managed',confidence='native-owner',cleanup_eligible=False,text=text,footprint=owner))
            except (ValueError,KeyError,TypeError) as exc:
                findings.append(dict(group=item_id(group),kind='annotation',status='uncertain',confidence='uncertain',cleanup_eligible=False,reason=str(exc)))
    for owner,entries in nets.items():
        if len(entries)>1:
            for group,text in entries:findings.append(dict(group=group,kind='annotation',status='duplicate',confidence='uncertain',cleanup_eligible=False,footprint=owner,text=text))
    if error:findings.append(dict(group=None,kind='metadata',status='uncertain',confidence='uncertain',cleanup_eligible=False,reason=error))
    managed={row['group'] for row in records};bytext={}
    for row in records:bytext.setdefault(row['text'],[]).append(row['group'])
    for row in records:
        gid=row['group'];group=groups.get(gid);issues=[];orphan=[]
        if gid is None:
            owner=texts.get(row['text']);fp=footprints.get(row['footprint'])
            valid=owner is not None and fp is not None and (owner[1] is not None and item_id(owner[1])==row['footprint'] or [t for g,t in nets.get(row['footprint'],[])]==[row['text']])
            findings.append(dict(group=None,kind='text',status='managed' if valid else 'orphan_metadata',confidence='manifest',cleanup_eligible=False,text=row['text'],footprint=row['footprint']))
            continue
        if group is None:
            findings.append(dict(group=gid,kind='leaders',status='orphan_metadata',confidence='manifest',cleanup_eligible=False,text=row['text'],reason='Managed group is absent.'));continue
        members=list(group.GetItems());fp=footprints.get(row['footprint']);owner=texts.get(row['text'])
        if group.GetName()!=GUIDE_PREFIX+row['text']:issues.append('Group name does not match recorded owner.')
        if set(item_id(i) for i in members)!=set(row['leaders']):issues.append('Group members changed or are missing.')
        if group.GetParentGroup() is not None:issues.append('Managed group is nested in another group.')
        if group.IsLocked() or any(i.IsLocked() for i in members) or fp is not None and fp.IsLocked() or owner is not None and owner[0].IsLocked():issues.append('An owner or generated object is locked.')
        for obj in members:
            if (not isinstance(obj,api.PCB_SHAPE) or obj.GetShape()!=api.SHAPE_T_SEGMENT
                    or obj.GetLayer() not in (api.F_SilkS,api.B_SilkS) or item_id(obj) not in drawings
                    or memberships.get(item_id(obj))!=[gid] or obj.GetParentGroupId().AsString()!=gid):
                issues.append('A member is not an exclusively owned board silkscreen segment.');break
        if fp is None:orphan.append('Owning footprint is absent.')
        if owner is None:orphan.append('Owning text is absent.')
        elif fp is not None:
            native_owner=owner[1]
            net_matches=[t for g,t in nets.get(row['footprint'],[])]
            if not (native_owner is not None and item_id(native_owner)==row['footprint'] or net_matches==[row['text']]):issues.append('Text no longer belongs to the recorded footprint.')
        detached=(not issues and not orphan and owner is not None and fp is not None
                  and not _guide_attached(board,members,owner[0],fp,row['settings'],api))
        status=('uncertain' if issues else 'orphan' if orphan else 'detached' if detached
                else 'duplicate' if len(bytext[row['text']])>1 else 'managed')
        reason=issues+orphan+(['Guide endpoints no longer meet the current rendered-text and 2D planner body envelopes.'] if detached else [])
        findings.append(dict(group=gid,kind='leaders',status=status,confidence='uncertain' if issues else 'manifest',cleanup_eligible=not issues,text=row['text'],footprint=row['footprint'],attachment='detached' if detached else 'attached' if owner is not None and fp is not None and not issues and not orphan else 'not_checked',reason=' '.join(reason)))
    for gid,group in groups.items():
        if group.GetName().startswith(GUIDE_PREFIX) and gid not in managed:
            findings.append(dict(group=gid,kind='leaders',status='legacy_unverified',confidence='uncertain',cleanup_eligible=False,reason='Namespace-only legacy ownership; review without deleting artwork.'))
    if source!=_fingerprint(board,api):raise ValueError('Board changed during generated-object audit.')
    return Audit(source,tuple(findings),tuple(records))


@dataclass(frozen=True)
class CleanupPlan:
    source_fingerprint: str
    group_ids: tuple
    before_properties: dict
    after_properties: dict


def plan_cleanup(board,api,group_ids=None):
    """Preview explicit removal of verified generated leaders, retaining text."""
    report=audit(board,api);eligible={r['group'] for r in report.findings if r.get('cleanup_eligible')}
    wanted=eligible if group_ids is None else set(group_ids)
    if not wanted<=eligible:raise ValueError('Cleanup contains uncertain, missing or protected groups; review the audit.')
    before=_properties(board);after=dict(before)
    if wanted:
        retained={}
        for row in report.records:
            updated=dict(row,group=None,leaders=[]) if row['group'] in wanted else row
            retained.setdefault(updated['group'] or 'text:'+updated['text'],updated)
        after[MANIFEST_KEY]=manifest_value(list(retained.values()))
    return CleanupPlan(report.source_fingerprint,tuple(sorted(wanted)),before,after)


class CleanupTransaction:
    """Atomic cleanup with stale checks and exact reversible native ownership."""
    def __init__(self,board,api,preview):
        self.board,self.api,self.preview=board,api,preview;self.expected=preview.source_fingerprint;self.applied=False
        available={item_id(g):g for g in board.Groups()}
        self.groups=[(available[key],list(available[key].GetItems())) for key in preview.group_ids]

    def _check(self):
        if _fingerprint(self.board,self.api)!=self.expected:raise ValueError('Board changed; audit again before cleanup or undo.')

    def _presence(self,item,wanted,journal):
        def ensure(present):
            objects=self.board.Groups() if isinstance(item,self.api.PCB_GROUP) else self.board.GetDrawings()
            if any(item_id(obj)==item_id(item) for obj in objects)!=present:
                (self.board.Add if present else self.board.Remove)(item)
        journal.append(lambda:ensure(not wanted));ensure(wanted)

    @staticmethod
    def _membership(group,item,wanted,journal):
        def ensure(present):
            if any(item_id(obj)==item_id(item) for obj in group.GetItems())!=present:
                (group.AddItem if present else group.RemoveItem)(item)
        journal.append(lambda:ensure(not wanted));ensure(wanted)

    def _properties(self,values,previous,journal):
        journal.append(lambda:self.board.SetProperties(_native_properties(self.api,previous)))
        self.board.SetProperties(_native_properties(self.api,values))

    def _run(self,forward):
        self._check();journal=[]
        try:
            for group,members in self.groups:
                if forward:
                    for item in members:self._membership(group,item,False,journal);self._presence(item,False,journal)
                    self._presence(group,False,journal)
                else:
                    self._presence(group,True,journal)
                    for item in members:self._presence(item,True,journal);self._membership(group,item,True,journal)
            target=self.preview.after_properties if forward else self.preview.before_properties
            previous=self.preview.before_properties if forward else self.preview.after_properties
            self._properties(target,previous,journal)
            expected=_fingerprint(self.board,self.api)
        except Exception as original:
            errors=[]
            for inverse in reversed(journal):
                try:inverse()
                except Exception as exc:errors.append(str(exc))
            if errors:
                failure=RuntimeError('Generated-object cleanup recovery needs attention: '+'; '.join(errors));failure.transaction=self
                raise failure from original
            raise
        self.expected=expected;self.applied=forward;return self

    def redo(self):
        if self.applied:raise ValueError('Cleanup is already applied.')
        return self._run(True)

    def undo(self):
        if not self.applied:raise ValueError('Cleanup is not applied.')
        return self._run(False)


def apply_cleanup(board,api,preview):
    """Apply an explicit reviewed cleanup and return its undo/redo transaction."""
    if _fingerprint(board,api)!=preview.source_fingerprint:raise ValueError('Board changed; audit again before cleanup.')
    return CleanupTransaction(board,api,preview).redo()


def verified_group_ids(board,api):
    """Return only manifest-verified, exclusively owned, unprotected guide groups."""
    return frozenset(row['group'] for row in audit(board,api).findings if row.get('cleanup_eligible'))


def generation_properties(board,api,entries,settings=None,removed_text_ids=()):
    """Build properties for an existing generation transaction, without writes.

    ``entries`` contains ``(footprint, text, leader_group_or_None)`` for the
    accepted objects. Text-only records persist settings without creating fake
    geometry. Existing records for other text owners remain intact. Journal the
    returned ``SetProperties`` write together with text and leader edits. Explicit
    ``removed_text_ids`` forget only annotations removed by that transaction;
    they never delete native text themselves.
    """
    if not isinstance(removed_text_ids,(list,tuple,set,frozenset)) or len(removed_text_ids)>MAX_RECORDS:
        raise ValueError('Removed text identifiers must be a bounded collection.')
    removed={_uuid(value) for value in removed_text_ids}
    previous,error=_manifest(board)
    if error:raise ValueError('Cannot replace uncertain generated-object metadata: '+error)
    settings={key:value for key,value in (settings or {}).items() if key in SETTING_KEYS}
    current=[ownership_record(board,api,group,fp,text,settings) for fp,text,group in entries]
    replaced={row['text'] for row in current}
    if replaced & removed:raise ValueError('A removed text cannot also be registered as generated.')
    return manifest_properties(board,[row for row in previous if row['text'] not in replaced and row['text'] not in removed]+current)
