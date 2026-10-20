"""Independent multi-net SI studies with explicit terminals and shared provenance."""
from __future__ import annotations
import copy
import math

INPUTS={'rise_ns','frequency_mhz','source_ohm','load_ohm','z0_ohm','epsilon_eff',
        'eye_bitrate_mbps','eye_swing_v','return_nets','return_terminal_ids','return_terminal_roles'}
CASE_KEYS={'id','net','start','end','reference','inputs'}


def cases_from_config(config):
    """Read up to 64 explicit routes; preserve incomplete cases for per-case errors."""
    if not isinstance(config,dict) or set(config)-{'schema','cases','description'}:
        raise ValueError('Study JSON must contain cases and optional schema/description.')
    if config.get('schema','wayricad.quick-si-study-input/v1')!='wayricad.quick-si-study-input/v1':
        raise ValueError('Unsupported Quick SI study input schema.')
    cases=config.get('cases')
    if not isinstance(cases,list) or not 1<=len(cases)<=64:raise ValueError('A study needs 1 to 64 explicit cases.')
    seen=set();result=[]
    for index,case in enumerate(cases):
        if not isinstance(case,dict):raise ValueError('Every study case must be an object.')
        case=copy.deepcopy(case);identifier=case.get('id','case-'+str(index+1))
        if not isinstance(identifier,str) or not identifier.strip() or identifier in seen:raise ValueError('Case IDs must be nonempty and unique.')
        seen.add(identifier);case['id']=identifier;result.append(case)
    return result


def checked_case(case):
    """Validate explicit direction, assumptions and return assignments without guessing."""
    if set(case)-CASE_KEYS:raise ValueError('Unknown case fields: '+', '.join(sorted(set(case)-CASE_KEYS)))
    for key in ('net','start','end'):
        if not isinstance(case.get(key),str) or not case[key].strip():raise ValueError('Choose an explicit '+key+' for this case; terminal direction is never inferred.')
    if case['start']==case['end']:raise ValueError('Source and receiver must be distinct pads.')
    if not isinstance(case.get('reference','Auto'),str):raise ValueError('Reference must be Auto or a copper layer name.')
    inputs=copy.deepcopy(case.get('inputs',{}))
    if not isinstance(inputs,dict) or set(inputs)-INPUTS:raise ValueError('Unknown or invalid case inputs.')
    for key,value in inputs.items():
        if key.startswith('return_'):continue
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
            raise ValueError(key+' must be a finite number or null.')
    returns=inputs.get('return_nets',[])
    if not isinstance(returns,list) or any(not isinstance(v,str) or not v.strip() for v in returns) or len(set(returns))!=len(returns):
        raise ValueError('Return nets must be distinct nonempty net names.')
    if case['net'] in returns:raise ValueError('The signal net cannot also be its return net.')
    roles=inputs.get('return_terminal_roles',{})
    if not isinstance(roles,dict) or set(roles)-{'source','load'} or any(not isinstance(v,str) or not v.strip() for v in roles.values()):
        raise ValueError('Return roles must explicitly map source/load to pad labels.')
    terminals=inputs.get('return_terminal_ids',list(roles.values()))
    if not isinstance(terminals,list) or any(not isinstance(v,str) or not v.strip() for v in terminals) or len(set(terminals))!=len(terminals):raise ValueError('Return terminals must be distinct pad labels.')
    if (roles or terminals) and not returns:raise ValueError('Assign return nets before return terminal roles.')
    if any(v not in terminals for v in roles.values()):raise ValueError('Return role pads must be included in return_terminal_ids.')
    if roles and 'return_terminal_ids' not in inputs:inputs['return_terminal_ids']=terminals
    return inputs


def run_study(board,config,*,guard=None,analyzer=None):
    """Screen each route independently; a source change aborts the complete study."""
    cases=cases_from_config(config)
    if analyzer is None:
        from .quick_si import analyze
        analyzer=analyze
    output=[]
    for case in cases:
        if guard:guard()
        row=copy.deepcopy(case)
        try:
            inputs=checked_case(case);row['inputs']=copy.deepcopy(inputs)
            report,path=analyzer(board,case['net'],case['start'],case['end'],case.get('reference','Auto'),**inputs)
            row.update(status=report['status'],report=report,
                       path_data={key:value for key,value in vars(path).items() if key!='board_items'},
                       board_item_ids=[str(item.m_Uuid.AsString()) for item in path.board_items])
            if report.get('return_path'):row['return_status']=report['return_path'].get('status','UNKNOWN')
        except Exception as error:
            row.update(status='ERROR',error=str(error),error_type=type(error).__name__)
        if guard:guard()
        output.append(row)
    incomplete=any(row['status'] not in ('SCREENED','REVIEW') or row.get('return_status') in ('INCOMPLETE','UNRESOLVED','UNKNOWN') for row in output)
    review=any(row['status']=='REVIEW' or row.get('return_status')=='REVIEW' for row in output)
    return {'schema':'wayricad.quick-si-study/v1','status':'INCOMPLETE' if incomplete else 'REVIEW' if review else 'COMPLETE',
            'model':'Independent source-to-receiver route screens; no inter-net coupling, crosstalk or full-bus qualification.',
            'cases':output,'summary':{'cases':len(output),'reported':sum('report' in row for row in output),
                                    'errors':sum(row['status']=='ERROR' for row in output)}}
