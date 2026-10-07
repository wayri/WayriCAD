"""Persistent, reviewed source links with scoped destination conflict detection."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import copy
import hashlib
import json
import os
import shutil
import tempfile
import zipfile

from . import sexpr as sx
from .model import MergeError,SourceSpec
from .schematic import discover,new_uuid,canonical_path
from .repair import fingerprint,copy_project,project_files
from .assets import sha256
from .board import ITEMS,net_name,net_table,board_bounds,prepare_board,fp_reference,geometry_signature
from .netlist import KiCadCLI,compare_netlists
from .link_changes import snapshot_source,compare_snapshots,suggest_auto_links
from .version import VERSION

MANIFEST='wayri-fusion-links.json'


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def _normal(node):
    if not isinstance(node,list):
        if isinstance(node,sx.Quoted):return str(node)
        try:return round(float(node),7)
        except (ValueError,TypeError):return str(node)
    if sx.tag(node)=='members':return ['members',*sorted(_normal(n) for n in node[1:])]
    return [*[_normal(n) for n in node if not (isinstance(n,list) and sx.tag(n) in {'generator','generator_version','filled_polygon','fill_segments'})]]


def _load(target):
    project=Path(target).expanduser().resolve().with_suffix('.kicad_pro')
    path=project.parent/MANIFEST
    data=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {'schema':1,'links':[]}
    if data.get('schema')!=1 or not isinstance(data.get('links'),list):raise MergeError('Unsupported linked-import manifest.')
    if len(data['links'])>100:raise MergeError('A maximum of 100 linked design instances is supported.')
    ids=[entry['id'] for entry in data['links']]
    if len(ids)!=len(set(ids)):raise MergeError('Duplicate linked-import IDs in manifest.')
    root=sx.value(sx.load(project.with_suffix('.kicad_sch')),'uuid')
    if data.get('target_root_uuid',root)!=root:raise MergeError('Linked manifest belongs to a different schematic root UUID.')
    return project,data


def _write(root,data):
    (Path(root)/MANIFEST).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def _owned_settings(project,link):
    alias=link['alias'];classes=set(link.get('class_names',[]));nets=set(link.get('net_names',[]))
    ns=project.get('net_settings') or {}
    return {'text_variables':{k:v for k,v in project.get('text_variables',{}).items() if k.startswith(alias+'__')},
            'classes':[c for c in (ns.get('classes') or []) if c.get('name') in classes],
            'patterns':[p for p in (ns.get('netclass_patterns') or []) if p.get('netclass') in classes or p.get('pattern') in nets],
            'assignments':{k:v for k,v in (ns.get('netclass_assignments') or {}).items() if k in nets},
            'colors':{k:v for k,v in (ns.get('net_colors') or {}).items() if k in nets}}


def _scope(project,link,xml=None):
    root=project.parent;tree=sx.load(project.with_suffix('.kicad_sch'))
    wrapper=next((s for s in sx.children(tree,'sheet') if sx.value(s,'uuid')==link['wrapper_uuid']),None)
    files={}
    for name in link.get('sheet_files',[]):
        path=root/name
        if not path.is_file():files[name]=None
        else:files[name]=_digest(_normal(sx.load(path)))
    board=sx.load(project.with_suffix('.kicad_pcb')) if project.with_suffix('.kicad_pcb').is_file() else ['kicad_pcb']
    expected=set(link.get('pcb_item_ids',[]))
    items={}
    for item in sx.children(board):
        ident=sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')
        if ident in expected:
            semantic=copy.deepcopy(item)
            for node in sx.walk(semantic):
                if sx.child(node,'net') is not None:sx.put(node,'net',sx.q(net_name(node,net_table(board))))
            items[ident]=_digest(_normal(semantic))
    tables={}
    for name,nicknames in link.get('library_names',{}).items():
        table=sx.load(root/name) if (root/name).is_file() else []
        tables[name]={sx.value(n,'name'):_digest(_normal(n)) for n in sx.children(table,'lib') if sx.value(n,'name') in nicknames}
    assets={name:sha256(root/name) if (root/name).is_file() else None for name in link.get('asset_files',[])}
    settings=json.loads(project.read_text(encoding='utf-8-sig'))
    partitions={}
    if xml:
        refs=set(link['reference_map'].values())
        for ep,name in xml.pins.items():
            if ep[0] in refs:partitions[ep[0]+'.'+ep[1]]={'name':name,'pins':sorted([list(p) for p in xml.nets[name]])}
    return {'wrapper':_digest(_normal(wrapper)) if wrapper else None,'sheets':files,'pcb_items':items,
            'tables':tables,'assets':assets,'settings':_owned_settings(settings,link),'partitions':partitions}


def _origin_spec(spec):
    if not spec.section_origin:return None
    folder=Path(spec.project).resolve().parent
    for name in ('section-report.json','schematic-section-report.json'):
        path=folder/name
        if path.is_file():
            report=json.loads(path.read_text(encoding='utf-8-sig'))
            if report.get('source_spec'):
                original=SourceSpec(**report['source_spec']);original.project=spec.section_origin['project'];original.alias=spec.alias
                original.section_origin={};return asdict(original)
    original=SourceSpec(spec.section_origin['project'],spec.alias,variant='<Default>')
    source=discover(original,new_uuid(),require_board=False)
    if source.variant_names:raise MergeError('This older materialized section lacks its original variant configuration. Re-extract it with the current plugin before creating a live source link.')
    return asdict(original)


def _canonical_section(snapshot,origin):
    old='/'+snapshot['root_uuid'];new=canonical_path(origin['sheet_path'])
    def path(value):return new+value[len(old):] if value==old or value.startswith(old+'/') else value
    value=copy.deepcopy(snapshot)
    value['symbols']={path(key):dict(item, sheet_path=path(item['sheet_path'])) for key,item in value['symbols'].items()}
    value['components']={path(key):dict(item,occurrences=[path(p) for p in item['occurrences']]) for key,item in value['components'].items()}
    for net in value['nets']:net['pins']=[[path(p),pin] for p,pin in net['pins']]
    for sheet in value['sheets']:sheet['path']=path(sheet['path'])
    value['root_uuid']=new.split('/')[1]
    for item in value.get('board_items',{}).values():
        if item.get('symbol'):item['symbol']=path(item['symbol'])
    if 'schematic_items' in value:value['schematic_items']={path(key):item for key,item in value['schematic_items'].items()}
    return value


def _section_snapshot(spec,cli_path,cache,include_layout=True):
    value=_canonical_section(_snapshot(spec,cli_path,cache,include_layout),spec.section_origin)
    pcb=Path(spec.project).with_suffix('.kicad_pcb')
    if pcb.is_file():
        for item in sx.children(sx.load(pcb)):
            if sx.tag(item)=='gr_rect' and sx.value(item,'layer')=='Edge.Cuts':
                value.get('board_items',{}).pop(sx.value(item,'uuid'),None)
    return value


def _snapshot(spec,cli_path,cache,include_layout=True):
    semantic=copy.deepcopy(spec);semantic.alias='LinkedSource';semantic.x_mm=semantic.y_mm=None
    key=json.dumps({"spec":asdict(semantic),"include_layout":include_layout},sort_keys=True)
    if key not in cache:cache[key]=json.loads(json.dumps(snapshot_source(semantic,cli_path,include_layout=include_layout)))
    return copy.deepcopy(cache[key])


def _live_source(link,work,cli_path,cache,override=None):
    spec=SourceSpec(**link['source_spec']);origin=spec.section_origin
    if not origin:
        if override:spec.project=str(Path(override).resolve().with_suffix('.kicad_pro'))
        snapshot=_snapshot(spec,cli_path,cache,link.get("include_layout",True))
        if snapshot['root_uuid']!=link['source_root_uuid']:raise MergeError('Replacement source has a different root UUID; it cannot be silently linked.')
        return spec,snapshot
    original=SourceSpec(**link['origin_spec'])
    if override:original.project=str(Path(override).resolve().with_suffix('.kicad_pro'))
    full=_snapshot(original,cli_path,cache,link.get("include_layout",True))
    if full['root_uuid']!=link['source_root_uuid']:raise MergeError('Replacement section source has a different root UUID.')
    from .sections import preview_section,apply_section,preview_schematic_sections,apply_schematic_sections
    cache_spec=copy.deepcopy(original);cache_spec.alias='LinkedSource'
    key='section:'+json.dumps({'spec':asdict(cache_spec),'path':origin['sheet_path'],'region':origin['region_mm'],'max_depth':origin.get('max_depth')},sort_keys=True)
    if key not in cache:
        directory=work/new_uuid()
        if origin['region_mm'] is None:
            plan=preview_schematic_sections(original,[origin['sheet_path']],cli_path,max_depth=origin.get('max_depth'),
                                            allow_root=canonical_path(origin['sheet_path']).count('/')==1)
            materialized=apply_schematic_sections(plan,directory)[0]
        else:
            plan=preview_section(original,origin['sheet_path'],origin['region_mm'],cli_path,max_depth=origin.get('max_depth'))
            materialized=apply_section(plan,directory)
        cache[key]=asdict(materialized)
    materialized=SourceSpec(**copy.deepcopy(cache[key]));materialized.alias=link['alias']
    snapshot=_section_snapshot(materialized,cli_path,cache,link.get("include_layout",True))
    snapshot['hashes']=full['hashes'];snapshot['spec']=asdict(original);snapshot['variant']=full['variant']
    return materialized,snapshot


def _route_collisions(board,owned):
    """Exact coplanar segment/via touch proof, including KiCad unconnected nets."""
    import math
    from .layers import copper_sequence
    stack=copper_sequence(board)
    def geometry(item):
        kind=sx.tag(item)
        if kind not in {'segment','via','arc','zone'}:return None
        uid=sx.value(item,'uuid')
        if kind=='segment':
            a=tuple(float(v) for v in sx.child(item,'start')[1:3]);b=tuple(float(v) for v in sx.child(item,'end')[1:3]);layers={sx.value(item,'layer')}
        elif kind=='via':
            a=b=tuple(float(v) for v in sx.child(item,'at')[1:3]);pair=list(map(str,sx.child(item,'layers',[])[1:]))
            if len(pair)!=2 or any(layer not in stack for layer in pair):return None
            left,right=sorted(stack.index(layer) for layer in pair);layers=set(stack[left:right+1])
        else:
            if kind=='arc':
                a,m,b=[tuple(float(v) for v in sx.child(item,key)[1:3]) for key in ('start','mid','end')]
                den=2*(a[0]*(m[1]-b[1])+m[0]*(b[1]-a[1])+b[0]*(a[1]-m[1]))
                if abs(den)<1e-12:raise MergeError('Cannot prove a degenerate arc is isolated; repair source/destination arc geometry first.')
                aa=a[0]**2+a[1]**2;mm=m[0]**2+m[1]**2;bb=b[0]**2+b[1]**2
                cx=(aa*(m[1]-b[1])+mm*(b[1]-a[1])+bb*(a[1]-m[1]))/den
                cy=(aa*(b[0]-m[0])+mm*(a[0]-b[0])+bb*(m[0]-a[0]))/den
                radius=math.hypot(a[0]-cx,a[1]-cy)+float(sx.value(item,'width') or 0)/2
                a,b=(cx-radius,cy-radius),(cx+radius,cy+radius);layers={sx.value(item,'layer')}
            else:
                points=[tuple(float(v) for v in node[1:3]) for polygon in sx.children(item,'polygon') for node in sx.walk(polygon) if sx.tag(node)=='xy']
                if not points:return None
                a,b=(min(p[0] for p in points),min(p[1] for p in points)),(max(p[0] for p in points),max(p[1] for p in points))
                layers=set(map(str,sx.child(item,'layers',[])[1:])) or {sx.value(item,'layer')}
                if any('*' in name for name in layers):layers=set(stack)
            return uid,a,b,layers,0,(a[0],a[1],b[0],b[1]),kind
        radius=float(sx.value(item,'width') or sx.value(item,'size') or 0)/2
        return uid,a,b,layers,radius,(min(a[0],b[0])-radius,min(a[1],b[1])-radius,max(a[0],b[0])+radius,max(a[1],b[1])+radius),kind
    routes=[value for item in sx.children(board) if (value:=geometry(item)) is not None]
    inside=[item for item in routes if item[0] in owned];outside=[item for item in routes if item[0] not in owned]
    def point_distance(p,a,b):
        dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    found=[]
    for one in inside:
        for two in outside:
            if not one[3]&two[3]:continue
            x,y=one[5],two[5]
            if x[2]<y[0] or y[2]<x[0] or x[3]<y[1] or y[3]<x[1]:continue
            if one[6] in {'arc','zone'} or two[6] in {'arc','zone'}:
                found.append({'category':'copper_boundary','message':'Linked and unrelated copper envelopes overlap; exact arc/zone boundary isolation cannot be proven. Review or separate these layout items before updating.','uuid':one[0],'outside_uuid':two[0]})
                continue
            a,b,c,d=one[1],one[2],two[1],two[2]
            intersects=(cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0 and max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1])))
            distance=0 if intersects else min(point_distance(a,c,d),point_distance(b,c,d),point_distance(c,a,b),point_distance(d,a,b))
            if distance<=one[4]+two[4]+1e-7:found.append({'category':'copper_boundary','message':'Linked routing physically touches unrelated destination routing.','uuid':one[0],'outside_uuid':two[0]})
    return found


def _owned_layout_compatible(project,link,xml):
    """Prove locally edited linked items still belong to their schematic link."""
    pcb=project.with_suffix('.kicad_pcb')
    if not pcb.is_file():return False
    board=sx.load(pcb);table=net_table(board)
    items={sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id'):item
           for item in sx.children(board) if sx.tag(item) in ITEMS}
    expected=set(link.get('pcb_item_ids',[]))
    if not expected or not expected.issubset(items):return False
    source_items=link.get('source_baseline',{}).get('board_items',{})
    reverse={target:source for source,target in link.get('pcb_uuid_map',{}).items()}
    linked_nets=set(link.get('net_names',[]));refs=set(link.get('reference_map',{}).values())
    for uid in expected:
        item=items[uid];original=source_items.get(reverse.get(uid),{})
        if original and sx.tag(item)!=original.get('kind'):return False
        if sx.tag(item)=='footprint':
            ref=fp_reference(item)
            if ref not in refs:return False
            if canonical_path(sx.value(item,'path')) not in xml.components.get(ref,{}).get('paths',set()):return False
            pads=sx.children(item,'pad')
            if len({str(pad[1]) for pad in pads})!=len(pads):return False
            for pad in pads:
                actual=net_name(pad,table);expected_net=xml.pins.get((ref,str(pad[1])),'')
                if actual!=expected_net:return False
        elif sx.tag(item) in {'segment','arc','via','zone'}:
            if net_name(item,table) not in linked_nets:return False
    return True


def _conflicts(project,link,xml,allow_owned_layout=False):
    current=_scope(project,link,xml);baseline=link['target_baseline'];found=[]
    for key in ('wrapper','sheets','pcb_items','tables','assets','settings','partitions'):
        if current.get(key)!=baseline.get(key):
            if key=='pcb_items' and allow_owned_layout and _owned_layout_compatible(project,link,xml):continue
            found.append({'category':'destination_'+key,'message':'Destination-owned '+key.replace('_',' ')+' changed; update would overwrite local work.'})
    refs=set(link['reference_map'].values());owned=set(link.get('pcb_item_ids',[]));owned_nets=set(link.get('net_names',[]))
    for net in xml.nets.values():
        inside={ep for ep in net if ep[0] in refs};outside=net-inside
        if inside and outside:found.append({'category':'external_connection','message':'Linked pins connect to another destination design.','pins':sorted([list(p) for p in inside]),'outside_pins':sorted([list(p) for p in outside])})
    pcb=project.with_suffix('.kicad_pcb')
    if pcb.is_file():
        board=sx.load(pcb)
        found.extend(_route_collisions(board,owned))
        for item in sx.children(board):
            ident=sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')
            if sx.tag(item) in {'segment','arc','via','zone'} and ident not in owned and net_name(item,net_table(board)) in owned_nets:
                found.append({'category':'external_copper','message':'New destination copper attaches to a linked net.','uuid':ident})
            if sx.tag(item)=='footprint' and ident not in owned:
                attached=[str(pad[1]) for pad in sx.children(item,'pad') if net_name(pad,net_table(board)) in owned_nets]
                if attached:found.append({'category':'external_copper','message':'Unrelated destination footprint pads attach to a linked net.','uuid':ident,'pads':attached})
            if sx.tag(item)=='group' and ident not in owned and set(map(str,sx.child(item,'members',[])[1:]))&owned:
                found.append({'category':'external_group','message':'Destination group includes linked layout items.','uuid':ident})
    return found


def _resolution_for_conflict(conflict):
    """Offer a bounded repair; destination ownership is never silently ignored."""
    category=conflict.get('category','')
    if category.startswith('destination_'):
        return ('Review the local edit against the last imported snapshot. Preserve it '
                'by keeping this link unchanged, or restore the linked-owned item in '
                'a reviewed copy before rescanning. Ignore cannot overwrite local work.')
    if category=='external_connection':
        return ('Separate the cross-block schematic connection or update the two '
                'linked designs together in a reviewed candidate. Ignore would risk '
                'changing another design\'s electrical partition.')
    if category in {'external_copper','copper_boundary','external_group'}:
        return ('Separate or explicitly redesign the shared PCB object in a reviewed '
                'copy, then rerun native DRC. Ignore cannot bypass copper or group ownership.')
    return ('Inspect the saved target and source in a reviewed copy, repair the '
            'conflict, and rescan before updating.')


def _with_resolution(conflicts):
    return [dict(conflict,suggestion=_resolution_for_conflict(conflict),
                 can_ignore=False) for conflict in conflicts]


def _row(link):
    snapshot=link['source_baseline'];hierarchy=[]
    for sheet in snapshot.get('sheets',[]):
        display=str(sheet['name']).replace('/LinkedSource/', '/'+link['alias']+'/',1)
        if display in {'LinkedSource','/LinkedSource'}:display=('/' if display.startswith('/') else '')+link['alias']
        hierarchy.append({'sheet_path':sheet['path'],'display_path':display,
            'symbols':[{'identity':path,'reference':symbol['reference'],'value':symbol['value']}
                       for path,symbol in snapshot['symbols'].items() if symbol['sheet_path']==sheet['path']]})
    origin=link['source_spec'].get('section_origin') or {}
    return {'id':link['id'],'alias':link['alias'],'source_project':origin.get('project',link['source_spec']['project']),
            'selected_variant':link['source_baseline']['variant'],'include_layout':link['include_layout'],
            'status':'unscanned','update_unsupported_reason':link.get('update_unsupported_reason',''),'wrapper_uuid':link['wrapper_uuid'],'reference_map':copy.deepcopy(link['reference_map']),'component_count':len(snapshot['components']),
            'sheet_count':len(snapshot['sheets']),'hierarchy':hierarchy}


def list_links(target,cli_path=''):
    _,manifest=_load(target)
    return [_row(link) for link in manifest['links']]


def _find_sources(link,search_roots):
    candidates=[];visited=0;expected=link['source_root_uuid']
    for root in search_roots or []:
        root=Path(root).resolve()
        for directory,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','venv'} and not Path(directory,d).is_symlink()]
            if len(Path(directory).relative_to(root).parts)>8:dirs[:]=[];continue
            for name in files:
                if not name.endswith('.kicad_pro'):continue
                visited+=1
                if visited>1000:raise MergeError('Source relocation search exceeds 1,000 projects; narrow the search folder.')
                project=Path(directory,name);schematic=project.with_suffix('.kicad_sch')
                if not schematic.is_file():continue
                try:matches=sx.value(sx.load(schematic),'uuid')==expected
                except Exception:continue
                if matches:candidates.append({'project':str(project),'method':'Exact owning root UUID','automatic':False})
    return candidates


def scan_links(target,cli_path='',search_roots=None,source_overrides=None):
    project,manifest=_load(target);cli=KiCadCLI(cli_path);cache={};rows=[]
    with tempfile.TemporaryDirectory(prefix='fusion-scan-links-') as folder:
        work=Path(folder);xml=cli.export_netlist(project.with_suffix('.kicad_sch'),work/'target.xml')
        crossblock={}
        if any(link.get('include_layout') for link in manifest['links']):
            copied=work/'drc';copy_project(project.parent,copied)
            findings=cli.drc(copied/project.with_suffix('.kicad_pcb').name,work/'destination-drc.json')
            for link in manifest['links']:
                owned_ids=set(link.get('pcb_item_ids',[]))|set(link.get('pcb_uuid_map',{}).values())
                crossblock[link['id']]=[]
                for finding in findings.get('violations',[]):
                    finding_ids={str(item.get('uuid','')) for item in finding.get('items',[]) if item.get('uuid')}
                    if finding.get('type') in {'shorting_items','clearance','tracks_crossing'} and finding_ids & owned_ids and finding_ids-owned_ids:
                        crossblock[link['id']].append({'category':'copper_boundary','message':finding.get('description',finding['type']),'finding':finding})
        for link in manifest['links']:
            row=_row(link);row['conflicts']=_with_resolution(_conflicts(project,link,xml)+crossblock.get(link['id'],[]));row['changes']=[];row['major_changes']=0
            try:
                _,snapshot=_live_source(link,work,cli_path,cache,(source_overrides or {}).get(link['id']))
                for path in link['source_baseline'].get('hashes',{}):
                    if path not in snapshot['hashes']:snapshot['hashes'][path]=sha256(path) if Path(path).is_file() else None
                changes=compare_snapshots(link['source_baseline'],snapshot)
                if not changes['changes'] and snapshot.get('hashes')!=link['source_baseline'].get('hashes'):
                    changes['changes']=[{'category':'dependency','severity':'minor','identity':link['id'],'before':None,'after':None,'message':'Source files or dependencies changed; review regenerated assets.'}]
                    changes['minor_changes']=1;changes['summary']['total']=1;changes['summary']['minor']=1
                row.update(changes);row['auto_link_proposals']=suggest_auto_links(link['source_baseline'],snapshot)
                row['status']='conflict' if row['conflicts'] else ('changed' if row['changes'] else 'current')
            except Exception as error:
                row['status']='conflict' if row['conflicts'] else 'missing_source';row['error']=str(error)
                row['source_candidates']=_find_sources(link,search_roots)
            rows.append(row)
    return {'links':rows,'legacy_candidates':_legacy_candidates(project,manifest,cli_path),
            'report':{'links':len(rows),'changed':sum(r['status']=='changed' for r in rows),'conflicts':sum(r['status']=='conflict' for r in rows)}}


def record_import(candidate,target_project,sources,parent,batch,imported,merged,include_layout,cli_path):
    """Insertion hook: record only the newly generated, native-validated blocks."""
    project=Path(candidate)/Path(target_project).name;_,manifest=_load(project)
    if len(manifest['links'])+len(sources)>100:raise MergeError('A target may contain at most 100 linked design instances.')
    cache={};verified_sections=set();generated=[n for n in sx.children(imported) if sx.tag(n) in ITEMS] if imported else []
    cursor=0;root=sx.load(project.with_suffix('.kicad_sch'));project_data=json.loads(project.read_text())
    for source in sources:
        spec=copy.deepcopy(source.spec);origin_spec=_origin_spec(spec)
        snapshot=_snapshot(spec,cli_path,cache,include_layout)
        if not spec.section_origin:snapshot['hashes'].update({path:value for path,value in source.hashes.items() if include_layout or not path.lower().endswith('.kicad_pcb')})
        if spec.section_origin:
            snapshot=_section_snapshot(spec,cli_path,cache,include_layout)
            original_snapshot=_snapshot(SourceSpec(**origin_spec),cli_path,cache,include_layout)
            snapshot['hashes']=original_snapshot['hashes']
            canonical_origin=copy.deepcopy(origin_spec);canonical_origin['alias']='LinkedSource';canonical_origin['x_mm']=canonical_origin['y_mm']=None
            proof_key=_digest({'origin':canonical_origin,'snapshot':snapshot,'include_layout':include_layout})
            if proof_key not in verified_sections:
                with tempfile.TemporaryDirectory(prefix='fusion-link-provenance-') as folder:
                    _,verified=_live_source({'source_spec':asdict(spec),'origin_spec':origin_spec,'alias':spec.alias,
                        'source_root_uuid':snapshot['root_uuid'],'include_layout':include_layout},Path(folder),cli_path,{})
                    if compare_snapshots(snapshot,verified)['changes']:
                        raise MergeError('Materialized section differs from its claimed original source; re-extract it before creating a source link.')
                verified_sections.add(proof_key)
        source_prefix='/'+source.old_root_uuid;identity_prefix=canonical_path(spec.section_origin['sheet_path']) if spec.section_origin else source_prefix
        def identity(path):return identity_prefix+path[len(source_prefix):]
        pcb_map={};pcb_top=[];outer=None
        if include_layout:
            pcb_map=dict(source.pcb_uuid_map);mapped=set(pcb_map.values())
            if source.fusion_group_uuid:mapped.add(source.fusion_group_uuid)
            fresh=[n for n in generated if (sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id')) in mapped]
            pcb_top=[sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id') for n in fresh]
            outer=next((n for n in fresh if (sx.value(n,'uuid') or sx.value(n,'id'))==source.fusion_group_uuid),None)
            if spec.section_origin:
                for item in sx.children(source.board,'gr_rect'):
                    if sx.value(item,'layer')=='Edge.Cuts':pcb_map['__section_outline__']=pcb_map[sx.value(item,'uuid')]
        wrapper=next(s for s in sx.children(root,'sheet') if sx.value(s,'uuid')==source.wrapper_uuid)
        libraries={}
        for table in ('fp-lib-table','sym-lib-table'):
            tree=sx.load(project.parent/table)
            libraries[table]=[sx.value(n,'name') for n in sx.children(tree,'lib')
                              if sx.value(n,'uri').startswith('${KIPRJMOD}/'+(batch+'/' if batch else '')) and
                              ('Fusion_'+source.alias+':' in sx.value(n,'uri') or 'Fusion_'+source.alias+'.' in sx.value(n,'uri') or 'Fusion_'+source.alias+'_' in sx.value(n,'uri'))]
        asset_files=[]
        for path in project_files(project.parent/batch):
            relative=path.relative_to(project.parent/batch)
            if (relative.parts[:2]==('assets',source.alias) or relative.parts[:2]==('imported',source.alias)
                    or relative.parts and relative.parts[0]=='libraries' and
                    (relative.parts[1]=='Fusion_'+source.alias+'.kicad_sym' or relative.parts[1].startswith('Fusion_'+source.alias+'_'))):
                if path.suffix!='.kicad_sch':asset_files.append(str(path.relative_to(project.parent)))
        link={'id':new_uuid(),'alias':source.alias,'source_spec':asdict(spec),'origin_spec':origin_spec,
              'source_root_uuid':snapshot['root_uuid'],'source_baseline':snapshot,'include_layout':include_layout,
              'wrapper_uuid':source.wrapper_uuid,'wrapper_node':copy.deepcopy(wrapper),'batch':batch,
              'reference_map':dict(source.ref_map),'symbol_refs':{identity(r.old_path):r.new_ref for r in source.symbols},
              'schematic_ids':{identity(s.old_path):dict(s.ids) for s in source.sheets},
              'sheet_files':[(batch+'/' if batch else '')+s.relative_file for s in source.sheets],
              'pcb_uuid_map':pcb_map,'pcb_item_ids':pcb_top,'outer_group_uuid':(sx.value(outer,'id') or sx.value(outer,'uuid')) if include_layout and outer else None,
              'pcb_source_refs':{sx.value(fp,'uuid'):fp_reference(fp) for fp in sx.children(source.board,'footprint')},
              'translation_mm':list(source.translation),'library_names':libraries,'asset_files':asset_files,
              'class_names':list(source.class_map.values()),'net_names':list(source.net_map.values())}
        if origin_spec:
            durable=copy.deepcopy(origin_spec);durable['section_origin']=copy.deepcopy(spec.section_origin);durable['alias']=spec.alias
            durable['x_mm']=durable['y_mm']=None;link['source_spec']=durable;snapshot['variant']=original_snapshot['variant']
        link['target_baseline']=_scope(project,link,merged);manifest['links'].append(link)
    manifest['target_root_uuid']=sx.value(root,'uuid');manifest['plugin_version']=VERSION;_write(project.parent,manifest)


def _legacy_candidates(project,manifest,cli_path=''):
    from .legacy_links import candidates
    return candidates(project,manifest,cli_path)


def _strip_links(project,links,destination):
    copy_project(project.parent,destination);output=destination/project.name
    tree=sx.load(output.with_suffix('.kicad_sch'));wrappers={link['wrapper_uuid'] for link in links}
    tree[:]=[n for n in tree if not (sx.tag(n)=='sheet' and sx.value(n,'uuid') in wrappers)]
    sx.save(output.with_suffix('.kicad_sch'),tree)
    pcb=output.with_suffix('.kicad_pcb')
    if pcb.is_file():
        board=sx.load(pcb);ids={ident for link in links for ident in link.get('pcb_item_ids',[])}
        nets={name for link in links for name in link.get('net_names',[])}
        board[:]=[n for n in board if not ((sx.tag(n) in ITEMS and (sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id')) in ids)
                     or sx.tag(n)=='net' and len(n)>2 and str(n[2]) in nets)]
        sx.save(pcb,board)
    for name in ('fp-lib-table','sym-lib-table'):
        if not (destination/name).is_file():continue
        table=sx.load(destination/name);owned={nick for link in links for nick in link.get('library_names',{}).get(name,[])}
        table[:]=[n for n in table if not (sx.tag(n)=='lib' and sx.value(n,'name') in owned)];sx.save(destination/name,table)
    data=json.loads(output.read_text(encoding='utf-8-sig'));ns=data.get('net_settings') or {}
    classes={name for link in links for name in link.get('class_names',[])};nets={name for link in links for name in link.get('net_names',[])}
    data['text_variables']={key:value for key,value in data.get('text_variables',{}).items() if not any(key.startswith(link['alias']+'__') for link in links)}
    ns['classes']=[c for c in (ns.get('classes') or []) if c.get('name') not in classes]
    ns['netclass_patterns']=[p for p in (ns.get('netclass_patterns') or []) if p.get('netclass') not in classes and p.get('pattern') not in nets]
    for key in ('netclass_assignments','net_colors'):
        if isinstance(ns.get(key),dict):ns[key]={name:value for name,value in ns[key].items() if name not in nets}
    data['net_settings']=ns;output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    _,manifest=_load(output);selected={link['id'] for link in links};manifest['links']=[link for link in manifest['links'] if link['id'] not in selected]
    _write(destination,manifest)
    return output


def _rewrite_refs(tree,mapping):
    import re
    for node in sx.walk(tree):
        if sx.tag(node)=='reference' and len(node)>1 and str(node[1]) in mapping:node[1]=sx.q(mapping[str(node[1])])
        if sx.tag(node)=='property' and len(node)>2 and str(node[1]).casefold()=='reference' and str(node[2]) in mapping:node[2]=sx.q(mapping[str(node[2])])
        if sx.tag(node)=='fp_text' and len(node)>2 and str(node[1])=='reference' and str(node[2]) in mapping:node[2]=sx.q(mapping[str(node[2])])
        for index,value in enumerate(node):
            if isinstance(value,sx.Quoted) and '${' in value:
                node[index]=sx.q(re.sub(r'\$\{([^}:]+):',lambda match:'${'+mapping.get(match[1],match[1])+':',str(value)))


def _stable_maps(old,fresh,identity_overrides):
    mapping={};references={}
    aliases=identity_overrides or {}
    if len(set(aliases.values()))!=len(aliases):raise MergeError('Approved identity bindings must be one-to-one.')
    for before,after in aliases.items():
        if before not in old['source_baseline']['symbols'] or after not in fresh['source_baseline']['symbols']:
            raise MergeError('Approved identity binding is absent from its source snapshot.')
    reverse={after:before for before,after in aliases.items()}
    if old.get('include_layout') and aliases:
        old_footprints={item.get('symbol'):uid for uid,item in old['source_baseline'].get('board_items',{}).items() if item.get('kind')=='footprint'}
        new_footprints={item.get('symbol'):uid for uid,item in fresh['source_baseline'].get('board_items',{}).items() if item.get('kind')=='footprint'}
        for before,after in aliases.items():
            if before in old_footprints and after in new_footprints and old_footprints[before]!=new_footprints[after]:
                raise MergeError('Reviewed symbol identity binding changes its routed footprint UUID; retain the original footprint UUID or insert this replacement as a new design.')

    for path,ids in fresh['schematic_ids'].items():
        for source_uuid,generated_uuid in ids.items():
            stable=old['schematic_ids'].get(path,{}).get(source_uuid)
            occurrence=path+'/'+source_uuid
            if occurrence in reverse:
                old_path,old_uuid=reverse[occurrence].rsplit('/',1)
                stable=old['schematic_ids'].get(old_path,{}).get(old_uuid)
            if stable:mapping[generated_uuid]=stable
    mapping[fresh['wrapper_uuid']]=old['wrapper_uuid']
    if fresh.get('outer_group_uuid') and old.get('outer_group_uuid'):mapping[fresh['outer_group_uuid']]=old['outer_group_uuid']
    for source_uuid,generated_uuid in fresh['pcb_uuid_map'].items():
        if source_uuid in old['pcb_uuid_map']:mapping[generated_uuid]=old['pcb_uuid_map'][source_uuid]
    # KiCad can replace a footprint object while retaining the schematic
    # occurrence. Its new source UUID must still map to the placed target UUID.
    if old.get('include_layout'):
        old_fp={item.get('symbol'):uid for uid,item in old['source_baseline'].get('board_items',{}).items()
                if item.get('kind')=='footprint' and item.get('symbol')}
        new_fp={}
        for uid,item in fresh['source_baseline'].get('board_items',{}).items():
            if item.get('kind')=='footprint' and item.get('symbol'):
                if item['symbol'] in new_fp:raise MergeError('Multiple source footprints claim one schematic occurrence.')
                new_fp[item['symbol']]=uid
        for symbol,source_uuid in old_fp.items():
            incoming_uuid=new_fp.get(symbol)
            if not incoming_uuid or incoming_uuid==source_uuid:continue
            old_item=old['source_baseline']['board_items'][source_uuid]
            new_item=fresh['source_baseline']['board_items'][incoming_uuid]
            old_pads=[str(pad[1]) for pad in old_item.get('pad_connections',[])]
            new_pads=[str(pad[1]) for pad in new_item.get('pad_connections',[])]
            if len(old_pads)!=len(set(old_pads)) or sorted(old_pads)!=sorted(new_pads):
                raise MergeError('Replacement footprint changes pad numbers or duplicates a pad; review its mapping separately.')
            generated=fresh['pcb_uuid_map'].get(incoming_uuid)
            stable=old['pcb_uuid_map'].get(source_uuid)
            if not generated or not stable:raise MergeError('Replacement footprint lacks a verified PCB identity map.')
            mapping[generated]=stable
    for identity,target_ref in fresh['symbol_refs'].items():
        previous=reverse.get(identity,identity)
        if previous in old['symbol_refs']:
            stable=old['symbol_refs'][previous]
            if target_ref in references and references[target_ref]!=stable:raise MergeError('Approved bindings split a multi-unit component.')
            references[target_ref]=stable
    for uuid,reference in fresh.get('pcb_source_refs',{}).items():
        if uuid in old.get('pcb_source_refs',{}):
            previous=old['pcb_source_refs'][uuid]
            if reference in fresh['reference_map'] and previous in old['reference_map']:
                references.setdefault(fresh['reference_map'][reference],old['reference_map'][previous])
    if len(set(references.values()))!=len(references):raise MergeError('Reference identity mapping is ambiguous.')
    return mapping,references


def _rest_matches(before,after,owned_refs):
    rest=set(before.components)-owned_refs
    for ref in rest:
        if ref not in after.components or any(before.components[ref].get(key)!=after.components[ref].get(key) for key in ('value','footprint','paths')):
            raise MergeError('Linked update changed an unrelated destination component: '+ref)
    for name,endpoints in before.nets.items():
        selected={ep for ep in endpoints if ep[0] in rest}
        if not selected:continue
        names={after.pins.get(ep) for ep in selected}
        if len(names)!=1 or None in names or after.nets[next(iter(names))]!=endpoints:
            raise MergeError('Linked update changed unrelated destination pin connections.')


def _retain_target_layout(board,previous,links,ids,old_xml,final_xml):
    """Keep placed/routed target geometry while accepting new footprint bodies."""
    previous_items={sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id'):item
                    for item in sx.children(previous) if sx.tag(item) in ITEMS}
    owned={uid for old,_ in links for uid in old.get('pcb_item_ids',[])}
    rebuilt={ids.get(uid,uid) for _,fresh in links for uid in fresh.get('pcb_item_ids',[])}
    # Incoming source tracks/zones cannot be layered over the retained target
    # routes. A newly introduced footprint is kept as a staged new component.
    board[:]=[item for item in board if not (sx.tag(item) in ITEMS and
             (sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')) in (rebuilt-owned)
             and sx.tag(item)!='footprint')]
    updated_items={sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id'):item
                   for item in sx.children(board) if sx.tag(item) in ITEMS}
    old_table=net_table(previous);new_table=net_table(board)
    codes={name:code for code,name in new_table.items()}
    direct=any(sx.tag(node)=='net' and len(node)==2 and isinstance(node[1],sx.Quoted)
               for node in sx.walk(board))
    net_map={}
    for name,pins in old_xml.nets.items():
        names={final_xml.pins.get(pin) for pin in pins}
        if len(names)==1 and None not in names and final_xml.nets[next(iter(names))]==pins:
            net_map[name]=next(iter(names))
    for old,fresh in links:
        refs=set(old.get('reference_map',{}).values())
        for endpoint,name in old_xml.pins.items():
            if endpoint[0] in refs and endpoint in final_xml.pins and name not in net_map:
                raise MergeError('Cannot retain routed target copper after an electrical pin partition changed: '+endpoint[0]+'.'+endpoint[1])
    retained=[];replaced=[];footprint_pairs=[]
    original_geometry=geometry_signature(previous)
    for uid in owned:
        original=previous_items.get(uid)
        if original is None:raise MergeError('Linked target layout item is missing: '+uid)
        incoming=updated_items.get(uid)
        if sx.tag(original)=='footprint':
            if incoming is None or sx.tag(incoming)!='footprint':
                raise MergeError('Linked footprint disappeared from the updated source: '+fp_reference(original))
            ref=fp_reference(original)
            if sx.value(original,'layer')!=sx.value(incoming,'layer'):
                raise MergeError('Replacement footprint changes board side for '+ref+'; review placement manually.')
            old_pads={str(pad[1]):pad for pad in sx.children(original,'pad')}
            new_pads={str(pad[1]):pad for pad in sx.children(incoming,'pad')}
            if len(old_pads)!=len(sx.children(original,'pad')) or len(new_pads)!=len(sx.children(incoming,'pad')) or old_pads.keys()!=new_pads.keys():
                raise MergeError('Replacement footprint pad numbers differ for '+ref+'; retain target routing requires an explicit pad map.')
            for number,new_pad in new_pads.items():
                old_pad=old_pads[number]
                old_net=net_name(old_pad,old_table);new_net=net_name(new_pad,new_table)
                if old_net and (old_xml.pins.get((ref,number))!=old_net or net_map.get(old_net)!=new_net):
                    raise MergeError('Replacement footprint pad net differs from retained routing: '+ref+'.'+number)
                if not old_net and new_net:
                    raise MergeError('Replacement footprint connects a previously unconnected pad: '+ref+'.'+number)
                old_uid=sx.value(old_pad,'uuid') or sx.value(old_pad,'tstamp')
                if old_uid:sx.put(new_pad,'uuid',sx.q(old_uid))
            sx.put(incoming,'at',*copy.deepcopy(sx.child(original,'at')[1:]))
            for key in ('locked','unlocked'):
                sx.remove(incoming,key)
                if sx.child(original,key) is not None:incoming.append(copy.deepcopy(sx.child(original,key)))
            replaced.append(uid)
            footprint_pairs.append((original,incoming))
            continue
        if incoming is not None and sx.tag(incoming)!=sx.tag(original):
            raise MergeError('Linked target item type changed: '+uid)
        retained_item=copy.deepcopy(original)
        for node in sx.walk(retained_item):
            net=sx.child(node,'net')
            if net is None:continue
            old_name=net_name(node,old_table)
            if old_name:
                new_name=net_map.get(old_name)
                if not new_name or (not direct and new_name not in codes):
                    raise MergeError('Cannot prove the retained copper net after source update: '+old_name)
                net[:]=['net',sx.q(new_name)] if direct else ['net',codes[new_name],sx.q(new_name)]
        if incoming is None:
            board.append(retained_item)
        else:
            incoming[:]=retained_item
        retained.append(uid)
    adjusted=_prove_replacement_pad_attachments(board,previous,footprint_pairs,owned)
    updated_geometry=geometry_signature(board)
    changed_footprints=[uid for uid in replaced if original_geometry.get(uid)!=updated_geometry.get(uid)]
    return {'retained_target_layout_items':len(retained),
            'retained_target_placements':len(replaced),
            'adjusted_track_endpoints':adjusted,
            'changed_footprint_ids':changed_footprints}


def _prove_replacement_pad_attachments(board,previous,pairs,owned):
    """Keep or narrowly move a single attached endpoint; reject uncertain pads."""
    import math
    original_table=net_table(previous)
    original_routes={sx.value(item,'uuid'):item for item in sx.children(previous,'segment')
                     if sx.value(item,'uuid') in owned}
    updated_routes={sx.value(item,'uuid'):item for item in sx.children(board,'segment')}
    vias=[item for item in sx.children(previous,'via') if sx.value(item,'uuid') in owned]
    adjusted=0

    def pad_shape(fp,pad):
        position=sx.child(fp,'at');local=sx.child(pad,'at');size=sx.child(pad,'size')
        if not position or not local or not size:return None
        if (len(position)>3 and abs(float(position[3]))>1e-8) or (len(local)>3 and abs(float(local[3]))>1e-8):return None
        return (float(position[1])+float(local[1]),float(position[2])+float(local[2]),
                float(size[1])/2,float(size[2])/2,str(pad[3]),
                float(sx.value(pad,'roundrect_rratio') or 0))

    def contains(shape,point):
        x,y,hx,hy,kind,ratio=shape
        dx=abs(point[0]-x);dy=abs(point[1]-y)
        if kind=='rect':return dx<=hx+1e-6 and dy<=hy+1e-6
        if kind=='roundrect':
            radius=min(hx*2,hy*2)*ratio
            return dx<=hx+1e-6 and dy<=hy+1e-6 and (
                dx<=hx-radius or dy<=hy-radius or
                (dx-hx+radius)**2+(dy-hy+radius)**2 <=radius**2+1e-6)
        return False

    for old_fp,new_fp in pairs:
        old_pads={str(pad[1]):pad for pad in sx.children(old_fp,'pad')}
        for pad in sx.children(new_fp,'pad'):
            number=str(pad[1]);old_pad=old_pads[number]
            if _normal(old_pad)==_normal(pad):continue
            old_net=net_name(old_pad,original_table)
            if not old_net:continue
            old_shape=pad_shape(old_fp,old_pad);new_shape=pad_shape(new_fp,pad)
            if old_shape is None or new_shape is None:
                raise MergeError('Changed routed pad needs a supported unrotated rectangular footprint for attachment proof: '+fp_reference(new_fp)+'.'+number)
            layers=set(map(str,sx.child(old_pad,'layers',[])[1:]))
            attached=[]
            for uid,route in original_routes.items():
                if sx.value(route,'layer') not in layers or net_name(route,original_table)!=old_net:continue
                for endpoint in ('start','end'):
                    node=sx.child(route,endpoint)
                    if node and contains(old_shape,(float(node[1]),float(node[2]))):
                        attached.append((uid,endpoint,(float(node[1]),float(node[2]))))
            for via in vias:
                if net_name(via,original_table)!=old_net:continue
                node=sx.child(via,'at')
                if node and contains(old_shape,(float(node[1]),float(node[2]))) and not contains(new_shape,(float(node[1]),float(node[2]))):
                    raise MergeError('Changed pad would disconnect a retained via: '+fp_reference(new_fp)+'.'+number)
            moved=[entry for entry in attached if not contains(new_shape,entry[2])]
            if not moved:continue
            if len(attached)!=1 or len(moved)!=1:
                raise MergeError('Changed pad has branched or ambiguous retained copper: '+fp_reference(new_fp)+'.'+number)
            uid,endpoint,position=moved[0]
            new_center=new_shape[:2]
            if math.dist(position,new_center)>0.75:
                raise MergeError('Changed pad is too far from its retained trace endpoint: '+fp_reference(new_fp)+'.'+number)
            route=updated_routes.get(uid)
            if route is None:raise MergeError('Retained trace endpoint disappeared: '+uid)
            node=sx.child(route,endpoint)
            node[1]=str(round(new_center[0],6));node[2]=str(round(new_center[1],6))
            adjusted+=1
    return adjusted


def preview_update(target,link_ids,candidate_directory,cli_path='',acknowledge_major=False,source_overrides=None,identity_overrides=None,retain_destination_layout=False):
    from .insertion import preview_import,_target_integrity
    from .engine import publish
    project,manifest=_load(target);requested=set(link_ids)
    links=[link for link in manifest['links'] if link['id'] in requested]
    if not links or len(links)!=len(requested):raise MergeError('Select valid linked-import IDs.')
    for link in links:
        if link.get('update_unsupported_reason'):raise MergeError(link['alias']+': '+link['update_unsupported_reason'])
    if len({link['include_layout'] for link in links})!=1:raise MergeError('Update schematic-only and routed links in separate reviewed transactions.')
    destination=Path(candidate_directory).resolve()
    if destination.exists() or destination==project.parent or project.parent in destination.parents:raise MergeError('Choose a new update candidate folder outside the destination project.')
    target_hashes=fingerprint(project.parent);cli=KiCadCLI(cli_path);cache={};all_changes=[];snapshots={};specs=[]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-linked-update-',dir=destination.parent) as folder:
        work=Path(folder);old_xml=cli.export_netlist(project.with_suffix('.kicad_sch'),work/'original.xml')
        baseline_drc={}
        if links[0]['include_layout']:
            baseline_directory=work/'baseline-drc';copy_project(project.parent,baseline_directory)
            baseline_drc=cli.drc(baseline_directory/project.with_suffix('.kicad_pcb').name,work/'baseline-drc.json')
            owned_ids={uid for link in links for uid in [*link['pcb_item_ids'],*link['pcb_uuid_map'].values()]}
            for finding in baseline_drc.get('violations',[]):
                finding_ids={str(item.get('uuid','')) for item in finding.get('items',[]) if item.get('uuid')}
                if finding.get('type') in {'shorting_items','clearance','tracks_crossing'} and finding_ids & owned_ids and finding_ids-owned_ids:
                    raise MergeError('Destination conflict: linked copper intersects unrelated destination copper. Resolve the cross-block DRC finding before updating: '+finding.get('description',finding['type']))
        originals=[]
        for link in links:
            conflicts=_conflicts(project,link,old_xml,allow_owned_layout=retain_destination_layout)
            if conflicts:raise MergeError('Destination conflict for '+link['alias']+': '+conflicts[0]['message'])
            spec,current=_live_source(link,work,cli_path,cache,(source_overrides or {}).get(link['id']))
            changes=compare_snapshots(link['source_baseline'],current)
            all_changes.extend([dict(change,link_id=link['id'],alias=link['alias']) for change in changes['changes']]);snapshots[link['id']]=current
            if current['root_uuid']!=link['source_root_uuid']:raise MergeError('Source root UUID changed; explicit new insertion is required.')
            source=discover(spec,new_uuid(),require_board=link['include_layout'])
            if link['include_layout']:
                prepare_board(source);spec.x_mm=source.bbox[0]+link['translation_mm'][0];spec.y_mm=source.bbox[1]+link['translation_mm'][1]
            specs.append(spec)
            origin=spec.section_origin
            real_project=Path((source_overrides or {}).get(link['id']) or (link.get('origin_spec') or link['source_spec'])['project']).resolve()
            originals.append({'root':str(real_project.parent),'hashes':fingerprint(real_project.parent)})
        major=sum(change['severity']=='major' for change in all_changes)
        if major and not acknowledge_major:raise MergeError(str(major)+' major source changes require explicit acknowledgement. Review the pin/footprint/layout changes before previewing an update.')
        stripped=_strip_links(project,links,work/'stripped')
        plan=preview_import(stripped,specs,links[0]['include_layout'],work/'rebuilt',cli_path)
        candidate=Path(plan['candidate_directory']);fresh_project=candidate/project.name
        _,updated=_load(fresh_project);by_alias={link['alias']:link for link in updated['links']}
        ids={};references={};fresh_links=[]
        for old in links:
            fresh=by_alias[old['alias']];mapping,refs=_stable_maps(old,fresh,(identity_overrides or {}).get(old['id']))
            for key,value in mapping.items():
                if key in ids and ids[key]!=value:raise MergeError('Stable UUID mapping is ambiguous.')
                ids[key]=value
            references.update(refs);fresh_links.append((old,fresh))
        # New source components must not occupy references reserved by survivors.
        from .schematic import natural_ref
        old_board=project.with_suffix('.kicad_pcb')
        reserved=set(old_xml.components)
        if old_board.is_file():reserved.update(fp_reference(fp) for fp in sx.children(sx.load(old_board),'footprint'))
        used=set(old_xml.components)-{ref for link in links for ref in link['reference_map'].values()}
        used.update(references.values());counters={}
        for ref in reserved|used:
            try:prefix,number=natural_ref(ref);counters[prefix]=max(counters.get(prefix,0),number)
            except MergeError:pass
        for _,fresh in fresh_links:
            for ref in fresh['reference_map'].values():
                if ref in references:continue
                if ref in used or ref in reserved:
                    prefix,_=natural_ref(ref);number=counters.get(prefix,0)+1
                    new=prefix+(f'{number:04d}' if prefix.startswith('#') else str(number))
                    while new in used or new in reserved:number+=1;new=prefix+str(number)
                    references[ref]=new;counters[prefix]=number;used.add(new)
                else:used.add(ref)
        before_rebase=cli.export_netlist(fresh_project.with_suffix('.kicad_sch'),work/'before-rebase.xml')
        for old,fresh in fresh_links:
            for name in fresh['sheet_files']:
                tree=sx.load(candidate/name);sx.remap_identifiers(tree,ids)
                for node in sx.walk(tree):
                    if sx.tag(node)=='path' and len(node)>1:node[1]=sx.q('/'.join(ids.get(part,part) for part in str(node[1]).split('/')))
                _rewrite_refs(tree,references);sx.save(candidate/name,tree)
        root=sx.load(fresh_project.with_suffix('.kicad_sch'))
        old_wrappers={old['wrapper_uuid']:old['wrapper_node'] for old,_ in fresh_links}
        sx.remap_identifiers(root,ids)
        for wrapper in sx.children(root,'sheet'):
            if sx.value(wrapper,'uuid') not in old_wrappers:continue
            saved=old_wrappers[sx.value(wrapper,'uuid')];a=sx.child(saved,'at');b=sx.child(wrapper,'at');dx=float(a[1])-float(b[1]);dy=float(a[2])-float(b[2])
            for node in sx.walk(wrapper):
                if sx.tag(node)=='at' and len(node)>2:node[1]=str(float(node[1])+dx);node[2]=str(float(node[2])+dy)
            saved_pins={str(p[1]):sx.value(p,'uuid') for p in sx.children(saved,'pin')}
            for pin in sx.children(wrapper,'pin'):
                if str(pin[1]) in saved_pins:sx.put(pin,'uuid',sx.q(saved_pins[str(pin[1])]))
        sx.save(fresh_project.with_suffix('.kicad_sch'),root)
        final_xml=cli.export_netlist(fresh_project.with_suffix('.kicad_sch'),work/'final.xml')
        _rest_matches(old_xml,final_xml,{ref for link in links for ref in link['reference_map'].values()})
        net_names={}
        for name,pins in before_rebase.nets.items():
            transformed={(references.get(ref,ref),pin) for ref,pin in pins};names={final_xml.pins.get(ep) for ep in transformed}
            if len(names)!=1 or None in names or final_xml.nets[next(iter(names))]!=transformed:raise MergeError('Stable update changed source electrical partitions unexpectedly.')
            net_names[name]=next(iter(names))
        pcb=fresh_project.with_suffix('.kicad_pcb');retention={}
        if links[0]['include_layout']:
            board=sx.load(pcb);table=net_table(board);sx.remap_identifiers(board,ids);_rewrite_refs(board,references)
            for node in sx.walk(board):
                if sx.tag(node)=='path' and len(node)>1:node[1]=sx.q('/'.join(ids.get(part,part) for part in str(node[1]).split('/')))
                net=sx.child(node,'net')
                if net is not None:
                    name=net_name(node,table)
                    if len(net)>2:net[2]=sx.q(net_names.get(name,name))
                    elif len(net)>1 and isinstance(net[1],sx.Quoted):net[1]=sx.q(net_names.get(name,name))
            for net in sx.children(board,'net'):
                if len(net)>2:net[2]=sx.q(net_names.get(str(net[2]),str(net[2])))
            if retain_destination_layout:
                retention=_retain_target_layout(board,sx.load(project.with_suffix('.kicad_pcb')),
                                                fresh_links,ids,old_xml,final_xml)
            from .board import verify_native_associations
            verify_native_associations(board,final_xml)
            sx.save(pcb,board)
        # Net-class assignments follow the stable, re-exported net names.
        data=json.loads(fresh_project.read_text());ns=data.get('net_settings') or {}
        for key in ('netclass_assignments','net_colors'):
            if isinstance(ns.get(key),dict):ns[key]={net_names.get(name,name):value for name,value in ns[key].items()}
        for pattern in ns.get('netclass_patterns') or []:pattern['pattern']=net_names.get(pattern.get('pattern'),pattern.get('pattern'))
        fresh_project.write_text(json.dumps(data,indent=2),encoding='utf-8')
        drc=None
        if links[0]['include_layout']:
            before_board=sx.load(pcb);drc=cli.drc(pcb,candidate/'linked-update-drc.json');_target_integrity(before_board,sx.load(pcb))
            original_board=sx.load(project.with_suffix('.kicad_pcb'));owned={item for link in links for item in link['pcb_item_ids']}
            original_board[:]=[n for n in original_board if not (sx.tag(n) in ITEMS and (sx.value(n,'uuid') or sx.value(n,'tstamp') or sx.value(n,'id')) in owned)]
            _target_integrity(original_board,sx.load(pcb))
            safety_types={'shorting_items','clearance','tracks_crossing','copper_edge_clearance','hole_clearance'}
            def finding_identity(finding):
                return (finding.get('type'),finding.get('severity'),finding.get('description'),
                        tuple(sorted(str(item.get('uuid',item.get('description',''))) for item in finding.get('items',[]))))
            previous={finding_identity(f) for f in baseline_drc.get('violations',[]) if f.get('type') in safety_types}
            introduced=[f for f in drc.get('violations',[]) if f.get('type') in safety_types and finding_identity(f) not in previous]
            if introduced:raise MergeError('Linked update introduces a copper safety conflict: '+introduced[0].get('description',introduced[0].get('type','DRC finding')))
            if retain_destination_layout:
                changed=set(retention.get('changed_footprint_ids',[]))
                touching=[finding for finding in drc.get('violations',[]) if finding.get('type') in safety_types
                          and changed & {str(item.get('uuid','')) for item in finding.get('items',[])}]
                if touching:
                    raise MergeError('Replacement footprint has a copper safety finding: '
                                     +touching[0].get('description',touching[0].get('type','DRC finding')))
                previous_open={finding_identity(f) for f in baseline_drc.get('unconnected_items',[])}
                newly_open=[f for f in drc.get('unconnected_items',[])
                            if finding_identity(f) not in previous_open]
                if newly_open:
                    raise MergeError('Replacement footprint or retained route introduces an unconnected copper item: '
                                     +newly_open[0].get('description','review pad and track attachment.'))
        cli.run(['sch','erc','--format','json','--output',candidate/'linked-update-erc.json',fresh_project.with_suffix('.kicad_sch')],cwd=candidate)
        present_items={sx.value(item,'uuid') or sx.value(item,'tstamp') or sx.value(item,'id')
                       for item in sx.children(sx.load(pcb)) if sx.tag(item) in ITEMS} if retain_destination_layout and links[0]['include_layout'] else set()
        for old,fresh in fresh_links:
            fresh['id']=old['id'];fresh['wrapper_uuid']=old['wrapper_uuid']
            fresh['reference_map']={key:references.get(value,value) for key,value in fresh['reference_map'].items()}
            fresh['symbol_refs']={key:references.get(value,value) for key,value in fresh['symbol_refs'].items()}
            fresh['schematic_ids']={path:{key:ids.get(value,value) for key,value in values.items()} for path,values in fresh['schematic_ids'].items()}
            fresh['pcb_uuid_map']={key:ids.get(value,value) for key,value in fresh['pcb_uuid_map'].items()}
            fresh['pcb_item_ids']=[ids.get(value,value) for value in fresh['pcb_item_ids']]
            if retain_destination_layout:
                fresh['pcb_uuid_map']={key:value for key,value in
                    {**old.get('pcb_uuid_map',{}),**fresh['pcb_uuid_map']}.items() if value in present_items}
                fresh['pcb_item_ids']=[uid for uid in dict.fromkeys([*old.get('pcb_item_ids',[]),*fresh['pcb_item_ids']])
                                       if uid in present_items]
            fresh['outer_group_uuid']=ids.get(fresh.get('outer_group_uuid'),fresh.get('outer_group_uuid'))
            fresh['net_names']=[net_names.get(name,name) for name in fresh['net_names']]
            fresh['source_baseline']=snapshots[old['id']]
            if fresh.get('origin_spec'):
                durable=copy.deepcopy(fresh['origin_spec']);durable['section_origin']=copy.deepcopy(fresh['source_spec']['section_origin']);durable['alias']=fresh['alias']
                durable['x_mm']=durable['y_mm']=None;fresh['source_spec']=durable
            fresh['wrapper_node']=next(copy.deepcopy(s) for s in sx.children(root,'sheet') if sx.value(s,'uuid')==old['wrapper_uuid'])
            fresh['target_baseline']=_scope(fresh_project,fresh,final_xml)
        _write(candidate,updated)
        from .bom_fields import inventory,grouped_bom,export_csv
        reviewed=discover(SourceSpec(str(fresh_project),'ReviewedTarget',variant='<Default>'),new_uuid(),require_board=False)
        reviewed_rows=inventory([reviewed])
        export_csv(candidate/'insertion-bom.csv',grouped_bom(reviewed_rows),bom=True)
        export_csv(candidate/'insertion-fields.csv',reviewed_rows)
        rendered=candidate/'linked-update-preview'
        if rendered.exists():shutil.rmtree(rendered)
        rendered.mkdir()
        cli.run(['sch','export','svg','--output',rendered,fresh_project.with_suffix('.kicad_sch')],cwd=candidate)
        erc=json.loads((candidate/'linked-update-erc.json').read_text(encoding='utf-8-sig'))
        report={'plugin_version':VERSION,'linked_update':True,'updated_links':[link['id'] for link in links],
                'major_changes':major,'acknowledged_major_changes':bool(acknowledge_major),'changes':all_changes,'conflicts':[],
                'retain_destination_layout':bool(retain_destination_layout),**retention,
                'stable_references_and_uuids_preserved':True,'unrelated_destination_preserved':True,'manufacturing_approved':False,
                'drc_findings':len(drc.get('violations',[])) if drc else None,'unconnected_findings':len(drc.get('unconnected_items',[])) if drc else None,
                'erc_findings':sum(len(sheet.get('violations',[])) for sheet in erc.get('sheets',[]))}
        (candidate/'linked-update-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if fingerprint(project.parent)!=target_hashes or any(fingerprint(Path(entry['root']))!=entry['hashes'] for entry in originals):raise MergeError('Source or destination changed during linked update preview.')
        dependencies=[]
        for snapshot in snapshots.values():
            for path,value in snapshot.get('hashes',{}).items():
                if not Path(path).is_file() or sha256(path)!=value:raise MergeError('Source dependency changed during linked update preview: '+path)
                dependencies.append({'original_path':path,'sha256':value})
        for entry in plan.get('source_file_hashes',[]):
            if work not in Path(entry['original_path']).parents:dependencies.append(entry)
        publish(candidate,destination)
    return {'target_project':str(project),'target_hashes':target_hashes,'source_hashes':originals,'source_file_hashes':dependencies,
            'candidate_directory':str(destination),'candidate_hashes':fingerprint(destination),'report':report}


def apply_update(plan):
    """Apply a reviewed update with the same verified backup and stale guards as insertion."""
    from .insertion import apply_import
    return apply_import(plan)


def preview_adopt_links(target,link_ids,candidate_directory,cli_path=""):
    """Review archived-provenance adoption without changing destination geometry."""
    from .legacy_links import preview_adopt
    return preview_adopt(target,link_ids,candidate_directory,cli_path)


def preview_break_links(target,link_ids,candidate_directory,cli_path=''):
    """Detach monitoring while preserving every local schematic/layout/source copy."""
    from .engine import publish
    project,manifest=_load(target);requested=set(link_ids)
    if not requested or not requested<={link['id'] for link in manifest['links']}:
        raise MergeError('Select valid linked-import IDs to break.')
    destination=Path(candidate_directory).resolve()
    if destination.exists() or destination==project.parent or project.parent in destination.parents:
        raise MergeError('Choose a new break-links candidate outside the destination project.')
    original=fingerprint(project.parent);destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-break-links-',dir=destination.parent) as folder:
        candidate=Path(folder)/'candidate';copy_project(project.parent,candidate)
        manifest['links']=[link for link in manifest['links'] if link['id'] not in requested];_write(candidate,manifest)
        changes={name for name in original if sha256(candidate/name)!=original[name]}
        if changes!={MANIFEST}:raise MergeError('Breaking links changed local design files; nothing published.')
        if fingerprint(project.parent)!=original:raise MergeError('Destination changed during break-links review.')
        publish(candidate,destination)
    report={'plugin_version':VERSION,'linked_break':True,'broken_links':sorted(requested),'local_design_preserved':True,'sources_accessed':False,'major_changes':0}
    return {'target_project':str(project),'target_hashes':original,'source_hashes':[],'source_file_hashes':[],
            'candidate_directory':str(destination),'candidate_hashes':fingerprint(destination),'report':report}


def list_transactions(target):
    project=Path(target).resolve().with_suffix('.kicad_pro');current=fingerprint(project.parent);rows=[]
    for directory in project.parent.parent.glob(project.parent.name+'-FusionBackup-*'):
        receipt_file=directory/'transaction.json'
        if not receipt_file.is_file():continue
        try:
            receipt=json.loads(receipt_file.read_text(encoding='utf-8-sig'))
            if receipt.get('target_project')!=str(project) or not receipt.get('completed'):continue
            verified=fingerprint(directory/'project')==receipt['target_hashes']
            eligible=verified and current==receipt.get('applied_hashes')
            report=receipt.get('report',{})
            operation='break links' if report.get('linked_break') else ('undo' if report.get('linked_undo') else ('update' if report.get('linked_update') else 'import/adopt'))
            rows.append({'id':str(directory),'backup_directory':str(directory),'created_at':receipt.get('created_at',''),
                         'operation':operation,'eligible':eligible,'error':'' if eligible else ('Destination changed after this transaction.' if verified else 'Backup changed.')})
        except (OSError,ValueError,KeyError):continue
    return sorted(rows,key=lambda row:row['created_at'],reverse=True)


def preview_undo(target,backup_directory,candidate_directory,cli_path=''):
    """Restore one verified transaction snapshot; later local edits must be resolved first."""
    from .engine import publish
    project=Path(target).resolve().with_suffix('.kicad_pro');backup=Path(backup_directory).resolve()
    receipt=json.loads((backup/'transaction.json').read_text(encoding='utf-8-sig'))
    current=fingerprint(project.parent)
    if receipt.get('target_project')!=str(project) or not receipt.get('completed') or current!=receipt.get('applied_hashes'):
        raise MergeError('Destination changed after this transaction; undo would overwrite local edits.')
    restored=fingerprint(backup/'project')
    if restored!=receipt['target_hashes']:raise MergeError('Undo backup changed; recovery cannot be certified.')
    destination=Path(candidate_directory).resolve()
    if destination.exists() or destination==project.parent or project.parent in destination.parents:
        raise MergeError('Choose a new undo candidate outside the destination project.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-undo-',dir=destination.parent) as folder:
        candidate=Path(folder)/'candidate';copy_project(backup/'project',candidate)
        if fingerprint(candidate)!=restored or fingerprint(project.parent)!=current:raise MergeError('Destination or backup changed during undo preview.')
        publish(candidate,destination)
    report={'plugin_version':VERSION,'linked_undo':True,'undo_backup':str(backup),'restored_verified_snapshot':True,'major_changes':0}
    return {'target_project':str(project),'target_hashes':current,'source_hashes':[{'root':str(backup/'project'),'hashes':restored}],
            'source_file_hashes':[],'candidate_directory':str(destination),'candidate_hashes':restored,'undo_backup':str(backup),
            'remove_files':sorted(set(current)-set(restored)),'report':report}
