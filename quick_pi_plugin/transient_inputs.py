"""Explicit transient setup from selected loads; never infer PCB L or C."""
import math
import copy

PARAMETERS = [('source_voltage_V','Source V',1.),('source_resistance_ohm','Shared / total path R mΩ',1e-3),
              ('source_inductance_H','Shared source L nH',1e-9),('source_current_limit_A','Source budget A (optional)',1.),
              ('duration_s','Duration µs',1e-6),('step_s','Integration step µs',1e-6)]
LOAD_COLUMNS = [('id','Load',None),('initial_current_A','Before A',1.),('step_current_A','After A',1.),
                ('step_time_s','Step at µs',1e-6),('path_resistance_ohm','Branch R mΩ',1e-3),
                ('path_inductance_H','Branch L nH',1e-9),('capacitance_F','Effective C µF',1e-6),
                ('esr_ohm','Cap ESR mΩ',1e-3),('min_voltage_V','Min V (optional)',1.),('max_voltage_V','Max V (optional)',1.)]
OPTIONAL = {'source_current_limit_A','min_voltage_V','max_voltage_V'}


def engineering_from_study(study):
    """Render explicit SI model values in familiar electrical/time units."""
    def text(value,scale):return '' if value is None else str(value) if scale is None else f'{float(value)/scale:.12g}'
    return ({key:text(study.get(key),scale) for key,_label,scale in PARAMETERS},
            [[text(row.get(key),scale) for key,_label,scale in LOAD_COLUMNS] for row in study.get('loads',[])])


def engineering_to_study(parameters,rows,*,validate=True,banks=None,rise_times=None):
    """Convert reviewed mΩ/nH/µF/µs controls into the existing SI solver model."""
    def number(key,label,value,scale):
        if not str(value).strip():
            if key in OPTIONAL or not validate:return None
            raise ValueError('Enter '+label+'.')
        try:result=float(value)*scale
        except (ValueError,TypeError) as exc:raise ValueError(label+' must be a number.') from exc
        if not math.isfinite(result):raise ValueError(label+' must be finite.')
        return result
    output={}
    for key,label,scale in PARAMETERS:
        value=number(key,label,parameters[key],scale)
        if value is not None:output[key]=value
    output['loads']=[]
    if not 1<=len(rows)<=64:raise ValueError('Define 1 to 64 transient load units.')
    for index,values in enumerate(rows,1):
        if len(values)!=len(LOAD_COLUMNS):raise ValueError('Each transient load needs all displayed columns.')
        row={}
        bank=(banks or {}).get(index-1)
        for (key,label,scale),value in zip(LOAD_COLUMNS,values):
            if key=='id':row[key]=str(value).strip()
            elif bank and key in ('capacitance_F','esr_ohm'):continue
            else:
                parsed=number(key,f'Row {index} '+label,value,scale)
                if parsed is not None:row[key]=parsed
        if bank:
            row['shunt_capacitors']=copy.deepcopy(bank)
            row['rise_time_s']=(rise_times or {}).get(index-1,0.)
        output['loads'].append(row)
    if validate:
        from .transient import _request
        _request(output)
    return output


def dc_path_resistance(request,bundle):
    """Reuse ΔV/I only for one matching, feasible fixed-current DC path.

    This is the total solved path resistance, not a fitted regulator output
    resistance. It belongs in only one place in the lumped one-load circuit.
    Multiple loads, nonlinear drops, returns/thermal feedback and changed
    endpoint/current inputs are not reduced to an invented common resistor.
    """
    if not isinstance(bundle,dict):return None
    previous=bundle.get('request',{});result=bundle.get('result',{})
    if (not result or bundle.get('physical_return') or bundle.get('electrothermal') or
            previous.get('series') or request.get('series') or previous.get('package_conduction') or request.get('package_conduction') or
            previous.get('model_dimension','2.5d')!='2.5d' or previous.get('load_resistance_ohm') is not None or
            result.get('feasibility',{}).get('feasible') is False or
            any(row.get('forward_drop_V',0) for row in result.get('components',[]))):return None
    def signature(value):
        sources=value.get('source_terminals',[value.get('source_terminal')])
        loads=value.get('sinks') or [{'terminal':value.get('sink_terminal'),'current_A':value.get('sink_current')}]
        return (value.get('net'),tuple(sources),tuple((tuple(load.get('terminals',[load.get('terminal')])),load.get('current_A')) for load in loads),value.get('source_voltage'))
    if signature(request)!=signature(previous):return None
    if any(not isinstance(value,str) or not value for value in request.get('source_terminals',[request.get('source_terminal')])):return None
    sinks=result.get('sinks',[])
    if len(sinks)!=1:return None
    try:
        current=float(sinks[0]['current_A']);drop=float(sinks[0]['voltage_drop_V'])
        resistance=drop/current
    except (KeyError,TypeError,ValueError,ZeroDivisionError):return None
    return resistance if math.isfinite(resistance) and current>0 and resistance>0 else None


def initial_study(request,terminals=(),bundle=None):
    if request.get('load_power_W') is not None or any('power_W' in row for row in request.get('sinks',[]) if isinstance(row,dict)):
        raise ValueError('Rail transient setup requires prescribed-current loads; constant-power dynamics are not modeled.')
    labels={row['id']:row.get('label',row['id']) for row in terminals}
    loads=request.get('sinks') or [{'terminal':request.get('sink_terminal','Load 1'),
                                  'current_A':request.get('sink_current',1.),
                                  'min_voltage_V':request.get('sink_min_voltage'),
                                  'max_voltage_V':request.get('sink_max_voltage')}]
    rows=[]
    for load in loads:
        if not isinstance(load,dict) or 'current_A' not in load:
            raise ValueError('Each transient seed load requires an explicit current_A; power/control dynamics are not inferred.')
        identifier=load.get('terminal',load.get('id','Load '+str(len(rows)+1)))
        label=load.get('label') or (' + '.join(labels.get(value,value) for value in load.get('terminals',[])[:4])) or labels.get(identifier,identifier)
        row={'id':str(label)[:128],'initial_current_A':0.,
             'step_current_A':load['current_A'],'step_time_s':10e-6,
             'path_resistance_ohm':0.,'path_inductance_H':0.,'esr_ohm':0.,'capacitance_F':None}
        for key in ('min_voltage_V','max_voltage_V'):
            if load.get(key) is not None:row[key]=load[key]
        rows.append(row)
    return {'source_voltage_V':request.get('source_voltage',1.),'source_resistance_ohm':dc_path_resistance(request,bundle),
            'source_inductance_H':0.,'source_current_limit_A':request.get('source_current_limit'),
            'duration_s':100e-6,'step_s':1e-7,'loads':rows}


def recommend_step(study):
    """Return a reviewed step suggestion from the explicit linear R/L/C modes.

    Finite generalized eigenvalues of A x = λ E x describe the solver's
    passive descriptor system. Twenty samples per fastest e-fold/radian and
    at least 1,000 intervals per window are starting points, not convergence
    proof. The existing half-step comparison must still be reviewed.
    """
    if any(row.get('shunt_capacitors') for row in study.get('loads',[])):
        from .transient_shunts import recommend_step as bank_step
        return bank_step(study)
    from .transient import _request,MAX_COARSE_INTERVALS
    import numpy as np
    from scipy.linalg import eigvals
    # Evaluate model validity with a valid budget before proposing refinement.
    candidate=dict(study,step_s=float(study['duration_s'])/1000)
    normalized=_request(candidate);loads=normalized['loads'];count=len(loads)
    inductance=np.diag([row['path_inductance_H'] for row in loads])+normalized['source_inductance_H']*np.ones((count,count))
    resistance=np.diag([row['path_resistance_ohm']+row['esr_ohm'] for row in loads])+normalized['source_resistance_ohm']*np.ones((count,count))
    capacity=np.diag([row['capacitance_F'] for row in loads]);zero=np.zeros((count,count));identity=np.eye(count)
    descriptor=np.block([[inductance,zero],[zero,capacity]])
    dynamics=np.block([[-resistance,-identity],[identity,zero]])
    modes=eigvals(dynamics,descriptor);rates=[abs(value) for value in modes if np.isfinite(value) and abs(value)>0]
    step=min(normalized['duration_s']/1000,1/(20*max(rates))) if rates else normalized['duration_s']/1000
    intervals=math.ceil(normalized['duration_s']/step)
    return dict(step_s=step,intervals=intervals,within_budget=intervals<=MAX_COARSE_INTERVALS,
                maximum_intervals=MAX_COARSE_INTERVALS,
                note='Starting suggestion from explicit R/L/C modes; review half-step convergence. Ideal steps have no finite rise-time waveform.')
