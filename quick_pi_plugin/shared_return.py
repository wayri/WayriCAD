"""Simultaneous fixed-current rail coupling through one common return mesh.

The ordinary positive-demand FEM is solved at zero source potential, then its
potential and current directions are reversed. This is exactly the physical
return-injection solution for a linear conductor, including every cross term.
"""
import copy
import math
from .terminals import pad_names,source_names
from .service import sink_requests,mesh_cell_budget

_SETTINGS={'edge_mm','plating_mm','mesh_backend','options','stackup_override','max_cells'}


def validate_groups(study):
    groups=study.get('shared_returns',[])
    if not isinstance(groups,list) or len(groups)>32:
        raise ValueError('shared_returns must contain at most 32 explicit groups.')
    cases={c['name']:c for c in study['cases']};used_cases=set();used_nets=set();names=set()
    for group in groups:
        if not isinstance(group,dict) or set(group)-({'name','net','source_terminals','loads'}|_SETTINGS):
            raise ValueError('Unknown shared-return settings.')
        mesh_cell_budget(group)
        for key in ('name','net'):
            if not isinstance(group.get(key),str) or not group[key].strip():
                raise ValueError('Shared return requires explicit '+key+'.')
        if group['name'] in names or group['net'] in used_nets:
            raise ValueError('Shared return names and copper nets must be unique; solve each return net once.')
        names.add(group['name']);used_nets.add(group['net']);source_names(group)
        loads=group.get('loads')
        if not isinstance(loads,list) or not 1<=len(loads)<=1024:
            raise ValueError('Shared return requires explicit load mappings.')
        mappings=set();local_cases=set();pads=set(group['source_terminals'])
        for load in loads:
            if not isinstance(load,dict) or set(load)!={'case','sink','terminals'}:
                raise ValueError('Each return load needs case, sink ID and terminals.')
            if not isinstance(load['case'],str) or load['case'] not in cases:
                raise ValueError('Return mapping names an unknown case.')
            if not isinstance(load['sink'],str) or not load['sink']:
                raise ValueError('Return mapping requires a load sink ID.')
            key=(load['case'],load['sink'])
            if key in mappings:raise ValueError('Repeated shared-return load mapping.')
            mappings.add(key);local_cases.add(load['case'])
            selected=pad_names(load)
            if pads.intersection(selected):raise ValueError('Return terminal units overlap.')
            pads.update(selected)
        if used_cases.intersection(local_cases):raise ValueError('A rail case can belong to only one shared return.')
        used_cases.update(local_cases);rail_nets=set()
        for name in local_cases:
            case=cases[name];electrical=case['electrical']
            if ('return_conduction' in case or 'electrothermal' in case or
                    electrical.get('model_dimension','2.5d')!='2.5d' or
                    electrical.get('package_conduction') or electrical.get('load_resistance_ohm') is not None):
                raise ValueError('Shared returns require fixed-temperature, fixed-current 2.5D copper; independent loops, thermal feedback, packages and resistive loads are unsupported.')
            if electrical['net']==group['net'] or electrical['net'] in rail_nets:
                raise ValueError('Shared-return rails must have distinct supply nets; combine loads on the same rail into one case.')
            rail_nets.add(electrical['net'])
            specs=sink_requests(electrical)
            if any(not spec.get('id') for spec in specs):
                raise ValueError('Shared-return supply loads require explicit stable sink IDs.')
            expected={(name,spec['id']) for spec in specs}
            if {key for key in mappings if key[0]==name}!=expected:
                raise ValueError('Map every load ID in each shared-return case exactly once.')
        if any(c['electrical']['net']==group['net'] for c in study['cases']):
            raise ValueError('A shared return net cannot also be an independently driven supply case.')
    return groups


def _checked(result,expected):
    for key in ('sink_current_A','total_power_W','energy_relative_error','current_balance_error_A'):
        value=result.get(key)
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
            raise ValueError('Shared-return evidence needs finite '+key+'.')
    if not math.isclose(result['sink_current_A'],expected,rel_tol=1e-9,abs_tol=1e-12):
        raise ValueError('Shared-return demand and solved current disagree.')
    if result['total_power_W']<0 or abs(result['energy_relative_error'])>1e-6 or abs(result['current_balance_error_A'])>max(1e-8,expected*1e-6):
        raise ValueError('Shared-return copper failed current or power conservation.')


def execute_groups(study,rows,execute_case,board_path,sha,current):
    definitions={case['name']:case for case in study['cases']}
    cases={row['name']:row for row in rows};results=[]
    for group in study.get('shared_returns',[]):
        current();members={mapping['case'] for mapping in group['loads']}
        record={'name':group['name'],'net':group['net'],'status':'COMPLETED','source_sha256':sha}
        try:
            if any(cases[name]['status']=='FAILED' for name in members):
                raise ValueError('A participating supply solve failed; no partial shared return is accepted.')
            demands={}
            for name in members:
                specs=sink_requests(definitions[name]['electrical'])
                _checked(cases[name]['electrical']['result'],math.fsum(s['current_A'] for s in specs))
                demands.update({(name,s['id']):s for s in specs})
            request={key:copy.deepcopy(group[key]) for key in _SETTINGS if key in group}
            request.update(action='solve',board_path=board_path,net=group['net'],
                source_terminals=group['source_terminals'],source_voltage=0.,model_dimension='2.5d',
                sinks=[{'id':str(i),'terminals':mapping['terminals'],
                        'current_A':demands[(mapping['case'],mapping['sink'])]['current_A']}
                       for i,mapping in enumerate(group['loads'])])
            returned=execute_case(request);current()
            for binding in (returned,returned.get('geometry',{})):
                if binding.get('source_sha256') not in (None,sha):
                    raise ValueError('Shared-return geometry belongs to another source hash.')
            raw=returned['result'];total_current=math.fsum(s['current_A'] for s in request['sinks'])
            _checked(raw,total_current)
            solved={s['id']:s for s in raw['sinks']}
            if len(raw['sinks'])!=len(group['loads']) or set(solved)!={str(i) for i in range(len(group['loads']))}:
                raise ValueError('Shared-return solver lost load identity.')
            record.update(return_conduction=returned,total_current_A=total_current,
                return_loss_W=raw['total_power_W'],loads=[],
                physical_return_potential_V=[None if v is None else -v for v in raw.get('potential_V',[])],
                return_reference={'zero_terminals':group['source_terminals'],
                    'physical_potential_multiplier':-1,'physical_current_multiplier':-1},
                notice='One simultaneous return copper solve includes common-impedance coupling. '
                    'Raw return FEM potentials/currents have reversed direction; multiply by -1 for physical return injections. '
                    'Each load return contribution I × ground rise includes interaction terms; shared copper loss is counted once. '
                    'Ideal equipotential pad units and prescribed currents at fixed temperature; no AC fields, regulator dynamics or thermal feedback.')
            returned['return_conduction_notice']=record['notice']
            for i,mapping in enumerate(group['loads']):
                spec=demands[(mapping['case'],mapping['sink'])]
                rail=cases[mapping['case']]['electrical']['result']
                supplies=[s for s in rail['sinks'] if s['id']==mapping['sink']]
                if len(supplies)!=1:raise ValueError('Supply solver lost load identity.')
                supply=supplies[0];ground=-solved[str(i)]['voltage_V']
                voltage=supply['voltage_V']-ground;demand=spec['current_A']
                if not math.isclose(solved[str(i)]['current_A'],demand,rel_tol=1e-9,abs_tol=1e-12):
                    raise ValueError('Solved return injection disagrees with its mapped supply load.')
                if not all(math.isfinite(x) for x in (ground,voltage)) or ground < -1e-10:
                    raise ValueError('Invalid passive shared-return potential.')
                if not math.isclose(supply['current_A'],demand,rel_tol=1e-9,abs_tol=1e-12):
                    raise ValueError('Supply load current disagrees with return injection.')
                low=spec.get('min_voltage_V',0.);high=spec.get('max_voltage_V')
                good=voltage>=low-1e-12 and (high is None or voltage<=high+1e-12)
                record['loads'].append({**mapping,'current_A':demand,'ground_rise_V':ground,
                    'supply_voltage_V':supply['voltage_V'],'supply_drop_V':supply['voltage_drop_V'],
                    'delivered_load_voltage_V':voltage,'return_power_contribution_W':demand*ground,
                    'load_power_W':demand*voltage,'voltage_limits_met':good})
            terminal_loss=math.fsum(load['return_power_contribution_W'] for load in record['loads'])
            if not math.isclose(terminal_loss,record['return_loss_W'],rel_tol=1e-6,abs_tol=1e-10):
                raise ValueError('Shared-return terminal power and copper loss disagree.')
            record['supply_loss_W']=math.fsum(cases[n]['electrical']['result']['total_power_W'] for n in members)
            record['total_loss_W']=record['supply_loss_W']+record['return_loss_W']
            record['source_power_W']=math.fsum(cases[n]['electrical']['result']['source_voltage_V'] *
                math.fsum(s['current_A'] for s in sink_requests(definitions[n]['electrical'])) for n in members)
            record['load_power_W']=math.fsum(s['load_power_W'] for s in record['loads'])
            record['power_balance_error_W']=abs(record['source_power_W']-record['load_power_W']-record['total_loss_W'])
            if record['power_balance_error_W']>max(1e-9,abs(record['source_power_W'])*1e-6):
                raise ValueError('Coupled rail/return power conservation failed.')
            for name in members:
                loads=[s for s in record['loads'] if s['case']==name]
                budget=definitions[name]['electrical'].get('source_current_limit')
                feasible=all(s['voltage_limits_met'] for s in loads) and (budget is None or math.fsum(s['current_A'] for s in loads)<=budget+1e-12)
                case=cases[name]
                case['shared_return']={'group':group['name'],'loads':copy.deepcopy(loads),'feasible':feasible,
                    'notice':'Shared copper loss is reported once in the group, not added independently to each rail.'}
                if not feasible:case['status']='INFEASIBLE';record['status']='INFEASIBLE'
                elif case['status']=='INFEASIBLE':
                    review=case.get('return_path',{}).get('return_path',{})
                    case['status']='INCOMPLETE' if review.get('unknown_count') else 'REVIEW_REQUIRED' if review.get('warning_count') else 'COMPLETED'
        except InterruptedError:
            raise
        except Exception as exc:
            record={'name':group['name'],'net':group['net'],'status':'FAILED','error':str(exc),'error_type':type(exc).__name__,'source_sha256':sha}
            for name in members:
                cases[name].pop('shared_return',None)
                cases[name].update(status='FAILED',error='Shared return '+group['name']+': '+str(exc))
        current();results.append(record)
    return results


def physical_report_bundle(group):
    """Render physical ground rise/current arrows while retaining raw FEM evidence."""
    bundle=dict(group['return_conduction'])
    bundle['auxiliary_reversed_current_result']=bundle['result']
    raw=dict(bundle['result']);bundle['result']=raw
    raw['vias']=[dict(row) for row in raw['vias']]
    raw['sinks']=[dict(row) for row in raw['sinks']]
    raw['potential_V']=[None if v is None else -v for v in raw['potential_V']]
    for key in ('cell_J_A_mm2','cell_sheet_current_A_mm'):
        raw[key]=[None if row is None else [-v for v in row] for row in raw[key]]
    for key in ('source_voltage_V','sink_voltage_V','source_current_A','sink_current_A','total_sink_current_A'):
        raw[key]=-raw[key]
    for row in raw['vias']:
        if row.get('current_A') is not None:row['current_A']=-row['current_A']
    for row in raw['sinks']:
        row['voltage_V']=-row['voltage_V'];row['current_A']=-row['current_A']
        row['min_voltage_V']=None;row['max_voltage_V']=None;row['within_voltage_limits']=True
    raw['negative_sink_voltage']=False;raw['physical_return']=True
    raw['feasibility']={'feasible':True,'status':'RETURN INJECTION BOUNDARIES','violations':[],
        'notice':'Ground injection boundaries, not supply load limits. Delivered voltage feasibility is evaluated in the parent coupled study.'}
    raw['model']='2.5D physical shared-return conduction; ground zero at source-ground unit'
    bundle['physical_return']=True
    bundle['return_conduction_notice']=(
        'Plots show physical ground rise and physical current direction. Signed load demands are negative because '
        'load-ground contacts inject current into copper; signed source current is negative because source ground removes it. '
        'Copper loss remains positive. Complete original reversed-current FEM evidence is retained in auxiliary_reversed_current_result. '
        'Delivered supply voltage and source budgets are checked in the parent shared-return study.')
    return bundle
