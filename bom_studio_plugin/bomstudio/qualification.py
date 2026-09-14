"""Explicit manufacturer land-pattern and pin-function comparison.

Inputs must be a human-transcribed, source-linked *recommended land pattern*,
not a package outline. No drawing OCR, arbitrary unit inference, or pin swaps.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import math
import re
from . import footprints, evidence
from .partsdb import digest, text
from .sexpr import parse
from .engine import now


def finite(v,label,lower=-100000,upper=100000):
    if type(v) not in (int,float) or not math.isfinite(v) or not lower<=v<=upper:
        raise ValueError(label+' must be a finite number in the declared millimeter/degree frame.')
    return float(v)


def actual_geometry(file):
    file=Path(file);tree,hash_=footprints.load_tree(file,8*1024*1024)
    if tree.tag!='footprint':raise ValueError('Qualification uses a local .kicad_mod, not a placed-board footprint with transformed coordinates.')
    pads=[]
    for pad in tree.nodes('pad'):
        if not pad.val() or pad.val(2)=='np_thru_hole':continue
        at=pad.one('at');size=pad.one('size');layers=pad.one('layers');drill=pad.one('drill')
        if not at or not size:raise ValueError('Pad geometry is incomplete.')
        data={'number':pad.val(),'kind':pad.val(2),'shape':pad.val(3),
              'x':float(at.val(1)),'y':float(at.val(2)),'width':float(size.val(1)),'height':float(size.val(2)),
              'rotation':float(at.val(3,'0'))%360,'layers':sorted(a.value for a in layers.atoms[1:]) if layers else [],
              'drill':None,'mask_margin':None,'paste_margin':None,'paste_ratio':None,'roundrect_ratio':None,'custom':bool(pad.one('primitives'))}
        for key,node in [('mask_margin','solder_mask_margin'),('paste_margin','solder_paste_margin'),('paste_ratio','solder_paste_margin_ratio'),('roundrect_ratio','roundrect_rratio')]:
            n=pad.one(node) or tree.one(node)
            if n:data[key]=float(n.val())
        if drill:
            nums=[float(a.value) for a in drill.atoms[1:] if a.value!='oval']
            data['drill']=nums if len(nums)==2 else nums*2 if len(nums)==1 else None
            if drill.one('offset'):data['custom']=True
        for k in ('x','y','width','height','rotation'):finite(data[k],k)
        for k in ('mask_margin','paste_margin','paste_ratio','roundrect_ratio'):
            if data[k] is not None:finite(data[k],k,-10,10)
        for d in data['drill'] or []:finite(d,'drill',.001,100)
        if data['width']<=0 or data['height']<=0:raise ValueError('Pad sizes must be positive.')
        pads.append(data)
    return {'file':str(file.resolve()),'sha256':hash_,'pads':pads,'format':tree.get('version'),'top_view':True}


def validate_spec(spec):
    if not isinstance(spec,dict) or spec.get('schema')!='wayricad-land-pattern-1':raise ValueError('Use wayricad-land-pattern-1 specification.')
    allowed={'schema','manufacturer','mpn','source_url','document_revision','document_sha256','page','frame','tolerance_mm','angle_tolerance_deg','pads','pin_functions','notes','reviewed_by'}
    if set(spec)-allowed:raise ValueError('Unknown qualification specification keys: '+', '.join(sorted(set(spec)-allowed)))
    for k in ('manufacturer','mpn','source_url','document_revision','document_sha256','frame','reviewed_by'):
        if not text(spec.get(k,''),k,4096).strip():raise ValueError('Qualification source requires '+k)
    evidence.safe_url(spec['source_url'])
    if not isinstance(spec.get('page'),(str,int)) or isinstance(spec.get('page'),bool) or not str(spec['page']).strip():raise ValueError('Record the source document page or drawing locator.')
    if not re.fullmatch('[a-fA-F0-9]{64}',spec['document_sha256']):raise ValueError('Document SHA-256 must be recorded.')
    if spec['frame']!='top-view-mm':raise ValueError('Transcribe top-view-mm in the SAME footprint origin/orientation; no mirror/rotation is inferred.')
    finite(spec.get('tolerance_mm'), 'tolerance_mm',0,1)
    finite(spec.get('angle_tolerance_deg',.1),'angle_tolerance_deg',0,5)
    pads=spec.get('pads')
    if not isinstance(pads,list) or not 1<=len(pads)<=4096:raise ValueError('Provide 1..4096 explicit electrical pads.')
    for p in pads:
        if not isinstance(p,dict):raise ValueError('Each pad must be an object.')
        if set(p)-{'number','x','y','width','height','rotation','shape','kind','layers','drill','mask_margin','paste_margin','paste_ratio','roundrect_ratio'}:raise ValueError('Unknown pad specification property.')
        text(p.get('number'),'pad number',50)
        if not p['number']:raise ValueError('Pad number is required.')
        for k in ('x','y','width','height','rotation'):finite(p.get(k),k)
        if p['width']<=0 or p['height']<=0:raise ValueError('Positive pad dimensions required.')
        if p.get('shape') not in ('rect','roundrect','circle','oval'):raise ValueError('Only rect, roundrect, circle and oval shapes supported for qualification.')
        if p.get('kind') not in ('smd','thru_hole','connect'):raise ValueError('Specify pad mounting kind.')
        if not isinstance(p.get('layers'),list) or not p['layers'] or any(not isinstance(s,str) for s in p['layers']):raise ValueError('Explicit copper/mask/paste layers required.')
        for k in ('mask_margin','paste_margin','paste_ratio','roundrect_ratio'):
            if k in p and p[k] is not None:finite(p[k],k,-10,10)
        if p.get('drill') is not None:
            if not isinstance(p['drill'],list) or len(p['drill'])!=2:raise ValueError('Drill needs [x_mm,y_mm].')
            for d in p['drill']:finite(d,'drill',.001,100)
    pins=spec.get('pin_functions',{})
    if not isinstance(pins,dict) or len(pins)>4096:raise ValueError('pin_functions must be pin-number to explicit accepted names.')
    for k,v in pins.items():
        text(k,'pin number',50)
        if not isinstance(v,list) or not v or any(not isinstance(x,str) or not x for x in v):raise ValueError('Each pin needs at least one explicit accepted function name.')
    return spec


def run(ws,variant,cid,spec):
    validate_spec(spec);ws.project.check_unchanged()
    row=next((r for r in ws.rows(variant) if r['id']==cid),None)
    if not row:raise ValueError('Select an existing physical component.')
    if evidence.identity(spec['manufacturer'],spec['mpn'])!=evidence.identity(row['fields'].get('Manufacturer',''),row['fields'].get('MPN','')):
        raise ValueError('Specification does not match the full exact manufacturer and orderable MPN.')
    inspection=footprints.Inspector(ws).inspect(row);library=inspection['library'];issues=[];comparisons=[]
    if library.get('status')!='read':raise ValueError('A resolved local .kicad_mod is required for numeric land-pattern comparison.')
    actual=actual_geometry(library['source']);pads=actual['pads'];by_num=defaultdict(list)
    for index,p in enumerate(pads):by_num[p['number']].append((index,p))
    used=set();tol=spec['tolerance_mm'];angle=spec.get('angle_tolerance_deg',.1)
    def issue(severity,code,message):issues.append({'severity':severity,'code':code,'message':message,'reference':row['ref']})
    for expected in spec['pads']:
        num=expected['number'];available=[(i,p) for i,p in by_num[num] if i not in used]
        if not available:issue('error','PAD_MISSING','No remaining physical pad '+num);continue
        i,p=min(available,key=lambda x:(x[1]['x']-expected['x'])**2+(x[1]['y']-expected['y'])**2);used.add(i)
        mismatch=[];unknown=[]
        for k in ('x','y','width','height'):
            if abs(p[k]-expected[k])>tol+1e-12:mismatch.append(k)
        if abs((p['rotation']-expected['rotation']+180)%360-180)>angle+1e-12:mismatch.append('rotation')
        for k in ('kind','shape'):
            if p[k]!=expected[k]:mismatch.append(k)
        if sorted(p['layers'])!=sorted(expected['layers']):mismatch.append('layers')
        if p['custom']:unknown.append('custom geometry/drill offset unsupported')
        if expected['kind']=='thru_hole':
            if not p['drill'] or not expected.get('drill'):unknown.append('drill')
            elif any(abs(a-b)>tol+1e-12 for a,b in zip(p['drill'],expected['drill'])):mismatch.append('drill')
        elif p['drill'] is not None:mismatch.append('unexpected drill')
        for k in ('mask_margin','paste_margin','paste_ratio')+ (('roundrect_ratio',) if expected['shape']=='roundrect' else ()):
            if expected.get(k) is None or p.get(k) is None:unknown.append(k+' (implicit project/defaults not assumed)')
            elif abs(expected[k]-p[k])>(1e-6 if k.endswith('ratio') else tol):mismatch.append(k)
        if mismatch:issue('error','PAD_GEOMETRY_MISMATCH','Pad '+num+': '+', '.join(mismatch))
        if unknown:issue('unknown','PAD_GEOMETRY_UNRESOLVED','Pad '+num+': '+', '.join(unknown))
        comparisons.append({'number':num,'expected':expected,'actual':p,'mismatch':mismatch,'unknown':unknown})
    if len(used)!=len(pads):issue('error','EXTRA_ELECTRICAL_PADS','Actual footprint contains electrical pad instances absent from the specification.')
    pins=inspection['symbol'];expected_names=spec.get('pin_functions',{})
    if pins['issues']:issue('unknown','SYMBOL_PIN_MAP_UNRESOLVED','; '.join(pins['issues']))
    if set(expected_names)!=set(pins['pin_numbers']):issue('unknown','PIN_FUNCTION_COVERAGE','Function specification must cover every actual symbol pin, with no extras.')
    for pin,names in expected_names.items():
        actual_name=pins['pin_names'].get(pin)
        if actual_name is not None and actual_name not in names:issue('error','PIN_FUNCTION_MISMATCH',f'Pin {pin}: symbol {actual_name!r}; source-approved names {names!r}')
    if set(pins['pin_numbers'])!={p['number'] for p in spec['pads']}:issue('unknown','SYMBOL_LAND_PATTERN_PIN_COVERAGE','Symbol and recommended pad number sets differ; explicitly resolve exposed/NC pins.')
    status='MISMATCH' if any(i['severity']=='error' for i in issues) else 'INCOMPLETE' if issues else 'MATCHED_DECLARED_CHECKS'
    report={'schema':'wayricad-qualification-1','generated_at':now(),'variant':variant,'component':cid,'reference':row['ref'],
            'manufacturer':spec['manufacturer'],'mpn':spec['mpn'],'footprint':row['fields']['Footprint'],'footprint_file':actual['file'],
            'footprint_sha256':actual['sha256'],'symbol_sha256':digest(pins),'spec_sha256':digest(spec),'source':{k:spec[k] for k in ('source_url','document_revision','document_sha256','reviewed_by')},
            'status':status,'issues':issues,'pad_comparisons':comparisons,'pin_comparison':{'actual':pins,'expected':expected_names},
            'coverage':['pad count/number/position/size/rotation/shape/layers','explicit drill/mask/paste/roundrect geometry','explicit exact pin-function aliases'],
            'excluded':['body courtyard/assembly/mechanical clearance','un-numbered paste apertures','IPC solder-joint tolerancing','current/voltage/thermal/electrical suitability','source transcription authenticity','3D/courtyard and schematic electrical pin types'],
            'notice':'Matched declared checks is not a manufacturer or engineering qualification. Obtain a scoped human approval after the independent checks.'}
    report['fingerprint']=digest({k:v for k,v in report.items() if k!='generated_at'})
    return report
