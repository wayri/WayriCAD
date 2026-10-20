"""Independent saved-board PI cases with explicit terminals and source bindings."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path

SCHEMA = 'wayricad.pi-batch/v1'
MAX_CASES = 32
_ELECTRICAL = {'net','source_terminal','source_voltage','sinks','sink_terminal','sink_current',
    'source_current_limit','sink_min_voltage','sink_max_voltage','edge_mm','plating_mm',
    'mesh_backend','model_dimension','max_tetrahedra','options','stackup_override',
    'package_conduction','load_resistance_ohm'}
_RETURN = {'return_nets','sample_pitch_mm','return_via_radius_mm','return_terminal_ids','return_terminal_roles'}


def validate_study(study):
    """Validate case ownership and bounds; numerical errors stay per-case results."""
    if not isinstance(study,dict) or set(study) != {'schema','cases'} or study['schema'] != SCHEMA:
        raise ValueError('Batch study needs exactly schema=wayricad.pi-batch/v1 and cases.')
    cases=study['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError('A batch needs 1 to 32 independent cases.')
    names=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)-{'name','electrical','return_path','return_conduction','electrothermal'}:
            raise ValueError('Each case supports name, electrical, return_path, return_conduction and electrothermal only.')
        name=case.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>160 or name in names:
            raise ValueError('Case names must be unique nonempty strings, at most 160 characters.')
        names.add(name)
        electrical=case.get('electrical')
        if not isinstance(electrical,dict) or set(electrical)-_ELECTRICAL:
            raise ValueError('Case electrical settings contain unsupported fields or a case-owned board/action.')
        if not all(key in electrical for key in ('net','source_terminal','source_voltage')):
            raise ValueError('Every case needs explicit net, source_terminal and source_voltage.')
        if not all(isinstance(electrical[key],str) and electrical[key].strip() for key in ('net','source_terminal')):
            raise ValueError('Case net and source_terminal must be nonempty strings.')
        if 'sinks' not in electrical and not all(key in electrical for key in ('sink_terminal','sink_current')):
            raise ValueError('Every case needs explicit sinks/current_A or sink_terminal and sink_current.')
        if 'return_path' in case:
            returns=case['return_path']
            if not isinstance(returns,dict) or set(returns)-_RETURN:
                raise ValueError('Return review settings contain unsupported fields.')
            nets=returns.get('return_nets')
            if (not isinstance(nets,list) or not nets or
                    any(not isinstance(net,str) or not net.strip() for net in nets) or len(nets)!=len(set(nets))):
                raise ValueError('Return review requires explicit, unique return_nets.')
        if 'return_conduction' in case and not isinstance(case['return_conduction'],dict):
            raise ValueError('Return conduction must be an explicit settings object.')
        if 'return_conduction' in case and 'electrothermal' in case:
            raise ValueError('Combined supply/return thermal feedback is unsupported; use a fixed-temperature DC loop.')
        if 'electrothermal' in case:
            thermal=case['electrothermal']
            if not isinstance(thermal,dict) or set(thermal)-{'thermal_settings','coupling','thermal_result','branch_heat_mappings'}:
                raise ValueError('Coupling accepts explicit thermal_settings, coupling, thermal_result and branch_heat_mappings.')
            if not isinstance(thermal.get('thermal_settings'),dict) or not isinstance(thermal.get('coupling'),dict):
                raise ValueError('Coupling needs explicit thermal_settings and coupling objects.')
    return study


def parse_study(data):
    """Reuse bounded, duplicate-key and nonfinite-number rejecting JSON intake."""
    from .electrothermal_cli import parse_envelope
    envelope=parse_envelope(b'{"mode":"steady","study":'+data+b'}')
    return validate_study(envelope['study'])


def load_study(path):
    source=Path(path).resolve()
    if not source.is_file() or source.stat().st_size>4*1024*1024:
        raise ValueError('Batch JSON must be a file no larger than 4 MiB.')
    data=source.read_bytes()
    return parse_study(data),hashlib.sha256(data).hexdigest()


def initial_study(electrical):
    """Seed one case from current explicit GUI selections, without guessing other rails."""
    selected={key:copy.deepcopy(value) for key,value in electrical.items() if key in _ELECTRICAL}
    return {'schema':SCHEMA,'cases':[{'name':selected.get('net') or 'Selected rail','electrical':selected}]}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(request, execute_case):
    """Run independent cases; any source change invalidates the entire batch.

    Return-path review is geometric evidence, not solved return-loop resistance.
    Temperature feedback is independent per case, never combined board heating.
    """
    study=copy.deepcopy(validate_study(request.get('study')))
    path=Path(request['board_path']).resolve()
    if not path.is_file() or path.suffix.lower()!='.kicad_pcb':
        raise ValueError('Choose a saved KiCad PCB for the batch.')
    before=_sha(path)
    if request.get('source_sha256') not in (None,before):
        raise ValueError('Saved PCB changed. Reload before running the batch.')
    study_path=Path(request['study_input_path']) if request.get('study_input_path') else None
    def current():
        if _sha(path)!=before:
            raise ValueError('Saved PCB changed during batch analysis; every case is invalidated.')
        if study_path and _sha(study_path)!=request.get('study_file_sha256'):
            raise ValueError('Batch study changed during analysis; every case is invalidated.')
    cases=[]
    for case in study['cases']:
        current()
        row={'name':case['name'],'status':'COMPLETED','source_sha256':before}
        try:
            physical_status=review_status='COMPLETED'
            electrical={**case['electrical'],'action':'solve','board_path':str(path)}
            return_copper=None
            if 'return_conduction' in case:
                from .power_loop import return_request
                return_copper=return_request(electrical,case['return_conduction'])
            bundle=execute_case(electrical)
            if not isinstance(bundle,dict) or not isinstance(bundle.get('result'),dict):
                raise ValueError('Electrical solver returned no operating point.')
            for binding in (bundle,bundle.get('geometry',{})):
                if binding.get('source_sha256') not in (None,before):raise ValueError('Case geometry belongs to another board hash.')
            row['electrical']=bundle
            if bundle['result'].get('feasibility',{}).get('feasible') is False:
                physical_status='INFEASIBLE'
            if return_copper is not None:
                from .power_loop import summarize_loop
                returned=execute_case({**return_copper,'board_path':str(path)})
                if not isinstance(returned,dict) or not isinstance(returned.get('result'),dict):
                    raise ValueError('Return copper solver returned no operating point.')
                for binding in (returned,returned.get('geometry',{})):
                    if binding.get('source_sha256') not in (None,before):raise ValueError('Return geometry belongs to another board hash.')
                row['return_conduction']=returned
                row['loop']=summarize_loop(electrical,bundle['result'],returned['result'],case['return_conduction'])
                returned['return_voltage_reference']=copy.deepcopy(row['loop']['return_voltage_reference'])
                returned['return_conduction_notice']=row['loop']['notice']
                physical_status='COMPLETED' if row['loop']['feasible'] else 'INFEASIBLE'
            if 'return_path' in case:
                returns=execute_case({'action':'return_path','board_path':str(path),
                                      'signal_net':electrical['net'],**case['return_path']})
                row['return_path']=returns
                diagnostic=returns.get('return_path',{})
                if not diagnostic or diagnostic.get('unknown_count',0):
                    review_status='INCOMPLETE'
                elif diagnostic.get('warning_count',0):
                    review_status='REVIEW_REQUIRED'
            if 'electrothermal' in case:
                thermal=execute_case({'action':'electrothermal','mode':'steady','require_explicit_thermal':True,'board_path':str(path),
                    'source_sha256':before,'study':{'electrical':case['electrical'],**case['electrothermal']}})
                row['electrothermal']=thermal
                coupled=thermal.get('electrothermal',{})
                if not coupled.get('converged'):
                    physical_status='INCOMPLETE'
                elif not coupled.get('limits',{}).get('operating_point_valid'):
                    physical_status='INFEASIBLE'
                else:
                    physical_status='COMPLETED'
            ranks={'COMPLETED':0,'REVIEW_REQUIRED':1,'INCOMPLETE':2,'INFEASIBLE':3}
            row['status']=max((physical_status,review_status),key=ranks.get)
        except InterruptedError:
            raise
        except Exception as exc:
            row.update(status='FAILED',error=str(exc),error_type=type(exc).__name__)
        current();cases.append(row)
    current()
    batch={'schema':SCHEMA,'status':'COMPLETED' if all(row['status']=='COMPLETED' for row in cases) else 'INCOMPLETE',
           'source_sha256':before,'cases':cases,
           'assumptions':['Independent cases on one saved PCB; no inter-net crosstalk or shared-source interaction is solved.',
               'Ordinary DC always includes copper I²R losses. Optional thermal feedback uses only each case’s explicit materials and boundaries.',
               'Return-path geometry is reviewed separately; return-loop voltage drop is calculated only with explicit return_conduction. Loop inductance and AC impedance are not inferred.']}
    return {'batch':batch,'source_sha256':before,'request':copy.deepcopy(request)}


def cli_main(args, run_job, forbidden=False):
    if forbidden or not args.board:
        raise ValueError('--batch requires a PCB and cannot combine with unrelated PI flags; put settings in each case.')
    source=args.batch.resolve();study,study_sha=load_study(source)
    protected=[source,args.board.resolve()]
    targets=[args.output.resolve()] if args.output else []
    if args.output and args.output.suffix.lower()!='.json':
        raise ValueError('Batch JSON output requires a .json filename.')
    if args.html:
        html=args.html.resolve().with_suffix('.html');targets.extend((html,html.with_suffix('.json')))
    if len({target.resolve() for target in targets})!=len(targets):
        raise ValueError('Batch --output and HTML paired JSON must use distinct destinations.')
    for target in targets:
        if any(target==item or (target.exists() and os.path.samefile(target,item)) for item in protected):
            raise ValueError('Outputs must not overwrite the source board or batch study.')
    request={'action':'batch','board_path':str(args.board.resolve()),'study':study,
             'study_input_path':str(source),'study_file_sha256':study_sha}
    if args.html:request['html_output']=str(args.html.resolve().with_suffix('.html'))
    result=run_job(request,timeout=args.timeout)
    payload=json.dumps(result,indent=2,allow_nan=False)
    if args.output:
        from wayricad_runtime.report_ui import checked_sources,publish_documents
        publish_documents({args.output:payload+'\n'},sources=[*protected,*checked_sources(result)])
    print(payload)
    if any(row['status']=='INFEASIBLE' for row in result['batch']['cases']):return 4
    return 0 if result['batch']['status']=='COMPLETED' else 3
