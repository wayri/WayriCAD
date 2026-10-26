"""Bounded report/config intake for native KiCad IBIS circuit exports."""
from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path


def read_json(path, maximum=16*1024*1024):
    """Read finite JSON without allowing an unbounded report/config allocation."""
    path=Path(path)
    with path.open('rb') as stream:
        raw=stream.read(maximum+1)
    if len(raw)>maximum:raise ValueError('Input exceeds the allowed JSON size: '+path.name)
    def reject(value):raise ValueError('Non-finite JSON number: '+value)
    result=json.loads(raw.decode('utf-8-sig'),parse_constant=reject)
    if not isinstance(result,dict):raise ValueError('Expected a JSON object: '+path.name)
    return result,hashlib.sha256(raw).hexdigest()


def require_report_source(report):
    """Check the saved source/rule hashes carried by a completed route report."""
    fingerprints=report.get('source_fingerprints')
    if not isinstance(fingerprints,dict) or not fingerprints:
        raise ValueError('The route has no saved source hashes. Reopen a saved board and screen it again.')
    boards=[path for path in fingerprints if Path(path).suffix.lower()=='.kicad_pcb']
    if len(boards)!=1:raise ValueError('A circuit export must be bound to one saved PCB.')
    from .service import require_source
    require_source({'board_path':boards[0],'source_fingerprints':fingerprints})


def require_case_sources(cases):
    """Hash each distinct saved design once per export validation boundary."""
    checked=set()
    for case in cases:
        report=case['report']
        fingerprints=report.get('source_fingerprints')
        if not isinstance(fingerprints,dict) or not fingerprints:
            require_report_source(report)
        key=json.dumps(fingerprints,sort_keys=True,separators=(',',':'))
        if key not in checked:
            require_report_source(report)
            checked.add(key)


def circuit_cases(report, assignments, selected=None):
    """Bind every selected complete path to two explicitly assigned IBIS pins.

    A report-only export cannot infer signal direction or silently discard a
    requested case. Model files are checked again by the native circuit writer.
    """
    if assignments.get('schema','wayricad.quick-si-ibis/v1')!='wayricad.quick-si-ibis/v1':
        raise ValueError('Unsupported IBIS assignment schema.')
    if set(assignments)-{'schema','description','cases'}:
        raise ValueError('Unknown IBIS assignment configuration fields.')
    configured=assignments.get('cases')
    if not isinstance(configured,dict) or not configured:
        raise ValueError('IBIS assignments require a cases object keyed by case ID (route for one path).')
    if report.get('schema')=='wayricad.quick-si-study/v1':
        available=report.get('cases',[])
        if not isinstance(available,list):raise ValueError('Study cases must be a list.')
    elif report.get('schema')=='wayricad.quick-si/v1':
        available=[{'id':'route','report':report}]
    else:raise ValueError('Choose a Quick SI route or independent-study report.')
    if not 1<=len(available)<=64:raise ValueError('Export one to 64 explicit paths.')
    ids=[row.get('id') for row in available if isinstance(row,dict)]
    if len(ids)!=len(available) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('Report case IDs must be nonempty and unique.')
    selected=list(ids if selected is None else selected)
    if not selected or len(set(selected))!=len(selected) or set(selected)-set(ids):
        raise ValueError('Select distinct existing report case IDs.')
    from .ibis_models import load_ibis,assignment_from_catalog
    result=[];catalogs={}
    for identifier in selected:
        row=available[ids.index(identifier)]
        if not isinstance(row.get('report'),dict):raise ValueError(identifier+': no completed route report.')
        endpoints=configured.get(identifier)
        if not isinstance(endpoints,dict) or set(endpoints)!={'source','sink'}:
            raise ValueError(identifier+': assign both source and sink IBIS models.')
        bound=dict(row['report'])
        bound['source_fingerprints']=report.get('source_fingerprints') or bound.get('source_fingerprints')
        pair={}
        for role in ('source','sink'):
            value=endpoints[role]
            if not isinstance(value,dict) or not all(value.get(key) for key in ('path','component','pin','model')):
                raise ValueError(identifier+': incomplete '+role+' IBIS assignment.')
            if not isinstance(value.get('sha256'),str) or len(value['sha256'])!=64:
                raise ValueError(identifier+': '+role+' requires the reviewed IBIS sha256 from ibis-catalog.')
            if set(value)-{'path','component','pin','model','role','corner','corners','sha256','model_type'}:
                raise ValueError(identifier+': unknown '+role+' IBIS assignment fields.')
            path=str(Path(value['path']).resolve())
            if path not in catalogs:catalogs[path]=load_ibis(path)
            catalog=catalogs[path]
            if value['sha256']!=catalog['sha256']:
                raise ValueError(identifier+': IBIS file changed since assignment review.')
            pair[role]=assignment_from_catalog(catalog,value['component'],value['pin'],
                value['model'],role,value.get('corners',value.get('corner','typ')))
        result.append(dict(id=identifier,report=bound,**pair))
    require_case_sources(result)
    return result


def relative_model_paths(assignments, config_path):
    """Resolve model files relative to their assignment document, not shell cwd."""
    result=copy.deepcopy(assignments)
    cases=result.get('cases')
    if isinstance(cases,dict):
        for pair in cases.values():
            if not isinstance(pair,dict):continue
            for value in pair.values():
                if not isinstance(value,dict) or not isinstance(value.get('path'),str):continue
                path=Path(value['path'])
                if not path.is_absolute():value['path']=str(Path(config_path).resolve().parent/path)
    return result
