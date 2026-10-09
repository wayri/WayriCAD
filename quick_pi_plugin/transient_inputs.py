"""Explicit transient setup from selected loads; never infer PCB L or C."""


def initial_study(request,terminals=()):
    labels={row['id']:row.get('label',row['id']) for row in terminals}
    loads=request.get('sinks') or [{'terminal':request.get('sink_terminal','Load 1'),
                                  'current_A':request.get('sink_current',1.),
                                  'min_voltage_V':request.get('sink_min_voltage'),
                                  'max_voltage_V':request.get('sink_max_voltage')}]
    rows=[]
    for load in loads:
        identifier=load.get('terminal',load.get('id','Load '+str(len(rows)+1)))
        row={'id':labels.get(identifier,identifier),'initial_current_A':0.,
             'step_current_A':load['current_A'],'step_time_s':.001,
             'path_resistance_ohm':0.,'path_inductance_H':0.,'esr_ohm':0.,'capacitance_F':None}
        for key in ('min_voltage_V','max_voltage_V'):
            if load.get(key) is not None:row[key]=load[key]
        rows.append(row)
    return {'source_voltage_V':request.get('source_voltage',1.),'source_resistance_ohm':None,
            'source_inductance_H':0.,'source_current_limit_A':request.get('source_current_limit'),
            'duration_s':.01,'step_s':1e-5,'loads':rows}
