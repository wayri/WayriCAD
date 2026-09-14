"""Selection-only KiCad IPC adapter. Does not edit/save native board objects.

KiCad 10 path: BOM <-> PCB IPC <-> native schematic cross-selection.
Schematic relay and viewport actions have no completion acknowledgement;
they are never described as independently verified by this adapter.
"""
from __future__ import annotations
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
import os
import time
import uuid

class BridgeUnavailable(ValueError):pass


def identifier(value):
    if value is None:return ''
    v=getattr(value,'value',value)
    if not isinstance(v,str):return ''
    try:return str(uuid.UUID(v))
    except (ValueError,TypeError,AttributeError):return ''


def _path_segments(value, depth=0):
    """Read data, never a message's debug/string representation.

    Official wire contract: FootprintInstance.proto.symbol_path.path is a
    repeated KIID. SDK wrappers can differ from that protobuf representation.
    None/empty is distinct from a populated but unreadable or malformed path.
    """
    if depth > 4:raise ValueError('Nested UUID path is unsupported.')
    if value is None:return []
    if isinstance(value,str):return value.strip('/').split('/') if value.strip('/') else []
    if isinstance(value,(list,tuple)):return list(value)
    # Prefer a wrapper's protobuf over guessed attributes/string conversion.
    proto=getattr(value,'proto',None)
    if proto is not None and proto is not value:return _path_segments(proto,depth+1)
    path=getattr(value,'path',None)
    if path is not None:
        if isinstance(path,str):return _path_segments(path,depth+1)
        try:return list(path)
        except TypeError:raise ValueError('UUID path is not a sequence.')
    # Some SDK releases expose SheetPath.kiids instead of .path.
    kiids=getattr(value,'kiids',None)
    if kiids is not None:
        try:return list(kiids)
        except TypeError:raise ValueError('UUID path is not a sequence.')
    raise ValueError('Unrecognized SDK UUID-path representation.')


def path_details(value, source='value'):
    try:values=_path_segments(value)
    except (ValueError,TypeError,AttributeError) as exc:
        return {'path':'','state':'unsupported','source':source,'reason':str(exc)}
    if not values:return {'path':'','state':'absent','source':source,'reason':'No associated schematic UUID path.'}
    if len(values)>256:return {'path':'','state':'invalid','source':source,'reason':'UUID path exceeds 256 members.'}
    ids=[identifier(v) for v in values]
    if not all(ids):return {'path':'','state':'invalid','source':source,'reason':'Associated schematic path contains a malformed UUID.'}
    return {'path':'/'+('/'.join(ids)),'state':'valid','source':source,'reason':''}


def symbol_path(value):
    return path_details(value)['path']


def footprint_path_details(fp):
    proto=getattr(fp,'proto',None)
    if proto is not None and hasattr(proto,'symbol_path'):
        return path_details(proto.symbol_path,'proto.symbol_path.path')
    # Compatibility for older SDKs and explicit test adapters. An invalid
    # canonical path must never fall through to a weak reference-only match.
    if hasattr(fp,'sheet_path'):return path_details(fp.sheet_path,'sheet_path')
    if hasattr(fp,'symbol_path'):return path_details(fp.symbol_path,'symbol_path')
    return path_details(None,'no SDK path field')


def footprint_path(fp):
    return footprint_path_details(fp)['path']


def _reference(fp):
    value=getattr(getattr(getattr(fp,'reference_field',None),'text',None),'value','')
    return str(value)


def is_busy_error(exc):
    """Recognize the explicit host-busy status only, not arbitrary timeouts."""
    status=getattr(exc,'status',None)
    for value in (status,getattr(status,'status',None),getattr(exc,'code',None)):
        name=getattr(value,'name','')
        if name in ('AS_BUSY','BUSY'):return True
    return 'AS_BUSY' in str(exc) or type(exc).__name__ in ('KiCadBusyError','ApiBusyError')


def document_identity(board):
    d=board.document;p=d.project
    if not p.name or not p.path or not d.board_filename:raise BridgeUnavailable('Open a saved board through its KiCad project before linking.')
    project=(Path(p.path)/(str(p.name)+'.kicad_pro')).resolve()
    boardpath=Path(d.board_filename)
    if not boardpath.is_absolute():boardpath=Path(p.path)/boardpath
    if boardpath.suffix.lower()!='.kicad_pcb':raise BridgeUnavailable('The connected document is not a PCB.')
    return str(project),str(boardpath.resolve())


def diagnostic():
    try:version=metadata.version('kicad-python')
    except metadata.PackageNotFoundError:version=None
    return {'schema':'wayricad-link-diagnostic-1','dependency':'kicad-python==0.8.0','installed':version,
            'inherited_socket':bool(os.environ.get('KICAD_API_SOCKET')),'inherited_token':bool(os.environ.get('KICAD_API_TOKEN')),
            'pcb_selection':'optional IPC adapter','schematic_selection':'KiCad native relay, not a direct schematic API',
            'viewport':'optional experimental allowlisted RunAction; submission is not viewport verification',
            'host_tested':False,'core_requires_ipc':False}


class Bridge:
    """All methods run on one owner thread via SelectionService."""
    def __init__(self,factory=None):
        self.factory=factory;self.client=None;self.board=None;self.identity=None;self.project=None
        self.mapping={};self.reverse={};self.children={};self.items={};self.warnings=[];self.options={}
        self.last_ids=[];self.sequence=0;self.last_signature=None;self.sent=None;self.indexed_at=0;self.version='';self.mapping_details=[];self.footprint_details=[]
    def close(self):
        if self.client:
            closer=getattr(self.client,'close',None)
            if callable(closer):
                try:closer()
                except Exception:pass
        self.client=None;self.board=None;self.mapping={};self.reverse={};self.children={};self.identity=None
        self.last_signature=None;self.sent=None;self.last_ids=[];self.indexed_at=0;self.mapping_details=[];self.footprint_details=[]
        return {'connected':False,'ids':[]}
    def discover(self):
        """Resolve a saved project from an explicitly inherited PCB IPC context."""
        if not os.environ.get('KICAD_API_SOCKET'):raise BridgeUnavailable('No inherited KiCad IPC socket for project discovery.')
        self.close()
        try:
            if self.factory:factory=self.factory
            else:
                try:
                    from kipy import KiCad
                    if metadata.version('kicad-python')!='0.8.0':raise BridgeUnavailable('Project discovery requires kicad-python==0.8.0.')
                    factory=KiCad
                except ImportError as exc:raise BridgeUnavailable('Optional kicad-python==0.8.0 is not installed; choose a saved project manually.') from exc
            self.client=factory(client_name='org.wayricad.bomstudio',timeout_ms=1500)
            version=self.client.get_version()
            if getattr(version,'major',None)!=10:raise BridgeUnavailable('Automatic discovery is limited to KiCad 10; open/connect other hosts explicitly.')
            identity=document_identity(self.client.get_board())
            if not Path(identity[0]).is_file():raise BridgeUnavailable('IPC project is not a saved local .kicad_pro file.')
            return {'project':identity[0],'board':identity[1]}
        finally:self.close()
    def connect(self,project,options=None):
        options=options or {}
        if not isinstance(options,dict) or set(options)-{'socket','reference_fallback','experimental_focus','allow_untested'}:raise ValueError('Unknown live-link option.')
        for k in ('reference_fallback','experimental_focus','allow_untested'):
            if k in options and not isinstance(options[k],bool):raise ValueError(k+' must be a boolean.')
        socket=options.get('socket') or os.environ.get('KICAD_API_SOCKET')
        if socket and (not isinstance(socket,str) or len(socket)>2048 or any(c in socket for c in '\r\n\x00') or ('://' in socket and not socket.startswith('ipc://'))):raise ValueError('Only a local IPC socket is allowed, not TCP/network endpoints.')
        self.close();self.options=options;self.project=project
        try:
            if self.factory:factory=self.factory
            else:
                try:
                    from kipy import KiCad
                    installed=metadata.version('kicad-python')
                    if installed!='0.8.0':raise BridgeUnavailable('This bridge is pinned to kicad-python 0.8.0. Use the supplied requirements.txt in this interpreter; core BOM tools still work without it.')
                    factory=KiCad
                except ImportError as e:raise BridgeUnavailable('Live link needs optional kicad-python==0.8.0. Install requirements.txt using the same Python interpreter, or launch through KiCad managed plugin support.') from e
            kwargs={'client_name':'org.wayricad.bomstudio','timeout_ms':1500}
            if socket:kwargs['socket_path']=socket
            self.client=factory(**kwargs);version=self.client.get_version();major=getattr(version,'major',None)
            self.version=str(getattr(version,'full_version','') or '.'.join(str(getattr(version,k,0)) for k in ('major','minor','patch')))
            if major!=10 and not options.get('allow_untested'):raise BridgeUnavailable('This selection adapter targets KiCad 10. Future/other hosts require explicit untested-host opt-in; no KiCad 11 claim is made.')
            self.board=self.client.get_board();self.identity=document_identity(self.board)
            self.verify_project();self.reindex();return self.poll(refresh=False)
        except Exception as e:
            self.close()
            if isinstance(e,(ValueError,BridgeUnavailable)):raise
            raise BridgeUnavailable('Cannot connect to KiCad IPC ('+type(e).__name__+'). Launch from PCB Editor, enable IPC and confirm the saved project. No native data was edited.') from e
    def verify_project(self):
        expected=str(self.project.pro_path.resolve())
        if os.path.normcase(self.identity[0])!=os.path.normcase(expected):raise BridgeUnavailable('Connected board belongs to a different project. Open the matching project in both KiCad and WayriCAD.')
    def check(self):
        if not self.client:raise BridgeUnavailable('Live link is disconnected.')
        board=self.client.get_board();current=document_identity(board)
        if current!=self.identity:
            self.close();raise BridgeUnavailable('KiCad changed its active board/project. Link disconnected to avoid selecting the wrong design.')
        self.board=board;self.verify_project()
    def reindex(self):
        paths=defaultdict(set);refs=defaultdict(set);expected=defaultdict(set)
        for c in self.project.components:
            refs[c.ref].add(c.id)
            for member in c.members:
                path=symbol_path(member.path+'/'+member.uuid)
                if path:paths[path].add(c.id);expected[c.id].add(path)
        # Native footprints created by older exporters sometimes omit just the
        # root sheet UUID. Only remove a known project root, never arbitrary
        # suffixes or sheet IDs. Repeated-sheet ambiguities remain blocked.
        roots={p.split('/')[1] for p in paths}
        rootless=defaultdict(set)
        if len(roots)==1:
            for path,cids in paths.items():
                shortened='/'+('/'.join(path.strip('/').split('/')[1:]))
                if shortened!='/' and shortened not in paths:rootless[shortened].update(cids)
        proposals=defaultdict(list);warnings=[];children={};items={};details=[];by_ref=defaultdict(list)
        fps=list(self.board.get_footprints())
        if len(fps)>100000:raise BridgeUnavailable('Live board exceeds the bridge limit of 100,000 footprints.')
        fid_counts=defaultdict(int)
        for fp in fps:fid_counts[identifier(getattr(fp,'id',None))]+=1
        for fp in fps:
            fid=identifier(getattr(fp,'id',None));reference=_reference(fp)
            pathinfo=footprint_path_details(fp);path=pathinfo['path'];matches=set();method='uuid-path'
            record={'reference':reference,'footprint_id':fid,'path':path,'path_source':pathinfo['source'],
                    'path_state':pathinfo['state'],'method':None,'component_ids':[],'reason':pathinfo['reason']}
            details.append(record);by_ref[reference].append(record)
            if not fid or fid_counts[fid]!=1:
                record['reason']='Missing or duplicate live footprint UUID; linking blocked.';warnings.append(reference+': '+record['reason']);continue
            if getattr(getattr(fp,'attributes',None),'not_in_schematic',False):
                record['reason']='Footprint is marked not in schematic.';continue
            if pathinfo['state']=='valid':
                matches=paths.get(path,set())
                if not matches and path in rootless:matches=rootless[path];method='uuid-path-root-omitted'
                if not matches:record['reason']='Live schematic UUID path does not match this saved project.'
            elif pathinfo['state']=='absent' and self.options.get('reference_fallback'):
                matches=refs.get(reference,set());method='reference-fallback'
            if len(matches)==1:
                cid=next(iter(matches));proposals[cid].append((fid,fp,record));items[fid]=fp
                record.update(method=method,component_ids=[cid],reason='Unique '+method+' match.')
                if method=='reference-fallback':warnings.append(reference+': weak reference-only match (no schematic UUID path).')
                if self.project.by_id[cid].ref!=reference:warnings.append(reference+': UUID matches '+self.project.by_id[cid].ref+'; save/reload after reannotation.')
            else:
                if len(matches)>1:record['reason']='Ambiguous path/reference matches multiple BOM instances.'
                warnings.append(reference+': '+(record['reason'] or 'No unique schematic match.')+' Not linked.')
            definition=getattr(fp,'definition',None)
            parts=list(getattr(definition,'items',[]))+list(getattr(fp,'texts_and_fields',[]))
            parts+=[getattr(fp,'reference_field',None),getattr(fp,'value_field',None)]
            for child in parts:
                key=identifier(getattr(child,'id',None)) or identifier(getattr(getattr(child,'text',None),'id',None))
                if key:
                    if key in children and children[key]!=fid:children[key]=''
                    else:children[key]=fid
        mapping={};reverse={};component_details=[]
        for c in self.project.components:
            targets=proposals.get(c.id,[])
            if len(targets)==1:
                fid,fp,record=targets[0];mapping[c.id]=fp;reverse[fid]=c.id
                reason=record['reason'];state='linked'
            elif len(targets)>1:
                reason='duplicate PCB footprints map to this symbol; linking blocked.';state='ambiguous'
                warnings.append(c.ref+': '+reason)
                for _,_,record in targets:record['reason']=reason;record['component_ids']=[]
            else:
                same_ref=by_ref.get(c.ref,[]);state='unmapped'
                reason=('No live footprint with this reference. It may be schematic-only, excluded, absent from this PCB, or reannotated.'
                        if not same_ref else '; '.join(dict.fromkeys(r['reason'] for r in same_ref)))
            component_details.append({'id':c.id,'reference':c.ref,'state':state,'expected_paths':sorted(expected[c.id]),
                                      'footprint_ids':[f for f,_,_ in targets],'reason':reason,
                                      'same_reference_candidates':by_ref.get(c.ref,[])})
        self.mapping=mapping;self.reverse=reverse;self.children=children;self.items=items;self.warnings=warnings
        self.mapping_details=component_details;self.footprint_details=details;self.indexed_at=time.monotonic()

    def mapping_report(self,refresh=True):
        if not self.client:return {'schema':'wayricad-link-mapping-1','connected':False,'components':[],'footprints':[],
                                   'message':'Connect from the PCB Editor first.'}
        if refresh:self.check();self.reindex()
        return {'schema':'wayricad-link-mapping-1','connected':True,'version':self.version,'project':self.identity[0],
                'board':self.identity[1],'mapped':len(self.mapping),'total':len(self.project.components),
                'components':self.mapping_details,'footprints':self.footprint_details,
                'options':{k:v for k,v in self.options.items() if k!='socket'},
                'schematic':'native-relay-unverified','native_data_modified':False,
                'privacy':'Includes project paths, references and UUIDs. No IPC socket or session token.'}

    def selected_ids(self,selection):
        ids=set();unmapped=0;seen=set();remaining=list(selection);limit=0
        while remaining:
            item=remaining.pop();limit+=1
            if limit>20000:raise BridgeUnavailable('Selection exceeds 20,000 items; narrow it in KiCad.')
            key=identifier(getattr(item,'id',None)) or identifier(getattr(getattr(item,'text',None),'id',None)) or identifier(item);parent=identifier(getattr(item,'parent',None))
            if key and key in seen:continue
            if key:seen.add(key)
            fid=key if key in self.reverse else parent if parent in self.reverse else self.children.get(key,'')
            if fid in self.reverse:ids.add(self.reverse[fid])
            elif type(item).__name__=='Group' and hasattr(item,'items'):remaining.extend(item.items)
            else:unmapped+=1
        return sorted(ids),unmapped
    def poll(self,refresh=True):
        if not self.client:return {'connected':False,'ids':[]}
        try:
            if refresh:self.check()
            if time.monotonic()-self.indexed_at>5:self.reindex()
            selected=list(self.board.get_selection())
        except Exception as exc:
            if not is_busy_error(exc):raise
            return {'connected':True,'busy':True,'version':self.version,'project':self.identity[0],'board':self.identity[1],
                    'ids':list(self.last_ids),'sequence':self.sequence,'origin':'busy','mapped_components':len(self.mapping),
                    'total_components':len(self.project.components),'message':'KiCad is busy; selection following will retry.',
                    'schematic':'native-relay-unverified','native_data_modified':False}
        ids,unmapped=self.selected_ids(selected)
        signature=(tuple(ids),unmapped)
        if signature!=self.last_signature:self.sequence+=1;self.last_signature=signature
        self.last_ids=ids
        return {'connected':True,'version':self.version,'project':self.identity[0],'board':self.identity[1],
                'sequence':self.sequence,'ids':ids,'references':[self.project.by_id[i].ref for i in ids],
                'selected_items':len(selected),'unmapped_selected':unmapped,'mapped_components':len(self.mapping),
                'total_components':len(self.project.components),'warnings':self.warnings[:100],'warning_count':len(self.warnings),
                'origin':'bom' if self.sent and tuple(ids)==self.sent[0] and time.monotonic()-self.sent[1]<3 else 'editor',
                'schematic':'native-relay-unverified','focus':'experimental-opt-in' if self.options.get('experimental_focus') else 'disabled',
                'reference_fallback':self.options.get('reference_fallback',False),'native_data_modified':False,'variant_sync':False}
    def select(self,ids,focus=False,allow_partial=False):
        if not isinstance(ids,list) or not ids or len(ids)>2000 or any(not isinstance(i,str) for i in ids):raise ValueError('Select 1–2,000 component IDs.')
        if any(i not in self.project.by_id for i in ids):raise ValueError('Unknown component ID; editor selection unchanged.')
        if not isinstance(focus,bool) or not isinstance(allow_partial,bool):raise ValueError('Selection options must be booleans.')
        self.check();self.project.check_unchanged();self.reindex()
        missing=[i for i in ids if i not in self.mapping]
        if missing and not allow_partial:
            refs=[self.project.by_id[i].ref if i in self.project.by_id else 'unknown ID' for i in missing]
            raise ValueError('No unique live footprint for '+', '.join(refs[:8])+(' …' if len(refs)>8 else '')+
                             '. Editor selection unchanged. Open Mapping diagnostics for exact UUID/path reasons; '
                             'partial linking only helps a group containing other mapped parts.')
        targets=list({identifier(self.mapping[i].id):self.mapping[i] for i in ids if i in self.mapping}.values())
        if not targets:raise ValueError('None of these components has a linked PCB footprint; existing editor selection is unchanged.')
        old=list(self.board.get_selection())
        try:
            self.board.clear_selection();self.board.add_to_selection(targets)
        except Exception as e:
            restored=False
            try:
                self.board.clear_selection()
                if old:self.board.add_to_selection(old)
                restored=True
            except Exception:pass
            raise BridgeUnavailable('Selection update failed. Previous selection '+('restored.' if restored else 'could not be restored; inspect KiCad.')+' Native design data was not edited.') from e
        result=self.poll(refresh=False);expected={i for i in ids if i in self.mapping}
        if set(result['ids'])!=expected:raise BridgeUnavailable('KiCad selection readback differs from the requested set; inspect the editors. Native data was not edited.')
        self.sent=(tuple(result['ids']),time.monotonic());result.update(origin='bom',missing_ids=missing,focus_result='not_requested')
        if focus:
            if not self.options.get('experimental_focus'):result['focus_result']='disabled_enable_experimental_focus'
            else:
                try:
                    status=self.client.run_action('common.Control.zoomFitSelection')
                    result['focus_result']='submitted_unverified' if int(status)==1 else 'unavailable'
                except Exception:result['focus_result']='unavailable'
        return result


class SelectionService:
    """Own the IPC socket on a single thread. HTTP requests never share its socket."""
    def __init__(self,factory=None):self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='wayricad-ipc');self.bridge=Bridge(factory);self.closed=False
    def call(self,operation,*args,**kwargs):
        if self.closed:raise BridgeUnavailable('Selection service is closed.')
        if operation not in ('connect','poll','select','close','discover','mapping_report'):raise ValueError('Unknown link operation.')
        return self.worker.submit(getattr(self.bridge,operation),*args,**kwargs).result()
    def close(self):
        if not self.closed:
            try:self.call('close')
            finally:self.closed=True;self.worker.shutdown(wait=True,cancel_futures=True)
