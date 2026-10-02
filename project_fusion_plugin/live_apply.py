"""Reviewed, non-saving live PCB edits through official KiCad IPC.

This boundary deliberately does not expose a schematic transaction, net creation,
file overwrite or legacy pcbnew mutation. Installed KiCad 10 kicad-python supports
PCB item commits, not a cross-editor project transaction. Callers must show a
preview and pass a detached-native validation result bound to the exact plan.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import uuid
from . import sexpr as sx
from .model import MergeError

API_REFERENCE='https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/'

class UnsupportedLiveApply(MergeError):pass
class StaleLivePlan(MergeError):pass
class LiveRollbackError(MergeError):pass


def _sha(data):return hashlib.sha256(data).hexdigest()
def _blob(value):
    if hasattr(value,'SerializeToString'):return value.SerializeToString(deterministic=True)
    if hasattr(value,'proto'):return _blob(value.proto)
    return json.dumps(value,sort_keys=True,default=str).encode()
def _id(item):return str(item.id.value)
def _canonical(tree):return sx.dumps(tree).encode()
def _item_key(node):return sx.value(node,'uuid') or sx.value(node,'tstamp')

def capabilities(board=None):
    required=('get_as_string','get_footprints','get_nets','get_enabled_layers','begin_commit','push_commit','drop_commit','update_items','create_items','get_items_by_id')
    missing=list(required) if board is None else [name for name in required if not callable(getattr(board,name,None))]
    return dict(pcb_live_available=not missing,pcb_placement=not missing,pcb_typed_item_import=not missing,
        schematic_live_available=False,new_net_import_available=False,cross_editor_atomic_commit=False,
        missing_methods=missing,placement_scope='Existing unrouted footprints; same side; translate/rotate only',
        import_scope='Reviewed typed PCB items using existing target nets and layers; no project rules/library writes',
        undo='One native PCB undo/redo step per accepted apply',
        status='Ready for PCB preview' if not missing else 'Originating PCB IPC connection unavailable',api_reference=API_REFERENCE)


def connect_originating_board(expected_path, *, client=None, timeout_ms=2000):
    """Read only the exact open PCB on the toolbar-provided IPC endpoint.

    Never enables IPC, scans sockets, chooses docs[0], starts or restarts KiCad.
    """
    expected=Path(expected_path).expanduser()
    if not expected.is_absolute() or expected.suffix.lower()!='.kicad_pcb':
        raise UnsupportedLiveApply('Live apply needs the exact absolute target PCB path')
    try:
        from kipy import KiCad
        from kipy.board import Board
        from kipy.proto.common.types import DocumentType
        if client is None:
            socket=os.environ.get('KICAD_API_SOCKET','').strip();token=os.environ.get('KICAD_API_TOKEN','')
            if not socket or not token:
                raise UnsupportedLiveApply('No originating IPC endpoint. Launch Fusion from the PCB Editor IPC action. IPC will not be enabled automatically.')
            client=KiCad(socket_path=socket,kicad_token=token,timeout_ms=timeout_ms)
        if client.get_version().major<10:raise UnsupportedLiveApply('Live Fusion PCB edits require KiCad 10 or later')
        matched=[]
        for doc in client.get_open_documents(DocumentType.DOCTYPE_PCB):
            name=str(doc.board_filename);path=Path(name)
            if not path.is_absolute():
                directory=Path(str(doc.project.path))
                if not directory.is_absolute():continue
                if directory.suffix.lower() in ('.kicad_pro','.pro'):directory=directory.parent
                path=directory/path
            if str(path.resolve()).casefold()==str(expected.resolve()).casefold():matched.append(doc)
        if len(matched)!=1:raise UnsupportedLiveApply('Exact originating PCB was not uniquely found; reopen its Fusion action')
        board=Board(client._client,matched[0])
        capture_snapshot(board)
        return board
    except UnsupportedLiveApply:raise
    except Exception as error:
        token=os.environ.get('KICAD_API_TOKEN','');message=str(error)
        if token:message=message.replace(token,'[redacted]')
        raise UnsupportedLiveApply('Originating PCB IPC is unavailable: '+message+'. Keep editors open and use a reviewed project copy.') from error


def _rules(board):
    nets=list(board.get_nets());names=sorted(str(n.name) for n in nets)
    classes={}
    if callable(getattr(board,'get_netclass_for_nets',None)) and nets:
        classes={str(n):_sha(_blob(c)) for n,c in board.get_netclass_for_nets(nets).items()}
    project_classes=[]
    if callable(getattr(board,'get_project',None)):
        project=board.get_project()
        if callable(getattr(project,'get_net_classes',None)):project_classes=sorted(_sha(_blob(c)) for c in project.get_net_classes())
    stack=board.get_stackup() if callable(getattr(board,'get_stackup',None)) else None
    return dict(nets=names,layers=sorted(board.get_enabled_layers()),classes=classes,
                stackup=_sha(_blob(stack)) if stack is not None else None,project_classes=project_classes)


def capture_snapshot(board):
    caps=capabilities(board)
    if not caps['pcb_live_available']:raise UnsupportedLiveApply(caps['status']+': '+', '.join(caps['missing_methods']))
    document=getattr(board,'document',None)
    if document is None:raise UnsupportedLiveApply('No originating document identity; launch from its PCB Editor action')
    text=board.get_as_string();tree=sx.loads(text)
    if sx.tag(tree)!='kicad_pcb':raise UnsupportedLiveApply('Originating IPC document is not a PCB')
    rules=_rules(board)
    return dict(document_sha256=_sha(_blob(document)),board_sha256=_sha(_canonical(tree)),
                rules=rules,rules_sha256=_sha(_blob(rules)),tree=tree)


@dataclass
class LivePlan:
    snapshot:dict
    updates:list=field(default_factory=list)
    additions:list=field(default_factory=list)
    title:str='Fusion PCB placement'
    uuid_map:dict=field(default_factory=dict)
    warnings:list=field(default_factory=lambda:['PCB-only transaction: schematic hierarchy and project/library tables are not changed.'])
    plan_sha256:str=''

    def seal(self):
        self.plan_sha256=_sha(_blob(dict(source=self.snapshot['board_sha256'],document=self.snapshot['document_sha256'],
            rules=self.snapshot['rules_sha256'],snapshot_tree=_sha(_canonical(self.snapshot['tree'])),snapshot_rules=_sha(_blob(self.snapshot['rules'])),updates=[_sha(_blob(i)) for i in self.updates],
            additions=[_sha(_blob(i)) for i in self.additions],uuid_map=self.uuid_map)))
        return self

    def overview(self):
        return dict(plan_sha256=self.plan_sha256,source_board_sha256=self.snapshot['board_sha256'],
                    updated_items=len(self.updates),added_items=len(self.additions),warnings=list(self.warnings),
                    schematic_changed=False,new_nets_created=False,files_written=False)


def _repeated(descriptor):
    value=getattr(descriptor,'is_repeated',None)
    return bool(value) if value is not None else descriptor.label==descriptor.LABEL_REPEATED


def _any_payload(proto):
    if getattr(getattr(proto,'DESCRIPTOR',None),'full_name','')!='google.protobuf.Any':return None
    from kipy.util import unpack_any
    try:return unpack_any(proto)
    except Exception as error:raise UnsupportedLiveApply('Unsupported typed child geometry in imported IPC item') from error


def _net_names(proto):
    packed=_any_payload(proto)
    if packed is not None:return _net_names(packed)
    names=set()
    if getattr(getattr(proto,'DESCRIPTOR',None),'name','')=='Net':
        if str(proto.name):names.add(str(proto.name))
        return names
    for descriptor,value in proto.ListFields():
        if descriptor.message_type is None:continue
        if _repeated(descriptor):
            if descriptor.message_type.GetOptions().map_entry:values=value.values()
            else:values=value
        else:values=[value]
        for child in values:
            if hasattr(child,'ListFields'):names.update(_net_names(child))
    return names


def _layers(proto):
    packed=_any_payload(proto)
    if packed is not None:return _layers(packed)
    found=set()
    for descriptor,value in proto.ListFields():
        if descriptor.enum_type is not None and descriptor.enum_type.name=='BoardLayer':
            for layer in value if _repeated(descriptor) else [value]:
                name=descriptor.enum_type.values_by_number[int(layer)].name
                if name not in ('BL_UNKNOWN','BL_UNDEFINED'):found.add(int(layer))
        if descriptor.message_type is None:continue
        if _repeated(descriptor):values=value.values() if descriptor.message_type.GetOptions().map_entry else value
        else:values=[value]
        for child in values:
            if hasattr(child,'ListFields'):found.update(_layers(child))
    return found


def _remap(proto,mapping):
    packed=_any_payload(proto)
    if packed is not None:
        _remap(packed,mapping);proto.Pack(packed);return
    kind=getattr(getattr(proto,'DESCRIPTOR',None),'name','')
    if kind=='KIID':
        old=str(proto.value)
        if old in mapping:proto.value=mapping[old]
        return
    if kind=='Net':
        # Stable names, never the incoming board's deprecated local net code.
        if 'code' in proto.DESCRIPTOR.fields_by_name:proto.ClearField('code')
        return
    for descriptor,value in proto.ListFields():
        if descriptor.message_type is None:continue
        if _repeated(descriptor):
            values=value.values() if descriptor.message_type.GetOptions().map_entry else value
        else:values=[value]
        for child in values:
            if hasattr(child,'ListFields'):_remap(child,mapping)


def _identities(proto):
    packed=_any_payload(proto)
    if packed is not None:return _identities(packed)
    if getattr(getattr(proto,'DESCRIPTOR',None),'name','')=='KIID':return {str(proto.value)} if proto.value else set()
    found=set()
    for descriptor,value in proto.ListFields():
        if descriptor.message_type is None:continue
        if _repeated(descriptor):values=value.values() if descriptor.message_type.GetOptions().map_entry else value
        else:values=[value]
        for child in values:
            if hasattr(child,'ListFields'):found.update(_identities(child))
    return found


def preview_items(board,items,instance_key,*,schematic_required=False):
    """Import official SDK wrappers already extracted by a supported adapter.

    Arbitrary saved-board parsing is not supplied by installed official kipy;
    callers may not convert unsupported custom geometry to approximate wrappers.
    """
    if schematic_required:raise UnsupportedLiveApply('Installed API cannot commit schematic and PCB hierarchy together; create a reviewed project copy')
    if not str(instance_key).strip():raise MergeError('A stable unique import instance key is required')
    snapshot=capture_snapshot(board);incoming=list(items)
    if not incoming:raise MergeError('No supported PCB items selected')
    source_ids=set().union(*[_identities(i.proto) for i in incoming])
    if any(not hasattr(i,'id') or not _id(i) for i in incoming):raise MergeError('Incoming item lacks a stable identity')
    if len({_id(i) for i in incoming})!=len(incoming):raise MergeError('Duplicate incoming root item identities')
    namespace=uuid.uuid5(uuid.NAMESPACE_URL,snapshot['document_sha256']+'/'+str(instance_key))
    mapping={old:str(uuid.uuid5(namespace,old)) for old in sorted(source_ids)}
    existing=set(sx.declared_uuids(snapshot['tree']))
    if set(mapping.values()) & existing:raise StaleLivePlan('This import instance already exists; choose another instance key')
    allowed=set(snapshot['rules']['nets']);additions=[]
    references={str(i.reference_field.text.value) for i in board.get_footprints()}
    for item in incoming:
        disabled=_layers(item.proto)-set(snapshot['rules']['layers'])
        if disabled:raise UnsupportedLiveApply('Incoming items require disabled target layers: '+', '.join(map(str,sorted(disabled))))
        unknown=_net_names(item.proto)-allowed
        if unknown:raise UnsupportedLiveApply('New nets cannot be created atomically by installed API: '+', '.join(sorted(unknown)))
        if hasattr(item.proto,'symbol_path') and item.proto.symbol_path.path:
            raise UnsupportedLiveApply('Linked source footprint requires schematic hierarchy import, unavailable as a live transaction')
        payload=copy.deepcopy(item.proto)
        _remap(payload,mapping)
        # Construct once after remapping; SDK footprint caches repack Any children.
        clone=type(item)(payload)
        if hasattr(clone,'reference_field'):
            reference=str(clone.reference_field.text.value)
            if reference in references:raise MergeError('Incoming footprint reference collides: '+reference)
            references.add(reference)
        additions.append(clone)
    return LivePlan(snapshot,additions=additions,title='Fusion PCB item import',uuid_map=mapping).seal()


def preview_placement(board,candidate_tree):
    """Translate/rotate existing unrouted footprints using a reviewed native candidate.

    Side flips, routed/copper-coupled moves, new items, net/identity changes and
    changed board settings are rejected. These need a complete native adapter.
    """
    snapshot=capture_snapshot(board)
    if isinstance(candidate_tree,str):candidate_tree=sx.loads(candidate_tree)
    before=snapshot['tree'];candidate=copy.deepcopy(candidate_tree)
    old={_item_key(n):n for n in sx.children(before,'footprint')}
    proposed={_item_key(n):n for n in sx.children(candidate,'footprint')}
    if not old or set(old)!=set(proposed):raise UnsupportedLiveApply('Live placement requires the same existing footprint UUIDs; this candidate needs project import')
    # Candidate changes must be exclusively root footprint at(x,y,angle).
    normalized=copy.deepcopy(candidate)
    for footprint in sx.children(normalized,'footprint'):
        original=old[_item_key(footprint)];at=sx.child(footprint,'at');previous=sx.child(original,'at')
        if at is None or previous is None:raise MergeError('Footprint placement is missing')
        at[:]=copy.deepcopy(previous)
    if _canonical(normalized)!=_canonical(before):raise UnsupportedLiveApply('Candidate also changes footprint side, fields, nets, geometry, routing or board settings')
    numeric_nets={str(n[1]):str(n[2]) for n in sx.children(before,'net') if len(n)>2}
    def net(node):
        value=sx.child(node,'net')
        if value is None:return ''
        return str(value[2]) if len(value)>2 else numeric_nets.get(str(value[1]),str(value[1]))
    coupled={net(n) for n in sx.children(before) if sx.tag(n) in ('segment','arc','via','zone')}
    live={_id(i):i for i in board.get_footprints()};updates=[]
    for uid,original in old.items():
        after=proposed[uid]
        if sx.child(original,'at')==sx.child(after,'at'):continue
        if uid not in live:raise StaleLivePlan('Live footprint disappeared')
        if any(net(p) and net(p) in coupled for p in sx.children(original,'pad')):
            raise UnsupportedLiveApply('Cannot move a footprint coupled to existing routed copper: '+sx.propval(original,'Reference'))
        raw=live[uid]
        if getattr(raw,'locked',False):raise UnsupportedLiveApply('Unlock selected footprint before live placement')
        values=sx.child(after,'at')[1:]
        x,y=float(values[0]),float(values[1]);angle=float(values[2]) if len(values)>2 else 0.0
        if not all(math.isfinite(v) for v in (x,y,angle)):raise MergeError('Placement must be finite')
        clone=type(raw)(raw.proto)
        clone.position=type(raw.position).from_xy(round(x*1e6),round(y*1e6))
        clone.orientation=type(raw.orientation).from_degrees(angle)
        updates.append(clone)
    if not updates:raise MergeError('No placement changes selected')
    return LivePlan(snapshot,updates=updates).seal()


def apply_plan(board,plan,*,native_review):
    """Apply explicit reviewed changes as one undo step; never save a live file.

    Native review is externally performed on a detached candidate, and must bind
    this exact plan and source rules. A dictionary alone is not native validation;
    the GUI owns the real CLI report and supplies its confirmed hashes.
    """
    sealed=copy.copy(plan).seal().plan_sha256
    if not plan.plan_sha256 or sealed!=plan.plan_sha256:raise StaleLivePlan('Reviewed plan payload changed')
    for key,value in [('plan_sha256',plan.plan_sha256),('source_board_sha256',plan.snapshot['board_sha256']),('rules_sha256',plan.snapshot['rules_sha256'])]:
        if native_review.get(key)!=value:raise StaleLivePlan('Native review does not bind '+key)
    if native_review.get('native_candidate_nonregression_verified') is not True:raise UnsupportedLiveApply('Detached native KiCad candidate verification is required before live apply')
    def check():
        now=capture_snapshot(board)
        if any(now[key]!=plan.snapshot[key] for key in ('document_sha256','board_sha256','rules_sha256')):
            raise StaleLivePlan('Open PCB or its unsaved state/rules changed after preview; preview again')
    check();transaction=board.begin_commit();rollback_snapshot=None
    try:
        rollback_snapshot=capture_snapshot(board)
        check()
        for method,items in [('update_items',plan.updates),('create_items',plan.additions)]:
            if not items:continue
            returned=list(getattr(board,method)(items))
            if len(returned)!=len(items) or {_id(i):_blob(i) for i in returned}!={_id(i):_blob(i) for i in items}:
                raise MergeError('KiCad rejected or clamped reviewed '+method+'; transaction will roll back')
        wanted=[*plan.updates,*plan.additions]
        observed=list(board.get_items_by_id([i.id for i in wanted]))
        if {_id(i):_blob(i) for i in observed}!={_id(i):_blob(i) for i in wanted}:raise MergeError('Native staged-item readback differs from preview')
        if _rules(board)!=plan.snapshot['rules']:raise MergeError('Live transaction changed nets, rules or enabled layers')
        changed={_id(i) for i in wanted}
        def untouched(tree):return sorted(_canonical(n) for n in sx.children(tree) if _item_key(n) not in changed)
        staged=sx.loads(board.get_as_string())
        if untouched(staged)!=untouched(plan.snapshot['tree']):raise MergeError('Live transaction changed unrelated editor items or board settings')
        board.push_commit(transaction,plan.title)
    except Exception as failure:
        try:
            board.drop_commit(transaction)
            restored=capture_snapshot(board)
            if rollback_snapshot is None or any(restored[k]!=rollback_snapshot[k] for k in ('document_sha256','board_sha256','rules_sha256')):
                raise LiveRollbackError('Rollback did not restore the captured unsaved editor state')
        except Exception as rollback:raise LiveRollbackError('Native rollback failed; leave editor open and inspect undo/recovery state: '+str(rollback)) from failure
        raise
    return dict(applied=True,undo_group=plan.title,updated_items=len(plan.updates),added_items=len(plan.additions),
                schematic_changed=False,files_written=False,native_transaction=True)
