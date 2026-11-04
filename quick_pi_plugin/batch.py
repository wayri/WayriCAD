"""Saved-board PI rail cases and shared-return groups with explicit bindings."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = 'wayricad.pi-batch/v1'
MAX_CASES = 32
_ELECTRICAL = {'net','source_terminal','source_terminals','source_voltage','sinks','sink_terminal','sink_terminals','sink_current','series',
    'source_current_limit','sink_min_voltage','sink_max_voltage','edge_mm','plating_mm',
    'mesh_backend','mesh_sizing','max_cells','model_dimension','max_tetrahedra','options','stackup_override',
    'package_conduction','load_resistance_ohm','load_power_W'}
_RETURN = {'return_nets','sample_pitch_mm','return_via_radius_mm','return_terminal_ids','return_terminal_roles'}


def _validate_series(electrical,case,study):
    """Check portable series contracts; saved-pad topology needs board inventory."""
    from .terminals import pad_names
    from .series_models import validate_model
    stages=electrical['series']
    if not isinstance(stages,list) or not 1<=len(stages)<=128:
        raise ValueError('Series batch cases need 1 to 128 explicit component stages.')
    if (electrical.get('model_dimension','2.5d')!='2.5d' or
            any(key in electrical for key in ('load_power_W','load_resistance_ohm','sinks')) or
            'package_conduction' in electrical or
            any(key in case for key in ('return_conduction','electrothermal')) or study.get('shared_returns')):
        raise ValueError('Series batch cases support independent 2.5D prescribed-current paths only; '
                         'constant power/resistance, multisink, 3D, package conduction, return conduction, '
                         'electrothermal and shared returns are unsupported.')
    for key in ('source_voltage','sink_current'):
        value=electrical.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or (key=='sink_current' and value<0):
            raise ValueError('Series batch cases need finite source_voltage and nonnegative prescribed sink_current.')
    occupied=set()
    def electrode(spec,anchor,group):
        value=spec.get(anchor)
        if not isinstance(value,str) or not value.strip():
            raise ValueError('Each series electrode needs an explicit anchor pad: '+anchor)
        ids=pad_names({'terminals':spec[group]}) if group in spec else [value]
        # Anchor/group aliases need saved inventory before identity comparison.
        if occupied.intersection(ids):
            raise ValueError('Repeated series endpoint across source, sink or component electrodes.')
        occupied.update(ids)
    electrode(electrical,'source_terminal','source_terminals')
    electrode(electrical,'sink_terminal','sink_terminals')
    for stage in stages:
        if not isinstance(stage,dict):raise ValueError('Every series stage must be an explicit component object.')
        parallel=stage.get('parallel',[])
        if not isinstance(parallel,list) or len(parallel)>64:
            raise ValueError('Define at most 64 explicit parallel components per series stage.')
        for index,branch in enumerate([stage,*parallel]):
            if not isinstance(branch,dict) or (index and 'parallel' in branch):
                raise ValueError('Parallel series components must be explicit, non-nested objects.')
            electrode(branch,'from_pad','from_pads');electrode(branch,'to_pad','to_pads')
            try:
                validate_model(branch)
                values=[float(branch.get(key,0.)) for key in ('resistance_ohm','inductance_h')]
            except (TypeError,OverflowError) as exc:
                raise ValueError('Series component model values must be finite numbers.') from exc
            if any(not math.isfinite(value) or value<0 for value in values):
                raise ValueError('Series R and L must be finite and nonnegative.')
            if not any(values) and not any(key in branch for key in ('fixed_drop_v','diode')):
                raise ValueError('Every series component needs resistance, inductance or a forward-drop model.')
            if parallel and any(key in branch for key in ('fixed_drop_v','diode')):
                raise ValueError('Parallel series stages support linear R/L models only.')


def validate_study(study):
    """Validate case ownership and bounds; numerical errors stay per-case results."""
    if not isinstance(study,dict) or set(study)-{'schema','cases','shared_returns'} or not {'schema','cases'}<=set(study) or study.get('schema') != SCHEMA:
        raise ValueError('Batch study needs schema=wayricad.pi-batch/v1, cases and optional shared_returns.')
    cases=study['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:
        raise ValueError('A batch needs 1 to 32 rail cases.')
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
        from .mesh_sizing import mode as sizing_mode
        sizing_mode(electrical)
        if not all(key in electrical for key in ('net','source_voltage')):
            raise ValueError('Every case needs explicit net, source pad unit and source_voltage.')
        if 'series' in electrical:
            _validate_series(electrical,case,study)
        else:
            from .terminals import source_names
            source_names(electrical)
        if not isinstance(electrical['net'],str) or not electrical['net'].strip():
            raise ValueError('Case net must be a nonempty string.')
        from .constant_power import requested,guard
        if requested(electrical):
            guard(dict(electrical,action='solve'))
            if study.get('shared_returns') or 'return_conduction' in case or 'electrothermal' in case:
                raise ValueError('Constant-power batch cases currently require independent fixed-temperature copper; coupled returns/electrothermal power regulation are unsupported.')
        if 'sinks' not in electrical and not ('sink_terminal' in electrical and ('sink_current' in electrical or 'load_power_W' in electrical)):
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
    from .shared_return import validate_groups
    validate_groups(study)
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
    """Run rail cases and shared returns; source changes invalidate the batch.

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
    from .shared_return import execute_groups
    shared=execute_groups(study,cases,execute_case,str(path),before,current)
    current()
    batch={'schema':SCHEMA,'status':'COMPLETED' if all(row['status']=='COMPLETED' for row in cases) else 'INCOMPLETE',
           'source_sha256':before,'cases':cases,'shared_returns':shared,
           'assumptions':['Explicit shared-return groups solve common copper once with all mapped rail currents. Other cases remain independent; no AC fields or shared-source regulation is solved.',
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
