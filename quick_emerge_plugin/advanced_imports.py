"""Reviewed, bounded fabrication imports through public EMerge 3 read APIs.

Imports create geometry only. No lumped ports, feeds, S parameters, component
models or material guesses are synthesized. This adapter does not execute
project scripts or load parser caches. It preserves all source-file hashes and
requires an explicit material/layer/unit recipe reviewed before the solve.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
from pathlib import Path
import os
import re
import xml.etree.ElementTree as ET

KINDS=('gerber','gds','gds_xml','odb')
MAX_BYTES=200*1024*1024
MAX_FILE_BYTES=50*1024*1024
MAX_FILES=1000


def _number(value,name,minimum=0,positive=False):
    if isinstance(value,bool):raise ValueError(name+' must be finite numeric data')
    try:value=float(value)
    except (ValueError,TypeError,OverflowError) as exc:raise ValueError(name+' must be numeric') from exc
    if not math.isfinite(value) or value<minimum or (positive and value==minimum):raise ValueError(name+' is outside its supported range')
    return value


def _sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def _child(root,name):
    if not isinstance(name,str) or not name or Path(name).is_absolute():raise ValueError('Import recipe filenames must be relative to the source directory')
    path=root/Path(name)
    if any(p=='..' for p in Path(name).parts):raise ValueError('Import recipe cannot traverse outside the source directory')
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Import recipe file is missing or outside the source directory: '+name)
    if path.stat().st_size>MAX_FILE_BYTES:raise ValueError('Import file exceeds 50 MiB: '+name)
    return path.resolve()


def _material_recipes(raw):
    if not isinstance(raw,dict) or not 1<=len(raw)<=64:raise ValueError('Provide 1 to 64 reviewed material definitions')
    result={}
    for name,item in raw.items():
        if not isinstance(name,str) or not name.strip() or not isinstance(item,dict):raise ValueError('Material names and definitions must be explicit')
        kind=item.get('type')
        if kind=='pec':
            if set(item)!={'type'}:raise ValueError('PEC material has no numerical properties')
            result[name]={'type':'pec'}
        elif kind=='dielectric':
            if set(item)-{'type','er','loss_tangent'} or 'er' not in item:raise ValueError('Dielectric needs explicit er and optional loss_tangent')
            er=_number(item['er'],'permittivity',positive=True);tand=_number(item.get('loss_tangent',0),'loss tangent')
            if tand>1:raise ValueError('Loss tangent above one is outside this import contract')
            result[name]={'type':kind,'er':er,'loss_tangent':tand}
        elif kind=='conductor':
            if set(item)!={'type','conductivity_s_m'}:raise ValueError('Conductor needs conductivity_s_m')
            result[name]={'type':kind,'conductivity_s_m':_number(item['conductivity_s_m'],'conductivity',positive=True)}
        else:raise ValueError('Supported reviewed material types are pec, dielectric and conductor')
    return result


def _recipe(kind,path,base):
    if path.suffix.lower()!='.json' or path.stat().st_size>1024*1024:raise ValueError('Import recipe must be a JSON file no larger than 1 MiB')
    try:r=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError) as exc:raise ValueError('Import recipe must be UTF-8 JSON data') from exc
    common={'schema','reviewed','units'}
    allowed={'gds':common|{'materials','layers','ignored_layers','cell','gds_db_unit_m','scale','min_edge_m'},
             'gds_xml':common|{'xml_file','layer_names','material_names','gds_db_unit_m','cell','datatypes','dielectric_margin_mm'},
             'gerber':common|{'materials','copper_layers','substrate','trace_material','trace_thickness_um','drills'},
             'odb':common|{'materials','substrate_material','trace_material','stack_thickness_m','layer_names','reverse_stack','generate_vias'}}[kind]
    if not isinstance(r,dict) or set(r)-allowed or r.get('schema')!=1 or r.get('reviewed') is not True:raise ValueError('Recipe requires schema 1, reviewed=true and only documented keys')
    if r.get('units') not in (('embedded',) if kind in ('gds','gds_xml','odb') else ('mm','inch')):raise ValueError('Review embedded file units (GDS/ODB) or explicit mm/inch (Gerber)')
    if kind!='gds_xml':r['materials']=_material_recipes(r.get('materials'))
    if kind=='gds':
        r['gds_db_unit_m']=_number(r.get('gds_db_unit_m'),'reviewed GDS database unit',positive=True)
        r['scale']=_number(r.get('scale',1),'GDS coordinate multiplier',positive=True)
        r['min_edge_m']=_number(r.get('min_edge_m',0),'minimum edge length')
        if not isinstance(r.get('layers'),list) or not 1<=len(r['layers'])<=64:raise ValueError('GDS requires 1 to 64 reviewed layers')
        pairs=set();names=set()
        for layer in r['layers']:
            if not isinstance(layer,dict) or set(layer)!={'layer','datatype','name','z_m','thickness_m','material'}:raise ValueError('GDS layer requires layer/datatype/name/z_m/thickness_m/material')
            for key in ('layer','datatype'):
                if type(layer[key]) is not int or not 0<=layer[key]<=32767:raise ValueError('GDS layer/datatype must be nonnegative integers')
            pair=(layer['layer'],layer['datatype'])
            if pair in pairs or not isinstance(layer['name'],str) or not layer['name'] or layer['name'] in names:raise ValueError('GDS layer mapping and names must be unique')
            pairs.add(pair);names.add(layer['name'])
            if layer['material'] not in r['materials']:raise ValueError('GDS layer uses an unreviewed material')
            layer['z_m']=_number(layer['z_m'],'GDS layer height',minimum=-2)
            layer['thickness_m']=_number(layer['thickness_m'],'GDS layer thickness')
            if not layer['thickness_m'] and r['materials'][layer['material']]['type']!='pec':raise ValueError('Zero-thickness GDS layers require PEC; finite material needs a volume')
        ignored=r.get('ignored_layers',[])
        if not isinstance(ignored,list) or any(not isinstance(p,list) or len(p)!=2 or any(type(v) is not int for v in p) for p in ignored):raise ValueError('ignored_layers must list explicit [layer,datatype] pairs')
        if len(set(map(tuple,ignored)))!=len(ignored) or pairs&set(map(tuple,ignored)):raise ValueError('Ignored GDS layers cannot duplicate mapped layers')
        r['ignored_layers']=ignored
    elif kind=='gds_xml':
        xml=_child(base,r.get('xml_file'))
        data=xml.read_bytes()
        try:text=data.decode('utf-8-sig')
        except UnicodeError as exc:raise ValueError('Stack XML must use UTF-8 encoding') from exc
        if len(data)>1024*1024 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('Stack XML must be <=1 MiB with no DTD or entities')
        try:root=ET.fromstring(text)
        except ET.ParseError as exc:raise ValueError('Invalid stack XML') from exc
        if root.tag!='Stackup' or root.get('schemaVersion') not in ('2.0','3.0','3.1'):raise ValueError('Supported literal stack XML schema versions are 2.0, 3.0 and 3.1')
        for element in root.iter():
            if any(str(v).lstrip().startswith('=') for v in element.attrib.values()):raise ValueError('This import accepts literal stack XML only; resolve expressions before review')
        for key in ('layer_names','material_names'):
            if not isinstance(r.get(key),list) or not r[key] or any(not isinstance(v,str) or not v for v in r[key]) or len(set(r[key]))!=len(r[key]):raise ValueError('XML recipe must explicitly review unique '+key)
        r['gds_db_unit_m']=_number(r.get('gds_db_unit_m'),'reviewed GDS database unit',positive=True)
        r['dielectric_margin_mm']=_number(r.get('dielectric_margin_mm',0),'dielectric lateral margin')
        r['datatypes']=r.get('datatypes',[0])
        if not isinstance(r['datatypes'],list) or not r['datatypes'] or any(type(v) is not int or v<0 for v in r['datatypes']):raise ValueError('GDS XML datatypes must be explicit nonnegative integers')
    elif kind=='gerber':
        layers=r.get('copper_layers')
        if not isinstance(layers,list) or not 1<=len(layers)<=32:raise ValueError('Provide 1 to 32 explicitly mapped Gerber copper files')
        indices=[]
        for layer in layers:
            if not isinstance(layer,dict) or set(layer)!={'file','index','name'} or type(layer['index']) is not int or layer['index']<0 or not isinstance(layer['name'],str) or not layer['name']:raise ValueError('Gerber mapping needs file/index/name')
            file=_child(base,layer['file']);text=file.read_text(encoding='ascii',errors='strict')
            unit='mm' if '%MOMM*%' in text.upper() else 'inch' if '%MOIN*%' in text.upper() else None
            if unit!=r['units']:raise ValueError('Gerber embedded unit does not match the reviewed unit')
            indices.append(layer['index'])
        if len(set(indices))!=len(indices):raise ValueError('Gerber copper indices must be unique')
        if min(indices)!=0 or max(indices)<1:raise ValueError('Gerber mapping must explicitly include bottom index 0 and a top copper index')
        if not isinstance(r.get('drills',[]),list) or len(r.get('drills',[]))>32:raise ValueError('At most 32 explicitly plated Excellon files are supported')
        sub=r.get('substrate')
        if not isinstance(sub,dict) or set(sub)!={'thickness_mm','material','outline_mm'} or sub['material'] not in r['materials']:raise ValueError('Reviewed substrate needs thickness_mm/material/outline_mm')
        if r['materials'][sub['material']]['type']!='dielectric':raise ValueError('Gerber substrate material must be dielectric')
        sub['thickness_mm']=_number(sub['thickness_mm'],'substrate thickness',positive=True)
        outline=sub['outline_mm']
        if not isinstance(outline,list) or not 3<=len(outline)<=10000:raise ValueError('Substrate outline requires 3 to 10000 reviewed XY vertices')
        for p in outline:
            if not isinstance(p,list) or len(p)!=2:raise ValueError('Substrate outline vertices must be XY millimetres')
            p[:]=[_number(v,'outline coordinate',minimum=-2000) for v in p]
        if max(indices)>31:raise ValueError('Gerber supports at most 32 ordered copper layers')
        r['trace_thickness_um']=_number(r.get('trace_thickness_um'),'trace thickness',positive=True)
        if r.get('trace_material') not in r['materials'] or r['materials'][r['trace_material']]['type']=='dielectric':raise ValueError('Explicit conducting trace_material is required')
        for drill in r.get('drills',[]):
            if not isinstance(drill,dict) or set(drill)!={'file','plated'} or drill['plated'] is not True:raise ValueError('Only explicitly plated circular Excellon drill files are supported')
            text=_child(base,drill['file']).read_text(encoding='ascii')
            if re.search(r'(?m)^\s*(G85|G00|M15)',text,re.I):raise ValueError('Excellon slots/routing are unsupported; they cannot silently become vias')
            unit='mm' if re.search(r'(?m)^\s*(METRIC|M71)',text,re.I) else 'inch' if re.search(r'(?m)^\s*(INCH|M72)',text,re.I) else None
            if unit!=r['units']:raise ValueError('Excellon unit does not match reviewed fabrication units')
    elif kind=='odb':
        for key in ('substrate_material','trace_material'):
            if r.get(key) not in r['materials']:raise ValueError('ODB requires reviewed '+key)
        if not isinstance(r.get('stack_thickness_m'),list) or not 1<=len(r['stack_thickness_m'])<=64:raise ValueError('ODB requires explicit physical stack_thickness_m')
        r['stack_thickness_m']=[_number(v,'ODB stack thickness',positive=True) for v in r['stack_thickness_m']]
        if not isinstance(r.get('layer_names'),list) or not r['layer_names'] or any(not isinstance(v,str) or not v for v in r['layer_names']):raise ValueError('ODB requires explicit signal-layer names')
        if r['materials'][r['trace_material']]['type']!='pec':raise ValueError('ODB trace importer creates sheets; only explicitly reviewed PEC traces are qualified. Finite conductivity needs a thickness boundary model')
        if r['materials'][r['substrate_material']]['type']!='dielectric' or r['materials'][r['trace_material']]['type']=='dielectric':raise ValueError('ODB substrate must be dielectric and traces must be conducting')
        if len(set(r['layer_names']))!=len(r['layer_names']):raise ValueError('ODB reviewed layer names must be unique')
        for key in ('reverse_stack','generate_vias'):
            if type(r.get(key)) is not bool:raise ValueError('ODB requires explicit boolean '+key)
    return r


def import_identity(kind,path,recipe_path):
    """Hash an input file or complete directory plus its reviewed JSON recipe."""
    if kind not in KINDS:raise ValueError('Supported import kinds: '+', '.join(KINDS))
    source=Path(path).expanduser()
    recipe=Path(recipe_path).expanduser()
    if source.is_symlink() or recipe.is_symlink():raise ValueError('Import inputs cannot be symbolic links')
    source=source.resolve(strict=True);recipe=recipe.resolve(strict=True)
    if kind in ('gds','gds_xml'):
        if not source.is_file() or source.suffix.lower() not in ('.gds','.gdsii'):raise ValueError('GDS imports require a GDSII binary file')
        base=source.parent;files=[source]
    else:
        if not source.is_dir():raise ValueError('Gerber and ODB imports require an uncompressed source directory')
        base=source;files=[]
        for root,dirs,names in os.walk(source,followlinks=False):
            for name in dirs+names:
                candidate=Path(root)/name
                if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):raise ValueError('Import directories cannot contain links or junctions')
            files.extend(Path(root)/name for name in names)
            if len(files)>MAX_FILES:raise ValueError('Import exceeds 1000 input files')
    parsed=_recipe(kind,recipe,base)
    if kind=='gds_xml':files.append(_child(base,parsed['xml_file']))
    if not files:raise ValueError('Import directory contains no files')
    records=[];total=0
    for file in sorted(set(files),key=lambda p:p.relative_to(base).as_posix()):
        size=file.stat().st_size;total+=size
        if size>MAX_FILE_BYTES or total>MAX_BYTES:raise ValueError('Import exceeds 50 MiB per file or 200 MiB total')
        records.append({'relative_path':file.relative_to(base).as_posix(),'bytes':size,'sha256':_sha(file)})
    recipe_hash=_sha(recipe)
    payload={'kind':kind,'files':records,'recipe_sha256':recipe_hash,'recipe':parsed}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {'kind':kind,'path':str(source),'sha256':digest,'files':records,'recipe_path':str(recipe),'recipe_sha256':recipe_hash,'recipe':parsed,'coordinate_unit':'metres after explicit file-unit conversion','manifest_schema':1}


def verify_import(advanced):
    identity=import_identity(advanced['import_kind'],advanced['import_path'],advanced['import_recipe_path'])
    if identity['sha256']!=advanced.get('import_sha256'):raise ValueError('Imported fabrication geometry or reviewed recipe changed; preview and review again')
    return identity


def _materials(em,recipes):
    return {name:em.lib.PEC if r['type']=='pec' else em.Material(name=name,er=r['er'],tand=r['loss_tangent']) if r['type']=='dielectric' else em.Material(name=name,cond=r['conductivity_s_m']) for name,r in recipes.items()}


def build_import(em,advanced):
    """Create reviewed objects in the caller's active EMerge Simulation.

    Returns objects, conductors, identity, scope and assumptions. The caller
    supplies an enclosing air region, meshing, scattering excitation and solve.
    Recheck ``verify_import`` after solving, before publishing result custody.
    """
    identity=verify_import(advanced);r=identity['recipe'];kind=identity['kind']
    source=Path(identity['path']);base=source.parent if source.is_file() else source
    try:read=importlib.import_module('emerge.read')
    except ImportError as exc:raise RuntimeError('Selected solver lacks EMerge 3 public import APIs') from exc
    objects=[];conductors=[];assumptions=['Imported geometry only; no electrical feeds or lumped ports inferred','Material and layer assignment are the explicitly reviewed recipe, not fabrication qualification','No convergence qualification; external components, solder and assembly are not imported']
    try:
        if kind=='gds':
            mats=_materials(em,r['materials'])
            parsed=read.GDSFile(source,layers=None,cell=r.get('cell'))
            if not math.isclose(parsed.library.db_unit,r['gds_db_unit_m'],rel_tol=1e-12):raise ValueError('GDS embedded database unit differs from review')
            found=set(parsed.found_layers);mapped={(v['layer'],v['datatype']) for v in r['layers']};ignored=set(map(tuple,r['ignored_layers']))
            if found!=mapped|ignored:raise ValueError('Every present GDS layer/datatype must be explicitly mapped or ignored; mapped layers must exist')
            layers={(v['layer'],v['datatype']):read.GDSLayer(z=v['z_m'],thickness=v['thickness_m'] or None,material=mats[v['material']],name=v['name']) for v in r['layers']}
            built=read.GDSFile(source,layers=layers,cell=r.get('cell'),scale=r['scale'],scale_factor=1,min_edge=r['min_edge_m'])
            objects=list(built)
            conductors=[built.objects[(v['layer'],v['datatype'])] for v in r['layers'] if r['materials'][v['material']]['type']!='dielectric']
            assumptions.append('Unmapped GDS layer/datatype pairs are rejected unless explicitly recorded as ignored')
        elif kind=='gerber':
            mats=_materials(em,r['materials']);sub=r['substrate'];count=max(v['index'] for v in r['copper_layers'])+1
            if count<2:raise ValueError('Gerber substrate import requires at least two indexed copper heights')
            pcb=read.FileBasedPCB(sub['thickness_mm'],unit=.001,material=mats[sub['material']],trace_material=mats[r['trace_material']],layers=count,trace_thickness=r['trace_thickness_um']*1e-6,thick_traces=True)
            pcb.set_board_outline([p[0] for p in sub['outline_mm']],[p[1] for p in sub['outline_mm']])
            for layer in r['copper_layers']:conductors.append(pcb.layer_from_file(layer['index'],str(_child(base,layer['file'])),curved=True))
            for drill in r.get('drills',[]):pcb.vias_from_file(str(_child(base,drill['file'])),layer1=0,layer2=count-1)
            dielectric=pcb.generate_pcb(merge=True)
            objects.extend(dielectric if isinstance(dielectric,list) else [dielectric])
            if r.get('drills'):
                vias=pcb.generate_vias(merge=False);conductors.extend(vias if isinstance(vias,list) else [vias])
            objects.extend(conductors)
            assumptions.extend(['Gerber copper index 0 is bottom; higher indices use evenly spaced reviewed substrate heights','Substrate uses the explicit reviewed polygon outline; no routed mechanical outline is inferred','Only explicitly plated circular Excellon drill files are modeled as vias'])
        elif kind=='gds_xml':
            xml=_child(base,r['xml_file']);stack=read.read_stackup_xml(xml)
            if set(v.name for v in stack.layers)!=set(r['layer_names']) or set(stack.materials)!=set(r['material_names']):raise ValueError('XML layer/material names differ from the explicit review')
            for material in stack.materials.values():
                if material.type.lower() not in ('dielectric','conductor','semiconductor','resistor') or not all(math.isfinite(v) for v in (material.permittivity,material.loss_tangent,material.conductivity)) or material.permittivity<=0 or not 0<=material.loss_tangent<=1 or material.conductivity<0:raise ValueError('XML material must have finite positive permittivity and nonnegative supported loss/conductivity')
            if any(layer.material!='PEC' and stack.materials[layer.material].type.lower()=='conductor' and layer.thickness<=0 for layer in stack.layers):raise ValueError('Finite-conductivity XML layers require explicit positive thickness')
            if any(v.type.lower()=='resistor' for v in stack.materials.values()):raise ValueError('Sheet resistor XML layers are unsupported; do not silently omit them')
            if any(d.boundary_layer is not None for d in stack.dielectrics):raise ValueError('Boundary-shaped XML dielectric slabs are not qualified in this adapter')
            parsed=read.GDSFile(source,layers=None,cell=r.get('cell'))
            if not math.isclose(parsed.library.db_unit,r['gds_db_unit_m'],rel_tol=1e-12):raise ValueError('GDS embedded database unit differs from review')
            built=read.GDSFromXML(xml=xml,gds=source,cell=r.get('cell'),size_scale=1,datatypes=tuple(r['datatypes']),min_edge=0)
            objects=list(built)
            for layer in stack.layers:
                if layer.gds_layer in built.objects and (layer.material=='PEC' or stack.materials[layer.material].type.lower()=='conductor'):conductors.append(built.objects[layer.gds_layer])
            x0,y0,x1,y1=built.bounds();margin=r['dielectric_margin_mm']*.001
            for slab in stack.dielectrics:
                m=stack.materials[slab.material]
                if not all(math.isfinite(v) for v in (slab.zmin,slab.zmax,m.permittivity,m.loss_tangent,m.conductivity)) or slab.zmax<=slab.zmin:raise ValueError('XML dielectric dimensions/material are invalid')
                mat=em.Material(name=slab.material,er=m.permittivity,tand=m.loss_tangent,cond=m.conductivity)
                objects.append(em.geo.Box(x1-x0+2*margin,y1-y0+2*margin,slab.zmax-slab.zmin,position=(x0-margin,y0-margin,slab.zmin)).set_material(mat).prio_set(10))
            assumptions.append('Literal gds2palace XML planar dielectric stack; embedded material values preserved; no expression evaluation or implicit feeds')
        else:
            mats=_materials(em,r['materials'])
            odb=read.ODBImport(str(source),mats[r['substrate_material']],stack_thickness=r['stack_thickness_m'],reverse_stack=r['reverse_stack'],centralize=False,thick_traces=False,trace_material=mats[r['trace_material']],cache_path=None,plot=False)
            names=[layer.name for layer in odb.pcbd.iter_geo_layers()]
            if set(names)!=set(r['layer_names']):raise ValueError('ODB signal-layer names differ from the explicit review')
            dielectric=odb.generate_dielectric(merged=True);objects.extend(dielectric if isinstance(dielectric,list) else [dielectric])
            conductors.extend(odb.generate_traces())
            if r['generate_vias']:conductors.extend(odb.generate_vias())
            objects.extend(conductors)
            assumptions.extend(['ODB structural stack override and trace/substrate materials are explicitly reviewed; caches and component scripts are not loaded','ODB sheets use explicitly reviewed PEC; all dielectric slabs use the reviewed homogeneous substrate material rather than inferred manufacturer materials'])
    except ImportError as exc:
        raise RuntimeError('This importer needs the EMerge cad extra (emcad and, for Gerber, pygerber). Configure and qualify a solver runtime with emerge[cad]; the active environment was not modified. '+str(exc)) from exc
    if not objects or len(objects)>256 or any(obj is None for obj in objects):raise ValueError('Import must produce 1 to 256 actual geometry objects')
    if verify_import(advanced)!=identity:raise ValueError('Import inputs changed during geometry construction')
    return {'objects':objects,'conductors':conductors,'identity':identity,'scope':'reviewed-'+kind+'-scattering','assumptions':assumptions}
